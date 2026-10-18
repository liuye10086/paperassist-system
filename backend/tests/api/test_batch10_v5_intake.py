import pytest
from tests.api.test_analysis import client,selection
from tests.integration.test_research_plan import research

@pytest.mark.parametrize('kind',['legacy_plan','v4_requirement','legacy_preview','legacy_recommendation'])
def test_new_http_requests_cannot_bypass_v5_source_gate(client,kind):
    root='/api/v1/projects/unknown'
    if kind=='legacy_plan':path=root+'/files/unknown/analysis-plans';body=dict(dataset_id='unknown',expected_setup_revision=0,selection=selection())
    elif kind=='v4_requirement':path=root+'/analysis-plans';body=dict(schema_version=4,input_kind='data',file_id='unknown',dataset_id='unknown',expected_setup_revision=0,selection=None,research_request=research(),evidence_version_ids=[])
    else:
        path=root+'/files/unknown/analysis-recommendations'+('/preview' if kind=='legacy_preview' else '')
        body=dict(schema_version=4,dataset_id='unknown',sheet_name='Sheet1',candidate_columns=['A'],research_summary='safe',output_language='en')
        if kind=='legacy_recommendation':body['external_processing']={}
    response=client.post(path,json=body,headers={'Idempotency-Key':'legacy-source-bypass'})
    assert response.status_code==422,response.text
    assert response.json()['detail']['code']=='task_input_invalid'
