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
