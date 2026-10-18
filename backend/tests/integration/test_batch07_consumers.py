"""Only isolated synthetic schemas/assets; no cloud model is invoked."""
from tests.helpers.legacy_plans import seed_legacy_plan
from tests.helpers.statistics import statistics_post
from tests.api.test_analysis import client
from tests.integration.test_batch07_quality_pipeline import published, quality_task
from tests.integration.test_dataset_preparation import run, review, decide, decision
from app.db.database import database_connection, migration_connection


def quality_published(client, base, parent, *, key='quality'):
    task,_=quality_task(client,base,parent,key=key)
    assert run(task)['status']=='waiting_confirmation'
    accepted=decide(client,task,decision(review(client,task))).json()
    assert run(accepted)['status']=='succeeded'
    return review(client,task)['result']


def test_v2_parent_chain_readonly_source_audit_and_lifecycle(client):
    from app.maintenance.dataset_source_audit import audit_dataset_sources
    base,parent=published(client)
    child=quality_published(client,base,parent)
    grandchild=quality_published(client,base,child,key='quality-second')
    with database_connection() as db:
        checks=audit_dataset_sources(db)
    assert all(c['invalid']==0 for c in checks),checks
    details=client.get(base+'/details')
    assert details.status_code==200,details.text
    assert details.json()['references']['prepared_dataset_derivations']==2
    assessment=client.get(base+'/lifecycle/assessment').json()
    assert assessment['counts']['prepared_dataset_derivations']==2
    assert not any(r['code']=='integrity_unknown' for r in assessment['reasons']),assessment
    with migration_connection(write=True) as db:
        db.execute('UPDATE prepared_dataset_derivations SET manifest_sha256=%s WHERE prepared_dataset_id=%s',('0'*64,child['id']))
    with database_connection() as db:
        checks=audit_dataset_sources(db)
    assert any(c['table']=='prepared_dataset_derivations' and c['invalid'] for c in checks)


def test_one_quality_source_requires_two_plans_and_keeps_distinct_effective_n(client):
    import pytest
    from tests.integration.test_correlation_plan import prepared_correlations, create_correlation
    from tests.helpers.analysis_plan import run_plan,review_plan,plan_decision,decide_plan
    from app.maintenance.database_audit import audit_database
    base,_,parent=prepared_correlations(client,rows=[['X','Y','Group'],[10,1,'A'],[20,2,'A'],[20,2,'A'],[' NA ',3,'A'],[40,None,'B'],[1000,10,'B'],[50,5,'B'],[1000,10,'B'],[60,6,'B'],[70,7,'B']])
    recipe=dict(fields=[dict(column=1,trim_text=True,missing_markers=['NA']),dict(column=2),dict(column=3)],manual_exclusions=[dict(row=9,reason='Synthetic reason'),dict(row=11,reason='Synthetic reason')],duplicate_policy='exact')
    task,_=quality_task(client,base,parent,recipe)
    run(task);accepted=decide(client,task,decision(review(client,task))).json();run(accepted)
    quality=review(client,task)['result']
    selected=dict(task_type='descriptive_boxplot',sheet_name=quality['source']['sheet_name'],numeric_column='A',group_column=None,unit='',missing_policy='exclude_selected_missing')
    response=seed_legacy_plan(client, base+'/analysis-plans',json=dict(dataset_id=quality['id'],expected_setup_revision=0,selection=selected),headers={'Idempotency-Key':'descriptive-quality-plan'})
    assert response.status_code==202,response.text
    plan=response.json()
    assert run_plan(plan)['status']=='waiting_confirmation'
    assert statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).status_code==409
    approved=decide_plan(client,plan,plan_decision(review_plan(client,plan))).json()
    assert run_plan(approved)['status']=='succeeded'
    result=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1})
    assert result.status_code==200,result.text
    descriptive=result.json()
    assert descriptive['overall']['n']==6 and descriptive['overall']['mean']==pytest.approx(1180/6)
    assert descriptive['check']['row_count']==7 and descriptive['check']['excluded_count']==1
    correlation,_=create_correlation(client,base,quality,changes={'expected_setup_revision':1})
    assert run_plan(correlation)['status']=='waiting_confirmation'
    approved=decide_plan(client,correlation,plan_decision(review_plan(client,correlation))).json()
    assert run_plan(approved)['status']=='succeeded'
    result=statistics_post(client, base+'/analysis-runs',json={'expected_revision':2})
    assert result.status_code==200,result.text
    value=result.json()
    assert value['statistics']['n']==5 and value['check']['excluded_count']==2
    assert value['source']==descriptive['source']==quality['source']
    assert value['analysis_plan']['plan_id']!=descriptive['analysis_plan']['plan_id']
    assert value['row_audit']['included_rows']==[2,3,7,8,10]
    with database_connection() as db:
        audit=audit_database(db)
    assert audit['ok'],audit


