"""Forward-only research-status facts and immutable real synthetic v3 evidence."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pytest
from app.core.exceptions import StorageError
from app.domain.figure_workbench import explanations as e
from app.domain.external_processing import digest
from tests.domain.test_batch06_explanations import draft


FIXTURE=Path(__file__).parents[1]/'fixtures/historical_figure_explanation_v3.json'


def golden():return json.loads(FIXTURE.read_text(encoding='utf-8'))


def test_real_published_v3_remains_readable_and_byte_unchanged():
    before=FIXTURE.read_bytes();bundle=golden();original=deepcopy(bundle)
    assert e.validate_saved(bundle,bundle['explanation'])==bundle['explanation']
    assert bundle==original and FIXTURE.read_bytes()==before
    old=e.build_payload(bundle,version='figure_explanation_v3')
    assert digest(old)==bundle['explanation']['payload_sha256']
    from app.domain.model_usage.gateway import input_digest
    assert input_digest(instructions=e.instructions_for(old),payload=old)==bundle['explanation']['provenance']['model_input_digest']
    assert old['facts']['design.status']['raw'] is True
    assert '尚未提供' in old['facts']['limitation.1']['value']
    assert e.version_for(bundle['figure'])=='figure_explanation_v5'


@pytest.mark.parametrize('language',['zh-CN','en'])
@pytest.mark.parametrize('provided',[False,True])
@pytest.mark.parametrize('structure',['unknown','independent'])
def test_v4_design_presence_and_verification_are_consistent(language,provided,structure):
    bundle=golden();bundle['figure']['language']=language
    request=bundle['result']['analysis_context']['plan']['research_request']
    request.update(output_language=language,study_design='PRIVATE DESIGN' if provided else '',observation_structure=structure)
    payload=e.build_payload(bundle,version=e.V4_VERSION)
    assert payload['figure_explanation_contract']==4
    assert payload['facts']['design.status']['raw'] is provided
    assert payload['facts']['design.structure']['raw']==structure
    assert 'PRIVATE DESIGN' not in json.dumps(payload,ensure_ascii=False)
    notes=[value['value'] for key,value in payload['facts'].items() if key.startswith('limitation.')]
    assert not any('研究设计、样本来源、实验步骤及测量背景尚未提供' in note for note in notes)
    if provided:
        assert not any('研究设计未提供' in note or 'Research design not provided' in note for note in notes)
    saved=e.render(bundle,draft(payload),{'model_call_id':'test','response_id':'test'},version=e.V4_VERSION)
    assert saved['engine']['id']=='figure_explanation_v4'
    assert e.validate_saved(bundle,saved)==saved


def test_unknown_or_cross_figure_explanation_versions_are_rejected():
    bundle=golden()
    for version in ('figure_explanation_v999','figure_explanation_v1','figure_explanation_v2'):
        bad=deepcopy(bundle['explanation']);bad['engine']['id']=version
        with pytest.raises(StorageError):e.validate_saved(bundle,bad)
    bad=deepcopy(bundle['explanation']);bad['engine']['id']='figure_explanation_v4'
    with pytest.raises(StorageError):e.validate_saved(bundle,bad)


def test_legacy_v3_style_reuse_retains_its_original_contract():
    old=golden();new=deepcopy(old);new['figure']['id']='style-copy';new['figure']['sha256']='a'*64
    new['configuration']['config']['style']['palette']='gray'
    value=e.reuse(old,new,old['explanation'])
    assert value['engine']['id']=='figure_explanation_v3'
    assert value['payload_sha256']==old['explanation']['payload_sha256']
    e.validate_saved(new,value)


@pytest.mark.parametrize('language',['zh-CN','en'])
def test_v4_roc_evaluation_role_is_a_user_declaration_not_program_verification(language):
    from tests.domain.test_batch06_explanations_readable import frozen
    bundle=frozen('roc_curve',language)
    bundle['figure']['engine']['id']='openai_figure_workbench_v3'
    bundle['figure']['presentation']['schema_version']=2
    old=e.build_payload(bundle,version='figure_explanation_v3');new=e.build_payload(bundle,version=e.V4_VERSION)
    label='用户声明的评估角色（未经程序核验）' if language=='zh-CN' else 'User-declared evaluation role (not programmatically verified)'
    assert new['facts']['modeling.evaluation_role']['label']==label
    assert label in new['facts']['modeling.coding']['value']
    for key in old['facts']:
        if not key.startswith('limitation.'):assert new['facts'][key]['raw']==old['facts'][key]['raw']
