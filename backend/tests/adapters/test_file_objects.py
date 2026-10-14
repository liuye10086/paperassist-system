import hashlib
import os
import subprocess
from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from app.adapters.storage import ProjectStore
from app.core.exceptions import StorageError
from app.adapters import file_objects


def test_local_upload_descriptor_replay_and_project_isolation(tmp_path):
    objects = file_objects.LocalFileObjects(tmp_path)
    project, operation, item = (str(uuid4()) for _ in range(3))
    descriptor = objects.put_original(project, operation, 'xlsx', b'original', item_id=item)
    assert descriptor == objects.put_original(project, operation, 'xlsx', b'original', item_id=item)
    assert descriptor.size_bytes == 8
    assert descriptor.sha256 == hashlib.sha256(b'original').hexdigest()
    assert descriptor.storage_backend == 'local'
    assert objects.original(asdict(descriptor)) == b'original'
    assert descriptor.object_key != objects.put_original(str(uuid4()), operation, 'xlsx', b'original', item_id=item).object_key
    assert descriptor.object_key != objects.put_original(project, str(uuid4()), 'xlsx', b'original', item_id=item).object_key
    assert not list(tmp_path.rglob('*.part'))


def test_local_upload_does_not_replace_corrupted_publication(tmp_path):
    objects = file_objects.LocalFileObjects(tmp_path)
    project, operation = str(uuid4()), str(uuid4())
    descriptor = objects.put_original(project, operation, 'xlsx', b'original')
    target = tmp_path / descriptor.object_key
    target.write_bytes(b'changed!')
    with pytest.raises(StorageError) as error:
        objects.put_original(project, operation, 'xlsx', b'original')
    assert (error.value.code, error.value.status) == ('file_changed', 409)
    assert target.read_bytes() == b'changed!'
    assert not list(tmp_path.rglob('*.part'))


def test_local_port_concurrent_immutable_different_content(tmp_path):
    assert hasattr(file_objects, 'LocalObjectStorage'), 'shared local byte port missing'
    port = file_objects.LocalObjectStorage(tmp_path)
    def publish(content):
        try:
            port.put_immutable('files/concurrent.xlsx', content)
            return content
        except StorageError as error:
            assert (error.code, error.status) == ('file_changed', 409)
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(publish, [b'first', b'other']))
    winners = [value for value in results if value is not None]
    assert len(winners) == 1
    assert port.read('files/concurrent.xlsx', 6) == winners[0]
    port.put_immutable('files/concurrent.xlsx', winners[0])
    assert not list(tmp_path.rglob('*.part'))


class PrivateContractFixture:
    """In-memory contract fixture only; no production private integration."""
    backend_name = 'private-contract-fixture'

    def __init__(self):
        self.objects = {}
        self.read_limits = []

    def put_immutable(self, key, content):
        if key in self.objects and self.objects[key] != content:
            raise StorageError('file_changed', 'contract conflict', 409)
        self.objects[key] = content

    def read(self, key, max_bytes):
        self.read_limits.append(max_bytes)
        try:
            return self.objects[key][:max_bytes]
        except KeyError as exc:
            raise FileNotFoundError(key) from exc


def test_common_private_fixture_uses_same_descriptor_and_bounded_integrity(tmp_path):
    assert hasattr(file_objects, 'FileObjects'), 'shared object facade missing'
    port = PrivateContractFixture()
    objects = file_objects.FileObjects(port)
    descriptor = objects.put_original(str(uuid4()), str(uuid4()), 'pdf', b'original')
    saved = asdict(descriptor)
    assert descriptor.storage_backend == port.backend_name
    assert objects.original(saved) == b'original'
    assert port.read_limits[-1] == descriptor.size_bytes + 1
    port.objects[descriptor.object_key] = b'original extra'
    with pytest.raises(StorageError) as changed:
        objects.original(saved)
    assert (changed.value.code, changed.value.status) == ('file_changed', 409)
    assert port.read_limits[-1] == descriptor.size_bytes + 1
    with pytest.raises(StorageError):
        objects.original({**saved, 'storage_backend': 'local'})
    with pytest.raises(StorageError):
        objects.original({**saved, 'object_key': '../outside'})


