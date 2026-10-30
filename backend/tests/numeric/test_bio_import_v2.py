import hashlib
import io
import json
import tarfile
from pathlib import Path
import h5py
import numpy as np
import pytest
from PIL import Image


def import_payload(tmp_path,alternate=False,mismatch=False):
    output=tmp_path/'output';output.mkdir()
    h5=tmp_path/'matrix.h5'
    from test_bio_hdf5 import fixture
    fixture(h5)
    image=io.BytesIO();Image.new('RGB',(8,8),'white').save(image,format='PNG')
    parts={'GSM9999999_matrix.h5':h5.read_bytes(),
           'GSM9999999_tissue_positions_list.csv':b'a,1,0,0,2,2\nb,1,1,1,4,4\n',
           'GSM9999999_scalefactors_json.json':b'{"tissue_hires_scalef":1,"spot_diameter_fullres":1}',
           'GSM9999999_tissue_hires_image.png':image.getvalue()}
    if alternate:
        parts.update({'GSM9999999_matrix.mtx':b'%%MatrixMarket matrix coordinate integer general\n2 2 3\n1 1 '+(b'2' if mismatch else b'1')+b'\n2 1 2\n1 2 3\n',
                      'GSM9999999_features.tsv':b'g1\tA\tGene Expression\ng2\tA\tGene Expression\n',
                      'GSM9999999_barcodes.tsv':b'a\nb\n'})
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w') as archive:
        for name,content in sorted(parts.items()):
            info=tarfile.TarInfo(name);info.size=len(content);archive.addfile(info,io.BytesIO(content))
    source=tmp_path/'input.tar';source.write_bytes(stream.getvalue())
    return {'mode':'import_v2','files':[{'id':'source-file-id','filename':'input.tar','path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'size_bytes':source.stat().st_size,'role':'archive'}],
            'matrix_representation':'10x_h5','compare_alternate':alternate,'settings':{},'identity':{},'output_directory':str(output)}


def test_h5_only_v2_preserves_real_origin_and_canonical_axes(tmp_path):
    from app.adapters.bio_engine.importer import import_v2
    payload=import_payload(tmp_path);result=import_v2(payload)
    assert result['parser_version']=='geo_visium_import_v2'
    assert result['n_features']==2 and result['n_observations']==2
    outputs={m['key']:m for m in result['outputs']}
    np.testing.assert_array_equal(np.load(outputs['matrix_data']['path']),[1,2,3])
    assert np.load(outputs['matrix_indptr']['path']).dtype==np.int64
    assert all(m['source_file_id']=='source-file-id' for m in result['outputs'])
    assert any(m['role']=='derived_representation' and m['source_member_name'].startswith('derived/') for m in result['outputs'])
    assert any(m['role']=='alternate_matrix' and m['verification_state']=='verified' for m in result['outputs'])
    assert result['manifest']['representation']['comparison']['status']=='not_comparable'


def test_h5_and_mtx_all_values_compared_and_mismatch_blocks(tmp_path):
    from app.adapters.bio_engine.importer import import_v2
    good=tmp_path/'good';good.mkdir();bad=tmp_path/'bad';bad.mkdir()
    result=import_v2(import_payload(good,alternate=True))
    assert result['manifest']['representation']['comparison']['status']=='identical'
    with pytest.raises(ValueError,match='h5_matrix_mismatch'):import_v2(import_payload(bad,alternate=True,mismatch=True))


def test_h5_only_import_runs_in_fixed_linux_sandbox(tmp_path):
    from test_bio_engine_transport import child
    result=child(import_payload(tmp_path))
    assert result['parser_version']=='geo_visium_import_v2'
    assert result['manifest']['representation']['matrix_representation']=='10x_h5'


def test_foreign_gsm_representation_cannot_be_attested_equal(tmp_path):
    from app.adapters.bio_engine.importer import import_v2
    payload=import_payload(tmp_path,alternate=True);path=Path(payload['files'][0]['path'])
    parts={}
    with tarfile.open(fileobj=io.BytesIO(path.read_bytes())) as archive:
        for member in archive:
            name=member.name.replace('GSM9999999','GSM8888888') if member.name.endswith(('.mtx','features.tsv','barcodes.tsv')) else member.name
            parts[name]=archive.extractfile(member).read()
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w') as archive:
        for name,content in sorted(parts.items()):
            info=tarfile.TarInfo(name);info.size=len(content);archive.addfile(info,io.BytesIO(content))
    path.write_bytes(stream.getvalue());payload['files'][0].update(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),size_bytes=path.stat().st_size)
    with pytest.raises(Exception,match='multiple_accessions'):import_v2(payload)
