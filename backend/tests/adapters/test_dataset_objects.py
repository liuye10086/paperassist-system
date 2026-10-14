"""Reject traversal and symlink/junction aliases without touching original assets."""
import hashlib
import os
from pathlib import Path
import subprocess
import pytest
from app.adapters.dataset_objects import DatasetObjects
from app.core.exceptions import StorageError


@pytest.mark.parametrize('key',['../x','datasets/../x','files/x.json','datasets\\x','/datasets/x','datasets/x:y'])
def test_reject_unsafe_object_keys(tmp_path,key):
    with pytest.raises(StorageError) as error:
        DatasetObjects(tmp_path).path(key)
    assert error.value.code=='dataset_changed'


def test_missing_and_changed_bytes(tmp_path):
    objects=DatasetObjects(tmp_path)
    key='datasets/11111111-1111-1111-1111-111111111111/'+('a'*64)+'.json'
    record=dict(object_key=key,size_bytes=3,sha256=hashlib.sha256(b'old').hexdigest())
    with pytest.raises(StorageError) as error:objects.read(record)
    assert error.value.code=='dataset_missing'
    path=objects.path(key);path.parent.mkdir(parents=True);path.write_bytes(b'new')
    with pytest.raises(StorageError) as error:objects.read(record)
    assert error.value.code=='dataset_changed'


def test_reject_real_linked_dataset_directory(tmp_path):
    root = tmp_path / 'assets'
    root.mkdir()
    external = tmp_path / 'unrelated'
    external.mkdir()
    original = external / 'unchanged.txt'
    original.write_bytes(b'unchanged')
    link = root / 'datasets'
    try:
        link.symlink_to(external, target_is_directory=True)
    except OSError:
        if os.name != 'nt':
            pytest.skip('Platform does not permit directory links.')
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(external)],
                                capture_output=True, timeout=10)
        assert result.returncode == 0, 'Windows dataset junction fixture must be created.'
    try:
        with pytest.raises(StorageError) as error:
            DatasetObjects(root).path('datasets/11111111-1111-1111-1111-111111111111/' + 'a' * 64 + '.json')
        assert error.value.code == 'dataset_changed'
        assert original.read_bytes() == b'unchanged'
        assert list(external.iterdir()) == [original]
    finally:
        # Remove only this test-created link, never recurse into its target.
        if link.is_symlink():
            link.unlink()
        else:
            link.rmdir()
