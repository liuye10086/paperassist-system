"""Untrusted worker output cannot bypass parent-side leaf identity checks."""
import hashlib
import importlib.util
from uuid import uuid4

import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def adapter():
    name = 'app.adapters.bio_analysis_execution'
    assert importlib.util.find_spec(name) is not None, 'B02 fenced persistence adapter missing'
    return __import__(name, fromlist=['build_candidate'])


def test_candidate_rejects_duplicate_keys_and_changed_output_bytes(tmp_path):
    module = adapter()
    from app.adapters.bio_objects import BioAnalysisObjects
    from app.core.exceptions import StorageError
    path = tmp_path/'summary.tsv'
    path.write_bytes(b'barcode\tcounts\nA\t4\n')
    output = dict(key='qc',role='table',format='tsv',path=str(path),size_bytes=path.stat().st_size,
                  sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    task = dict(id=str(uuid4()),input_digest='a'*64,input_snapshot=dict(run_id=str(uuid4())))
    result = dict(outputs=[output,dict(output)],manifest={},summary={},steps=[],checks=[],effective_params={})
    with pytest.raises(StorageError):
        module.build_candidate(task,result,BioAnalysisObjects(tmp_path/'assets'),'qc')
    result['outputs'] = [output]
    path.write_bytes(b'bad content')
    with pytest.raises(StorageError):
        module.build_candidate(task,result,BioAnalysisObjects(tmp_path/'assets'),'qc')


def test_equal_content_different_keys_keep_two_logical_members(tmp_path):
    module = adapter()
    from app.adapters.bio_objects import BioAnalysisObjects
    path = tmp_path/'zero.json'
    path.write_bytes(b'[]')
    output = dict(key='first',role='table',format='json',path=str(path),size_bytes=2,
                  sha256=hashlib.sha256(b'[]').hexdigest())
    task = dict(id=str(uuid4()),input_digest='a'*64,input_snapshot=dict(run_id=str(uuid4())))
    result = dict(outputs=[output,{**output,'key':'second'}],manifest={},summary={},steps=[],checks=[],effective_params={})
    candidate, leaves = module.build_candidate(task,result,BioAnalysisObjects(tmp_path/'assets'),'qc')
    assert len(candidate['members']) == 2
    assert len({m['id'] for m in candidate['members']}) == 2
    assert candidate['members'][0]['object_key'] == candidate['members'][1]['object_key']