def test_common_private_fixture_missing_and_unavailable_errors(tmp_path, monkeypatch):
    port = PrivateContractFixture()
    objects = file_objects.FileObjects(port)
    descriptor = objects.put_original(str(uuid4()), str(uuid4()), 'pdf', b'original')
    del port.objects[descriptor.object_key]
    with pytest.raises(StorageError) as missing:
        objects.original(asdict(descriptor))
    assert (missing.value.code, missing.value.status) == ('file_missing', 410)
    def unavailable(*args):
        raise OSError('contract fixture unavailable')
    monkeypatch.setattr(port, 'read', unavailable)
    with pytest.raises(StorageError) as error:
        objects.original(asdict(descriptor))
    assert (error.value.code, error.value.status) == ('storage_unavailable', 503)
    monkeypatch.setattr(port, 'put_immutable', unavailable)
    with pytest.raises(StorageError) as error:
        objects.put_original(str(uuid4()), str(uuid4()), 'pdf', b'original')
    assert (error.value.code, error.value.status) == ('storage_unavailable', 503)


def test_local_publication_cleans_only_unpublished_temp_on_link_failure(tmp_path, monkeypatch):
    objects = file_objects.LocalFileObjects(tmp_path)
    preserved = tmp_path / 'files' / 'preserved.xlsx'
    preserved.parent.mkdir()
    preserved.write_bytes(b'preserved')
    def fail_link(*args):
        raise OSError('cannot publish')
    monkeypatch.setattr(os, 'link', fail_link)
    with pytest.raises(StorageError) as error:
        objects.put_original(str(uuid4()), str(uuid4()), 'xlsx', b'original')
    assert error.value.code == 'storage_unavailable'
    assert list(preserved.parent.iterdir()) == [preserved]
    assert preserved.read_bytes() == b'preserved'


@pytest.mark.parametrize('project,operation,file_type,item', [
    ('', str(uuid4()), 'xlsx', None),
    (str(uuid4()), 'C:/outside', 'xlsx', None),
    (str(uuid4()), str(uuid4()), '../xlsx', None),
    (str(uuid4()), str(uuid4()), 'xlsx', '../item'),
])
def test_upload_rejects_arbitrary_operation_paths_before_writing(tmp_path, project, operation, file_type, item):
    with pytest.raises(StorageError) as invalid:
        file_objects.LocalFileObjects(tmp_path).put_original(project, operation, file_type, b'original', item_id=item)
    assert (invalid.value.code, invalid.value.status) == ('file_changed', 409)
    assert list(tmp_path.iterdir()) == []


def test_legacy_text_project_identity_is_encoded_before_path_generation(tmp_path):
    objects = file_objects.LocalFileObjects(tmp_path)
    operation, item = str(uuid4()), str(uuid4())
    saved = [objects.put_original(project, operation, 'xlsx', b'original', item_id=item)
             for project in ('../outside', 'C:/outside', '历史:项目/一')]
    assert len({descriptor.object_key for descriptor in saved}) == 3
    assert len({descriptor.id for descriptor in saved}) == 3
    for descriptor in saved:
        assert objects.original(asdict(descriptor)) == b'original'
        assert descriptor.object_key.startswith('files/upload-')
        assert len(descriptor.object_key.split('/')) == 2
        assert ':' not in descriptor.object_key
    assert not list(tmp_path.rglob('*.part'))


@pytest.mark.parametrize('change', [{'size_bytes': True}, {'size_bytes': -1}, {'size_bytes': '3'}, {'sha256': 'bad'}])
def test_invalid_original_metadata_raises_stable_error_before_io(tmp_path, change):
    objects = file_objects.LocalFileObjects(tmp_path)
    with pytest.raises(StorageError) as error:
        objects.original({**record(), **change})
    assert (error.value.code, error.value.status) == ('file_changed', 409)


def test_original_digest_does_not_introduce_a_new_business_size_limit(tmp_path):
    # 10 MiB + one byte is a small real fixture, not a giant allocation.
    content = b'x' * (10485760 + 1)
    assert file_objects.original_digest(content) == hashlib.sha256(content).hexdigest()


