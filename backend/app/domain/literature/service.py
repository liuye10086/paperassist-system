"""Owner-scoped retrieval snapshots and explicit project candidate decisions."""
from datetime import timezone
import hashlib
import json
import re
from urllib.parse import quote
from uuid import uuid4

from psycopg.types.json import Jsonb

from app.adapters.task_store import TaskStore, source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_preparation.service import append_checkpoint
from app.domain.literature.contracts import SearchRequest, WORKFLOW, effective_query
from app.domain.literature.objects import LiteratureObjects
from app.domain.admin_configuration.bindings import resolve, bind


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def require_snapshot(task):
    try:
        snapshot = task['input_snapshot']
        request = SearchRequest.model_validate(snapshot['input']).model_dump(mode='json')
        if (task['task_type'] != 'literature_search' or task['workflow_version'] != WORKFLOW
                or set(snapshot) != {'schema_version', 'input', 'effective_query', 'project_id', 'workflow_version'}
                or type(snapshot['schema_version']) is not int or snapshot['schema_version'] != 1
                or snapshot['project_id'] != task['project_id'] or snapshot['workflow_version'] != WORKFLOW
                or snapshot['input'] != request or snapshot['effective_query'] != effective_query(SearchRequest.model_validate(request))
                or digest(snapshot) != task['input_digest']):
            raise ValueError()
        return snapshot
    except (KeyError, TypeError, ValueError) as exc:
        raise source_conflict() from exc


def input_version(task):
    snapshot = require_snapshot(task)
    return dict(kind='literature_search', workflow_version=WORKFLOW, search_id=task['id'],
                input_digest=task['input_digest'], output_language=snapshot['input']['output_language'])


def task_configuration(db, task):
    """Legacy numeric defaults are known; never invent a historical identity."""
    from app.domain.admin_configuration.contracts import Ncbi
    version = resolve(db, kind='task', object_id=task['id'])
    return (version['bundle']['ncbi'] if version else Ncbi().model_dump()), version


def configuration(db=None, task=None):
    from app.adapters.ncbi import get_ncbi_settings, NcbiError
    if db is None:
        from app.db.database import database_connection
        with database_connection() as connection:
            return configuration(connection, task)
    version = task_configuration(db, task)[1] if task is not None else resolve(db)
    try:
        settings = get_ncbi_settings(version=version)
        available = settings.enabled
    except NcbiError:
        available = False
    return dict(available=available, reason=None if available else 'ncbi_not_configured',
        candidate_limits=[20, 50, 100], default_limit=20, page_size=10,
        publication_types=['Clinical Trial', 'Randomized Controlled Trial', 'Review', 'Systematic Review',
                           'Meta-Analysis', 'Observational Study', 'Case Reports'],
        full_text_acquisition=False, claim_verification=False)


def latest_checkpoint(db, task):
    snapshot = require_snapshot(task)
    row = db.execute('SELECT * FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1', (task['id'],)).fetchone()
    if not row:
        raise source_conflict()
    state = row['state_json']
    search = db.execute('SELECT * FROM literature_searches WHERE task_id=%s', (task['id'],)).fetchone()
    try:
        keys = {'schema_version','input_digest','pmids','next_offset','warnings'}
        node = state.get('resume_node') if row['next_node'] == 'await_confirmation' else row['next_node']
        if (not keys <= set(state) or set(state)-keys-{'resume_node'}
                or type(state['schema_version']) is not int or state['schema_version'] != 1
                or state['input_digest'] != task['input_digest'] or node not in ('search','fetch','publish','done')
                or not isinstance(state['pmids'],list) or len(state['pmids'])>snapshot['input']['limit']
                or any(not isinstance(p,str) or not re.fullmatch(r'[1-9][0-9]{0,11}',p) for p in state['pmids'])
                or len(set(state['pmids'])) != len(state['pmids'])
                or type(state['next_offset']) is not int or not 0<=state['next_offset']<=len(state['pmids'])
                or not isinstance(state['warnings'],list) or any(not isinstance(w,str) for w in state['warnings'])
                or not search or search['project_id'] != task['project_id'] or search['user_id'] != task['user_id']
                or search['input_json'] != snapshot['input'] or search['effective_query'] != snapshot['effective_query']
                or search['pmids_json'] != state['pmids']):
            raise ValueError()
        offset = state['next_offset']
        hits = db.execute('SELECT ordinal,record_json FROM literature_search_hits WHERE task_id=%s ORDER BY ordinal',(task['id'],)).fetchall()
        received = [h['record_json'].get('pmid') for h in hits]
        if (len(received) != search['retrieved_count']
                or any(not 1<=h['ordinal']<=offset or h['record_json'].get('pmid')!=state['pmids'][h['ordinal']-1] for h in hits)
                or search['missing_pmids_json'] != [p for p in state['pmids'][:offset] if p not in received]
                or len(received)+len(search['missing_pmids_json']) != offset
                or node == 'search' and (offset or state['pmids'] or search['matched_count'] is not None)
                or node != 'search' and search['matched_count'] is None
                or node == 'fetch' and (offset>=len(state['pmids']) or offset%20)
                or node in ('publish','done') and offset!=len(state['pmids'])):
            raise ValueError()
    except (TypeError,KeyError,ValueError,IndexError) as exc:
        raise source_conflict() from exc
    return dict(row)


