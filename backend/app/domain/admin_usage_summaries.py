"""Sealed captures with independently replayed immutable observations, never balances."""
from datetime import datetime
from uuid import uuid4
import json
from psycopg.types.json import Jsonb
from app.db.database import database_connection
from app.core.exceptions import StorageError
from app.domain.admin_operations import require_identity,bounds
from app.domain.admin_configuration.catalog import digest
from app.domain.admin_usage import calls_query,call_projection,token_projection,empty_totals,add_call,group_key
from app.domain.model_usage.accounting import public_reconciliation

REVISION='admin-usage-capture-v1'
IDENTITY=('id','user_id','project_id','task_id','model','input_digest','created_at','policy_snapshot','price_snapshot')


def safe_json(value):
    return json.loads(json.dumps(value,default=lambda x:x.isoformat() if isinstance(x,datetime) else str(x),sort_keys=True))


def fingerprint(value):return digest(safe_json(value))


def priced_observation(event):
    from app.domain.model_usage.contracts import PriceSnapshot
    from app.domain.model_usage.pricing import estimate_usage
    if event['event_type']!='observation':return None
    # A tool fee is not recoverable from normalized token usage; do not invent it.
    value=estimate_usage(PriceSnapshot.model_validate(event['price_snapshot']),event['provider_usage'])
    return dict(id=event['id'],token_estimate_micro_usd=value['estimated_cost_micro_usd'])


def selected_observation(events):
    unique={}
    for event in sorted(events,key=lambda e:(e['created_at'],e['id'])):
        if event['event_type']=='observation':unique.setdefault(event['event_digest'],event)
    return max(unique.values(),key=lambda e:(e['created_at'],e['id']),default=None)


def reconciliation_projection(events,policy,captured_status):
    reconciliations=[e for e in events if e['event_type']=='reconciliation']
    # Revisions define append order, including equal timestamps and random IDs.
    latest=max(reconciliations,key=lambda e:e['reconciliation']['revision'],default=None)
    actual=latest['reconciliation']['actual_micro_usd'] if latest else {}
    # Status is explicitly historical capture; amounts, tool applicability and
    # timestamp come only from the immutable original sources, never today's call.
    call=dict(status=captured_status,policy_snapshot=policy,
        actual_token_micro_usd=actual.get('token_micro_usd'),actual_tool_micro_usd=actual.get('tool_micro_usd'))
    reconciled_at=max((e['created_at'] for e in reconciliations),default=None)
    return safe_json(public_reconciliation(call,reconciled_at))


def totals(calls,group_by):
    result=empty_totals();groups={}
    for call in calls:
        add_call(result['summary'],call);add_call(result['by_provenance'][call['provider_provenance']],call)
        local={**call,'created_at':datetime.fromisoformat(call['created_at'])}
        key=group_key(local,group_by)
        group=groups.setdefault(key,empty_totals())
        add_call(group['summary'],call);add_call(group['by_provenance'][call['provider_provenance']],call)
    return dict(**result,groups=[dict(key=k,**groups[k]) for k in sorted(groups)],group_by=group_by,
        total=len(calls),currency='USD',coverage=dict(immutable_recomputed=['tokens','observed_estimates','reconciled_components'],
        captured_mutable=['call_status','accounted_micro_usd','reserved_micro_usd','tool_evidence','provenance'],
        excludes=['budget_balances','available_quota','research_snapshots','provider_response'],historical_missing_is_zero=False))


def seal(row):
    return fingerprint({k:row[k] for k in ('asof','filters','source_revision','result','source_manifest')})


