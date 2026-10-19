"""Frozen literature inputs and durable suggestion projections."""
import re
from uuid import uuid4
from psycopg.types.json import Jsonb

from app.adapters.task_store import TaskStore, source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_preparation.service import append_checkpoint
from app.domain.literature.service import digest
from app.domain.literature_assistance.contracts import WORKFLOW, request_adapter, validate_result


def require_snapshot(task):
    try:
        snapshot = task['input_snapshot']
        request = request_adapter.validate_python(snapshot['input']).model_dump(mode='json')
        if (task['task_type'] != 'literature_assistance' or task['workflow_version'] != WORKFLOW
                or set(snapshot) != {'schema_version','project_id','workflow_version','input','material'}
                or type(snapshot['schema_version']) is not int or snapshot['schema_version'] != (2 if request['kind']=='evidence_comparison' else 1)
                or snapshot['workflow_version'] != WORKFLOW or snapshot['project_id'] != task['project_id']
                or snapshot['input'] != request or not isinstance(snapshot['material'], dict)
                or digest(snapshot) != task['input_digest']):
            raise ValueError()
        if request['kind'] == 'evidence_comparison':
            material = snapshot['material']
            if (material['project_id'] != task['project_id'] or material['claim']['id'] != request['claim_id']
                or material['claim']['revision'] != request['claim_revision']
                or material['output_language'] != request['output_language']
                or [e['id'] for e in material['evidence']] != request['evidence_ids']
                or len({e['project_reference_id'] for e in material['evidence']}) < 2
                or {r['id'] for r in material['references']} != {e['project_reference_id'] for e in material['evidence']}):
                raise ValueError()
        elif request['kind'] == 'evidence_review':
            material = snapshot['material']
            if (material['project_id'] != task['project_id'] or material['claim']['id'] != request['claim_id']
                    or material['claim']['revision'] != request['claim_revision']
                    or material['project_reference_id'] != request['project_reference_id']
                    or material['output_language'] != request['output_language']
                    or {e['id'] for e in material['evidence']} != set(request['evidence_ids'])):
                raise ValueError()
        elif snapshot['material'] != request:
            raise ValueError()
        return snapshot
    except (KeyError,TypeError,ValueError) as exc:
        raise source_conflict() from exc


def input_version(task):
    snapshot = require_snapshot(task)
    return dict(kind='literature_assistance', workflow_version=WORKFLOW,
                assistance_kind=snapshot['input']['kind'], input_digest=task['input_digest'],
                output_language=snapshot['input']['output_language'])


def checkpoint(db, task):
    require_snapshot(task)
    row = db.execute('SELECT * FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1', (task['id'],)).fetchone()
    if not row or row['next_node'] not in ('check','await_confirmation','done'):
        raise source_conflict()
    state = row['state_json']
    if (type(state.get('schema_version')) is not int or state.get('schema_version') != 1 or state.get('input_digest') != task['input_digest']
            or set(state) != {'schema_version','input_digest'}):
        raise source_conflict()
    return dict(row)


def last_call(db, task_id):
    row = db.execute('SELECT * FROM model_calls WHERE task_id=%s ORDER BY created_at DESC,id LIMIT 1', (task_id,)).fetchone()
    return dict(row) if row else None


def saved_calls(db, task):
    """Narrow stored facts only: neither model names nor prices establish provenance."""
    rows = db.execute('''SELECT c.*,
        (SELECT e.provider_usage FROM usage_events e WHERE e.call_id=c.id
         AND e.provider_usage IS NOT NULL ORDER BY e.created_at DESC,e.id DESC LIMIT 1) AS saved_usage
        FROM model_calls c WHERE c.task_id=%s AND c.project_id=%s AND c.user_id=%s
        ORDER BY c.created_at,c.id''', (task['id'],task['project_id'],task['user_id'])).fetchall()
    result=[]
    for row in rows:
        raw=row['saved_usage']
        usage=None
        if isinstance(raw,dict):
            details=raw.get('input_tokens_details')
            usage={key:raw.get(key) for key in ('input_tokens','output_tokens','total_tokens')}
            usage['cached_input_tokens']=details.get('cached_tokens') if isinstance(details,dict) else None
            usage={key:value if type(value) is int and value>=0 else None for key,value in usage.items()}
        result.append(dict(model=row['model'],status=row['status'],provider_status=row['provider_status'],
            error_code=row['error_code'],provenance='not_recorded',usage_status=row['usage_status'],usage=usage,
            estimated_cost_micro_usd=row['estimated_cost_micro_usd'],created_at=row['created_at'].isoformat()))
    return result


def recovery_actions(db, task):
    # There is deliberately no route that grants real-model authorization.
    if task['status'] == 'waiting_confirmation' and task['reason_code'] == 'budget_exceeded':
        from app.domain.tasks.waits import get_open_wait
        saved = get_open_wait(db,task)
        return ['resume'] if saved and saved['kind']=='budget_confirmation' and saved['task_revision']==task['revision'] else []
    call = last_call(db, task['id'])
    if task['status'] == 'failed' and task.get('error_code') in ('storage_unavailable','task_worker_interrupted','model_provider_unavailable'):
        return ['retry'] if not call or call.get('provider_response_id') else []
    return []


