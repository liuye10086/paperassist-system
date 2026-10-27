"""Read-only reporting over existing calls, observations, prices and reservations."""
from datetime import timezone

from app.adapters.model_usage_store import ModelUsageStore
from app.core.exceptions import StorageError
from app.db.database import database_connection
from app.domain.admin_operations import bounds,filtered_time,period,require_identity
from app.domain.model_usage.accounting import accounting_projection,public_reconciliation
from app.domain.model_usage.tool_evidence import tool_count

PROVENANCES=('openai_live','synthetic_fixture','unknown')
TOKEN_FIELDS=('input_tokens','output_tokens','total_tokens')


def provider_provenance(call):
    """Synthetic evidence wins. Arbitrary provider IDs or environments prove no live spend."""
    for container in (call.get('input_snapshot'),call.get('provider_state'),call.get('policy_snapshot')):
        if not isinstance(container,dict):continue
        if any(container.get(key) is True for key in ('synthetic_fixture','synthetic','fixture','synthetic_scope')):
            return 'synthetic_fixture'
        if any(container.get(key)=='synthetic_fixture' for key in
               ('provider_provenance','writing_provider_provenance','source_kind','scope','provenance')):
            return 'synthetic_fixture'
    state=call.get('provider_state') or {}
    return ('openai_live' if state.get('writing_provider_provenance')=='openai_live'
            and call.get('task_type')=='manuscript_writing'
            and call.get('workflow_version')=='manuscript_writing_v2' else 'unknown')


def empty_summary():
    result={key:0 for key in ('call_count','estimated_micro_usd','estimated_unknown_count','actual_known_micro_usd',
        'actual_unknown_count','reconciled_count','partial_count','pending_count','not_applicable_count',
        'reserved_micro_usd','accounted_micro_usd','tool_call_count','tool_call_unknown_count',
        'configured_tool_call_count','observed_actual_tool_uses','actual_tool_usage_known_calls','actual_tool_usage_unknown_calls')}
    result['actual_micro_usd']=0
    for key in TOKEN_FIELDS:result[key]={'known':0,'unknown_count':0}
    return result


def empty_totals():
    return {'summary':empty_summary(),'by_provenance':{key:empty_summary() for key in PROVENANCES}}


def add_call(summary,call):
    summary['call_count']+=1
    estimate=call['estimated_cost_micro_usd']
    if estimate is None:summary['estimated_unknown_count']+=1
    else:summary['estimated_micro_usd']+=estimate
    recon=call['reconciliation'];summary[recon['status']+'_count']+=1
    summary['actual_known_micro_usd']+=recon['actual_micro_usd'] or 0
    if recon['status'] not in ('reconciled','not_applicable'):summary['actual_unknown_count']+=1
    summary['actual_micro_usd']=None if summary['actual_unknown_count'] else summary['actual_known_micro_usd']
    summary['reserved_micro_usd']+=call['reserved_micro_usd']
    summary['accounted_micro_usd']+=call['accounted_micro_usd']
    summary['tool_call_count']+=call['tool_call_known_count']
    summary['tool_call_unknown_count']+=int(call['tool_call_count'] is None)
    summary['configured_tool_call_count']+=call['configured_tool_call_count']
    summary['observed_actual_tool_uses']+=call['tool_call_known_count']
    summary['actual_tool_usage_known_calls']+=int(call['tool_call_count'] is not None)
    summary['actual_tool_usage_unknown_calls']+=int(call['tool_call_count'] is None)
    for name in TOKEN_FIELDS:
        if call[name] is None:summary[name]['unknown_count']+=1
        else:summary[name]['known']+=call[name]


def token_projection(usage):
    usage=usage or {}
    tokens={name:usage.get(name) for name in TOKEN_FIELDS}
    for name,value in tokens.items():
        if type(value) is not int or not 0<=value<=1_000_000_000_000:tokens[name]=None
    # A normalized observation with contradictory totals cannot prove a token amount.
    if tokens['input_tokens'] is not None and tokens['output_tokens'] is not None:
        total=tokens['input_tokens']+tokens['output_tokens']
        if tokens['total_tokens'] is None:tokens['total_tokens']=total
        elif tokens['total_tokens']!=total:tokens={name:None for name in TOKEN_FIELDS}
    return tokens


def call_projection(row):
    tools,tools_unknown=tool_count(row)
    tokens=token_projection(row['provider_usage'])
    reservation={'reserved_micro_usd':row['reservation_reserved'] or 0,
                 'accounted_micro_usd':row['reservation_accounted'] or 0,'status':row['reservation_status']}
    accounted,reserved=accounting_projection(dict(row),reservation)
    fields=('id','user_id','user_email','project_id','task_id','task_type','model','status',
            'estimated_cost_micro_usd','created_at','updated_at')
    return {**{key:row[key] for key in fields},**tokens,
        'tool_call_count':None if tools_unknown else tools,'tool_call_known_count':tools,
        'configured_tool_call_count':int(bool(row['policy_snapshot'].get('tools'))),
        'observed_actual_tool_uses':tools,'actual_tool_usage_known_calls':int(not tools_unknown),
        'actual_tool_usage_unknown_calls':int(tools_unknown),
        'provider_provenance':provider_provenance(row),
        'reconciliation':public_reconciliation(dict(row),row['reconciled_at']),
        'reserved_micro_usd':reserved,'accounted_micro_usd':accounted}