class UsageSummaries:
    def __init__(self,user_id):self.user_id=user_id

    def save(self,**filters):
        group_by=filters.pop('group_by','model');start,end=bounds(filters.get('start'),filters.get('end'))
        filters.update(start=start,end=end)
        with database_connection(write=True) as db:
            require_identity(db,self.user_id,admin=True)
            user_id,project_id,task_id=(filters.get(k) for k in ('user_id','project_id','task_id'))
            if user_id and not db.execute('SELECT id FROM users WHERE id=%s',(user_id,)).fetchone():
                raise StorageError('admin_user_not_found','账号不存在。',404)
            if project_id:
                project=db.execute('SELECT owner_id FROM projects WHERE id=%s',(project_id,)).fetchone()
                if not project:raise StorageError('project_not_found','项目不存在。',404)
                if user_id and project['owner_id']!=user_id:raise StorageError('admin_query_invalid','用户与项目筛选范围不一致。',422)
            if task_id:
                task=db.execute('SELECT user_id,project_id FROM tasks WHERE id=%s',(task_id,)).fetchone()
                if not task:raise StorageError('task_not_found','任务不存在。',404)
                if (user_id and task['user_id']!=user_id) or (project_id and task['project_id']!=project_id):
                    raise StorageError('admin_query_invalid','任务筛选范围不一致。',422)
            asof=db.execute('SELECT clock_timestamp() AS now').fetchone()['now']
            query,values=calls_query(filters);entries=[];calls=[]
            for raw in db.execute(query,values):
                if raw['created_at']>asof:continue
                events=[dict(e) for e in db.execute('SELECT * FROM usage_events WHERE call_id=%s AND created_at<=%s ORDER BY created_at,id',(raw['id'],asof))]
                chosen=selected_observation(events)
                call=safe_json(call_projection({**raw,'provider_usage':chosen['provider_usage'] if chosen else None}))
                calls.append(call)
                entries.append(dict(call_id=raw['id'],identity_sha256=fingerprint({k:raw[k] for k in IDENTITY}),
                    selected_observation_id=chosen['id'] if chosen else None,
                    priced_observations=[priced_observation(e) for e in events if e['event_type']=='observation'],
                    events=[dict(id=e['id'],event_type=e['event_type'],created_at=e['created_at'].isoformat(),sha256=fingerprint(e)) for e in events],
                    captured_projection=call,captured_projection_sha256=fingerprint(call)))
            row=dict(id=str(uuid4()),asof=asof,filters=safe_json(dict(**filters,group_by=group_by)),source_revision=REVISION,
                result=totals(calls,group_by),source_manifest=dict(schema_version=1,calls=entries))
            row['sha256']=seal(row)
            db.execute('INSERT INTO admin_usage_summaries(id,actor_user_id,asof,filters,source_revision,result,source_manifest,sha256) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                (row['id'],self.user_id,asof,Jsonb(row['filters']),REVISION,Jsonb(row['result']),Jsonb(row['source_manifest']),row['sha256']))
            return {k:v for k,v in row.items() if k!='source_manifest'}

    def _row(self,db,identity):
        require_identity(db,self.user_id,admin=True)
        row=db.execute('SELECT * FROM admin_usage_summaries WHERE id=%s',(identity,)).fetchone()
        if not row:raise StorageError('admin_usage_summary_not_found','保存的用量汇总不存在。',404)
        return dict(row)

    def list(self,page=1,page_size=10):
        with database_connection() as db:
            require_identity(db,self.user_id,admin=True)
            total=db.execute('SELECT count(*) AS n FROM admin_usage_summaries').fetchone()['n']
            rows=db.execute('SELECT id,created_at,asof,filters,source_revision,sha256,result FROM admin_usage_summaries ORDER BY created_at DESC,id DESC LIMIT %s OFFSET %s',(page_size,(page-1)*page_size)).fetchall()
            return dict(items=[{**r,'result':{'summary':r['result']['summary']}} for r in rows],total=total,page=page,page_size=page_size)

    def detail(self,identity,page=1,page_size=10,group_page=1,group_page_size=50):
        with database_connection() as db:
            row=self._row(db,identity);entries=row.pop('source_manifest')['calls']
            groups=row['result']['groups'];row['result']={**row['result'],'groups':groups[(group_page-1)*group_page_size:group_page*group_page_size]}
            return dict(**row,items=[e['captured_projection'] for e in entries[(page-1)*page_size:page*page_size]],
                total=len(entries),page=page,page_size=page_size,group_total=len(groups),group_page=group_page,group_page_size=group_page_size)

    def verify(self,identity):
        with database_connection() as db:
            row=self._row(db,identity);errors=[];calls=[]
            if row['source_revision']!=REVISION or seal(row)!=row['sha256']:errors.append('capture_hash_mismatch')
            for entry in row['source_manifest']['calls']:
                raw=db.execute('SELECT * FROM model_calls WHERE id=%s',(entry['call_id'],)).fetchone()
                if not raw or fingerprint({k:raw[k] for k in IDENTITY})!=entry['identity_sha256']:
                    errors.append('call_identity_mismatch');continue
                events=[]
                for ref in entry['events']:
                    event=db.execute('SELECT * FROM usage_events WHERE id=%s AND call_id=%s',(ref['id'],entry['call_id'])).fetchone()
                    if not event or fingerprint(dict(event))!=ref['sha256'] or event['created_at']>row['asof']:
                        errors.append('usage_source_mismatch');continue
                    events.append(dict(event))
                chosen=selected_observation(events)
                if [priced_observation(e) for e in events if e['event_type']=='observation']!=entry['priced_observations']:
                    errors.append('frozen_price_projection_mismatch')
                if (chosen['id'] if chosen else None)!=entry['selected_observation_id']:errors.append('observation_selection_mismatch')
                captured=entry['captured_projection'];recomputed={**captured,**token_projection(chosen['provider_usage'] if chosen else None)}
                if fingerprint(captured)!=entry['captured_projection_sha256'] or recomputed!=captured:errors.append('token_projection_mismatch')
                # Original estimates are frozen at the first fully estimated receipt.
                observations=[e for e in events if e['event_type'] in ('observation','release')]
                settled=next((e for e in observations if e['usage_status']=='estimated'),None)
                known=[e['estimated_cost_micro_usd'] for e in observations if e['estimated_cost_micro_usd'] is not None]
                estimate=settled['estimated_cost_micro_usd'] if settled else max(known,default=None)
                if estimate!=captured['estimated_cost_micro_usd']:errors.append('estimate_projection_mismatch')
                recomputed['reconciliation']=reconciliation_projection(events,raw['policy_snapshot'],captured['status'])
                if recomputed['reconciliation']!=captured['reconciliation']:
                    errors.append('reconciliation_projection_mismatch')
                calls.append(recomputed)
            rebuilt=totals(calls,row['filters']['group_by'])
            if rebuilt!=row['result']:errors.append('result_mismatch')
            return dict(id=identity,verified=not errors,recomputed_immutable_fields=not errors,
                errors=sorted(set(errors)),asof=row['asof'],source_revision=REVISION,
                captured_mutable_fields=row['result']['coverage']['captured_mutable'])
