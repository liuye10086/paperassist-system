"""Existing synthetic business sources for the new task foundation tests."""
from tests.api.test_boxplot import prepared


def boxplot_task_input(client):
    from app.domain.tasks.contracts import TaskCreateRequest

    base, file, result, _ = prepared(client)
    return base.split('/')[4], TaskCreateRequest(
        task_type='boxplot', file_id=file['id'], analysis_run_id=result['id'],
        expected_revision=result['setup_revision']), base, result


def task_owner(client):
    return client.get('/api/v1/auth/me').json()['user']['id']


def historical_word_task(store, project, request, key):
    """Persist the queued Word task shape used before reader exports were introduced."""
    from datetime import datetime, timezone
    from uuid import uuid4
    from app.adapters.task_store import workflow_version
    from app.domain.external_processing import request_digest

    with store.connection(write=True) as db:
        snapshot = store.source_snapshot(db, store.require_project(db, project), request)
        moment = datetime.now(timezone.utc)
        task = dict(
            id=str(uuid4()), project_id=project, user_id=store.user_id,
            task_type='word_report', idempotency_key=key, input_digest=request_digest(request),
            input_snapshot=snapshot, workflow_version=workflow_version('word_report', snapshot),
            status='queued', phase='export', revision=1, current_attempt=0,
            reason_code=None, created_at=moment, updated_at=moment,
        )
        store.insert_task(db, task)
        store.append_event(db, task, 'created')
        store.enqueue(db, task)
    return task


def historical_collection_export(repository, project, version_id, key):
    """Resume a collection build request accepted before reader exports were introduced."""
    from uuid import uuid4
    from psycopg.types.json import Jsonb
    from app.adapters.report_store import digest
    from app.domain.report_collections.contracts import RENDERER

    with repository.store.connection(write=True) as db:
        version = db.execute('SELECT sha256 FROM report_collection_versions WHERE id=%s FOR UPDATE',
                             (version_id,)).fetchone()
        revision = db.execute('SELECT COALESCE(max(export_revision),0)+1 AS next FROM report_build_requests WHERE version_id=%s',
                              (version_id,)).fetchone()['next']
        request_id = str(uuid4())
        request_digest = digest(dict(version_id=version_id, sha256=version['sha256'], request_key=key))
        db.execute("""INSERT INTO report_build_requests(id,version_id,export_revision,renderer_version,request_key,
            request_digest,status,dependencies_json,created_at,updated_at)
            VALUES(%s,%s,%s,%s,%s,%s,'waiting',%s,now(),now())""",
            (request_id, version_id, revision, RENDERER, key, request_digest, Jsonb([])))
        repository.advance_in_transaction(db, project, request_id)
        return repository.request_view(db, request_id)


def historical_model_wait(task):
    """Recreate a pre-upgrade task paused before its first provider submission."""
    from app.adapters.task_execution_store import TaskExecutionStore
    store = TaskExecutionStore()
    lease = store.claim(task['id'], task['revision'], task_type=task['task_type'])
    assert lease is not None
    return store.wait_explanation(lease, 'budget_exceeded', 'model_budget_exceeded')