CALL_SOURCE='''model_calls c JOIN users u ON u.id=c.user_id
    JOIN tasks t ON t.id=c.task_id AND t.user_id=c.user_id AND t.project_id=c.project_id
    JOIN projects p ON p.id=c.project_id AND p.owner_id=c.user_id
    LEFT JOIN LATERAL (SELECT e.provider_usage FROM (
        SELECT DISTINCT ON (event_digest) provider_usage,created_at,id FROM usage_events
        WHERE call_id=c.id AND event_type='observation'
        ORDER BY event_digest,created_at,id) e
        ORDER BY e.created_at DESC,e.id DESC LIMIT 1) latest ON true
    LEFT JOIN LATERAL (SELECT r.reserved_micro_usd,r.accounted_micro_usd,r.status
        FROM budget_reservations r JOIN model_budgets b ON b.id=r.budget_id
        WHERE r.call_id=c.id ORDER BY CASE b.scope_type WHEN 'user' THEN 0 WHEN 'project' THEN 1 ELSE 2 END,b.id LIMIT 1) reservation ON true'''
CALL_SELECT='''c.*,u.email AS user_email,t.task_type,t.workflow_version,t.input_snapshot,latest.provider_usage,
    reservation.reserved_micro_usd AS reservation_reserved,reservation.accounted_micro_usd AS reservation_accounted,
    reservation.status AS reservation_status,
    (SELECT max(e.created_at) FROM usage_events e WHERE e.call_id=c.id AND e.event_type='reconciliation') AS reconciled_at'''


def calls_query(filters):
    clauses=[];values=[]
    for key in ('user_id','project_id','task_id','model'):
        if filters.get(key) is not None:clauses.append('c.'+key+'=%s');values.append(filters[key])
    filtered_time(clauses,values,'c.created_at',filters.get('start'),filters.get('end'))
    return 'SELECT '+CALL_SELECT+' FROM '+CALL_SOURCE+(' WHERE '+' AND '.join(clauses) if clauses else '')+' ORDER BY c.created_at DESC,c.id DESC',tuple(values)


def group_key(call,group_by):
    if group_by in ('day','month'):
        return call['created_at'].astimezone(timezone.utc).strftime('%Y-%m-%d' if group_by=='day' else '%Y-%m')
    return call[{'user':'user_id','project':'project_id','task':'task_id','model':'model'}[group_by]]


def usage_summary(db,filters, *, group_by=None,page=1,page_size=10,group_page=1,group_page_size=50):
    totals=empty_totals();groups={};items=[]
    query,values=calls_query(filters)
    # Reporting reads only persisted source rows. No new balance or summary ledger.
    for index,row in enumerate(db.execute(query,values)):
        call=call_projection(row)
        add_call(totals['summary'],call);add_call(totals['by_provenance'][call['provider_provenance']],call)
        if (page-1)*page_size<=index<page*page_size:items.append(call)
        if group_by:
            key=group_key(call,group_by)
            if key not in groups:groups[key]=empty_totals()
            add_call(groups[key]['summary'],call);add_call(groups[key]['by_provenance'][call['provider_provenance']],call)
    keys=sorted(groups)
    return dict(**totals,items=items,total=totals['summary']['call_count'],page=page,page_size=page_size,
        group_by=group_by,groups=[dict(key=key,**groups[key]) for key in keys[(group_page-1)*group_page_size:group_page*group_page_size]],
        group_total=len(groups),group_page=group_page,group_page_size=group_page_size)


class UsageReporting:
    def __init__(self,user_id, *, admin=False):self.user_id=user_id;self.admin=admin

    def read(self, *, user_id=None,project_id=None,task_id=None,model=None,start=None,end=None,
             page=1,page_size=10,group_by='model',group_page=1,group_page_size=50):
        start,end=bounds(start,end)
        if not self.admin:user_id=self.user_id
        with database_connection() as db:
            require_identity(db,self.user_id,admin=self.admin)
            if user_id is not None and not db.execute('SELECT id FROM users WHERE id=%s',(user_id,)).fetchone():
                raise StorageError('admin_user_not_found','账号不存在。',404)
            if project_id:
                project=db.execute('SELECT id,owner_id FROM projects WHERE id=%s',(project_id,)).fetchone()
                if not project or (not self.admin and project['owner_id']!=self.user_id):
                    raise StorageError('project_not_found','项目不存在。',404)
                if user_id and project['owner_id']!=user_id:
                    raise StorageError('admin_query_invalid','用户与项目筛选范围不一致。',422)
            if task_id:
                task=db.execute('SELECT id,user_id,project_id FROM tasks WHERE id=%s',(task_id,)).fetchone()
                if not task or (not self.admin and task['user_id']!=self.user_id):
                    raise StorageError('task_not_found','任务不存在。',404)
                if (user_id and task['user_id']!=user_id) or (project_id and task['project_id']!=project_id):
                    raise StorageError('admin_query_invalid','任务与用户或项目筛选范围不一致。',422)
            filters=dict(user_id=user_id,project_id=project_id,task_id=task_id,model=model,start=start,end=end)
            result=usage_summary(db,filters,group_by=group_by,page=page,page_size=page_size,
                                 group_page=group_page,group_page_size=group_page_size)
            budget_rows=db.execute("SELECT * FROM model_budgets WHERE scope_type='user'"+
                (' AND user_id=%s' if user_id else '')+' ORDER BY user_id',(user_id,) if user_id else ()).fetchall()
            budgets=[dict(user_id=row['user_id'],scope_key=row['scope_key'],**ModelUsageStore.budget_view(db,'user',dict(row))) for row in budget_rows]
            if user_id and not budgets:
                budgets=[dict(user_id=user_id,scope_key=user_id,**ModelUsageStore.budget_view(db,'user',None))]
            return dict(**result,currency='USD',period=period(start,end),
                coverage=dict(scope='persisted_unified_model_calls',historical_missing_is_zero=False),
                user_charge_enabled=False,quota={'configured':False},budget_scope='cumulative_unfiltered',budgets=budgets)
