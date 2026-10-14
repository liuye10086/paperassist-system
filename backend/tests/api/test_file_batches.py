"""Real isolated PostgreSQL tests for asynchronous upload registration."""
from uuid import uuid4

from tests.api.test_projects import client, create_project, legacy_project  # noqa: F401
from tests.api.test_excel import workbook_bytes
from app.db.database import database_connection
import pytest
from app.core.exceptions import StorageError


def register(client, project, content=None, filename='data.xlsx', key='batch-one'):
    content = workbook_bytes() if content is None else content
    item = {'client_id': str(uuid4()), 'filename': filename, 'size_bytes': len(content)}
    base = f"/api/v1/projects/{project['id']}/file-batches"
    response = client.post(base, headers={'Idempotency-Key': key}, json={'items': [item]})
    assert response.status_code == 201, response.text
    return base, response.json(), item, content


def test_registration_mixed_replay_and_conflict(client):
    project = create_project(client)
    base = f"/api/v1/projects/{project['id']}/file-batches"
    items = [{'client_id': str(uuid4()), 'filename': name, 'size_bytes': size}
             for name, size in [('data.xlsx', 10), ('bad.csv', 10), ('empty.xlsx', 0), ('huge.xlsx', 10485761)]]
    body = {'items': items}
    first = client.post(base, headers={'Idempotency-Key': 'same'}, json=body)
    assert first.status_code == 201, first.text
    batch = first.json()
    assert [item['status'] for item in batch['items']] == ['pending', 'rejected', 'rejected', 'rejected']
    assert [item['error']['code'] for item in batch['items'][1:]] == ['unsupported_file_type', 'empty_file', 'file_too_large']
    replay = client.post(base, headers={'Idempotency-Key': 'same'}, json=body)
    assert replay.status_code == 200 and replay.json() == batch
    items[0]['size_bytes'] = 11
    assert client.post(base, headers={'Idempotency-Key': 'same'}, json=body).status_code == 409
    assert client.get(base).json()['items'] == [batch]
    assert client.get(base + '/' + batch['id']).json() == batch


def test_upload_atomic_queued_and_idempotent(client):
    project = create_project(client)
    base, batch, item, content = register(client, project)
    url = base + '/' + batch['id'] + '/items/' + item['client_id']
    response = client.post(url, files={'file': (item['filename'], content)})
    assert response.status_code == 202, response.text
    saved = response.json()
    assert saved['status'] == 'queued' and saved['task']['task_type'] == 'parse_file'
    assert saved['task']['input_version']['kind'] == 'parse_file'
    assert client.post(url, files={'file': (item['filename'], content)}).json() == saved
    assert client.post(url, files={'file': (item['filename'], b'x' * len(content))}).status_code == 409
    details = client.get(base + '/' + batch['id']).json()
    assert details['revision'] > batch['revision']
    file_url = f"/api/v1/projects/{project['id']}/files/{saved['file_id']}"
    assert client.get(file_url + '/preview').status_code == 409
    assert client.get(file_url + '/details').json()['parse_revision'] == 1
    assert client.get(file_url + '/download').content == content
    workspace = client.get('/api/v1/tasks/' + saved['task']['id'] + '/workspace')
    assert workspace.status_code == 200, workspace.text
    assert workspace.json()['source']['analysis_run_id'] is None
    assert workspace.json()['artifacts'] == {'figure': None, 'explanation': None, 'report': None}
    with database_connection() as db:
        for table in ('files', 'tasks', 'task_events', 'task_outbox', 'file_parse_results'):
            assert db.execute('SELECT count(*) AS n FROM ' + table).fetchone()['n'] == 1


def test_duplicate_ids_and_wrong_project(client):
    project = create_project(client)
    base, batch, item, content = register(client, project)
    assert client.post(base, headers={'Idempotency-Key': 'duplicate'}, json={'items': [item, item]}).status_code == 422
    other = create_project(client, 'other')
    wrong = f"/api/v1/projects/{other['id']}/file-batches/{batch['id']}"
    assert client.get(wrong).status_code == 404
    assert client.post(wrong + '/items/' + item['client_id'], files={'file': (item['filename'], content)}).status_code == 404


