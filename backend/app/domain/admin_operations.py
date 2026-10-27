"""Explicit safe operational projections; account audit shares the business transaction."""
from datetime import timezone
import time
from uuid import uuid4

from app.core.errors import PUBLIC_CODES
from app.core.exceptions import StorageError
from app.db.database import database_connection, ensure_schema_current


def require_identity(db, user_id, *, admin=True):
    row=db.execute('SELECT id,role,active FROM users WHERE id=%s',(user_id,)).fetchone()
    if not row or not row['active']:
        raise StorageError('authentication_required','请登录后继续。',401)
    if admin and row['role']!='admin':
        raise StorageError('permission_denied','仅有效管理员可以访问运营后台。',403)
    return row


def audit_account(db, before, after, reason, *, actor=None, request_id=None, source='cli', operator=None):
    db.execute('''INSERT INTO admin_audit_events(id,source,operator,actor_user_id,target_user_id,
        before_role,after_role,before_active,after_active,reason,effective_at,request_id)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
        (str(uuid4()),source,operator,actor,after['id'],before['role'] if before else None,
         after['role'],before['active'] if before else None,after['active'],reason,after['updated_at'],request_id))


def guard_last_admin(db, before, role, active):
    if before['role']=='admin' and before['active'] and (role!='admin' or not active):
        count=db.execute("SELECT count(*) AS n FROM users WHERE role='admin' AND active").fetchone()['n']
        if count<=1:
            raise StorageError('admin_last_active','必须保留至少一个有效管理员。',409)


def bounds(start=None, end=None):
    for value in (start,end):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise StorageError('admin_query_invalid','查询时间必须包含时区。',422)
    if start and end and start>=end:
        raise StorageError('admin_query_invalid','开始时间必须早于结束时间。',422)
    return (start.astimezone(timezone.utc) if start else None,end.astimezone(timezone.utc) if end else None)


def period(start,end):
    return dict(kind='bounded' if start or end else 'cumulative',timezone='UTC',**{'from':start,'to':end})


def coverage(db):
    row=db.execute('SELECT started_at FROM operational_collection WHERE id=1').fetchone()
    return dict(started_at=row['started_at'] if row else None,historical_missing_is_zero=False,policy='retain_no_auto_delete')


def filtered_time(clauses,values,column,start,end, *, epoch=False):
    if start:
        clauses.append(column+'>=%s');values.append(start.timestamp() if epoch else start)
    if end:
        clauses.append(column+'<%s');values.append(end.timestamp() if epoch else end)


def page_query(db,select,source,where,values,page,page_size,order):
    condition=' WHERE '+' AND '.join(where) if where else ''
    total=db.execute('SELECT count(*) AS n FROM '+source+condition,tuple(values)).fetchone()['n']
    rows=db.execute('SELECT '+select+' FROM '+source+condition+' ORDER BY '+order+' LIMIT %s OFFSET %s',
                    tuple(values)+ (page_size,(page-1)*page_size)).fetchall()
    return dict(items=[dict(row) for row in rows],total=total,page=page,page_size=page_size)


USER_FIELDS='id,email,role,active,admin_revision,updated_at'
TASK_FIELDS='t.id,t.user_id,u.email AS user_email,t.project_id,t.task_type,t.phase,t.status,t.revision,t.created_at,t.updated_at,t.current_attempt,t.error_code'
TASK_DIAGNOSTICS='''a.started_at,a.finished_at,
    CASE WHEN a.finished_at IS NOT NULL THEN floor(extract(epoch FROM(a.finished_at-a.started_at))*1000)::bigint END AS elapsed_ms,
    (SELECT count(*) FROM task_attempts ta WHERE ta.task_id=t.id) AS attempt_count,
    (SELECT request_id FROM operational_request_events e WHERE e.task_id=t.id ORDER BY e.created_at DESC,e.request_id DESC LIMIT 1) AS request_id'''
TASK_SOURCE='''tasks t JOIN users u ON u.id=t.user_id
    LEFT JOIN task_attempts a ON a.task_id=t.id AND a.attempt_no=t.current_attempt'''


class AdminOperations:
    def __init__(self,user_id):self.user_id=user_id

    def list_users(self, *, page=1,page_size=10,q=None,role=None,active=None):
        clauses=[];values=[]
        if q:
            # Literal substring: wildcard characters are not a query language.
            clauses.append("email ILIKE %s ESCAPE '\\'")
            values.append('%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%')
        if role is not None:clauses.append('role=%s');values.append(role)
        if active is not None:clauses.append('active=%s');values.append(active)
        with database_connection() as db:
            require_identity(db,self.user_id)
            result=page_query(db,USER_FIELDS,'users',clauses,values,page,page_size,'email,id')
        for row in result['items']:row['allowed_actions']=[] if row['id']==self.user_id else ['edit']
        return result

    def change_user(self,target,request,request_id):
        from app.auth.revocations import revoke_sessions,invalidate_recovery_codes
        with database_connection(write=True) as db:
            require_identity(db,self.user_id)
            row=db.execute('SELECT '+USER_FIELDS+' FROM users WHERE id=%s',(target,)).fetchone()
            if not row:raise StorageError('admin_user_not_found','账号不存在。',404)
            if target==self.user_id:raise StorageError('admin_self_change','请由其他管理员修改当前账号。',409)
            if row['admin_revision']!=request.expected_revision:
                raise StorageError('admin_revision_conflict','账号版本已变化，请刷新后重试。',409)
            if row['role']==request.role and row['active']==request.active:
                raise StorageError('admin_change_invalid','账号角色和状态没有变化。',422)
            guard_last_admin(db,row,request.role,request.active)
            now=time.time()
            changed=db.execute('''UPDATE users SET role=%s,active=%s,admin_revision=admin_revision+1,updated_at=%s
                WHERE id=%s RETURNING '''+USER_FIELDS,(request.role,request.active,now,target)).fetchone()
            audit_account(db,row,changed,request.reason,actor=self.user_id,request_id=request_id,source='web')
            invalidate_recovery_codes(db,target,now)
            revoke_sessions(db,user_id=target,reason='admin_account_changed',source='web',revoked_at=now)
            return {**dict(changed),'allowed_actions':['edit']}

    def task_projection(self,row):
        value=dict(row)
        value['error_code']=value['error_code'] if value['error_code'] in PUBLIC_CODES else None
        value['can_open_workspace']=value['user_id']==self.user_id
        value['allowed_actions']=[]
        return value

    def list_tasks(self, *, page=1,page_size=10,status=None,task_type=None,user_id=None,start=None,end=None):
        start,end=bounds(start,end);clauses=[];values=[]
        for name,value in (('status',status),('task_type',task_type),('user_id',user_id)):
            if value is not None:clauses.append('t.'+name+'=%s');values.append(value)
        filtered_time(clauses,values,'t.created_at',start,end)
        with database_connection() as db:
            require_identity(db,self.user_id)
            result=page_query(db,TASK_FIELDS+','+TASK_DIAGNOSTICS,TASK_SOURCE,clauses,values,page,page_size,'t.created_at DESC,t.id DESC')
        result['items']=[self.task_projection(row) for row in result['items']]
        return result

    def task_detail(self,task_id):
        with database_connection() as db:
            require_identity(db,self.user_id)
            row=db.execute('SELECT '+TASK_FIELDS+','+TASK_DIAGNOSTICS+' FROM '+TASK_SOURCE+' WHERE t.id=%s',(task_id,)).fetchone()
            if not row:raise StorageError('task_not_found','任务不存在。',404)
            result=self.task_projection(row)
        result['workspace_url']=None
        if result['can_open_workspace']:
            from app.domain.tasks.workspace import TaskWorkspaceService
            workspace=TaskWorkspaceService(self.user_id).get(task_id)
            result['allowed_actions']=workspace['allowed_actions']
            result['workspace_url']='/api/v1/tasks/'+task_id+'/workspace'
        return result

    def logs(self, *, page=1,page_size=10,request_id=None,task_id=None,user_id=None,status=None,start=None,end=None):
        start,end=bounds(start,end);clauses=[];values=[]
        for name,value in (('request_id',request_id),('task_id',task_id),('user_id',user_id),('status',status)):
            if value is not None:clauses.append(name+'=%s');values.append(value)
        filtered_time(clauses,values,'created_at',start,end)
        with database_connection() as db:
            require_identity(db,self.user_id)
            return {**page_query(db,'request_id,route_template,method,status,elapsed_ms,user_id,task_id,error_code,created_at',
                'operational_request_events',clauses,values,page,page_size,'created_at DESC,request_id DESC'),'coverage':coverage(db)}

    def audits(self, *, page=1,page_size=10,target_user_id=None,actor_user_id=None,start=None,end=None):
        start,end=bounds(start,end);clauses=[];values=[]
        for name,value in (('target_user_id',target_user_id),('actor_user_id',actor_user_id)):
            if value is not None:clauses.append(name+'=%s');values.append(value)
        filtered_time(clauses,values,'effective_at',start,end,epoch=True)
        with database_connection() as db:
            require_identity(db,self.user_id)
            return {**page_query(db,'id,source,operator,actor_user_id,target_user_id,before_role,after_role,before_active,after_active,reason,effective_at,request_id',
                'admin_audit_events',clauses,values,page,page_size,'effective_at DESC,id DESC'),'coverage':coverage(db)}

    def metrics(self, *, start=None,end=None):
        start,end=bounds(start,end);clauses=[];values=[]
        filtered_time(clauses,values,'created_at',start,end)
        condition=' WHERE '+' AND '.join(clauses) if clauses else ''
        with database_connection() as db:
            require_identity(db,self.user_id)
            counts=db.execute('''SELECT count(*) AS requests,count(*) FILTER(WHERE status>=400) AS errors,
                count(*) FILTER(WHERE status=429) AS rate_limited,
                count(*) FILTER(WHERE method='POST' AND route_template='/api/v1/tasks/{task_id}/retry') AS retry_requests,
                count(*) FILTER(WHERE method='POST' AND route_template='/api/v1/tasks/{task_id}/resume') AS resume_requests
                FROM operational_request_events'''+condition,tuple(values)).fetchone()
            from app.domain.admin_usage import usage_summary
            usage=usage_summary(db,{'start':start,'end':end})
            return dict(counts,coverage=coverage(db),period=period(start,end),model_calls=usage['summary']['call_count'],
                tool_calls=usage['summary']['tool_call_count'],
                tool_calls_unknown_count=usage['summary']['tool_call_unknown_count'],
                configured_tool_call_count=usage['summary']['configured_tool_call_count'],
                observed_actual_tool_uses=usage['summary']['observed_actual_tool_uses'],
                actual_tool_usage_known_calls=usage['summary']['actual_tool_usage_known_calls'],
                actual_tool_usage_unknown_calls=usage['summary']['actual_tool_usage_unknown_calls'],
                model_calls_by_provenance={key:value['call_count'] for key,value in usage['by_provenance'].items()})


def record_request(event,task_candidate=None):
    """Only telemetry is fail-open at caller. Never read any research content here."""
    with database_connection(write=True, capture=True) as db:
        ensure_schema_current(db)
        user_id=event.get('user_id')
        if user_id and not db.execute('SELECT id FROM users WHERE id=%s',(user_id,)).fetchone():
            event['user_id']=None;user_id=None
        task_id=None
        if user_id and task_candidate:
            row=db.execute('''SELECT t.id FROM tasks t JOIN users u ON u.id=%s
                WHERE t.id=%s AND u.active AND (t.user_id=u.id OR (u.role='admin' AND %s))''',
                (user_id,task_candidate,bool(event.get('route_template','') and event['route_template'].startswith('/api/v1/admin/tasks')))).fetchone()
            task_id=row['id'] if row else None
        fields=('request_id','route_template','method','status','elapsed_ms','user_id','task_id','error_code','created_at')
        event['task_id']=task_id
        db.execute('INSERT INTO operational_request_events('+','.join(fields)+') VALUES('+','.join(['%s']*len(fields))+')',
                   tuple(event.get(key) for key in fields))