def test_original_large_trusted_record_reaches_bounded_port(tmp_path):
    port = PrivateContractFixture()
    port.objects['files/historical.xlsx'] = b'tiny'
    objects = file_objects.FileObjects(port)
    with pytest.raises(StorageError) as invalid:
        objects.original({'storage_backend': port.backend_name, 'object_key': 'files/historical.xlsx',
            'size_bytes': 10485760 + 1, 'sha256': hashlib.sha256(b'tiny').hexdigest()})
    assert invalid.value.code == 'file_changed'
    assert port.read_limits == [10485760 + 2]


def test_local_read_handles_large_bound_in_small_chunks(tmp_path, monkeypatch):
    port = file_objects.LocalObjectStorage(tmp_path)
    (tmp_path / 'files').mkdir()
    (tmp_path / 'files' / 'tiny.xlsx').write_bytes(b'tiny')
    from pathlib import Path
    original_open = Path.open
    sizes = []
    class Reader:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.stream.close()
        def read(self, size):
            sizes.append(size)
            assert 0 < size <= 65536
            return self.stream.read(size)
    def observed_open(path, *args, **kwargs):
        return Reader(original_open(path, *args, **kwargs))
    monkeypatch.setattr(Path, 'open', observed_open)
    assert port.read('files/tiny.xlsx', 2**63-1) == b'tiny'
    assert sizes and max(sizes) <= 65536


@pytest.mark.parametrize('size', [2**63-1, 2**63, 10**100])
def test_unsafe_read_length_is_rejected_before_port_io(tmp_path, size):
    port = PrivateContractFixture()
    with pytest.raises(StorageError) as invalid:
        file_objects.FileObjects(port).original({'storage_backend': port.backend_name,
            'object_key': 'files/tiny.xlsx', 'size_bytes': size, 'sha256': 'a'*64})
    assert (invalid.value.code, invalid.value.status) == ('file_changed', 409)
    assert port.read_limits == []


def record(**changes):
    return dict(id='old', file_type='xlsx', size_bytes=3, sha256=hashlib.sha256(b'old').hexdigest(), **changes)


def test_legacy_snapshot_original_and_integrity(tmp_path):
    store = ProjectStore(tmp_path)
    path = store.files_dir / 'old.xlsx'
    path.write_bytes(b'old')
    assert store.original(record()) == b'old'
    assert store.original(record(object_key='files/old.xlsx', storage_backend='local')) == b'old'
    path.write_bytes(b'bad')
    with pytest.raises(StorageError) as changed:
        store.original(record())
    assert changed.value.status == 409
    path.unlink()
    with pytest.raises(StorageError) as missing:
        store.original(record())
    assert missing.value.status == 410


@pytest.mark.parametrize('changes', [
    {'object_key': '../outside.xlsx'}, {'object_key': 'C:/outside.xlsx'},
    {'object_key': 'files/../outside.xlsx'}, {'object_key': r'files\old.xlsx'},
    {'object_key': '/outside.xlsx'}, {'object_key': 'files//old.xlsx'},
    {'object_key': 'files/old.xlsx', 'storage_backend': 'remote'},
])
def test_objects_reject_unsafe_keys(tmp_path, changes):
    store = ProjectStore(tmp_path / 'assets')
    with pytest.raises(StorageError) as invalid:
        store.original(record(**changes))
    assert invalid.value.status == 409


def test_legacy_path_only_supports_explicit_xlsx_and_safe_id(tmp_path):
    store = ProjectStore(tmp_path)
    for changes in ({'id': '../outside'}, {'file_type': 'csv'}):
        item = record()
        item.update(changes)
        with pytest.raises(StorageError) as invalid:
            store.original(item)
        assert invalid.value.status == 409


def test_objects_reject_external_directory_link(tmp_path):
    store = ProjectStore(tmp_path / 'assets')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'old.xlsx').write_bytes(b'old')
    link = store.files_dir / 'escape'
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name != 'nt':
            pytest.skip('Platform does not permit creating a directory symlink.')
        # Windows junctions require no developer-mode symlink privilege.
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)], capture_output=True)
        if result.returncode:
            pytest.skip('Platform permits neither directory symlinks nor junctions.')
    try:
        with pytest.raises(StorageError) as invalid:
            store.original(record(object_key='files/escape/old.xlsx'))
        assert invalid.value.status == 409
    finally:
        # Remove only the exact link, never recurse into the outside directory.
        link.rmdir() if os.name == 'nt' else link.unlink()
    assert (outside / 'old.xlsx').read_bytes() == b'old'