def test_upload_transaction_failure_preserves_recoverable_object(client, reject_database_write):
    from app.core.config import get_data_dir
    project = create_project(client)
    base, batch, item, content = register(client, project)
    url = base + '/' + batch['id'] + '/items/' + item['client_id']
    with reject_database_write('files'):
        response = client.post(url, files={'file': (item['filename'], content)})
    assert response.status_code == 503
    assert client.get(base + '/' + batch['id']).json()['items'][0]['status'] == 'pending'
    paths = list((get_data_dir() / 'files').glob('upload-*.xlsx'))
    assert len(paths) == 1 and paths[0].read_bytes() == content
    with database_connection() as db:
        for table in ('files', 'tasks', 'task_events', 'task_outbox', 'file_parse_results'):
            assert db.execute('SELECT count(*) AS n FROM ' + table).fetchone()['n'] == 0
    assert client.post(url, files={'file': (item['filename'], content)}).status_code == 202
    assert len(list((get_data_dir() / 'files').glob('upload-*.xlsx'))) == 1


def test_failed_object_write_can_retransmit(client, monkeypatch):
    import os
    from app.core.config import get_data_dir
    project = create_project(client)
    base, batch, item, content = register(client, project)
    url = base + '/' + batch['id'] + '/items/' + item['client_id']
    original_fsync = os.fsync
    def fail_fsync(fd):
        raise OSError('disk unavailable')
    monkeypatch.setattr(os, 'fsync', fail_fsync)
    assert client.post(url, files={'file': (item['filename'], content)}).status_code == 503
    assert list((get_data_dir() / 'files').glob('upload-*.xlsx')) == []
    monkeypatch.setattr(os, 'fsync', original_fsync)
    assert client.post(url, files={'file': (item['filename'], content)}).status_code == 202


def test_unknown_commit_replay_does_not_delete_referenced_bytes(client, monkeypatch):
    from contextlib import contextmanager
    from app.adapters.task_store import TaskStore
    original = TaskStore.connection
    def after_commit(self, write=False):
        @contextmanager
        def connection():
            with original(self, write=write) as db:
                yield db
            if write:
                raise StorageError('storage_unavailable', 'unknown commit')
        return connection()
    project = create_project(client)
    base, batch, item, content = register(client, project)
    url = base + '/' + batch['id'] + '/items/' + item['client_id']
    monkeypatch.setattr(TaskStore, 'connection', after_commit)
    assert client.post(url, files={'file': (item['filename'], content)}).status_code == 503
    monkeypatch.setattr(TaskStore, 'connection', original)
    read = client.get(base + '/' + batch['id']).json()['items'][0]
    assert read['status'] == 'queued'
    assert client.post(url, files={'file': (item['filename'], content)}).json() == read
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM tasks').fetchone()['n'] == 1


def test_batch_owner_hidden_and_metadata_parse_revision_separate(client):
    from tests.integration.test_project_ownership import account_client
    project = create_project(client)
    base, batch, item, content = register(client, project)
    url = base + '/' + batch['id'] + '/items/' + item['client_id']
    with account_client('batch-other@example.test')[0] as other:
        assert other.get(base).status_code == 404
        assert other.get(base + '/' + batch['id']).status_code == 404
        assert other.post(url, files={'file': (item['filename'], content)}).status_code == 404
    saved = client.post(url, files={'file': (item['filename'], content)}).json()
    file_url = f"/api/v1/projects/{project['id']}/files/{saved['file_id']}"
    changed = client.put(file_url + '/purposes', json={'expected_revision': 1, 'purposes': ['paper']}).json()
    assert changed['metadata_revision'] == 2 and changed['parse_revision'] == 1
    assert client.get(base + '/' + batch['id']).json()['revision'] == 2


@pytest.mark.parametrize('field,value', [('size_bytes', -1), ('size_bytes', True), ('size_bytes', '1'),
    ('client_id', 'invalid'), ('filename', '../file.xlsx'), ('filename', ''), ('unknown', 'x')])
