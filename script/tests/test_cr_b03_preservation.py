"""Retention checks cannot silently overlook lost or changed old materials."""
import importlib.util
from pathlib import Path

import pytest


def module():
    path=Path(__file__).resolve().parents[1]/'cr_b03_preservation.py'
    assert path.is_file(), 'B03 retention implementation is missing'
    spec=importlib.util.spec_from_file_location('cr_b03_preservation',path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def test_inventory_hashes_bytes_and_comparison_reports_changed_and_missing(tmp_path):
    target=tmp_path/'assets';target.mkdir();(target/'a.bin').write_bytes(b'abc');(target/'b.bin').write_bytes(b'old')
    before=module().asset_inventory(target)
    (target/'a.bin').write_bytes(b'new');(target/'b.bin').unlink();(target/'new.bin').write_bytes(b'new')
    after=module().asset_inventory(target)
    assert module().compare_assets(before,after)=={'missing':['b.bin'],'changed':['a.bin'],'added':['new.bin'],'preserved':False}


def test_same_size_edits_are_detected_and_old_files_are_not_modified(tmp_path):
    (tmp_path/'file').write_bytes(b'123')
    a=module().asset_inventory(tmp_path);b=module().asset_inventory(tmp_path)
    assert a==b and (tmp_path/'file').read_bytes()==b'123'
    assert module().compare_assets(a,b)['preserved']
    (tmp_path/'file').write_bytes(b'321')
    assert module().compare_assets(a,module().asset_inventory(tmp_path))['changed']==['file']


def test_inventory_refuses_symlink_escape(tmp_path):
    outside=tmp_path/'outside';outside.mkdir();(outside/'secret').write_bytes(b'private')
    root=tmp_path/'assets';root.mkdir()
    try:(root/'linked').symlink_to(outside,target_is_directory=True)
    except OSError:pytest.skip('Host does not permit symlink creation')
    with pytest.raises(ValueError,match='link'):
        module().asset_inventory(root)


def test_old_column_comparison_allows_only_declared_additive_columns():
    before={'t':{'columns':['id','value'],'count':1,'sha256':'a'}}
    after={'t':{'columns':['id','value'],'count':1,'sha256':'a'},'new':{'columns':['id'],'count':0,'sha256':'b'}}
    assert module().compare_business(before,after)==[]
    after['t']['sha256']='c'
    assert module().compare_business(before,after)==['rows:t']
