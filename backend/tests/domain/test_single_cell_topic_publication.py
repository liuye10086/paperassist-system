"""Exercise the real publication branch without a database or numerical run."""
from types import SimpleNamespace
import pytest

from app.core.exceptions import StorageError
from app.domain.bio_insights import service as module


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def publication(monkeypatch, method, mode, recorded_scope):
    identity={'environment_digest':'environment','code_digest':'code'}
    payload={'config':{'kind':'integration','schema_version':2,'method':method,'communication_mode':mode},'identity':identity,'sources':[]}
    task={'id':'task','project_id':'project','user_id':'owner','task_type':'bio_integration','input_snapshot':{'run_id':'run'}}
    run={'id':'run','kind':'integration','plan_version_id':'plan','result_version_id':None}
    calls=[]
    db=SimpleNamespace(execute=lambda sql,args:calls.append(('execute',sql,args)))
    service=object.__new__(module.BioInsightsService)
    service.require_sources=lambda *args,**kwargs:payload
    service.require=lambda *args:run
    monkeypatch.setattr(module,'object_by_key',lambda *args:{'id':'object','sha256':'a'*64})
    monkeypatch.setattr(module,'insert',lambda db,table,row:calls.append(('insert',table,row)))
    from app.domain.bioinformatics import analysis_service
    def finish(db, task, checkpoint, moment, column, identifier):
        calls.append(('finish',column,identifier))
        return identifier
    monkeypatch.setattr(analysis_service,'finish',finish)
    prepared={'manifest':{'inference_scope':recorded_scope,'identity':identity,'methods':{'name':method}},'manifest_ref':{},
        'members':[{'id':'member','key':'topic_plot','role':'figure','format':'png','sha256':'b'*64,'size_bytes':10}]}
    return lambda:service.publish(db,task,{},None,prepared,progress=lambda:None),calls


@pytest.mark.parametrize('method,mode,expected',[
    ('slingshot','per_donor','sample_exploratory'),
    ('genie3','per_donor','sample_exploratory'),
    ('cellchat','per_donor','sample_exploratory'),
    ('cellchat','paired','donor_inference'),
    ('cellchat','unpaired','donor_inference'),
])
def test_topic_publication_saves_actual_scope_and_finishes(monkeypatch,method,mode,expected):
    publish,calls=publication(monkeypatch,method,mode,expected)
    identifier=publish()
    saved=[call[2] for call in calls if call[:2]==('insert','bio_insight_result_versions')]
    assert len(saved)==1 and saved[0]['inference_scope']==expected
    assert saved[0]['kind']=='integration' and saved[0]['provenance']=='system_computed'
    assert any(call[:2]==('insert','bio_insight_result_members') for call in calls)
    assert any(call[0]=='execute' and call[2]==(identifier,'run') for call in calls)
    assert calls[-1]==('finish','result_bio_insight_result_version_id',identifier)


def test_topic_publication_rejects_incorrect_scope_before_writes(monkeypatch):
    publish,calls=publication(monkeypatch,'cellchat','paired','sample_exploratory')
    with pytest.raises(StorageError) as error:
        publish()
    assert error.value.code=='bio_insight_source_conflict'
    assert calls==[]