def retry_in_transaction(store, db, task, expected_revision):
    from app.domain.tasks.waits import allowed_recovery_actions, resolve_open_wait
    actions = allowed_recovery_actions(db, task)
    if task['revision'] != expected_revision:
        raise StorageError('task_revision_conflict', '任务已变化，请重新读取。', 409)
    operation = 'resume' if task['status'] == 'waiting_confirmation' else 'retry'
    if operation not in actions:
        raise StorageError('task_transition_invalid', '当前检索任务尚不能恢复。', 409)
    checkpoint = latest_checkpoint(db, task)
    from .storage import authorize
    from app.core.config import get_data_dir
    authorize(db,get_data_dir(),task)
    now = db.execute('SELECT clock_timestamp() AS now').fetchone()['now']
    task.update(status='queued', revision=expected_revision + 1, retry_count=0,
                reason_code='confirmation_received' if operation == 'resume' else 'retry_requested',
                error_code=None, updated_at=max(now, task['updated_at']), _retry_reason='manual_retry')
    if checkpoint['next_node'] == 'await_confirmation':
        append_checkpoint(db, task, 'revise', checkpoint['state_json']['resume_node'], checkpoint['state_json'], checkpoint)
    store.update_task(db, task, expected_revision)
    resolve_open_wait(db, task)
    store.append_event(db, task, 'requeued')
    store.enqueue(db, task)
    return store.public_task(task)


