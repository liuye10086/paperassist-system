"""Frozen local evidence is never forwarded or rendered as calculated report facts."""
from tests.helpers.legacy_plans import seed_legacy_plan
import json
from io import BytesIO
from zipfile import ZipFile
import pytest
from tests.api.test_analysis import client
from app.db.database import database_connection


@pytest.mark.parametrize('language',['zh-CN','en'])
def test_v4_local_external_claims_stay_out_of_cloud_and_word(client,monkeypatch,language):
    from tests.integration import test_correlation_artifact_chain as chain
    from tests.domain.test_correlation_plan_contracts import research,selection
    original_decision=chain.plan_decision
    original_plot,original_explanation=chain.ModernPlotProvider,chain.ModernExplanationProvider
    providers=[]
    class CapturedPlot(original_plot):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs);providers.append(self)
    class CapturedExplanation(original_explanation):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs);providers.append(self)
    def plan_decision(view,*args,**kwargs):
        return original_decision({**view,'check':view['check']['data_check']},*args,**kwargs)
    def create_plan(client,base,prepared):
        project=base.split('/')[4];file=base.split('/')[-1]
        evidence=client.post(f'/api/v1/projects/{project}/external-evidence',json=dict(file_id=file,source_kind='original',
            title='EXTERNAL-UNVERIFIED-99999',user_note='EXTERNAL-UNVERIFIED-99999 P=0.000001 n=99999',
            intended_use='reference',original_data='unknown'),headers={'Idempotency-Key':'local-material'})
        assert evidence.status_code==201,evidence.text
        chosen=selection();chosen.update(sheet_name=prepared['source']['sheet_name'],units={'A':'','B':''})
        body=dict(schema_version=4,input_kind='data',file_id=file,dataset_id=prepared['id'],expected_setup_revision=0,
            selection=chosen,research_request=research(),evidence_version_ids=[evidence.json()['id']])
        response=seed_legacy_plan(client, base+'/analysis-plans',json=body,headers={'Idempotency-Key':'material-plan'})
        assert response.status_code==202,response.text
        return response.json(),body
    monkeypatch.setattr(chain,'create_correlation',create_plan)
    monkeypatch.setattr(chain,'plan_decision',plan_decision)
    monkeypatch.setattr(chain,'ModernPlotProvider',CapturedPlot)
    monkeypatch.setattr(chain,'ModernExplanationProvider',CapturedExplanation)
    chain.test_confirmed_plan_to_original_png_explanation_word_and_history(client,monkeypatch,language,'pair','pearson')
    with database_connection() as db:
        reports=[json.loads(r['report_json']) for r in db.execute('SELECT report_json FROM reports')]
        assert len(reports)==1
    # Task snapshots are local provenance, not the material sent to a provider.
    assert len(providers)==2
    assert 'EXTERNAL-UNVERIFIED-99999' not in json.dumps(providers[0].payload)
    assert 'EXTERNAL-UNVERIFIED-99999' not in json.dumps([post[1] for post in providers[1].posts])
    from app.core.config import get_data_dir
    data=get_data_dir()
    words=list(data.rglob('*.docx'))
    assert words
    for word in words:
        with ZipFile(BytesIO(word.read_bytes())) as archive:
            assert all(b'EXTERNAL-UNVERIFIED-99999' not in archive.read(n) for n in archive.namelist())
