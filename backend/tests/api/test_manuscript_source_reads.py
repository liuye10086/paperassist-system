"""Owner-scoped task reads reuse verified source bytes only within one request."""
from collections import Counter

from app.adapters.docx_parser import parse_docx
from app.adapters.document_objects import DocumentObjects
from app.adapters.file_objects import FileObjects
from app.adapters.task_store import TaskStore
from app.core.config import get_data_dir
from app.db.database import database_connection
from app.domain.manuscripts.service import ManuscriptService
from app.domain.tasks.file_parse_execution import run_parse_file_task
from tests.api.test_document_versions import client, uploaded_docx  # noqa: F401
from tests.api.test_literature_evidence import post
from tests.api.test_manuscripts import body


def test_list_reuses_source_bytes_but_verifies_every_task_and_workspace_rereads(client, monkeypatch):
    project, _, _, uploaded, _ = uploaded_docx(client)
    assert run_parse_file_task(uploaded['task']['id'], 1, parser=parse_docx)['status'] == 'succeeded'
    path = f'/api/v1/projects/{project["id"]}/manuscripts'
    candidates = client.get(path+'/candidates').json()['items']
    source = next(item for item in candidates if item['kind'] == 'document_version')
    selection = {key: source[key] for key in ('kind', 'id', 'file_id')} | {'role': 'image_observation'}
    task_ids = set()
    for key in ('first-source', 'second-source'):
        created = post(client, path, body(sources=[selection]), key)
        assert created.status_code == 201, created.text
        task_ids.add(created.json()['versions'][0]['task_id'])
    endpoint = f'/api/v1/projects/{project["id"]}/tasks?task_type=manuscript_draft'
    expected = client.get(endpoint).json()
    assert {item['task']['id'] for item in expected['items']} == task_ids
    assert all(item['source']['is_current'] for item in expected['items'])

    reads = Counter()
    verified = []
    required = []
    versions = []
    original, read = FileObjects.original, DocumentObjects._read
    verify, require = ManuscriptService.verify_task, TaskStore.require_task
    validate = ManuscriptService.validate_version
    def read_original(store, record):
        reads['original'] += 1
        return original(store, record)
    def read_object(store, record, limit):
        reads['json' if record['object_key'].endswith('.json') else 'image'] += 1
        return read(store, record, limit)
    def verify_task(service, db, task, **kwargs):
        verified.append(task['id'])
        return verify(service, db, task, **kwargs)
    def require_task(store, db, identity, **kwargs):
        required.append(identity)
        return require(store, db, identity, **kwargs)
    def validate_version(service, db, row):
        versions.append(row['id'])
        return validate(service, db, row)
    monkeypatch.setattr(FileObjects, 'original', read_original)
    monkeypatch.setattr(DocumentObjects, '_read', read_object)
    monkeypatch.setattr(ManuscriptService, 'verify_task', verify_task)
    monkeypatch.setattr(TaskStore, 'require_task', require_task)
    monkeypatch.setattr(ManuscriptService, 'validate_version', validate_version)
    response = client.get(endpoint)
    assert response.status_code == 200, response.text
    assert response.json() == expected
    assert Counter(verified) == Counter({task: 1 for task in task_ids})
    assert Counter(required) == Counter({task: 1 for task in task_ids})
    assert len(versions) == len(set(versions)) == 2
    assert reads == {'original': 1, 'json': 1, 'image': 2}

    reads.clear()
    workspace = client.get('/api/v1/tasks/'+next(iter(task_ids))+'/workspace')
    assert workspace.status_code == 200, workspace.text
    assert workspace.json()['source']['is_current']
    assert reads == {'original': 1, 'json': 1, 'image': 2}
    with database_connection() as db:
        manifest = db.execute('SELECT result_json FROM file_parse_results WHERE id=%s', (source['id'],)).fetchone()['result_json']
    image = get_data_dir()/manifest['images'][0]['object_key']
    image.write_bytes(b'corrupted synthetic image')
    changed = client.get(endpoint)
    assert changed.status_code == 200, changed.text
    assert all(not item['source']['is_current'] for item in changed.json()['items'])
    assert not client.get('/api/v1/tasks/'+next(iter(task_ids))+'/workspace').json()['source']['is_current']
    with database_connection(write=True) as db:
        db.execute('UPDATE tasks SET input_digest=%s WHERE id=%s', ('0'*64, next(iter(task_ids))))
    assert client.get(endpoint).status_code == 409
    from tests.integration.test_project_ownership import account_client
    endpoints = [endpoint, '/api/v1/tasks/'+next(iter(task_ids))+'/workspace']
    with account_client('source-reads-other@example.test')[0] as other:
        assert all(other.get(url).status_code == 404 for url in endpoints)
    owner = client.get('/api/v1/auth/me').json()['user']['id']
    with database_connection(write=True) as db:
        db.execute('UPDATE users SET active=FALSE WHERE id=%s', (owner,))
    assert all(client.get(url).status_code == 401 for url in endpoints)