def quality_correlations(client):
    from tests.integration.test_correlation_plan import prepared_correlations
    base,file,parent=prepared_correlations(client)
    recipe=dict(fields=[dict(column=i) for i in (1,2,3)],manual_exclusions=[dict(row=6,reason='LOCAL-QUALITY-REASON')],duplicate_policy='exact')
    task,_=quality_task(client,base,parent,recipe)
    run(task);accepted=decide(client,task,decision(review(client,task))).json();run(accepted)
    return base,file,review(client,task)['result']


def test_quality_single_word_freezes_local_receipt_and_keeps_cloud_boundary(client,monkeypatch):
    import json
    from tests.integration import test_correlation_artifact_chain as chain
    monkeypatch.setattr(chain,'prepared_correlations',quality_correlations)
    chain.test_confirmed_plan_to_original_png_explanation_word_and_history(client,monkeypatch,'en','pair','pearson')
    with database_connection() as db:
        snapshots=db.execute('SELECT task_type,input_snapshot FROM tasks').fetchall()
    words=[r['input_snapshot'] for r in snapshots if r['task_type']=='word_report']
    assert len(words)==1 and words[0]['processing']['receipt']['manual_excluded_row_count']==1
    assert 'LOCAL-QUALITY-REASON' in json.dumps(words[0]['processing'])
    for row in snapshots:
        if row['task_type'] in ('boxplot','explanation'):
            assert 'processing' not in row['input_snapshot']
            assert 'LOCAL-QUALITY-REASON' not in json.dumps(row['input_snapshot'])
    from app.maintenance.dataset_source_audit import audit_dataset_sources
    with migration_connection(write=True) as db:
        db.execute("UPDATE tasks SET input_snapshot=jsonb_set(input_snapshot,'{processing,receipt,retained_record_count}','999'::jsonb) WHERE task_type='word_report'")
    with database_connection() as db:
        checks=audit_dataset_sources(db)
    assert any(c['table']=='tasks' and c['invalid'] for c in checks)


def test_quality_collection_freezes_receipt_with_current_profile_and_independent_n(client,monkeypatch):
    from tests.integration import test_batch05_figure_store as source_module
    from tests.integration.test_batch05_collection_pipeline import complete_collection
    from app.maintenance.database_audit import audit_database
    monkeypatch.setattr(source_module,'prepared_correlations',quality_correlations)
    repository,project,result,state,_,_=complete_collection(client,monkeypatch)
    preview=repository.preview(project,state['id'],state['current_version_id'])
    assert result['source']['schema_version']==2
    assert preview['sections'][1]['content'][0]['record_count']==4
    processing=next(section for section in preview['sections'] if section['key']=='processing')['content'][0]
    assert processing['receipt']['root_record_count']==5 and processing['receipt']['retained_record_count']==4
    assert preview['items'][0]['result']['check']['valid_count']==3
    assert preview['items'][0]['projection']['result']['audit']['valid_n']==4
    request=state['versions'][0]['requests'][0]
    _,content=repository.download(project,state['id'],request['report']['id'])
    from docx import Document
    from io import BytesIO
    text=' '.join(p.text for p in Document(BytesIO(content)).paragraphs)
    assert 'LOCAL-QUALITY-REASON' in text
    with database_connection() as db:
        audit=audit_database(db)
        assert db.execute('SELECT count(*) AS n FROM model_calls WHERE task_id=%s',(request['task_id'],)).fetchone()['n']==0
    assert audit['ok'],audit