def retry_in_transaction(store, db, task, expected_revision):
    from app.domain.tasks.waits import resolve_open_wait
    action = 'resume' if task['status'] == 'waiting_confirmation' else 'retry'
    if task['revision'] != expected_revision or action not in recovery_actions(db, task):
        raise StorageError('task_transition_invalid','当前建议任务不能恢复。',409)
    db.execute('SELECT id FROM projects WHERE id=%s FOR UPDATE',(task['project_id'],)).fetchone()
    service = LiteratureAssistanceService(store)
    service.assert_current(task)
    previous = checkpoint(db, task)
    revision = task['revision']
    now = db.execute('SELECT clock_timestamp() AS now').fetchone()['now']
    task.update(status='queued', revision=revision+1, retry_count=0, reason_code='retry_requested' if action=='retry' else 'confirmation_received',
                error_code=None, updated_at=max(now,task['updated_at']),
                _retry_reason='manual_retry')
    if previous['next_node'] == 'await_confirmation':
        append_checkpoint(db,task,'check','check',previous['state_json'],previous)
    store.update_task(db,task,revision)
    resolve_open_wait(db,task)
    store.append_event(db,task,'requeued');store.enqueue(db,task)
    return store.public_task(task)


class LiteratureAssistanceService:
    def __init__(self, assets):
        self.assets = assets
        self.store = assets if isinstance(assets,TaskStore) else TaskStore(assets.owner_id,assets.db_config)

    def evidence(self):
        from app.domain.literature_evidence.service import LiteratureEvidenceService
        if isinstance(self.assets,TaskStore):
            from app.adapters.task_store import DatasetTaskAssets
            return LiteratureEvidenceService(DatasetTaskAssets(self.store.user_id,self.store.config))
        return LiteratureEvidenceService(self.assets)

    def assert_current(self, task):
        snapshot = require_snapshot(task)
        if snapshot['input']['kind'] in ('evidence_review','evidence_comparison'):
            try:
                if snapshot['input']['kind'] == 'evidence_comparison':
                    self.evidence().assert_comparison_inputs_current(task['project_id'],snapshot['material'])
                else:
                    self.evidence().assert_assistance_inputs_current(task['project_id'],snapshot['material'])
            except StorageError as exc:
                if exc.status in (404,409): raise source_conflict() from exc
                raise
        return snapshot

    def create(self, project_id, request, key):
        if not isinstance(key,str) or not re.fullmatch(r'[!-~]{1,128}',key):
            raise StorageError('task_input_invalid','建议请求标识无效。',422)
        material = request_adapter.validate_python(request.model_dump(mode='json')).model_dump(mode='json')
        with self.store.connection(write=True) as db:
            self.store.require_project(db,project_id)
            db.execute('SELECT id FROM projects WHERE id=%s FOR UPDATE',(project_id,)).fetchone()
            # Same-key replays preserve old inputs and historical proposals.
            existing = self.store.find_request(db,project_id,'literature_assistance',key)
            if existing:
                if require_snapshot(existing)['input'] != material:
                    raise StorageError('task_idempotency_conflict','同一请求标识已用于不同建议输入。',409)
                return self.store.public_task(existing),200
            if material['kind']=='evidence_comparison': frozen=self.evidence().comparison_snapshot(project_id,material)
            else: frozen = self.evidence().assistance_snapshot(project_id,material) if material['kind']=='evidence_review' else material
            snapshot = dict(schema_version=2 if material['kind']=='evidence_comparison' else 1,project_id=project_id,workflow_version=WORKFLOW,input=material,material=frozen)
            now = db.execute('SELECT clock_timestamp() AS now').fetchone()['now']
            task = dict(id=str(uuid4()),project_id=project_id,user_id=self.store.user_id,task_type='literature_assistance',
                idempotency_key=key,input_digest=digest(snapshot),input_snapshot=snapshot,workflow_version=WORKFLOW,
                status='queued',phase='plan' if material['kind']=='search_plan' else 'verify',revision=1,current_attempt=0,
                reason_code=None,created_at=now,updated_at=now)
            self.store.insert_task(db,task)
            db.execute('''INSERT INTO literature_assistance_requests(task_id,project_id,user_id,kind,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s)''',(task['id'],project_id,task['user_id'],material['kind'],now,now))
            append_checkpoint(db,task,'check','check',dict(schema_version=1,input_digest=task['input_digest']))
            self.store.append_event(db,task,'created');self.store.enqueue(db,task)
            return self.store.public_task(task),202

    def view(self, db, project_id, task_id):
        self.store.require_project(db,project_id)
        task = self.store.require_task(db,task_id)
        if task['task_type'] != 'literature_assistance' or task['project_id'] != project_id:
            raise StorageError('task_not_found','建议任务不存在。',404)
        snapshot = require_snapshot(task);checkpoint(db,task)
        row = db.execute('SELECT * FROM literature_assistance_requests WHERE task_id=%s AND project_id=%s AND user_id=%s',
                         (task_id,project_id,task['user_id'])).fetchone()
        if not row or row['kind'] != snapshot['input']['kind']:
            raise source_conflict()
        result = row['result_json']
        if result is not None:
            try: validate_result(result,snapshot)
            except ValueError as exc: raise source_conflict() from exc
        return dict(task=self.store.public_task(task),kind=row['kind'],input_version=input_version(task),result=result,
                    real_calls_enabled=False,model_calls=saved_calls(db,task))

    def get(self, project_id, task_id):
        with self.store.connection() as db:
            return self.view(db,project_id,task_id)

    def list(self, project_id, page=1):
        with self.store.connection() as db:
            self.store.require_project(db,project_id)
            total = db.execute('SELECT count(*) AS n FROM literature_assistance_requests WHERE project_id=%s AND user_id=%s',
                               (project_id,self.store.user_id)).fetchone()['n']
            rows = db.execute('''SELECT task_id FROM literature_assistance_requests WHERE project_id=%s AND user_id=%s
                ORDER BY created_at DESC,task_id LIMIT 10 OFFSET %s''',(project_id,self.store.user_id,(page-1)*10)).fetchall()
            return dict(project_id=project_id,items=[self.view(db,project_id,r['task_id']) for r in rows],total=total,page=page,page_size=10)
