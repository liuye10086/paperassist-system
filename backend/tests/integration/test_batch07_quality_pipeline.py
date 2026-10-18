"""Persisted v2 waits, revisions, publication, authenticated complete receipts."""
import copy
from tests.integration.test_dataset_preparation import create_preparation, run, review, decide, decision
from tests.api.test_analysis import client
from app.db.database import database_connection, migration_connection

def published(client, rows=None):
    base,file,raw,request,task=create_preparation(client,rows=rows)
    run(task); accepted=decide(client,task,decision(review(client,task))).json()
    assert run(accepted)['status']=='succeeded'
    return base,review(client,task)['result']

def quality_task(client,base,parent,recipe=None,key='quality'):
    defaults=client.get(base+'/prepared-dataset-versions/'+parent['id']+'/quality-defaults')
    assert defaults.status_code==200, defaults.text
    request=dict(base_dataset_id=parent['id'],recipe=recipe or defaults.json()['recipe'])
    response=client.post(base+'/dataset-quality-preparations',json=request,headers={'Idempotency-Key':key})
    assert response.status_code==202, response.text
    return response.json(),request

def test_quality_full_wait_publish_history_and_download(client):
    base,parent=published(client,[['X','Y','Group'],[10,1,'A'],[20,2,'A'],[20,2,'A'],[' NA ',3,'A'],[40,None,'B'],[1000,10,'B'],[50,5,'B'],[1000,10,'B'],[60,6,'B'],[70,7,'B']])
    recipe=dict(fields=[dict(column=1,trim_text=True,missing_markers=['NA']),dict(column=2),dict(column=3)],manual_exclusions=[dict(row=9,reason='explicit'),dict(row=11,reason='synthetic')],duplicate_policy='exact')
    task,request=quality_task(client,base,parent,recipe)
    waiting=run(task); assert waiting['status']=='waiting_confirmation'
    view=review(client,task); assert view['preview']['retained_record_count']==7
    assert view['preview']['changed_cell_count']==1
    impact=client.get(view['impact_download_url']); assert impact.status_code==200
    assert len(impact.json()['entries'])==4
    filtered=client.get(view['impact_url'],params={'operation':'manual_exclusion','reason':'explicit','checkpoint_id':view['checkpoint_id']})
    assert filtered.status_code==200 and [e['row'] for e in filtered.json()['items']]==[9]
    accepted=decide(client,task,decision(view)).json()
    assert run(accepted)['status']=='succeeded'
    result=review(client,task)['result']; assert result['source']['schema_version']==2
    assert result['base_source']==parent['source'] and result['parent_dataset_id']==parent['parent_dataset_id']
    assert client.get(result['impact_download_url']).content==impact.content
    rows=client.get(base+'/prepared-dataset-versions/'+result['id']+'/rows').json()
    assert [r['row'] for r in rows['rows']]==[2,3,5,6,7,8,10]
    import os,json
    from pathlib import Path
    if os.environ.get('BATCH07_API_FIXTURE'):
        Path(os.environ['BATCH07_API_FIXTURE']).write_text(json.dumps(dict(
            defaults=client.get(base+'/prepared-dataset-versions/'+parent['id']+'/quality-defaults').json(),
            review=view,published=result,rows=rows,impacts=client.get(result['impact_url']).json()),ensure_ascii=False,indent=2),encoding='utf-8')
    assert client.post(base+'/dataset-quality-preparations',json=request,headers={'Idempotency-Key':'quality'}).json()['id']==task['id']
    assert run(accepted) is None
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM prepared_dataset_derivations').fetchone()['n']==1

