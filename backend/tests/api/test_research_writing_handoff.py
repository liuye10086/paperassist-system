"""Research delivery candidates stay separate until explicit CAS publication."""
from tests.api.test_projects import client, upload


def prepared(client, kinds=None, title='外部数据事实'):
    project=client.post('/api/v1/projects',json=dict(name='闭环合成研究',research_topic='外部数字核对',project_type='research',delivery_kinds=kinds or ['sci_draft','thesis_draft']),headers={'Idempotency-Key':'handoff-project'}).json()
    base='/api/v1/projects/'+project['id']
    from app.db.database import database_connection
    with database_connection() as db:
        deliveries={r['kind']:r['id'] for r in db.execute('SELECT * FROM research_deliveries WHERE project_id=%s',(project['id'],)).fetchall()}
    file=upload(client,project['id']).json()['file']
    source=dict(source_kind='original_file',source_id=file['id'],locator=dict(kind='cell',sheet='研究数据',cell='B2'))
    finding=client.post(base+'/research-findings',json=dict(title=title,sources=[source]),headers={'Idempotency-Key':'handoff-finding'})
    assert finding.status_code==201,finding.text
    return base,deliveries,finding.json()


def test_exact_delivery_handoff_and_no_implicit_manuscript(client):
    base,deliveries,finding=prepared(client)
    body=dict(delivery_id=deliveries['sci_draft'],finding_version_ids=[finding['id']])
    response=client.post(base+'/research-results/writing-selection',json=body)
    assert response.status_code==200,response.text
    selected=response.json()
    assert selected['document_context']['document_kind']=='sci'
    assert selected['writing_scope']=='results_methods' and selected['can_execute'] is False
    assert selected['sources'][0]['kind']=='research_finding_version'
    assert 'file_id' not in selected['sources'][0]
    narrowed=client.post(base+'/research-results/writing-selection',json={**body,'sections':['results']})
    assert narrowed.status_code==200,narrowed.text
    assert narrowed.json()['merge_preview']['research_bridge']['sections']==['results']
    from app.db.database import database_connection
    with database_connection() as db:assert db.execute('SELECT count(*) AS n FROM manuscripts').fetchone()['n']==0
    assert client.post(base+'/manuscripts',json={}).status_code==409
    bad=client.post(base+'/research-results/writing-selection',json={**body,'delivery_id':'missing'})
    assert bad.status_code==404


def test_analysis_delivery_and_unconfigured_school_are_denied(client):
    base,deliveries,finding=prepared(client,['analysis','thesis_draft'])
    body=dict(finding_version_ids=[finding['id']])
    assert client.post(base+'/research-results/writing-selection',json={**body,'delivery_id':deliveries['analysis']}).status_code==409
    response=client.post(base+'/research-manuscript-candidates',json={**body,'delivery_id':deliveries['thesis_draft']},headers={'Idempotency-Key':'missing-school'})
    assert response.status_code==409,response.text
    config=client.get(base+'/research-results/writing-config',params={'delivery_id':deliveries['thesis_draft']})
    assert config.status_code==200,config.text
    assert config.json()['thesis']['ready'] is False


def test_first_candidate_explicit_publish_duplicate_recovery_and_stale_cas(client,tmp_path,monkeypatch):
    from app.adapters.task_execution_store import TaskExecutionStore
    def fail(self,*args,**kwargs):
        import sys
        raise sys.exc_info()[1]
    monkeypatch.setattr(TaskExecutionStore,'fail',fail)
    base,deliveries,finding=prepared(client)
    body=dict(delivery_id=deliveries['sci_draft'],finding_version_ids=[finding['id']])
    created=client.post(base+'/research-manuscript-candidates',json=body,headers={'Idempotency-Key':'candidate-first'})
    assert created.status_code==201,created.text
    value=created.json();assert value['manuscript_id'] is None and value['base_version_id'] is None
    from app.domain.research_results.execution import run_research_task
    done=run_research_task(value['task_id'],1,task_type='research_fact_draft',staging_directory=tmp_path/'stage')
    assert done['status']=='succeeded',done
    saved=client.get(base+'/research-manuscript-candidates/'+value['id']).json()
    assert saved['candidate']['candidate_origin']=='system_fact_draft'
    from app.db.database import database_connection
    with database_connection() as db:assert db.execute('SELECT count(*) AS n FROM manuscripts').fetchone()['n']==0
    endpoint=base+'/research-manuscript-candidates/'+value['id']+'/publish'
    publish=dict(candidate_id=value['id'],expected_revision=0)
    response=client.post(endpoint,json=publish,headers={'Idempotency-Key':'publish-first'})
    assert response.status_code==201,response.text
    result=response.json();root=result['manuscript_id']
    assert client.post(endpoint,json=publish,headers={'Idempotency-Key':'publish-first'}).json()==result
    assert client.post(endpoint,json=publish,headers={'Idempotency-Key':'publish-other'}).status_code==409
    history=client.get(base+'/manuscripts/'+root)
    assert history.status_code==200,history.text
    assert history.json()['versions'][0]['status']=='published'
    assert client.get(base+'/research-requests/candidate-first?kind=candidate').json()['id']==value['id']
    next_body={**body,'manuscript_id':root,'base_version_id':result['version_id'],'expected_revision':1,'sections':['results']}
    versions=[]
    for key in ['second','stale']:
        v=client.post(base+'/research-manuscript-candidates',json=next_body,headers={'Idempotency-Key':key}).json()
        assert run_research_task(v['task_id'],1,task_type='research_fact_draft',staging_directory=tmp_path/'stage')['status']=='succeeded'
        versions.append(v)
    for index,v in enumerate(versions):
        r=client.post(base+'/research-manuscript-candidates/'+v['id']+'/publish',json=dict(candidate_id=v['id'],expected_revision=1),headers={'Idempotency-Key':'publish-'+str(index)})
        assert r.status_code==(201 if index==0 else 409),r.text
    assert client.get(base+'/manuscripts/'+root+'/versions/1').status_code==200


