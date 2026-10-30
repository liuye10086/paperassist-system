"""Real saved native-order fixtures: never rebuild their insertion order."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pytest
from app.domain.external_processing import digest
from app.domain.figure_workbench import explanations as e

GOLDENS = Path(__file__).parents[1] / 'fixtures/figure_b07/old-v4-bundles-native-order'
assert len(list(GOLDENS.glob('*.json')))==17, 'All captured historical fixtures must be present.'

@pytest.fixture(autouse=True)
def postgres_schema():
    """This module exercises pure functions and deliberately uses no database."""
    yield None

@pytest.mark.parametrize('path', list(GOLDENS.glob('*.json')), ids=lambda p:p.name)
def test_native_v4_exact_replay(path):
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    value = json.loads(path.read_text(encoding='utf-8'))
    bundle, saved = value['bundle'], value['saved_explanation']
    original = deepcopy(value)
    assert e.V4_VERSION == 'figure_explanation_v4'
    assert e.validate_saved(bundle, saved) == saved
    payload = e.build_payload(bundle, version=e.V4_VERSION)
    assert digest(payload) == saved['payload_sha256'] == saved['provenance']['input_sha256']
    from app.domain.model_usage.gateway import input_digest
    assert input_digest(instructions=e.instructions_for(payload),payload=payload) == saved['provenance']['model_input_digest']
    rendered = e.render(bundle, saved['draft'], saved['provenance'],version=e.V4_VERSION)
    for key in ('sections','limitations','provenance','payload_sha256'):
        assert rendered[key] == saved[key]
    assert value == original
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before

def test_actual_v3_fixture_and_style_reuse_remain_v3():
    path=Path(__file__).parents[1]/'fixtures/historical_figure_explanation_v3.json'
    before=path.read_bytes();bundle=json.loads(before)
    saved=bundle['explanation']
    assert e.validate_saved(bundle,saved)==saved
    assert digest(e.build_payload(bundle,version=e.V3_VERSION))==saved['payload_sha256']
    newer=deepcopy(bundle);newer['figure'].update(id='offline-style',sha256='e'*64)
    newer['configuration']['config']['style']['palette']='gray'
    reused=e.reuse(bundle,newer,saved)
    assert reused['engine']['id']==e.V3_VERSION
    assert reused['payload_sha256']==saved['payload_sha256']
    assert e.validate_saved(newer,reused)==reused
    assert path.read_bytes()==before

def test_legacy_v1_and_v2_still_use_original_reference_templates():
    from tests.domain.test_batch05_figure_explanations import bundle as legacy_bundle
    from tests.domain.test_batch06_explanations_readable import frozen
    for bundle,version in ((legacy_bundle(),e.VERSION),(frozen('forest','en'),e.V2_VERSION)):
        bundle['figure'].update(analysis_run_id='offline',facts_sha256='a'*64,source={'kind':'prepared_dataset_version'})
        payload=e.build_payload(bundle,version=version)
        draft={section:'; '.join('{{'+key+'}}' for key in refs) for section,refs in payload['required_references'].items()}
        saved=e.render(bundle,draft,{'model_call_id':'offline','response_id':'offline'},version=version)
        assert e.validate_saved(bundle,saved)==saved
        assert saved['engine']['id']==version
