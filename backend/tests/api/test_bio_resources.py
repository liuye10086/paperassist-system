from tests.api.test_projects import client,create_project


def test_resource_request_is_queued_replayable_scoped_and_retains_real_original_file(client,monkeypatch):
    from app.domain.bio_insights.service import BioInsightsService
    from app.domain.bio_insights.resources import BioResourceService
    from app.adapters.storage import ProjectStore
    from app.core.config import get_data_dir
    from app.db.database import database_connection
    monkeypatch.setattr(BioInsightsService,'_runtime',lambda self:dict(engine_version='bio_insights_v1.0.0',environment_digest='e'*64,code_digest='c'*64,lock_sha256='f'*64))
    project=create_project(client)['id'];base=f'/api/v1/projects/{project}'
    uploaded=client.post(base+'/bio-resource-files',files={'file':('sets.gmt',b't1\tset 1\tg1\tg2\n')},headers={'Idempotency-Key':'gmt'}).json()
    body=dict(kind='gene_sets',title='custom sets',species_taxon_id=9606,namespace='Ensembl',release='v1',
        source=dict(institution='lab',name='provided sets',description='existing custom gene sets'),
        usage=dict(basis='project use',scope='project',redistribution_allowed=False),
        files=[dict(file_id=uploaded['file_id'],sha256=uploaded['sha256'],role='gmt',format='gmt')])
    assert client.post(base+'/bio-resources/preview',json=body).status_code==200
    response=client.post(base+'/bio-resources',json=body,headers={'Idempotency-Key':'resource-one'})
    assert response.status_code==202,response.text
    resource=response.json();assert resource['task']['task_type']=='bio_resource_import' and resource['members']==[]
    assert client.post(base+'/bio-resources',json=body,headers={'Idempotency-Key':'resource-one'}).status_code==200
    assert client.post(base+'/bio-resources',json={**body,'release':'v2'},headers={'Idempotency-Key':'resource-one'}).status_code==409
    assert client.get(base+'/bio-insight-requests/resource-one?kind=resource').json()['id']==resource['id']
    assert client.get(base+'/bio-resources').json()['total']==1
    other=create_project(client)['id']
    assert client.get(f'/api/v1/projects/{other}/bio-resources/{resource["id"]}').status_code==404
    with database_connection() as db:
        owner=db.execute('SELECT owner_id FROM projects WHERE id=%s',(project,)).fetchone()['owner_id']
        task=dict(db.execute('SELECT * FROM tasks WHERE id=%s',(resource['task_id'],)).fetchone())
    service=BioResourceService(ProjectStore(get_data_dir(),owner_id=owner))
    with service.store.connection() as db:
        payload=service.require_sources(db,task,runtime=False)
        assert payload['kind']=='bio_resource_import' and payload['config']['kind']=='gene_sets'
        assert payload['sources'][0]['source_id']==uploaded['file_id']
        initial=service.initial_resource_members(db,task)
        assert {m['role'] for m in initial}=={'input_snapshot','original_resource'}
        assert db.execute('SELECT original_file_id FROM bio_resource_members WHERE resource_version_id=%s AND role=%s',(resource['id'],'original_resource')).fetchone()['original_file_id']==uploaded['file_id']


def test_resource_impact_reaches_frozen_plan_and_run_and_rejects_other_project(client,monkeypatch,tmp_path):
    from tests.api.test_bio_insight_research_bridge import published
    from app.domain.bio_insights.execution import run_bio_insight_task
    from tests.domain.bio_insight_validation_fixtures import complete_resource,put,refresh,portable
    project,result,_=published(client,monkeypatch,tmp_path);base=f'/api/v1/projects/{project}'
    uploaded=client.post(base+'/bio-resource-files',files={'file':('sets.gmt',b't1\tset 1\tg1\n')},headers={'Idempotency-Key':'impact-gmt'}).json()
    body=dict(kind='gene_sets',title='custom sets',species_taxon_id=9606,namespace='Ensembl',release='v1',source=dict(institution='lab',name='provided sets',description='synthetic lifecycle'),usage=dict(basis='project use',scope='project',redistribution_allowed=False),files=[dict(file_id=uploaded['file_id'],sha256=uploaded['sha256'],role='gmt',format='gmt')])
    response=client.post(base+'/bio-resources',json=body,headers={'Idempotency-Key':'impact-resource'});assert response.status_code==202,response.text
    resource=response.json()
    def engine(payload,output):
        import json
        from pathlib import Path
        _,value=complete_resource(output);value['_root']=str(output);value['identity']=payload['identity'];value['manifest']['identity']=payload['identity']
        files=[{k:f[k] for k in ('file_id','sha256','format','role')} for f in payload['config']['files']]
        methods={k:payload['config'][k] for k in ('release','source','usage')};methods.update(resource_kind='gene_sets',input_files=files)
        value['methods']=methods;value['manifest']['methods']=methods;value['manifest']['source_bindings']=portable(payload['sources'])
        data=json.loads((Path(output)/'resource.json').read_text());data.update({k:payload['config'][k] for k in ('species_taxon_id','namespace','release','source','usage')});data['input_files']=files
        put(value,'resource',data);put(value,'methods',methods);put(value,'recipe',portable(payload));refresh(value);value.pop('_root');return value
    done=run_bio_insight_task(resource['task_id'],resource['task']['revision'],task_type='bio_resource_import',engine=engine,staging_directory=tmp_path/'resource-stage')
    assert done['status']=='succeeded',done
    resource=client.get(base+'/bio-resources/'+resource['id']).json()
    planbody=dict(name='resource dependency',kind='ora',decision='confirmed',expected_revision=0,sources=[dict(source_kind='bio_insight_result_version',source_id=result['id'],sha256=result['manifest_sha256'],role='result'),dict(source_kind='bio_resource_version',source_id=resource['id'],sha256=resource['manifest_sha256'],role='gene_sets')],config=dict(kind='ora',result_source_ids=[result['id']],resource_source_ids=[resource['id']],contrast_ids=['c'],q_column='original_q'))
    plan=client.post(base+'/bio-insight-plans',json=planbody,headers={'Idempotency-Key':'impact-ora-plan'});assert plan.status_code==201,plan.text
    plan=plan.json();run=client.post(base+'/bio-insight-runs',json=dict(plan_version_id=plan['id'],expected_plan_revision=1,source_digest=plan['source_digest']),headers={'Idempotency-Key':'impact-ora-run'});assert run.status_code==202,run.text
    response=client.get(base+'/bio-resources/'+resource['id']+'/impact');assert response.status_code==200,response.text
    affected={(v['source_kind'],v['source_id']) for v in response.json()['affected']}
    assert {('bio_insight_plan_version',plan['id']),('bio_insight_run',run.json()['id'])}<=affected
    other=create_project(client)['id'];assert client.get(f'/api/v1/projects/{other}/bio-resources/'+resource['id']+'/impact').status_code==404
