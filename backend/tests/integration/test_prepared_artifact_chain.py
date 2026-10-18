"""Historical pre-plan prepared results retain their independent artifact chain."""
from tests.helpers.legacy_statistics import seed_legacy_statistics
import copy
from io import BytesIO
from docx import Document
from app.adapters.storage import ProjectStore
from app.maintenance.database_audit import audit_database
from app.db.database import database_connection
from tests.api.test_analysis import client, selection
from tests.api.test_dataset_analysis import forbid_original
from tests.integration.test_dataset_preparation import create_preparation, run, review, decide, decision
from tests.integration import test_dataset_artifact_chain as raw_chain


def prepared_result(client):
    rows=[['说明'],[],[None,None,'处理组','读数'],[None,None,'不选此行',900],
          [None,None,' A ',1],[None,None,'NA',3],[None,None,' A ',5],
          [None,None,' B ',7],[None,None,' B ',9],[None,None,None,None],['边界标记']]
    base,file,raw,request,initial=create_preparation(client,rows=rows)
    run(initial)
    first=review(client,initial)
    defaults=client.get(base+'/dataset-versions/'+raw['id']+'/preparation-defaults',params={'header_row':3,'data_range':'C5:D10'})
    assert defaults.status_code==200,defaults.text
    recipe=defaults.json()['recipe']
    recipe['fields'][0].update(trim_text=True,missing_markers=['NA'])
    recipe['fields'][1].update(name='体重',unit=dict(status='confirmed',value='mg'))
    revised=decide(client,initial,decision(first,'revise',recipe),'revise-range')
    assert revised.status_code==202,revised.text
    run(revised.json())
    final=review(client,initial)
    approved=decide(client,initial,decision(final),'approve-range')
    assert approved.status_code==202,approved.text
    assert run(approved.json())['status']=='succeeded'
    prepared=review(client,initial)['result']
    saved=client.put(base+'/analysis-setup',json=selection(dataset_id=prepared['id'],expected_revision=0,
        numeric_column='D',group_column='C',unit='mg'))
    assert saved.status_code==200,saved.text
    # Explicit old persisted result, with real bounded math and legacy_unverified.
    result=seed_legacy_statistics(client,base,revision=1)
    assert result['source']==prepared['source']
    assert result['numeric_name']=='体重' and result['group_name']=='处理组'
    assert result['check']['row_count']==6 and result['check']['valid_count']==4 and result['check']['excluded_count']==2
    assert result['overall']['n']==4 and result['overall']['mean']==5.5
    return base,file,result


def test_prepared_full_chain_preserves_coordinates_source_and_word_labels(client,monkeypatch):
    monkeypatch.setattr(raw_chain,'new_result',prepared_result)
    chain=raw_chain.complete_chain(client,monkeypatch)
    text='\n'.join(p.text for p in Document(BytesIO(client.get(chain['report_url']).content)).paragraphs)
    assert '原始数据版本 1 · 整理数据版本 1' in text
    assert '所选整理区域 6 行' in text and '体重（列 D）' in text
    with database_connection() as db:
        audit=audit_database(db)
    assert audit['ok'],audit


def test_prepared_profile_and_old_saved_selection_survive_another_version(client,monkeypatch):
    base,file,result=prepared_result(client)
    source=copy.deepcopy(result['source'])
    profile=client.get(base+'/analysis-profile',params={'sheet':source['sheet_name'],'dataset_id':source['dataset_id']})
    assert profile.status_code==200,profile.text
    assert [(c['id'],c['name']) for c in profile.json()['columns']]==[('C','处理组'),('D','体重')]
    assert profile.json()['columns'][1]['unit']==dict(status='confirmed',value='mg')
    defaults=client.get(base+'/dataset-versions/'+source['parent_dataset_id']+'/preparation-defaults').json()
    second=client.post(base+'/dataset-preparations',json=dict(dataset_id=source['parent_dataset_id'],recipe=defaults['recipe']),headers={'Idempotency-Key':'next-version'}).json()
    run(second)
    accepted=decide(client,second,decision(review(client,second)),'approve-next').json()
    assert run(accepted)['status']=='succeeded'
    assert review(client,second)['result']['version']==2
    monkeypatch.setattr(ProjectStore,'original',forbid_original)
    assert client.get(base+'/analysis-setup').json()['source']==source
    state=client.get(base+'/analysis-result')
    assert state.status_code==200,state.text
    assert state.json()['result']['source']==source