def test_revision_paging_and_zero_active_block(client):
    base,parent=published(client,[['X','Y'],*([[' A ',1]]*45)])
    recipe=dict(fields=[dict(column=1,trim_text=True),dict(column=2)])
    task,_=quality_task(client,base,parent,recipe)
    run(task); view=review(client,task)
    assert [len(client.get(view['impact_url']+f'?page={p}').json()['items']) for p in (1,2,3)]==[20,20,5]
    revised=copy.deepcopy(view['recipe']); revised['manual_exclusions']=[dict(row=r,reason='explicit') for r in range(2,47)]
    accepted=decide(client,task,decision(view,'revise',revised),'revise').json()
    assert decide(client,task,decision(view),'stale').status_code==409
    assert run(accepted)['status']=='waiting_confirmation'
    new=review(client,task); assert new['preview']['retained_record_count']==0
    assert decide(client,task,decision(new),'empty').status_code==422

def test_receipt_and_parent_relation_tamper_fail_closed(client):
    base,parent=published(client)
    task,_=quality_task(client,base,parent); run(task)
    approved=decide(client,task,decision(review(client,task))).json(); assert run(approved)['status']=='succeeded'
    result=review(client,task)['result']
    with migration_connection(write=True) as db:
        db.execute("UPDATE prepared_dataset_derivations SET manifest_sha256=%s WHERE prepared_dataset_id=%s",('0'*64,result['id']))
    assert client.get(base+'/prepared-dataset-versions/'+result['id']).status_code==409

def test_legacy_task_has_no_quality_receipt(client):
    base,parent=published(client)
    response=client.get('/api/v1/tasks/'+parent['task_id']+'/dataset-preparation/impacts')
    assert response.status_code==404

def test_parallel_publications_share_root_sequence_and_keep_inherited_rows(client):
    from concurrent.futures import ThreadPoolExecutor
    base,parent=published(client)
    tasks=[]
    for key in ('q1','q2'):
        task,_=quality_task(client,base,parent,key=key); run(task)
        tasks.append(decide(client,task,decision(review(client,task)),key).json())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(run,tasks))
    assert [r['status'] for r in results]==['succeeded','succeeded']
    with database_connection() as db:
        versions=[r['version'] for r in db.execute('SELECT version FROM prepared_dataset_versions ORDER BY version')]
    assert versions==[1,2,3]
    parent=review(client,tasks[0])['result']
    recipe=dict(fields=[dict(column=1),dict(column=2)],manual_exclusions=[dict(row=3,reason='explicit')])
    task,_=quality_task(client,base,parent,recipe,key='child'); run(task)
    accepted=decide(client,task,decision(review(client,task)),'child').json(); assert run(accepted)['status']=='succeeded'
    result=review(client,task)['result']
    assert result['base_source']==parent['source'] and result['summary']['manual_excluded_row_count']==1