def test_export_task_list_validates_shared_version_once_but_each_task_and_request_again(client, monkeypatch):
    from app.db.database import migration_connection
    from app.domain.manuscripts import sources
    from app.domain.tasks.execution import run_task
    from tests.api.test_manuscripts import setup
    from psycopg.types.json import Jsonb
    from app.domain.literature.service import digest

    path, _, file = setup(client)
    selection = dict(kind='original', id=file['id'], file_id=file['id'], role='methods')
    created = post(client, path, body(sources=[selection]), 'shared-version').json()
    version = created['versions'][0]
    assert run_task(version['task_id'], 1)['status'] == 'succeeded'
    export_path = path+'/'+created['id']+'/versions/1/exports'
    exports = [post(client, export_path, {}, key).json() for key in ('shared-one', 'shared-two')]
    task_ids = {item['task_id'] for item in exports}
    endpoint = path.removesuffix('/manuscripts')+'/tasks?task_type=manuscript_docx'
    expected = client.get(endpoint).json()
    assert {item['task']['id'] for item in expected['items']} == task_ids
    calls = Counter()
    verified = []
    validate, verify, changes = ManuscriptService.validate_version, ManuscriptService.verify_task, sources.changes
    def validate_version(service, db, row):
        calls['version'] += 1
        return validate(service, db, row)
    def verify_task(service, db, task, **kwargs):
        verified.append(task['id'])
        return verify(service, db, task, **kwargs)
    def current_changes(*args, **kwargs):
        calls['changes'] += 1
        return changes(*args, **kwargs)
    monkeypatch.setattr(ManuscriptService, 'validate_version', validate_version)
    monkeypatch.setattr(ManuscriptService, 'verify_task', verify_task)
    monkeypatch.setattr(sources, 'changes', current_changes)
    for _ in range(2):
        calls.clear(); verified.clear()
        response = client.get(endpoint)
        assert response.status_code == 200, response.text
        assert response.json() == expected
        assert Counter(verified) == Counter({identity: 1 for identity in task_ids})
        assert calls == {'version': 1, 'changes': 1}

    # Workspace is a new read and verifies the version again.
    calls.clear()
    response = client.get('/api/v1/tasks/'+exports[0]['task_id']+'/workspace')
    assert response.status_code == 200, response.text
    assert calls['version'] >= 1 and calls['changes'] == 1
    with database_connection(write=True) as db:
        db.execute('UPDATE files SET sha256=%s WHERE id=%s', ('a'*64, file['id']))
    changed = client.get(endpoint)
    assert changed.status_code == 200, changed.text
    assert all(not item['source']['is_current'] for item in changed.json()['items'])
    # A new list request must revalidate the immutable version, not just task input.
    with migration_connection(write=True) as db:
        original_digest = db.execute('SELECT request_digest FROM manuscript_versions WHERE id=%s', (version['id'],)).fetchone()['request_digest']
        db.execute('UPDATE manuscript_versions SET request_digest=%s WHERE id=%s', ('0'*64, version['id']))
    assert client.get(endpoint).status_code == 409
    with migration_connection(write=True) as db:
        db.execute('UPDATE manuscript_versions SET request_digest=%s WHERE id=%s', (original_digest, version['id']))
    # A correctly hashed task still must match its exact export, even on a cache hit.
    target = expected['items'][-1]['task']['id']
    with database_connection(write=True) as db:
        task = db.execute('SELECT input_snapshot FROM tasks WHERE id=%s', (target,)).fetchone()
        snapshot = dict(task['input_snapshot'], export_id='not-the-saved-export')
        db.execute('UPDATE tasks SET input_snapshot=%s,input_digest=%s WHERE id=%s', (Jsonb(snapshot), digest(snapshot), target))
    assert client.get(endpoint).status_code == 409
