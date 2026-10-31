import importlib.util

import pytest
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def contracts():
    name = 'app.domain.research_results.contracts'
    assert importlib.util.find_spec('app.domain.research_results') is not None, 'research contracts missing'
    return __import__(name, fromlist=['ResearchSourceSelection'])


def test_source_selection_is_stable_typed_and_frozen_digest_is_required():
    c = contracts()
    source = dict(source_kind='original_file', source_id='stable-id')
    assert c.ResearchSourceSelection.model_validate(source).locator.schema_version == 1
    with pytest.raises(ValidationError):
        c.ResearchSourceSelection.model_validate({**source, 'path': 'C:/arbitrary'})
    with pytest.raises(ValidationError):
        c.FrozenResearchSource.model_validate({**source, 'project_id': 'p'})
    for invalid in ({'kind':'cell','sheet':'x','cell':'A0'}, {'kind':'row','row_key':{},'column':'p'}, {'kind':'field','field_path':'../../file'}):
        with pytest.raises(ValidationError):
            c.ResearchSourceSelection.model_validate({**source, 'locator': invalid})


def test_finding_requests_do_not_accept_client_facts_and_require_root_cas():
    c = contracts()
    source = dict(source_kind='original_file',source_id='f')
    data = dict(title='findings',sources=[source],expected_revision=0)
    c.FindingVersionRequest.model_validate(data)
    for extra in ({'facts':[{'raw_value':42}]}, {'set_id':'existing'}, {'expected_revision':1}):
        with pytest.raises(ValidationError):
            c.FindingVersionRequest.model_validate({**data,**extra})


def test_fact_preserves_decimal_text_and_rejects_nonfinite_or_unbounded_catalog():
    c = contracts()
    data = dict(id='n',source_kind='original_file',source_id='f',source_sha256='a'*64,
                locator={'kind':'field','field_path':'shape.n'},raw_value='0.000000000000123',
                display_value='0.000000000000123',unit='',observation_level='spot',comparison='',verification_status='verified')
    assert c.ResearchFact.model_validate(data).raw_value == data['raw_value']
    with pytest.raises(ValidationError):
        c.ResearchFact.model_validate({**data,'raw_value':float('nan')})
    source=dict(source_kind='original_file',source_id='f',project_id='p',sha256='a'*64,provenance='external_result')
    with pytest.raises(ValidationError) as error:
        c.ResearchFactCatalog.model_validate({'source':source,'facts':[{**data,'id':str(i)} for i in range(1001)]})
    assert any(e['loc']==('facts',) and e['type']=='too_long' for e in error.value.errors())


def test_figure_limits_and_panel_identity_are_enforced():
    c = contracts()
    panel = dict(source={'source_kind':'bio_figure_version','source_id':'fig'},label='A')
    good = dict(mode='reuse',panels=[panel],expected_revision=0)
    figure = c.ResearchFigureRequest.model_validate(good)
    assert figure.width_mm == 180 and figure.dpi == 300
    for extra in ({'dpi':1200}, {'width_mm':241}, {'mode':'composite'}, {'panels':[panel]*7}, {'formats':['svg','svg']}):
        with pytest.raises(ValidationError):
            c.ResearchFigureRequest.model_validate({**good,**extra})


def test_candidate_scope_and_initial_vs_existing_manuscript_are_explicit():
    c = contracts()
    good = dict(delivery_id='d',finding_version_ids=['v'])
    assert c.ResearchCandidateRequest.model_validate(good).sections == ['results','materials_and_methods']
    for extra in ({'sections':['discussion']},{'manuscript_id':'m'},{'expected_revision':1},{'sources':[]}):
        with pytest.raises(ValidationError):
            c.ResearchCandidateRequest.model_validate({**good,**extra})
    c.ResearchCandidateRequest.model_validate({**good,'manuscript_id':'m','base_version_id':'v','expected_revision':1})


def test_report_bounds_and_header_idempotency_contract():
    c = contracts()
    data = dict(title='report',finding_version_id='v')
    assert c.ResearchReportRequest.model_validate(data).language == 'zh-CN'
    for extra in ({'figure_version_ids':['x']*51},{'request_key':'body-key'}):
        with pytest.raises(ValidationError):
            c.ResearchReportRequest.model_validate({**data,**extra})
