import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.exceptions import StorageError


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


class AssetRows:
    def __init__(self):
        self.config = SimpleNamespace(url=SimpleNamespace(host='local', port=None, database='test'), schema='assets')
        self.projects = {'owned': 'account', 'other': 'other-account'}
        self.objects = []
        self.reservations = []
        self.history = []

    def execute(self, query, args):
        if 'pg_try_advisory_xact_lock' in query:
            return SimpleNamespace(fetchone=lambda: {'acquired': True})
        if 'FROM projects' in query:
            return [dict(id=project, owner_id=self.projects[project]) for project in args[0] if project in self.projects]
        if 'JOIN storage_references' in query:
            return self.objects
        if 'FROM storage_reservations' in query:
            return self.reservations
        raise AssertionError(query)


@pytest.fixture
def rows(monkeypatch):
    from app.domain.storage_governance import historical

    monkeypatch.setattr(historical, 'references', lambda db, *args, **kwargs: iter(db.history))
    return AssetRows()


def asset(root, key, content, *, project='owned', user='account'):
    path = root / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return dict(project_id=project, owner_id=user, object_key=key, size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest())


def test_collect_and_retry_remove_owned_assets_with_shared_refs_and_control_journal(tmp_path, rows):
    from app.domain.account_deletion_assets import collect_account_assets, remove_account_assets

    root = tmp_path / 'assets'
    main = asset(root, 'files/owned.xlsx', b'main')
    part = asset(root, f"{main['object_key']}.{uuid4().hex}.part", b'partial upload')
    shared = asset(root, 'files/shared.xlsx', b'shared')
    rows.objects.extend([main, shared, dict(shared, project_id='other', owner_id='other-account')])
    rows.history.append(asset(root, 'figures/legacy.png', b'historical figure'))
    staged = asset(root, 'task-staging/owned.part', b'candidate')
    reservation = dict(staged, id=str(uuid4()), namespace='local:assets-v1',
                       object_key='reports/owned.docx', kind='report', operation_key='operation', task_id='task',
                       candidate_json={'locations': ['task-staging/owned.part']})
    rows.reservations.append(reservation)
    journal_key = '.storage-intents/' + reservation['id'] + '.json'
    journal = {key: value for key, value in reservation.items() if key != 'candidate_json'}
    asset(root, journal_key, json.dumps(journal).encode())

    manifest = collect_account_assets(rows, root, 'account', ['owned'])
    assert {item['object_key'] for item in manifest} == {
        main['object_key'], part['object_key'], 'figures/legacy.png', staged['object_key'], journal_key}
    assert (root / main['object_key']).is_file()
    rows.projects.pop('owned')
    rows.objects[:] = [row for row in rows.objects if row['project_id'] != 'owned']
    rows.history.clear()
    rows.reservations.clear()
    remove_account_assets(rows, root, json.loads(json.dumps(manifest)))
    remove_account_assets(rows, root, manifest)
    assert (root / shared['object_key']).read_bytes() == b'shared'
    assert all(not (root / item['object_key']).exists() for item in manifest)


def test_remove_checks_replacement_bytes_and_preserves_newly_shared_key(tmp_path, rows):
    from app.domain.account_deletion_assets import collect_account_assets, remove_account_assets

    root = tmp_path / 'assets'
    original = asset(root, 'files/owned.xlsx', b'old')
    rows.objects.append(original)
    manifest = collect_account_assets(rows, root, 'account', ['owned'])
    rows.objects.clear()
    path = root / original['object_key']
    path.write_bytes(b'new')
    with pytest.raises(StorageError) as error:
        remove_account_assets(rows, root, manifest)
    assert error.value.code == 'account_delete_blocked'
    assert path.read_bytes() == b'new'

    rows.objects.append(dict(original, project_id='other', owner_id='other-account'))
    remove_account_assets(rows, root, manifest)
    assert path.read_bytes() == b'new'


def test_rejects_unowned_projects_and_unsafe_paths(tmp_path, rows):
    from app.domain.account_deletion_assets import collect_account_assets

    with pytest.raises(StorageError) as error:
        collect_account_assets(rows, tmp_path, 'account', ['other'])
    assert error.value.code == 'account_delete_blocked'

    protected = tmp_path / 'protected.xlsx'
    protected.write_bytes(b'private')
    rows.objects.append(dict(project_id='owned', owner_id='account', object_key='../protected.xlsx',
                             size_bytes=7, sha256=hashlib.sha256(b'private').hexdigest()))
    with pytest.raises(StorageError) as error:
        collect_account_assets(rows, tmp_path / 'assets', 'account', ['owned'])
    assert error.value.code == 'account_delete_blocked'
    assert protected.read_bytes() == b'private'


