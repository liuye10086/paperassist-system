"""Checkpointed PubMed reads; every publication is fenced by the existing lease."""
from datetime import timedelta
import logging
from threading import Event, Thread
import time
from uuid import uuid4

from psycopg.types.json import Jsonb

from app.adapters.ncbi import NcbiClient, NcbiError, parse_search, parse_fetch
from app.adapters.task_execution_store import TaskExecutionStore, LeaseLost
from app.adapters.task_store import TaskStore, source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_preparation.service import append_checkpoint
from app.domain.literature.objects import LiteratureObjects
from app.domain.literature.service import digest, require_snapshot, latest_checkpoint
from app.domain.tasks.waits import persist_wait

logger = logging.getLogger(__name__)


def reserve_request(repository, lease):
    """Shared 2/s budget across workers; never hold a transaction during HTTP."""
    with repository.connection(write=True) as db:
        task = repository.require_lease(db, lease)
        repository.require_owner(db, task)
        now = repository.now(db)
        row = db.execute("""INSERT INTO ncbi_rate_limits(scope,next_allowed_at)
            VALUES ('ncbi-eutilities',%s + interval '0.5 second')
            ON CONFLICT(scope) DO UPDATE SET next_allowed_at=
                GREATEST(ncbi_rate_limits.next_allowed_at,%s)+interval '0.5 second'
            RETURNING next_allowed_at-interval '0.5 second' AS slot""", (now, now)).fetchone()
        return max(0.0, (row['slot'] - now).total_seconds())


