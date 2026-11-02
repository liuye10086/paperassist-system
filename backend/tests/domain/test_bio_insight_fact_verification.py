import pytest
from app.domain.research_results.contracts import FrozenResearchSource
from app.domain.research_results.insight_projection import project_insight_facts

@pytest.fixture(autouse=True)
def postgres_schema():yield None

@pytest.mark.parametrize('provenance,status',[('external_result','unverified'),('system_computed','verified')])
@pytest.mark.parametrize('value',[0,False,'0','0.02','NOT_MEASURED',None])
def test_fact_verification_keeps_external_scope_and_exact_missing_zero_false(provenance,status,value):
    source=FrozenResearchSource(source_kind='bio_insight_result_member',source_id='member',project_id='project',sha256='a'*64,provenance=provenance,
        locator=dict(kind='row',table='comparison_results',row_key={'row_key':'r'},column='original_q'),
        content=dict(result_version_id='result',inference_scope='external_result' if provenance=='external_result' else 'derived',provenance=provenance,
            config={'kind':'result_import','na_values':['','NOT_MEASURED']},table_key='comparison_results',rows=[{'row_key':'r','original_q':value}]))
    fact=project_insight_facts(source).facts[0]
    assert fact.raw_value==value and type(fact.raw_value) is type(value)
    assert fact.verification_status==('missing' if value is None or value=='NOT_MEASURED' else status)
    assert fact.origin==provenance


def sample_source(value, row_key, schema_version=2):
    return FrozenResearchSource(source_kind='bio_insight_result_member',source_id='member',project_id='project',sha256='a'*64,provenance='system_computed',
        locator=dict(kind='row',table='comparison_results',row_key=row_key,column='p_value'),
        content=dict(result_version_id='result',inference_scope='sample_exploratory' if schema_version==2 else 'spot_exploratory',provenance='system_computed',
            config={'kind':'comparison','schema_version':schema_version},table_key='comparison_results',rows=[dict(row_key='opaque',feature_id='bovine',contrast_id='primary',p_value=value)]))


@pytest.mark.parametrize('value',[0,'0',None,'NA'])
def test_sample_explicit_readable_locator_keeps_values_and_old_fact_identity(value):
    from app.domain.research_results.bio_projection import fact_id
    from app.domain.research_results.contracts import ResearchLocator
    plain=sample_source(value,{'row_key':'opaque'})
    old=project_insight_facts(plain).facts[0]
    expected=ResearchLocator(kind='row',row_key={'row_key':'opaque'},column='p_value',table='comparison_results')
    assert old.id==fact_id(plain,expected) and old.locator==expected
    rich=sample_source(value,{'row_key':'opaque','feature_id':'bovine','contrast_id':'primary'})
    current=project_insight_facts(rich).facts[0]
    assert current.locator.row_key==rich.locator.row_key
    assert current.id==fact_id(rich,current.locator)
    assert current.raw_value==old.raw_value==value and type(current.raw_value) is type(value)
    assert current.display_value==old.display_value and current.verification_status==old.verification_status
    assert project_insight_facts(plain).facts[0].model_dump()==old.model_dump()
    legacy=sample_source(value,rich.locator.row_key,schema_version=1)
    previous=project_insight_facts(legacy).facts[0]
    assert previous.locator==expected and previous.id==fact_id(legacy,expected)


def test_sample_readable_locator_rejects_unverified_mismatch():
    with pytest.raises(ValueError):
        project_insight_facts(sample_source('0',{'row_key':'opaque','feature_id':'wrong'}))