def test_keeps_other_project_and_removes_analyst_candidate_receipt(tmp_path, rows):
    from app.domain.account_deletion_assets import collect_account_assets, remove_account_assets

    root = tmp_path / 'assets'
    original = asset(root, 'files/other.png', b'official', project='other', user='other-account')
    identifier = str(uuid4())
    descriptor_key = f'storage-candidates/{identifier}.json'
    operation = 'native-delivery:' + 'a' * 64
    envelope = dict(schema_version=1, kind='original', project_id='other', owner_id='other-account',
                    operation_key=operation, task_id=None, source_identity='b' * 64,
                    value={'actor_id': 'account', 'assignment_revision': 1})
    descriptor = asset(root, descriptor_key, json.dumps(envelope).encode(), project='other', user='other-account')
    rows.objects.extend([original, dict(descriptor, ref_kind='candidate_descriptor')])
    reservation = dict(original, id=identifier, namespace='local:assets-v1', kind='original', operation_key=operation,
                       task_id=None, candidate_json={'source_identity': envelope['source_identity'], 'descriptor': descriptor})
    rows.reservations.append(reservation)
    journal_key = f'.storage-intents/{identifier}.allocation.json'
    journal = {**reservation, 'stage': 'allocation', 'version': 2}
    journal.pop('candidate_json')
    asset(root, journal_key, json.dumps(journal).encode(), project='other', user='other-account')

    manifest = collect_account_assets(rows, root, 'account', [])
    assert {item['object_key'] for item in manifest} == {descriptor_key, journal_key}
    assert next(item for item in manifest if item['object_key'] == descriptor_key)['actor_receipt'] == {
        'reservation_id': identifier, 'project_id': 'other'}
    rows.objects[:] = [original]
    rows.reservations.clear()
    remove_account_assets(rows, root, manifest)
    assert (root / original['object_key']).read_bytes() == b'official'
    assert not (root / descriptor_key).exists()
    assert not (root / journal_key).exists()


@pytest.mark.parametrize('journal_exists', [True, False])
def test_removes_assigned_upload_receipt_and_keeps_project_original(tmp_path, rows, journal_exists):
    from app.domain.account_deletion_assets import collect_account_assets, remove_account_assets

    root = tmp_path / 'assets'
    original = asset(root, 'files/delegated.xlsx', b'formal data', project='other', user='other-account')
    identifier = str(uuid4())
    actor_hash = hashlib.sha256(b'account').hexdigest()
    operation_key = f'sync-assignment:{actor_hash}:{uuid4()}:{"a" * 64}'
    reservation = dict(original, id=identifier, namespace='local:assets-v1', operation_key=operation_key,
                       kind='original', task_id=None, state='settled')
    rows.reservations.append(reservation)
    rows.objects.append(original)
    journal_key = f'.storage-intents/{identifier}.json'
    if journal_exists:
        asset(root, journal_key, json.dumps(reservation).encode(), project='other', user='other-account')

    manifest = collect_account_assets(rows, root, 'account', [])
    assert len(manifest) == 1
    assert manifest[0]['object_key'] == journal_key
    assert manifest[0]['actor_receipt'] == {'reservation_id': identifier, 'project_id': 'other'}
    assert manifest[0].get('metadata_only', False) is (not journal_exists)
    rows.reservations.clear()
    remove_account_assets(rows, root, manifest)
    assert (root / original['object_key']).read_bytes() == b'formal data'
    assert not (root / journal_key).exists()


def test_collect_removes_only_owned_narrative_and_bulk_cache_scopes(tmp_path, monkeypatch, rows):
    from app.domain.account_deletion_assets import collect_account_assets, remove_account_assets
    from app.domain.bio_insights import bulk_delivery_cache

    root = tmp_path / 'assets'
    monkeypatch.setattr(bulk_delivery_cache.tempfile, 'gettempdir', lambda: str(tmp_path / 'temp'))
    owner = SimpleNamespace(directory=root, owner_id='account', db_config=rows.config)
    other = SimpleNamespace(directory=root, owner_id='other-account', db_config=rows.config)
    own_cache = bulk_delivery_cache.cache_for(owner, 'owned', 'word')
    other_cache = bulk_delivery_cache.cache_for(other, 'other', 'word')
    asset(own_cache.root, 'generation/payload', b'owner cache')
    asset(other_cache.root, 'generation/payload', b'other cache')
    asset(root, 'bio-reader-narratives/owned/result/en.json', b'owned narrative')
    asset(root, 'bio-reader-narratives/other/result/en.json', b'other narrative')

    manifest = collect_account_assets(rows, root, 'account', ['owned'])
    rows.projects.pop('owned')
    remove_account_assets(rows, root, manifest)
    remove_account_assets(rows, root, manifest)
    assert not own_cache.root.exists()
    assert not (root / 'bio-reader-narratives/owned').exists()
    assert (other_cache.root / 'generation/payload').read_bytes() == b'other cache'
    assert (root / 'bio-reader-narratives/other/result/en.json').read_bytes() == b'other narrative'


def test_incomplete_unlink_reuses_manifest_without_touching_other_files(tmp_path, monkeypatch, rows):
    from pathlib import Path
    from app.domain.account_deletion_assets import collect_account_assets, remove_account_assets

    root = tmp_path / 'assets'
    first = asset(root, 'files/first.xlsx', b'first')
    second = asset(root, 'files/second.xlsx', b'second')
    other = asset(root, 'files/other.xlsx', b'other', project='other', user='other-account')
    rows.objects.extend([first, second, other])
    manifest = collect_account_assets(rows, root, 'account', ['owned'])
    rows.objects[:] = [other]
    unlink = Path.unlink

    def fail_second(path, *args, **kwargs):
        if path.name == 'second.xlsx':
            raise PermissionError('file in use')
        return unlink(path, *args, **kwargs)

    with monkeypatch.context() as failure:
        failure.setattr(Path, 'unlink', fail_second)
        with pytest.raises(StorageError) as error:
            remove_account_assets(rows, root, manifest)
    assert error.value.code == 'account_delete_incomplete'
    assert not (root / first['object_key']).exists()
    assert (root / second['object_key']).read_bytes() == b'second'
    remove_account_assets(rows, root, manifest)
    assert not (root / second['object_key']).exists()
    assert (root / other['object_key']).read_bytes() == b'other'