def test_batch_strict_input(client, field, value):
    project = create_project(client)
    item = {'client_id': str(uuid4()), 'filename': 'data.xlsx', 'size_bytes': 10}
    item[field] = value
    base = f"/api/v1/projects/{project['id']}/file-batches"
    assert client.post(base, headers={'Idempotency-Key': 'invalid'}, json={'items': [item]}).status_code == 422


def test_upload_rejects_external_files_directory_junction(client, tmp_path):
    import os
    import subprocess
    from app.core.config import get_data_dir
    project = create_project(client)
    base, batch, item, content = register(client, project)
    root = get_data_dir()
    files = root / 'files'
    files.rmdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    try:
        files.symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name != 'nt':
            pytest.skip('Platform does not permit directory links')
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(files), str(outside)], capture_output=True)
        if result.returncode:
            pytest.skip('Platform does not permit directory links')
    try:
        response = client.post(base + '/' + batch['id'] + '/items/' + item['client_id'],
                               files={'file': (item['filename'], content)})
        assert response.status_code == 409
        assert list(outside.iterdir()) == []
    finally:
        files.rmdir() if os.name == 'nt' else files.unlink()


@pytest.mark.parametrize('extension,file_type', [('docx', 'docx'), ('pdf', 'pdf'), ('png', 'png'), ('jpg', 'jpeg')])
def test_batch_supported_types_consume_same_original_descriptor(client, tmp_path, extension, file_type):
    # Registration and queued publication only; never launch a parser/provider.
    project = create_project(client)
    base, batch, item, content = register(client, project, content=b'contract fixture', filename='same.' + extension)
    outside = tmp_path / 'outside'
    outside.write_bytes(b'preserved')
    response = client.post(base + '/' + batch['id'] + '/items/' + item['client_id'],
        files={'file': (item['filename'], content)},
        data={'server_path': str(outside), 'object_key': str(outside)})
    assert response.status_code == 202, response.text
    saved = response.json()
    with database_connection() as db:
        file = dict(db.execute('SELECT * FROM files WHERE id=%s', (saved['file_id'],)).fetchone())
        snapshot = db.execute('SELECT input_snapshot FROM tasks WHERE id=%s', (saved['task']['id'],)).fetchone()['input_snapshot']
    assert file['file_type'] == file_type and file['storage_backend'] == 'local'
    for field in ('id', 'file_type', 'storage_backend', 'object_key', 'size_bytes', 'sha256'):
        assert snapshot['file'][field] == file[field]
    download = client.get(f"/api/v1/projects/{project['id']}/files/{saved['file_id']}/download")
    assert download.status_code == 200 and download.content == content
    assert outside.read_bytes() == b'preserved'


def test_legacy_text_project_batch_upload_keeps_ownership_and_objects_isolated(client):
    from tests.integration.test_project_ownership import account_client
    from app.core.config import get_data_dir
    content = workbook_bytes()
    uploaded = []
    keys = []
    for identifier in ('project-1', 'project-2'):
        project = legacy_project(client, identifier)
        base, batch, item, _ = register(client, project, content=content, filename='same.xlsx')
        url = base + '/' + batch['id'] + '/items/' + item['client_id']
        response = client.post(url, files={'file': (item['filename'], content)})
        assert response.status_code == 202, response.text
        saved = response.json()
        assert client.post(url, files={'file': (item['filename'], content)}).json() == saved
        download = client.get(f"/api/v1/projects/{identifier}/files/{saved['file_id']}/download")
        assert download.status_code == 200 and download.content == content
        with database_connection() as db:
            key = db.execute('SELECT object_key FROM files WHERE id=%s', (saved['file_id'],)).fetchone()['object_key']
        assert identifier not in key
        keys.append(key)
        uploaded.append((url, saved))
    assert len(set(keys)) == 2 and uploaded[0][1]['file_id'] != uploaded[1][1]['file_id']
    assert len(list(get_data_dir().rglob('*.xlsx'))) == 2
    with account_client('legacy-batch-other@example.test')[0] as other:
        assert other.post(uploaded[0][0], files={'file': ('same.xlsx', content)}).status_code == 404
        assert other.get(f"/api/v1/projects/project-1/files/{uploaded[0][1]['file_id']}/download").status_code == 404
    assert len(list(get_data_dir().rglob('*.xlsx'))) == 2