def test_side_relation_failure_rolls_back_publication_and_retry_once(client):
    base,parent=published(client)
    task,_=quality_task(client,base,parent); run(task)
    accepted=decide(client,task,decision(review(client,task))).json()
    with migration_connection(write=True) as db:
        db.execute("""CREATE FUNCTION reject_quality_write() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'isolated rollback'; END $$""")
        db.execute('CREATE TRIGGER reject_quality_write BEFORE INSERT ON prepared_dataset_derivations FOR EACH ROW EXECUTE FUNCTION reject_quality_write()')
    try:
        failed=run(accepted); assert failed['status']=='failed'
        with database_connection() as db:
            assert db.execute('SELECT count(*) AS n FROM prepared_dataset_versions').fetchone()['n']==1
            assert db.execute('SELECT count(*) AS n FROM prepared_dataset_derivations').fetchone()['n']==0
            assert db.execute('SELECT next_node FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(task['id'],)).fetchone()['next_node']=='publish'
    finally:
        with migration_connection(write=True) as db:
            db.execute('DROP TRIGGER reject_quality_write ON prepared_dataset_derivations')
            db.execute('DROP FUNCTION reject_quality_write()')
    retry=client.post('/api/v1/tasks/'+task['id']+'/retry',json={'expected_revision':failed['revision']})
    assert retry.status_code==202, retry.text
    assert run(retry.json())['status']=='succeeded' and run(retry.json()) is None

def test_cross_project_owner_and_stale_receipts_are_rejected(client):
    import pytest
    from tests.api.test_analysis import add_file
    from app.domain.dataset_preparation.quality_service import QualityPreparationService
    from app.adapters.task_store import DatasetTaskAssets
    from app.db.database import get_database_config
    from app.core.exceptions import StorageError
    base,parent=published(client)
    task,request=quality_task(client,base,parent); run(task); view=review(client,task)
    other,_=add_file(client)
    assert client.post(other+'/dataset-quality-preparations',json=request,headers={'Idempotency-Key':'cross'}).status_code==404
    with pytest.raises(StorageError):
        QualityPreparationService(DatasetTaskAssets('different-owner',get_database_config())).manifest_for_task(task['id'])
    changed=copy.deepcopy(view['recipe']); changed['manual_exclusions']=[dict(row=2,reason='explicit')]
    accepted=decide(client,task,decision(view,'revise',changed),'revise').json(); run(accepted)
    assert client.get(view['impact_download_url']).status_code==409

def test_relational_audit_rejects_ancestor_manifest_metadata_tamper(client):
    import pytest
    from app.domain.dataset_preparation.quality_service import audit_published
    from app.core.exceptions import StorageError
    base,parent=published(client)
    for key in ('ancestor','child'):
        task,_=quality_task(client,base,parent,key=key); run(task)
        accepted=decide(client,task,decision(review(client,task)),key).json(); assert run(accepted)['status']=='succeeded'
        ancestor=parent; parent=review(client,task)['result']
    with migration_connection(write=True) as db:
        db.execute('UPDATE prepared_dataset_derivations SET base_prepared_dataset_id=%s WHERE prepared_dataset_id=%s',(parent['id'],ancestor['id']))
    with database_connection() as db:
        task=db.execute('SELECT * FROM tasks WHERE id=%s',(parent['task_id'],)).fetchone()
        row=db.execute('SELECT * FROM prepared_dataset_versions WHERE id=%s',(parent['id'],)).fetchone()
        with pytest.raises(StorageError): audit_published(db,task,row)

def test_frozen_receipt_download_does_not_recompute_transform(client,monkeypatch):
    base,parent=published(client)
    task,_=quality_task(client,base,parent); run(task)
    accepted=decide(client,task,decision(review(client,task))).json(); assert run(accepted)['status']=='succeeded'
    result=review(client,task)['result']; expected=client.get(result['impact_download_url']).content
    def forbidden(*args,**kwargs): raise AssertionError('Downloads must not rebuild historical receipts')
    monkeypatch.setattr('app.domain.dataset_preparation.quality_service.prepare_quality',forbidden)
    assert client.get(result['impact_download_url']).content==expected

def test_malformed_published_summary_returns_source_conflict(client):
    base,parent=published(client)
    task,_=quality_task(client,base,parent); run(task)
    accepted=decide(client,task,decision(review(client,task))).json(); assert run(accepted)['status']=='succeeded'
    result=review(client,task)['result']
    with migration_connection(write=True) as db:
        db.execute("UPDATE prepared_dataset_versions SET summary_json=jsonb_set(summary_json,'{retained_record_count}','999'::jsonb) WHERE id=%s",(result['id'],))
    assert client.get(base+'/prepared-dataset-versions/'+result['id']).status_code==409

def test_quality_task_list_and_workspace_accept_prepared_base(client):
    base,parent=published(client)
    task,_=quality_task(client,base,parent); run(task)
    project=base.split('/files/')[0]
    response=client.get(project+'/tasks')
    assert response.status_code==200,response.text
    item=next(item for item in response.json()['items'] if item['task']['id']==task['id'])
    assert item['source']['dataset_source']==parent['source']
    response=client.get('/api/v1/tasks/'+task['id']+'/workspace')
    assert response.status_code==200,response.text
    assert response.json()['allowed_actions']==['approve','revise']
