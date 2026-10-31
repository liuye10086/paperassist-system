"""Raw delimited inputs have no assumed header; formal tables do."""
import hashlib
import pytest
from app.adapters.bio_insights_reproduction import ReproductionArchive,table_shape
from app.core.exceptions import StorageError


def test_raw_positions_count_first_record_and_allow_repeated_first_values(tmp_path):
    path=tmp_path/'positions.csv';path.write_text('barcode1,1,2,2,100,100\nbarcode2,1,3,3,110,110\n',encoding='utf-8')
    expected=dict(format='csv',header='uninterpreted',column_count=6,records=2)
    assert table_shape(path,'csv',header='uninterpreted')==expected
    archive=ReproductionArchive()
    try:
        record=archive.add_file('input/positions.bin',path,dict(size_bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest()),
                                fmt='csv',table_header='uninterpreted')
        assert record['table']==expected
    finally:archive.close()
    with pytest.raises(StorageError):table_shape(path,'csv')


def test_raw_delimited_count_never_silently_accepts_ragged_records(tmp_path):
    path=tmp_path/'bad.tsv';path.write_text('a\tb\na\n',encoding='utf-8')
    with pytest.raises(StorageError):table_shape(path,'tsv',header='uninterpreted')


def test_programs_are_packaged_from_isolated_app_without_repository_scripts(tmp_path):
    from pathlib import Path
    import zipfile
    actual_app=Path(__file__).resolve().parents[2]/'app'
    isolated_app=tmp_path/'deployment/app';assets=isolated_app/'reproduction_assets/bio_insights';assets.mkdir(parents=True)
    originals={}
    for name in ('reproduce.py','render_worker.py'):
        originals[name]=(actual_app/'reproduction_assets/bio_insights'/name).read_bytes()
        (assets/name).write_bytes(originals[name])
    assert not (isolated_app.parent/'script').exists() and not (isolated_app.parent.parent/'script').exists()
    archive=ReproductionArchive()
    try:
        archive.add_reproduction_programs(isolated_app);handle,_=archive.finish(dict(schema_version=1))
        with zipfile.ZipFile(handle) as package:
            for name,content in originals.items():assert package.read(name)==content
    finally:archive.close()