def publish_candidate(client,base,body,tmp_path,key='integration'):
    from app.domain.research_results.execution import run_research_task
    response=client.post(base+'/research-manuscript-candidates',json=body,headers={'Idempotency-Key':key})
    assert response.status_code==201,response.text
    candidate=response.json()
    done=run_research_task(candidate['task_id'],1,task_type='research_fact_draft',staging_directory=tmp_path/'stage')
    assert done['status']=='succeeded',done
    published=client.post(base+'/research-manuscript-candidates/'+candidate['id']+'/publish',json=dict(candidate_id=candidate['id'],expected_revision=body.get('expected_revision',0)),headers={'Idempotency-Key':'publish-'+key})
    assert published.status_code==201,published.text
    return published.json()


def test_research_version_exports_and_enters_existing_writing_and_review(client,tmp_path):
    base,deliveries,finding=prepared(client)
    result=publish_candidate(client,base,dict(delivery_id=deliveries['sci_draft'],finding_version_ids=[finding['id']]),tmp_path)
    endpoint=base+'/manuscripts/'+result['manuscript_id']
    materials=client.get(endpoint+'/versions/1/writing-materials')
    assert materials.status_code==200,materials.text
    assert materials.json()['materials']['sources'][0]['facts'][0]['value']=='0'
    exported=client.post(endpoint+'/versions/1/exports',json={},headers={'Idempotency-Key':'export'})
    assert exported.status_code==201,exported.text
    from app.domain.manuscripts.execution import run_manuscript_task
    assert run_manuscript_task(exported.json()['task_id'],1)['status']=='succeeded'
    pdf=client.post(base+'/pdf-exports',json=dict(source_kind='manuscript_export',source_id=exported.json()['id'],request_key='research-project-pdf'))
    assert pdf.status_code==405,pdf.text
    preview=client.post(endpoint+'/writing-previews',json=dict(schema_version=2,output_language='zh-CN',base_revision=1,mode='full_draft',selected_source_ids=[finding['id']],selected_evidence_ids=[]),headers={'Idempotency-Key':'preview'})
    assert preview.status_code==201,preview.text
    context=client.get(endpoint+'/reviews/context')
    assert context.status_code==200,context.text


def test_school_research_uses_confirmed_purposes_and_preserves_frozen_context(client,tmp_path):
    from tests.api.test_thesis_manuscripts import bound
    from app.db.database import database_connection
    base,_,school=bound(client);project=base.split('/')[-1]
    with database_connection(write=True) as db:
        db.execute("UPDATE projects SET project_type='research' WHERE id=%s",(project,))
        delivery=db.execute("SELECT id FROM research_deliveries WHERE project_id=%s AND kind='thesis_draft'",(project,)).fetchone()['id']
    file=upload(client,project).json()['file']
    finding=client.post(base+'/research-findings',json=dict(title='学校研究',sources=[dict(source_kind='original_file',source_id=file['id'],locator=dict(kind='cell',sheet='研究数据',cell='B2'))]),headers={'Idempotency-Key':'school-finding'}).json()
    thesis=school['thesis'];thesis['chapter_mappings'][2]['result_group_ids']=['research-results']
    result=publish_candidate(client,base,dict(delivery_id=delivery,finding_version_ids=[finding['id']],thesis=thesis),tmp_path)
    endpoint=base+'/manuscripts/'+result['manuscript_id'];version=client.get(endpoint+'/versions/1')
    assert version.status_code==200,version.text
    snapshot=version.json()['snapshot'];assert snapshot['sections'][0]['purpose']=='introduction'
    assert snapshot['sections'][2]['paragraphs'][0]['research_fact']['raw_value']==0
    next_result=publish_candidate(client,base,dict(delivery_id=delivery,finding_version_ids=[finding['id']],manuscript_id=result['manuscript_id'],base_version_id=result['version_id'],expected_revision=1,sections=['results']),tmp_path,'school-next')
    next_snapshot=client.get(endpoint+'/versions/2').json()['snapshot']
    assert next_snapshot['thesis_context']==snapshot['thesis_context']
    assert next_snapshot['sections'][0]==snapshot['sections'][0] and next_snapshot['sections'][1]==snapshot['sections'][1]
    response=client.post(endpoint+'/writing-previews',json=dict(schema_version=3,base_revision=2,mode='rewrite_section',target_section='school-results',output_language='zh-CN',selected_source_ids=[finding['id']],selected_evidence_ids=[]),headers={'Idempotency-Key':'school-preview'})
    assert response.status_code==201,response.text
    with database_connection(write=True) as db:db.execute('UPDATE research_deliveries SET active=false WHERE id=%s',(delivery,))
    assert client.get(endpoint+'/versions/1').status_code==200
    assert client.get(base+'/research-results/writing-config',params={'delivery_id':delivery}).status_code==409
