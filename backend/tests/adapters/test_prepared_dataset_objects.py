"""Candidate publication is content addressed, bounded and never replaces bytes."""
import hashlib
import importlib
import json
import os
from uuid import uuid4
import pytest
from app.core.exceptions import StorageError


@pytest.fixture(autouse=True)
def postgres_schema():
    # Candidate object tests use only pytest's temporary directory.
    yield None


def objects_at(directory):
    return importlib.import_module('app.adapters.prepared_dataset_objects').PreparedDatasetObjects(directory)


def content():
    from tests.domain.test_dataset_preparation import raw_sheet, parent_source, preparation
    sheet = raw_sheet({(1, 3): ('text', '组'), (2, 3): ('text', ' a ')})
    obj = preparation().prepare_dataset(sheet, parent_source(), preparation().build_recipe(sheet))
    return obj.model_dump_json().encode('utf-8')


def test_candidate_roundtrip_and_idempotent_save(tmp_path):
    objects = objects_at(tmp_path)
    body = content()
    dataset_id = str(uuid4())
    record = objects.save(dataset_id, body)
    assert record == dict(object_key=f'prepared-datasets/{dataset_id}/{hashlib.sha256(body).hexdigest()}.json',
                          sha256=hashlib.sha256(body).hexdigest(), size_bytes=len(body))
    original = objects.path(record['object_key']).stat()
    assert objects.save(dataset_id, body) == record
    assert objects.path(record['object_key']).stat().st_mtime_ns == original.st_mtime_ns
    returned, obj = objects.read({'id': dataset_id, **record})
    assert returned == body
    assert obj.sheet.cells[0].coordinate == 'C2'
    assert obj.sheet.cells[0].value == ' a '


def test_candidate_hash_tamper_and_record_identity_are_rejected(tmp_path):
    objects = objects_at(tmp_path)
    record = objects.save(str(uuid4()), content())
    objects.path(record['object_key']).write_bytes(b'tampered')
    with pytest.raises(StorageError) as error:
        objects.read(record)
    assert error.value.code == 'dataset_changed'
    with pytest.raises(StorageError):
        objects.read({'id': str(uuid4()), **record})


@pytest.mark.parametrize('body', [b'', b'x' * (4194304 + 1), b'{}'], ids=['empty', 'oversized', 'invalid-contract'])
def test_invalid_or_oversized_candidate_is_not_published(tmp_path, body):
    with pytest.raises(StorageError):
        objects_at(tmp_path).save(str(uuid4()), body)
    assert list(tmp_path.rglob('*.json')) == []


def test_corrupt_preexisting_object_is_never_replaced(tmp_path):
    objects = objects_at(tmp_path)
    body = content()
    dataset_id = str(uuid4())
    key = f'prepared-datasets/{dataset_id}/{hashlib.sha256(body).hexdigest()}.json'
    path = objects.path(key)
    path.parent.mkdir(parents=True)
    path.write_bytes(b'corrupt existing object')
    with pytest.raises(StorageError):
        objects.save(dataset_id, body)
    assert path.read_bytes() == b'corrupt existing object'
    assert not list(tmp_path.rglob('*.part'))


def test_atomic_publication_cleans_partial_after_link_failure(tmp_path, monkeypatch):
    objects = objects_at(tmp_path)
    def fail_link(*args):
        raise OSError('simulated disk error')
    monkeypatch.setattr(os, 'link', fail_link)
    with pytest.raises(StorageError) as error:
        objects.save(str(uuid4()), content())
    assert error.value.code == 'storage_unavailable'
    assert not list(tmp_path.rglob('*.part'))
    assert not list(tmp_path.rglob('*.json'))


def test_missing_candidate_and_malformed_record_are_storage_errors(tmp_path):
    objects = objects_at(tmp_path)
    body = content()
    record = dict(object_key=f'prepared-datasets/{uuid4()}/{hashlib.sha256(body).hexdigest()}.json',
                  sha256=hashlib.sha256(body).hexdigest(), size_bytes=len(body))
    with pytest.raises(StorageError) as error:
        objects.read(record)
    assert error.value.code == 'dataset_missing'
    with pytest.raises(StorageError):
        objects.read({**record, 'size_bytes': '1'})


@pytest.mark.parametrize('key', ['../x', 'prepared-datasets/../x', 'datasets/x.json', 'prepared-datasets/x:y'])
def test_reject_unsafe_prepared_keys(tmp_path, key):
    with pytest.raises(StorageError):
        objects_at(tmp_path).path(key)


def test_object_contract_is_validated_before_save(tmp_path):
    data = json.loads(content())
    data['sheet']['cells'][0]['coordinate'] = 'A1'
    with pytest.raises(StorageError):
        objects_at(tmp_path).save(str(uuid4()), json.dumps(data).encode())


def test_atomic_publication_reuses_racing_identical_candidate(tmp_path, monkeypatch):
    objects = objects_at(tmp_path)
    body = content()
    real_link = os.link
    def competing_link(source, target):
        real_link(source, target)
        raise FileExistsError('another worker published the same bytes')
    monkeypatch.setattr(os, 'link', competing_link)
    record = objects.save(str(uuid4()), body)
    assert objects.read(record)[0] == body
    assert not list(tmp_path.rglob('*.part'))


def test_linked_prepared_namespace_cannot_touch_external_directory(tmp_path):
    root, external = tmp_path / 'assets', tmp_path / 'external'
    root.mkdir()
    external.mkdir()
    original = external / 'keep.txt'
    original.write_bytes(b'keep')
    link = root / 'prepared-datasets'
    try:
        link.symlink_to(external, target_is_directory=True)
    except OSError:
        if os.name != 'nt':
            pytest.skip('Platform does not permit directory links.')
        import subprocess
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(external)], capture_output=True, timeout=10)
        assert result.returncode == 0
    try:
        with pytest.raises(StorageError):
            objects_at(root).save(str(uuid4()), content())
        assert original.read_bytes() == b'keep'
        assert list(external.iterdir()) == [original]
    finally:
        if link.is_symlink():
            link.unlink()
        else:
            link.rmdir()