class LiteratureService:
    def __init__(self, assets):
        self.assets = assets
        self.store = TaskStore(assets.owner_id, assets.db_config)
        self.objects = LiteratureObjects(assets.directory)

    def create(self, project_id, request, key):
        with self.store.connection(write=True) as db:
            return self.create_in_transaction(db, project_id, request, key)

    def create_in_transaction(self, db, project_id, request, key):
        if not isinstance(key, str) or not re.fullmatch(r'[!-~]{1,128}', key):
            raise StorageError('task_input_invalid', '检索请求标识无效。', 422)
        material = request.model_dump(mode='json')
        snapshot = dict(schema_version=1, input=material, effective_query=effective_query(request), project_id=project_id, workflow_version=WORKFLOW)
        fingerprint = digest(snapshot)
        self.store.require_project(db, project_id)
        existing = self.store.find_request(db, project_id, 'literature_search', key)
        if existing:
            if existing['input_digest'] != fingerprint:
                raise StorageError('task_idempotency_conflict', '同一检索请求标识已用于不同输入。', 409)
            return self.store.public_task(existing), 200
        version = resolve(db)
        now = db.execute('SELECT clock_timestamp() AS now').fetchone()['now']
        task = dict(id=str(uuid4()), project_id=project_id, user_id=self.store.user_id, task_type='literature_search',
            idempotency_key=key, input_digest=fingerprint, input_snapshot=snapshot, workflow_version=WORKFLOW,
            status='queued', phase='search', revision=1, current_attempt=0, reason_code=None, created_at=now, updated_at=now)
        self.store.insert_task(db, task)
        bind(db, kind='task', object_id=task['id'], version=version)
        db.execute('''INSERT INTO literature_searches
            (task_id,project_id,user_id,input_json,effective_query,pmids_json,missing_pmids_json,retrieved_count,created_at,updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,0,%s,%s)''',
            (task['id'], project_id, self.store.user_id, Jsonb(material), snapshot['effective_query'], Jsonb([]), Jsonb([]), now, now))
        state = dict(schema_version=1, input_digest=fingerprint, pmids=[], next_offset=0, warnings=[])
        append_checkpoint(db, task, 'search', 'search', state)
        self.store.append_event(db, task, 'created')
        self.store.enqueue(db, task)
        return self.store.public_task(task), 202

    def require_search(self, db, project_id, search_id):
        self.store.require_project(db, project_id)
        task = self.store.require_task(db, search_id)
        if task['task_type'] != 'literature_search' or task['project_id'] != project_id:
            raise StorageError('literature_not_found', '文献检索记录不存在。', 404)
        snapshot = require_snapshot(task)
        row = db.execute('SELECT * FROM literature_searches WHERE task_id=%s AND project_id=%s AND user_id=%s',
                         (search_id, project_id, self.store.user_id)).fetchone()
        if not row or row['input_json'] != snapshot['input'] or row['effective_query'] != snapshot['effective_query']:
            raise source_conflict()
        return task, dict(row)

    def search_view(self, db, project_id, search_id):
        task, row = self.require_search(db, project_id, search_id)
        checkpoint = latest_checkpoint(db, task)
        return dict(id=search_id, project_id=project_id, task=self.store.public_task(task), input=row['input_json'],
            effective_query=row['effective_query'], query_translation=row['query_translation'], matched_count=row['matched_count'],
            retrieved_count=row['retrieved_count'], missing_pmids=row['missing_pmids_json'], warnings=checkpoint['state_json'].get('warnings', []),
            created_at=row['created_at'], updated_at=row['updated_at'],
            source_url='https://pubmed.ncbi.nlm.nih.gov/?term=' + quote(row['effective_query'], safe=''))

    def search(self, project_id, search_id):
        with self.store.connection() as db:
            return self.search_view(db, project_id, search_id)

    def searches(self, project_id, page=1):
        with self.store.connection() as db:
            self.store.require_project(db, project_id)
            total = db.execute('SELECT count(*) AS n FROM literature_searches WHERE project_id=%s AND user_id=%s',
                               (project_id, self.store.user_id)).fetchone()['n']
            rows = db.execute('''SELECT task_id FROM literature_searches WHERE project_id=%s AND user_id=%s
                ORDER BY created_at DESC,task_id LIMIT 10 OFFSET %s''', (project_id, self.store.user_id, (page-1)*10)).fetchall()
            return dict(project_id=project_id, items=[self.search_view(db, project_id, r['task_id']) for r in rows], total=total, page=page, page_size=10)

    def require_reference(self, db, project_id, reference_id):
        self.store.require_project(db, project_id)
        row = db.execute('SELECT * FROM project_references WHERE id=%s AND project_id=%s AND user_id=%s',
                         (reference_id, project_id, self.store.user_id)).fetchone()
        if not row:
            raise StorageError('literature_not_found', '项目候选文献不存在。', 404)
        return dict(row)

    def source_view(self, row):
        return dict(search_id=row['task_id'], receipt_id=row['receipt_id'], query=row['query'],
            source_context=row.get('source_context'),
            effective_query=row['effective_query'], retrieved_at=row['attempted_at'], source_kind=row['source_kind'],
            cached=row['cached_from_id'] is not None, ordinal=row['ordinal'],
            source_download_url=f'/api/v1/projects/{quote(row["project_id"], safe="")}/literature/receipts/{quote(row["receipt_id"], safe="")}/source')

    def reference_view(self, db, row, search_id=None):
        hit = db.execute('''SELECT h.*,r.attempted_at,r.source_kind,r.cached_from_id,s.effective_query,s.input_json->>'query' AS query,
            s.input_json->'source_context' AS source_context
            FROM literature_search_hits h JOIN literature_fetch_receipts r ON r.id=h.receipt_id
            JOIN literature_searches s ON s.task_id=h.task_id WHERE h.project_reference_id=%s AND h.project_id=%s AND h.user_id=%s
            AND (%s::text IS NULL OR h.task_id=%s)
            ORDER BY h.created_at DESC,h.id LIMIT 1''', (row['id'], row['project_id'], self.store.user_id,search_id,search_id)).fetchone()
        if not hit:
            raise source_conflict()
        self.require_search(db, row['project_id'], hit['task_id'])
        record = hit['record_json']
        identity = db.execute('SELECT pmid FROM literature_records WHERE id=%s', (row['reference_id'],)).fetchone()
        if not identity or record.get('pmid') != identity['pmid']:
            raise source_conflict()
        return dict(id=row['id'], project_id=row['project_id'], reference_id=row['reference_id'], pmid=identity['pmid'], record=record,
            selection=dict(status=row['selection_status'], note=row['selection_note'], revision=row['revision']),
            source=self.source_view(hit), created_at=row['created_at'], updated_at=row['updated_at'])

    def references(self, project_id, page=1, search_id=None, selection=None):
        with self.store.connection() as db:
            self.store.require_project(db, project_id)
            source = 'project_references p'
            condition = 'p.project_id=%s AND p.user_id=%s'
            order = 'p.created_at DESC,p.id'
            values = [project_id, self.store.user_id]
            if search_id is not None:
                self.require_search(db, project_id, search_id)
                source += ' JOIN literature_search_hits h ON h.project_reference_id=p.id AND h.project_id=p.project_id AND h.user_id=p.user_id'
                condition += ' AND h.task_id=%s'
                order = 'h.ordinal'
                values.append(search_id)
            if selection is not None:
                condition += ' AND p.selection_status=%s'
                values.append(selection)
            total = db.execute('SELECT count(*) AS n FROM ' + source + ' WHERE ' + condition, tuple(values)).fetchone()['n']
            rows = db.execute('SELECT p.* FROM ' + source + ' WHERE ' + condition + ' ORDER BY ' + order + ' LIMIT 10 OFFSET %s', tuple(values+[(page-1)*10])).fetchall()
            return dict(project_id=project_id, items=[self.reference_view(db, r, search_id) for r in rows], total=total, page=page, page_size=10)

    def reference(self, project_id, reference_id, page=1, search_id=None):
        with self.store.connection() as db:
            row = self.require_reference(db, project_id, reference_id)
            if search_id is not None:
                self.require_search(db, project_id, search_id)
                hit = db.execute('''SELECT 1 FROM literature_search_hits WHERE project_reference_id=%s
                    AND task_id=%s AND project_id=%s AND user_id=%s''',
                    (reference_id, search_id, project_id, self.store.user_id)).fetchone()
                if not hit:
                    raise StorageError('literature_not_found', '该检索中不存在此候选文献。', 404)
            view = self.reference_view(db, row, search_id)
            total = db.execute('SELECT count(*) AS n FROM literature_search_hits WHERE project_reference_id=%s', (reference_id,)).fetchone()['n']
            hits = db.execute('''SELECT h.*,r.attempted_at,r.source_kind,r.cached_from_id,s.effective_query,s.input_json->>'query' AS query,
                s.input_json->'source_context' AS source_context
                FROM literature_search_hits h JOIN literature_fetch_receipts r ON r.id=h.receipt_id
                JOIN literature_searches s ON s.task_id=h.task_id WHERE h.project_reference_id=%s
                ORDER BY h.created_at DESC,h.id LIMIT 10 OFFSET %s''', (reference_id, (page-1)*10)).fetchall()
            view['sources'] = dict(items=[self.source_view(h) for h in hits], total=total, page=page, page_size=10)
            view['decisions'] = row['decisions_json']
            return view

    def select(self, project_id, reference_id, request):
        with self.store.connection(write=True) as db:
            row = self.require_reference(db, project_id, reference_id)
            same = row['selection_status'] == request.status and row['selection_note'] == request.note
            if row['revision'] != request.expected_revision and not same:
                raise StorageError('literature_revision_conflict', '候选状态已变化，请重新读取。', 409)
            if not same:
                now = db.execute('SELECT clock_timestamp() AS now').fetchone()['now']
                decisions = row['decisions_json'] + [dict(revision=row['revision']+1, status=request.status, note=request.note,
                    decided_at=now.astimezone(timezone.utc).isoformat(), decided_by=self.store.user_id)]
                db.execute('''UPDATE project_references SET selection_status=%s,selection_note=%s,revision=revision+1,
                    decisions_json=%s,updated_at=%s WHERE id=%s AND revision=%s''',
                    (request.status, request.note, Jsonb(decisions), now, reference_id, row['revision']))
                row = self.require_reference(db, project_id, reference_id)
            return self.reference_view(db, row)

    def source(self, project_id, receipt_id):
        with self.store.connection() as db:
            self.store.require_project(db, project_id)
            row = db.execute('''SELECT * FROM literature_fetch_receipts WHERE id=%s AND project_id=%s AND user_id=%s
                AND status='succeeded' ''', (receipt_id, project_id, self.store.user_id)).fetchone()
            if not row:
                raise StorageError('literature_not_found', '检索来源记录不存在。', 404)
            self.require_search(db, project_id, row['task_id'])
        return self.objects.read(row), row['operation']