class Retrieval:
    def __init__(self, repository, lease, client):
        self.repository, self.lease, self.client = repository, lease, client
        self.objects = LiteratureObjects(repository.assets.directory)
        self.source_kind = getattr(client, 'source_kind', 'ncbi_eutilities')
        if self.source_kind not in ('ncbi_eutilities', 'synthetic_fixture'):
            raise source_conflict()
        if self.source_kind == 'synthetic_fixture' and repository.config.environment != 'test':
            raise source_conflict()

    def load(self, db):
        task = self.repository.require_lease(db, self.lease)
        self.repository.require_owner(db, task)
        snapshot = require_snapshot(task)
        checkpoint = latest_checkpoint(db, task)
        return task, snapshot, checkpoint

    def receipt(self, db, task, operation, request, *, evidence=None, error=None):
        identity = str(uuid4())
        evidence = evidence or {}
        db.execute('''INSERT INTO literature_fetch_receipts
            (id,task_id,project_id,user_id,operation,request_json,request_digest,source_kind,status,error_code,
             object_key,sha256,size_bytes,cached_from_id,attempted_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            (identity,task['id'],task['project_id'],task['user_id'],operation,Jsonb(request),digest(request),self.source_kind,
             'failed' if error else 'succeeded',error,evidence.get('object_key'),evidence.get('sha256'),
             evidence.get('size_bytes'),evidence.get('cached_from_id'),evidence.get('attempted_at') or self.repository.now(db)))
        return identity

    def obtain(self, operation, request):
        with self.repository.connection() as db:
            task, _, _ = self.load(db)
            cached = db.execute('''SELECT * FROM literature_fetch_receipts
                WHERE project_id=%s AND user_id=%s AND source_kind=%s AND operation=%s
                  AND request_digest=%s AND status='succeeded' AND cached_from_id IS NULL
                  AND attempted_at>=clock_timestamp()-interval '24 hours'
                ORDER BY attempted_at DESC,id LIMIT 1''',
                (task['project_id'],task['user_id'],self.source_kind,operation,digest(request))).fetchone()
        if cached:
            raw = self.objects.read(cached)
            result = parse_search(raw, request['limit']) if operation == 'esearch' else parse_fetch(raw, request['pmids'])
            return result, {**dict(cached), 'cached_from_id': cached['id']}
        if self.source_kind == 'ncbi_eutilities':
            time.sleep(reserve_request(self.repository, self.lease))
        with self.repository.connection() as db:
            self.load(db)  # Ownership may have changed while waiting for the shared slot.
            attempted_at = self.repository.now(db)
        try:
            result = (self.client.search(request['query'],request['limit'],request['sort']) if operation == 'esearch'
                      else self.client.fetch(request['pmids']))
        except NcbiError as exc:
            with self.repository.connection(write=True) as db:
                task, _, _ = self.load(db)
                self.receipt(db, task, operation, request, error=exc.code)
            raise
        return result, {**self.objects.save(result.raw, operation), 'attempted_at': attempted_at}

    def wait_configuration(self):
        with self.repository.connection(write=True) as db:
            task, _, checkpoint = self.load(db)
            revision = task['revision']
            state = {**checkpoint['state_json'], 'resume_node': checkpoint['next_node']}
            task.update(status='waiting_confirmation',revision=revision+1,
                        updated_at=max(self.repository.now(db),task['updated_at']),
                        reason_code='confirmation_required',error_code='ncbi_not_configured')
            append_checkpoint(db,task,'await_confirmation','await_confirmation',state,checkpoint)
            TaskStore.finish_attempt(db,task)
            TaskStore.update_task(db,task,revision)
            TaskStore.append_event(db,task,'waiting')
            persist_wait(db,task)
            return TaskStore.public_task(task)

    def search(self, snapshot):
        request = dict(operation='esearch',query=snapshot['effective_query'],
                       limit=snapshot['input']['limit'],sort=snapshot['input']['sort'])
        result, evidence = self.obtain('esearch',request)
        with self.repository.connection(write=True) as db:
            task, _, previous = self.load(db)
            if previous['next_node'] != 'search': raise source_conflict()
            self.receipt(db,task,'esearch',request,evidence=evidence)
            now = self.repository.now(db)
            db.execute('''UPDATE literature_searches SET query_translation=%s,matched_count=%s,pmids_json=%s,updated_at=%s
                WHERE task_id=%s''', (result.query_translation,result.count,Jsonb(result.pmids),now,task['id']))
            state = dict(schema_version=1,input_digest=task['input_digest'],pmids=result.pmids,next_offset=0,warnings=result.warnings)
            task['updated_at'] = max(now,task['updated_at'])
            append_checkpoint(db,task,'search','fetch' if result.pmids else 'publish',state,previous)

    def fetch(self, state):
        offset = state['next_offset']
        pmids = state['pmids'][offset:offset+20]
        request = dict(operation='efetch',pmids=pmids)
        result, evidence = self.obtain('efetch',request)
        with self.repository.connection(write=True) as db:
            task, _, previous = self.load(db)
            if previous['next_node'] != 'fetch' or previous['state_json'] != state: raise source_conflict()
            receipt_id = self.receipt(db,task,'efetch',request,evidence=evidence)
            now = self.repository.now(db)
            for record in result.records:
                pmid = record['pmid']
                db.execute('''INSERT INTO literature_records(id,pmid,created_at) VALUES (%s,%s,%s)
                    ON CONFLICT(pmid) DO NOTHING''', (str(uuid4()),pmid,now))
                reference = db.execute('SELECT id FROM literature_records WHERE pmid=%s',(pmid,)).fetchone()['id']
                db.execute('''INSERT INTO project_references
                    (id,project_id,user_id,reference_id,selection_status,selection_note,revision,decisions_json,created_at,updated_at)
                    VALUES (%s,%s,%s,%s,'candidate','',1,%s,%s,%s) ON CONFLICT(project_id,reference_id) DO NOTHING''',
                    (str(uuid4()),task['project_id'],task['user_id'],reference,Jsonb([]),now,now))
                candidate = db.execute('SELECT id,user_id FROM project_references WHERE project_id=%s AND reference_id=%s',
                                       (task['project_id'],reference)).fetchone()
                if candidate['user_id'] != task['user_id']: raise source_conflict()
                db.execute('''INSERT INTO literature_search_hits
                    (id,task_id,project_reference_id,reference_id,project_id,user_id,receipt_id,ordinal,record_json,created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                    (str(uuid4()),task['id'],candidate['id'],reference,task['project_id'],task['user_id'],receipt_id,
                     offset+pmids.index(pmid)+1,Jsonb(record),now))
            returned = {r['pmid'] for r in result.records}
            missing = [p for p in pmids if p not in returned]
            db.execute('''UPDATE literature_searches SET retrieved_count=retrieved_count+%s,
                missing_pmids_json=missing_pmids_json || %s,updated_at=%s WHERE task_id=%s''',
                (len(result.records),Jsonb(missing),now,task['id']))
            state = {**state,'next_offset':offset+len(pmids)}
            task['updated_at'] = max(now,task['updated_at'])
            append_checkpoint(db,task,'fetch','fetch' if state['next_offset'] < len(state['pmids']) else 'publish',state,previous)

    def run(self):
        while True:
            with self.repository.connection() as db:
                task, snapshot, checkpoint = self.load(db)
            node = checkpoint['next_node']
            if node == 'search': self.search(snapshot)
            elif node == 'fetch': self.fetch(checkpoint['state_json'])
            elif node == 'publish':
                with self.repository.connection(write=True) as db:
                    task, _, previous = self.load(db)
                    if previous['next_node'] != 'publish': raise source_conflict()
                    append_checkpoint(db,task,'publish','done',previous['state_json'],previous)
                    self.repository._finish(db,task,'succeeded',None)
                    return TaskStore.public_task(task)
            else: raise source_conflict()


def run_literature_task(task_id, task_revision, *, config=None, directory=None, client=None):
    repository = TaskExecutionStore(config=config,directory=directory)
    lease = repository.claim(task_id,task_revision,task_type='literature_search')
    if lease is None: return None
    stop = Event()
    def heartbeat():
        while not stop.wait(10):
            try:
                if not repository.heartbeat(lease): return
            except StorageError:
                logger.warning('literature heartbeat unavailable task_id=%s',task_id)
    thread = Thread(target=heartbeat,daemon=True)
    thread.start()
    try:
        if client is None:
            try:
                client = NcbiClient()
                if not client.settings.enabled: raise NcbiError('ncbi_not_configured')
            except NcbiError:
                return Retrieval(repository,lease,None).wait_configuration()
        return Retrieval(repository,lease,client).run()
    except LeaseLost:
        return None
    except NcbiError as exc:
        if exc.code == 'ncbi_not_configured':
            return Retrieval(repository,lease,None).wait_configuration()
        try: return repository.retry_failure(lease,exc.code)
        except LeaseLost: return None
    except Exception as exc:
        code = exc.code if isinstance(exc,StorageError) else ('storage_unavailable' if isinstance(exc,OSError) else 'task_execution_failed')
        logger.warning('literature task failed task_id=%s code=%s error_type=%s',task_id,code,type(exc).__name__)
        try: return repository.fail(lease,code)
        except LeaseLost: return None
    finally:
        stop.set()
        thread.join(timeout=1)
