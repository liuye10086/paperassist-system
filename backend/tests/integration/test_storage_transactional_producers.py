"""A2a: actual producers, isolated schemas and synthetic artifacts only."""
from contextlib import contextmanager
import hashlib
import json

import pytest

from app.adapters.storage import get_project_store
from app.core.exceptions import StorageError
from app.db.database import database_connection
from app.domain.storage_governance.service import set_policy, usage, reconcile_intents
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_boxplot import cloud  # noqa: F401
from tests.integration.test_explanations import writer  # noqa: F401


def dataset_candidate(client):
    from tests.api.test_datasets import prepared, generate, structure_parser
    from app.adapters.dataset_store import DatasetStore
    from app.adapters.task_execution_store import TaskExecutionStore
    project, _, _, base = prepared(client)
    view = generate(client, base, 0, 'storage-manifest')
    repo = TaskExecutionStore()
    lease = repo.claim(view['task']['id'], 1, task_type='extract_dataset')
    adapter = DatasetStore(repo)
    snapshot, raw = adapter.load(lease)
    structure = structure_parser(raw, snapshot['file']['filename'], snapshot['settings'])
    return project['id'], repo, lambda: adapter.complete(lease, snapshot, structure), structure, lease


def sync_candidate(client, kind):
    store = get_project_store()
    if kind == 'language':
        from tests.api.test_manuscript_figure_language import setup
        from app.domain.manuscripts.figure_language import FigureLanguageService
        project, _, _, body = setup(client)
        with store.connection() as db:
            owner = db.execute('SELECT owner_id FROM projects WHERE id=%s', (project,)).fetchone()['owner_id']
        from app.adapters.storage import ProjectStore
        service = FigureLanguageService(ProjectStore(store.directory, owner_id=owner))
        return project, service.store, lambda: service.create(project, body, 'storage-language'), 'manuscript_figure_language_versions'
    if kind == 'figure':
        from tests.api.test_boxplot import prepared
        base, file, result, _ = prepared(client)
        project = base.split('/')[4]
        figure = dict(analysis_run_id=result['id'], setup_revision=result['setup_revision'],
                      created_at=result['completed_at'], engine={'id': 'storage_synthetic_figure'})
        return project, store, lambda: store.save_figure(project, file['id'], figure, b'synthetic-figure-bytes'), 'figures'
    from tests.integration.test_reports import report_ready
    from app.domain.reports import context
    from app.adapters.report_store import ReportStore
    base, file, result, _, _, _ = report_ready(client)
    project = base.split('/')[4]
    snapshot, state = context(store, project, file['id'], result['id'])
    assert state['ready']
    repository = ReportStore(store)
    metadata = repository.metadata(snapshot)
    return project, store, lambda: repository.save(snapshot, metadata, b'synthetic-docx-bytes'), 'reports'


def test_dataset_manifest_admits_all_sheets_before_first_byte(client):
    from app.adapters.dataset_objects import DatasetObject
    project, repo, produce, structure, _ = dataset_candidate(client)
    sizes = [len(json.dumps(DatasetObject(schema_version=1, epoch=structure.epoch, sheet=sheet).model_dump(),
                           ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()) for sheet in structure.sheets]
    assert len(sizes) > 1
    with repo.connection(write=True) as db:
        before = usage(db, project_id=project)['usage_bytes']
        set_policy(db, 'project', project, before + sizes[0], 'enforced')
    with pytest.raises(StorageError) as error:
        produce()
    assert error.value.code == 'storage_quota_exceeded'
    assert not list((repo.assets.directory / 'datasets').rglob('*.json'))
    with repo.connection() as db:
        assert not db.execute('SELECT id FROM dataset_versions').fetchall()
        assert usage(db, project_id=project)['usage_bytes'] == before
    with repo.connection(write=True) as db:
        set_policy(db, 'project', project, before + sum(sizes), 'enforced')
    assert produce()['status'] == 'succeeded'
    with repo.connection() as db:
        rows = db.execute("SELECT o.*,r.kind FROM storage_objects o JOIN storage_references r ON r.object_id=o.id WHERE r.project_id=%s AND r.kind='dataset'", (project,)).fetchall()
        assert len(rows) == len(sizes)
        assert sum(row['size_bytes'] for row in rows) == sum(sizes)
        assert usage(db, project_id=project)['usage_bytes'] == before + sum(sizes)


@pytest.mark.parametrize('kind', ['figure', 'report', 'language'])
def test_sync_producer_rejects_quota_then_counts_bytes_and_replays_read(client, cloud, writer, kind):
    project, store, produce, directory = sync_candidate(client, kind)
    root = get_project_store().directory
    with store.connection(write=True) as db:
        before = usage(db, project_id=project)['usage_bytes']
        set_policy(db, 'project', project, before, 'enforced')
    prior_paths = set((root / directory).glob('*'))
    with pytest.raises(StorageError) as error:
        produce()
    assert error.value.code == 'storage_quota_exceeded'
    assert set((root / directory).glob('*')) == prior_paths
    with store.connection(write=True) as db:
        set_policy(db, 'project', project, before + 1000000, 'enforced')
    first = produce()
    with store.connection() as db:
        value = usage(db, project_id=project)
        assert value['usage_bytes'] > before
        assert value['reserved_bytes'] == 0
        objects = db.execute('SELECT o.* FROM storage_objects o JOIN storage_references r ON r.object_id=o.id WHERE r.project_id=%s', (project,)).fetchall()
        for obj in objects:
            raw = (root / obj['object_key']).read_bytes()
            assert len(raw) == obj['size_bytes'] and hashlib.sha256(raw).hexdigest() == obj['sha256']
    with store.connection(write=True) as db:
        set_policy(db, 'project', project, 0, 'enforced')
    replay = produce()
    assert (replay[0] if isinstance(replay, tuple) else replay) == (first[0] if isinstance(first, tuple) else first)
    with store.connection() as db:
        assert usage(db, project_id=project)['usage_bytes'] == value['usage_bytes']


@pytest.mark.parametrize('kind', ['figure', 'report', 'language'])
@pytest.mark.parametrize('commit_ack', [False, True])
def test_sync_unknown_commit_preserves_exact_target_and_attribution(client, cloud, writer, monkeypatch, kind, commit_ack):
    project, store, produce, directory = sync_candidate(client, kind)
    root = get_project_store().directory
    old_paths = set((root / directory).glob('*'))
    original_connection = store.connection

    @contextmanager
    def interrupted(write=False):
        with original_connection(write=write) as db:
            yield db
            if write and not commit_ack:
                raise StorageError('storage_unavailable', 'Synthetic precommit interruption')
        if write and commit_ack:
            raise StorageError('storage_unavailable', 'Synthetic lost commit acknowledgement')

    monkeypatch.setattr(store, 'connection', interrupted)
    with pytest.raises(StorageError):
        produce()
    monkeypatch.setattr(store, 'connection', original_connection)
    new_paths = set((root / directory).glob('*')) - old_paths
    assert len(new_paths) == 1, 'Unknown commit must retain this exact safe target'
    target = new_paths.pop()
    raw = target.read_bytes()
    with store.connection(write=True) as db:
        assert reconcile_intents(db, root) == 0
        reservation = db.execute('SELECT * FROM storage_reservations WHERE project_id=%s AND object_key=%s', (project, target.relative_to(root).as_posix())).fetchone()
        assert reservation and reservation['size_bytes'] == len(raw)
        assert reservation['sha256'] == hashlib.sha256(raw).hexdigest()
        assert reservation['state'] == ('settled' if commit_ack else 'unknown')
        value = usage(db, project_id=project)
        assert value['usage_bytes'] + value['reserved_bytes'] >= len(raw)


def test_dataset_rollback_recovers_identical_objects_and_original_task(client, monkeypatch):
    from app.domain.tasks.dataset_execution import run_dataset_task
    from tests.api.test_datasets import structure_parser
    project, repo, produce, _, lease = dataset_candidate(client)
    connection = repo.connection

    @contextmanager
    def interrupted(write=False):
        with connection(write=write) as db:
            yield db
            if write:
                raise StorageError('storage_unavailable', 'Synthetic manifest precommit interruption')

    monkeypatch.setattr(repo, 'connection', interrupted)
    with pytest.raises(StorageError):
        produce()
    monkeypatch.setattr(repo, 'connection', connection)
    with pytest.raises(StorageError) as error:
        produce()
    assert error.value.code == 'storage_accounting_unknown'
    before = {p.relative_to(repo.assets.directory).as_posix(): p.read_bytes()
              for p in (repo.assets.directory / 'datasets').rglob('*.json')}
    assert len(before) > 1
    with connection(write=True) as db:
        assert reconcile_intents(db, repo.assets.directory) == 0
        rows = db.execute("SELECT * FROM storage_reservations WHERE project_id=%s AND kind='dataset'", (project,)).fetchall()
        assert len(rows) == len(before)
        assert {r['object_key'] for r in rows} == set(before)
        assert len({r['task_id'] for r in rows}) == 1 and rows[0]['task_id']
        assert all(r['state'] == 'unknown' for r in rows)
    failed = repo.fail(lease, 'storage_accounting_unknown')
    with connection() as db:
        assert db.execute('SELECT error_category FROM task_attempts WHERE task_id=%s ORDER BY attempt_no DESC LIMIT 1',
                          (lease.task_id,)).fetchone()['error_category'] == 'source'
    url = '/api/v1/tasks/' + lease.task_id
    assert client.get(url + '/workspace').json()['allowed_actions'] == ['retry']
    with connection(write=True) as db:
        held = usage(db, project_id=project)
        set_policy(db, 'project', project, held['usage_bytes'], 'enforced')
    rejected = client.post(url + '/retry', json={'expected_revision': failed['revision']})
    assert rejected.status_code == 409 and rejected.json()['detail']['code'] == 'storage_quota_exceeded'
    with connection(write=True) as db:
        current = db.execute('SELECT * FROM tasks WHERE id=%s', (lease.task_id,)).fetchone()
        assert current['status'] == 'failed' and current['revision'] == failed['revision']
        assert usage(db, project_id=project)['unknown_reservation_count'] == len(before)
        set_policy(db, 'project', project, held['usage_bytes'] + held['reserved_bytes'], 'enforced')
    response = client.post(url + '/retry', json={'expected_revision': failed['revision']})
    assert response.status_code == 202, response.text
    assert response.json()['id'] == lease.task_id
    assert run_dataset_task(lease.task_id, response.json()['revision'], parser=structure_parser)['status'] == 'succeeded'
    assert {p.relative_to(repo.assets.directory).as_posix(): p.read_bytes()
            for p in (repo.assets.directory / 'datasets').rglob('*.json')} == before
    with connection() as db:
        assert db.execute('SELECT status FROM tasks WHERE id=%s', (rows[0]['task_id'],)).fetchone()['status'] == 'succeeded'
        assert db.execute("SELECT count(*) AS n FROM storage_reservations WHERE kind='dataset'").fetchone()['n'] == len(before)


@pytest.mark.parametrize('failure', ['quota', 'disk'])
def test_dataset_storage_failure_exposes_explicit_same_task_api_retry(client, monkeypatch, failure):
    from tests.api.test_datasets import prepared, generate, structure_parser
    from app.domain.tasks.dataset_execution import run_dataset_task
    from app.domain.storage_governance import service
    project, _, _, base = prepared(client)
    view = generate(client, base, 0, 'storage-api-retry')
    task_id = view['task']['id']
    with database_connection(write=True) as db:
        before = usage(db, project_id=project['id'])['usage_bytes']
        set_policy(db, 'project', project['id'], before if failure == 'quota' else before + 1000000, 'enforced')
        original_snapshot = db.execute('SELECT input_snapshot FROM tasks WHERE id=%s', (task_id,)).fetchone()['input_snapshot']
    with monkeypatch.context() as patch:
        if failure == 'disk':
            patch.setattr(service, 'disk_status', lambda _: dict(status='insufficient', free_bytes=1, threshold_bytes=2, total_bytes=3))
        failed = run_dataset_task(task_id, 1, parser=structure_parser)
    assert failed['status'] == 'failed'
    assert failed['error_code'] == ('storage_quota_exceeded' if failure == 'quota' else 'storage_disk_insufficient')
    with database_connection() as db:
        assert db.execute('SELECT error_category FROM task_attempts WHERE task_id=%s ORDER BY attempt_no DESC LIMIT 1',
                          (task_id,)).fetchone()['error_category'] == 'configuration'
    url = '/api/v1/tasks/' + task_id
    assert client.get(url + '/workspace').json()['allowed_actions'] == ['retry']
    with database_connection(write=True) as db:
        set_policy(db, 'project', project['id'], before + 1000000, 'enforced')
        assert db.execute('SELECT status FROM tasks WHERE id=%s', (task_id,)).fetchone()['status'] == 'failed'
    response = client.post(url + '/retry', json={'expected_revision': failed['revision']})
    assert response.status_code == 202, response.text
    assert response.json()['id'] == task_id
    assert run_dataset_task(task_id, response.json()['revision'], parser=structure_parser)['status'] == 'succeeded'
    with database_connection() as db:
        assert db.execute('SELECT input_snapshot FROM tasks WHERE id=%s', (task_id,)).fetchone()['input_snapshot'] == original_snapshot
        versions = db.execute('SELECT id FROM file_structure_versions WHERE task_id=%s', (task_id,)).fetchall()
        assert [row['id'] for row in versions] == [view['id']]
        assert not db.execute('SELECT id FROM model_calls').fetchall()


@pytest.mark.parametrize('code', ['storage_quota_exceeded', 'setup_conflict'])
def test_legacy_retrieval_storage_block_preserves_provider_identity(client, cloud, monkeypatch, code):
    from app.domain.boxplot import recover_legacy_boxplot
    from tests.api.test_boxplot import prepared, seed_legacy
    base, file, result, url = prepared(client)
    project = base.split('/')[4]
    job = seed_legacy(client, url)
    store = get_project_store()

    def blocked(*args,**kwargs):
        raise StorageError(code, 'Synthetic publication block', 409)

    monkeypatch.setattr(store, 'save_figure', blocked)
    if code.startswith('storage_'):
        with pytest.raises(StorageError) as error:
            recover_legacy_boxplot(project, file['id'], result['id'], store)
        assert error.value.code == code
    else:
        recover_legacy_boxplot(project, file['id'], result['id'], store)
    with store.connection() as db:
        saved = json.loads(db.execute('SELECT job_json FROM figure_jobs WHERE id=%s', (job['id'],)).fetchone()['job_json'])
        assert saved['response_id'] == job['response_id']
        assert saved['status'] == 'failed'


def test_legacy_background_poll_retains_storage_reason_and_original_job(client, cloud):
    from app.domain.boxplot import poll_pending_figures
    from tests.api.test_boxplot import prepared, seed_legacy
    base, _, _, url = prepared(client)
    project = base.split('/')[4]
    job = seed_legacy(client, url)
    with database_connection(write=True) as db:
        set_policy(db, 'project', project, usage(db, project_id=project)['usage_bytes'], 'enforced')
    poll_pending_figures()
    with database_connection() as db:
        saved = json.loads(db.execute('SELECT job_json FROM figure_jobs WHERE id=%s', (job['id'],)).fetchone()['job_json'])
        assert saved['status'] == 'failed'
        assert saved['message_code'] == 'storage_quota_exceeded'
        assert saved['response_id'] == job['response_id'] and saved['container_id'] == job['container_id']
        assert saved['payload'] == job['payload'] and saved['expected'] == job['expected']
        assert not db.execute('SELECT id FROM figures').fetchall()
        assert db.execute('SELECT count(*) AS n FROM figure_jobs').fetchone()['n'] == 1
    assert client.get(url).json()['job']['message_code'] == 'storage_quota_exceeded'
    assert not cloud.calls
