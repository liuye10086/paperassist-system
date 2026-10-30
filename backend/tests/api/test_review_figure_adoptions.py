"""Synthetic A/B real local numerics and pixels; provider only replaces network."""
from copy import deepcopy
from io import BytesIO
from hashlib import sha256
import json
import pytest
from tests.api.test_analysis import client


def post(client, path, body, key):
    return client.post(path, json=body, headers={'Idempotency-Key': key})


def actual_plot(client, monkeypatch, *, project=None, second=False):
    from tests.integration.test_correlation_plan import prepared_correlations
    from tests.helpers.analysis_plan import run_plan, review_plan, decide_plan
    from tests.helpers.statistics import statistics_post
    from tests.helpers.tasks import task_owner
    from tests.helpers.projection import check_projection, confirm_projection
    from tests.integration.test_batch05_figure_execution import frozen_policy, IndependentLineProvider
    from tests.api.test_review_science import upload_in_project
    from app.adapters.storage import ProjectStore
    from app.core.config import get_data_dir
    from app.adapters.figure_workbench_store import FigureWorkbenchStore, read_bundle
    from app.domain.figure_workbench.contracts import SaveConfiguration, ConfirmProjection, GenerateFigure
    from app.domain.figure_workbench.tasks import submit
    from app.domain.figure_workbench.execution import run_figure_workbench_task
    from app.domain.model_usage.service import ModelUsageService
    rows = [['X','Y','Observation'],[1,2,9],[2,4,8],[3,6,7],[4,None,6],[None,10,5]]
    if second:rows = [['X','Y','Observation'],[1,3,2],[2,8,5],[3,4,11],[4,9,18],[5,None,20]]
    with monkeypatch.context() as upload:
        if project:
            upload.setattr('tests.integration.test_dataset_preparation.add_file', lambda instance, values: upload_in_project(instance, project, values))
            original_post=client.post
            def namespaced_post(url,**kwargs):
                headers=dict(kwargs.get('headers') or {})
                if 'Idempotency-Key' in headers:headers['Idempotency-Key']='B-'+headers['Idempotency-Key']
                kwargs['headers']=headers
                return original_post(url,**kwargs)
            upload.setattr(client,'post',namespaced_post)
        path, file, prepared = prepared_correlations(client, rows=rows)
        from tests.domain.test_correlation_plan_contracts import selection,research
        from tests.test_batch09_research_flow import decision
        selected=selection();selected.update(sheet_name=prepared['source']['sheet_name'],units={'A':'','B':''})
        created=post(client,path+'/analysis-plans',dict(schema_version=5,input_kind='data',file_id=file['id'],dataset_id=prepared['id'],expected_setup_revision=0,selection=selected,research_request=research(),evidence_version_ids=[]),'current-v5-plan')
        assert created.status_code==202,created.text
        planned=created.json();assert run_plan(planned)['status']=='waiting_input'
        view=review_plan(client,planned)
        clarification={k:view[k] for k in ('input_version','checkpoint_id','wait_id','plan_revision')}
        clarification.update(expected_task_revision=view['task']['revision'],source_resolution=dict(confirmed=True,note='Synthetic exact uploaded file and prepared worksheet confirmed.'))
        supplied=post(client,'/api/v1/tasks/'+planned['id']+'/analysis-plan/source-decisions',clarification,'current-v5-source')
        assert supplied.status_code==202,supplied.text
        assert run_plan(supplied.json())['status']=='waiting_confirmation'
        approved=decide_plan(client,planned,decision(review_plan(client,planned)),'current-v5-approve')
        assert approved.status_code==202,approved.text
        assert run_plan(approved.json())['status']=='succeeded'
    result = statistics_post(client, path+'/analysis-runs', json={'expected_revision': 1}).json()
    assert result['engine']['id'] != 'synthetic_fixture'
    workbench = FigureWorkbenchStore(ProjectStore(get_data_dir(), owner_id=task_owner(client)))
    project = path.split('/')[4];args = (project, file['id'], result['id'])
    saved = workbench.save(*args, SaveConfiguration(config=dict(figure_kind='line',language='en',projection=dict(x_column='A',y_column='C'),style=dict(title='Synthetic B' if second else 'Synthetic A'))))
    vid = saved['version']['id'];checked = check_projection(workbench, *args, vid)
    projection = confirm_projection(workbench, *args, vid, ConfirmProjection(input_sha256=checked['input_sha256'], approved=True))
    monkeypatch.setattr('app.domain.figure_workbench.tasks.policy_for', frozen_policy)
    task = submit(workbench, *args, vid, GenerateFigure(idempotency_key='synthetic-B' if second else 'synthetic-A', external_processing=dict(confirmed=True,payload_sha256=workbench.external_preview(*args,vid)['payload_sha256'])))['task']
    for scope, key in [('user', workbench.tasks.user_id), ('project', project)]:
        usage=ModelUsageService(workbench.tasks.user_id);budget=usage.get_budget(scope,key)
        if budget['limit_micro_usd'] is None:usage.set_budget(scope,key,5000000,0)
    # Honest controlled transport: actual local projection supplies both its
    # synthetic manifest and an input-dependent Pillow geometry, never old bytes.
    class LocalPixels(IndependentLineProvider):
        def receipt(self):
            value=super().receipt();identity='resp_synthetic_'+result['id']
            value['response_id']=identity;value['response']['id']=identity
            return value
        def upload_input(self, container_id, payload, *, policy):
            response=super().upload_input(container_id,payload,policy=policy)
            from PIL import Image, ImageDraw
            image=Image.new('RGB',(2400,1600),'white');draw=ImageDraw.Draw(image)
            points=[(100+float(r['x'])*300,1450-float(r['y'])*50) for r in payload['observations'] if r.get('x') is not None and r.get('y') is not None]
            draw.line(points,fill='navy',width=10)
            for x,y in points:draw.ellipse((x-12,y-12,x+12,y+12),fill='red')
            draw.text((80,40),'SYNTHETIC local Pillow pixels / network disabled',fill='black')
            raw=BytesIO();image.save(raw,format='PNG');self.png=raw.getvalue()
            return response
        def download(self, file_id, container_id, limit, *, policy):
            if file_id=='cfile_png':return self.png
            # This is a controlled manifest, not an independent external recompute.
            expected=workbench.material(*args,vid)[4]
            return json.dumps(expected).encode()
    provider=LocalPixels(result,pending=False)
    for _ in range(5):
        task=run_figure_workbench_task(task['id'],task['revision'],provider_factory=lambda:provider)
        if task['status'] in ('succeeded','failed'):break
    assert task['status']=='succeeded',task
    bundle=read_bundle(workbench.assets,project,task['result_figure_id'])
    assert workbench.assets.figure_png(bundle['figure'])==provider.png
    return dict(project=project,file=file,result=result,config_id=vid,task=task,figure=bundle['figure'],png=provider.png,projection=projection,workbench=workbench)


def scenario(client,monkeypatch,*,full_parent=False):
    from app.domain.tasks.execution import run_task
    a=actual_plot(client,monkeypatch)
    path=f'/api/v1/projects/{a["project"]}/manuscripts'
    sources=[dict(kind='analysis_run',id=a['result']['id'],file_id=a['file']['id'],role='computed_results'),dict(kind='figure',id=a['figure']['id'],file_id=a['file']['id'],role='image_observation')]
    response=post(client,path,dict(title='Synthetic fixed parent A',output_language='en',sources=sources,results_groups=[dict(id='main',title='Synthetic results',analysis_run_ids=[a['result']['id']],figure_ids=[a['figure']['id']])]),'parent')
    assert response.status_code==201,response.text
    root=path+'/'+response.json()['id'];parent=response.json()['versions'][0]
    assert run_task(parent['task_id'],1)['status']=='succeeded'
    if full_parent:
        from tests.api.test_manuscript_writing_execution import WritingProvider
        from app.domain.model_usage.service import ModelUsageService
        from tests.helpers.tasks import task_owner
        from app.domain.manuscript_writing.execution import run_manuscript_writing_task
        requested=post(client,root+'/writing-requests',dict(base_revision=1,mode='full_draft',instructions='Synthetic A fixed numeric paragraphs; preserve saved result groups.',keywords=[],acknowledgements=''),'synthetic-parent-writing')
        assert requested.status_code==202,requested.text
        task=requested.json()['task'];usage=ModelUsageService(task_owner(client))
        usage.set_budget('task',task['id'],5000000,0)
        class ParentProvider(WritingProvider):
            def receipt(self):
                value=super().receipt();sections=deepcopy(self.payload['normalized_sections'])
                for section in sections:
                    section['paragraphs']=[{k:v for k,v in p.items() if k in ('id','text','source_ids','citations','numeric_bindings','origin')} for p in section['paragraphs']]
                    if section['id'] in ('abstract','discussion'):
                        section['paragraphs']=[dict(id='synthetic:'+section['id']+':1',text='n = '+str(a['result']['statistics']['n']),source_ids=[a['result']['id']],citations=[],numeric_bindings=[dict(source_id=a['result']['id'],value=str(a['result']['statistics']['n']))])]
                value['response']['output'][0]['content'][0]['text']=json.dumps(dict(sections=sections));return value
        done=run_manuscript_writing_task(task['id'],task['revision'],provider=ParentProvider(pending=False));assert done['status']=='succeeded',done
        published=post(client,root+'/writing-requests/'+task['id']+'/publish',dict(expected_revision=1),'synthetic-parent-publish')
        assert published.status_code==201,published.text
        parent=published.json()['versions'][0];assert run_task(parent['task_id'],1)['status']=='succeeded'
    url=f'/api/v1/projects/{a["project"]}/reviews'
    response=post(client,url+'/rounds',dict(title='Synthetic redraw',project_type='sci',synthetic=True,manuscript=dict(id=root.split('/')[-1],revision=parent['revision'],version_id=parent['id']),sources=[dict(role='reviewer',label='Synthetic reviewer',format='text',text='1. Update statistics and redraw the figure.')]),'round')
    assert response.status_code==202,response.text
    run_task(response.json()['task']['id'],1)
    round=client.get(url+'/rounds/'+response.json()['id']).json();path=url+'/rounds/'+round['id']
    b=actual_plot(client,monkeypatch,project=a['project'],second=True)
    link=post(client,path+'/task-links',dict(plan_revision=round['revision'],item_id=round['items'][0]['id'],task_id=b['task']['id'],purpose='plot'),'plot-link')
    assert link.status_code==201,link.text
    body=dict(plan_revision=round['revision'],item_id=round['items'][0]['id'],task_link_id=link.json()['id'],expected_current_revision=parent['revision'],supersedes_figure_id=a['figure']['id'],affected_locations=[dict(kind='figure',id=a['figure']['id'])],reason='Explicit synthetic B pixels replace A.')
    return a,b,root,parent,url,path,round,body


def test_figure_adoption_contract_exists_and_new_table_is_scoped():
    from app.domain.review_rounds.science import ScienceService
    from app.db.schema import metadata
    assert hasattr(ScienceService,'create_figure_adoption'), 'Explicit saved figure adoption is missing'
    assert 'review_figure_adoptions' in metadata.tables


def test_actual_synthetic_new_pixels_explicit_adoption_revision_docx_parent_and_history(client,monkeypatch,tmp_path):
    from app.domain.tasks.execution import run_task
    from app.db.database import database_connection
    from app.maintenance.review_science_audit import audit_review_science
    from zipfile import ZipFile
    a,b,root,parent,url,path,round,body=scenario(client,monkeypatch,full_parent=True)
    assert a['result']['statistics']!=b['result']['statistics']
    assert a['projection']['result']['series']!=b['projection']['result']['series']
    assert sha256(a['png']).hexdigest()!=sha256(b['png']).hexdigest()
    response=post(client,path+'/figure-adoptions',body,'figure-adopt')
    assert response.status_code==201,response.text
    adopted=response.json()
    from sqlalchemy.exc import DBAPIError
    from app.db.database import migration_connection
    with pytest.raises(DBAPIError):
        with database_connection(write=True) as db:db.execute('UPDATE review_figure_adoptions SET snapshot_json=snapshot_json WHERE id=%s',(adopted['id'],))
    with pytest.raises(DBAPIError,match='Immutable review continuation history'):
        with migration_connection(write=True) as db:db.execute('UPDATE review_figure_adoptions SET snapshot_json=snapshot_json WHERE id=%s',(adopted['id'],))
    assert client.get(root+'/versions/'+str(parent['revision'])).json()['snapshot']==parent['snapshot']
    assert post(client,path+'/figure-adoptions',body,'figure-adopt').json()['id']==adopted['id']
    assert post(client,path+'/figure-adoptions',body|dict(reason='Changed'),'figure-adopt').status_code==409
    with database_connection() as db:
        statistics=db.execute("SELECT id FROM tasks WHERE result_analysis_run_id=%s AND task_type='statistics_compute'",(b['result']['id'],)).fetchone()
    linked=post(client,path+'/task-links',dict(plan_revision=round['revision'],item_id=round['items'][0]['id'],task_id=statistics['id'],purpose='statistics'),'statistics-link').json()
    analysis=post(client,path+'/analysis-adoptions',dict(plan_revision=round['revision'],item_id=round['items'][0]['id'],task_link_id=linked['id'],supersedes_source_ids=[a['result']['id']],affected_locations=[dict(kind='figure',id=a['figure']['id'])],reason='Adopt actual local B statistics.'),'analysis-adopt')
    assert analysis.status_code==201,analysis.text
    context=client.get(path+'/revision-context').json();facts={f['path']:f for f in context['analysis_facts']}
    fact=facts['/statistics/n']
    ops=[dict(item_id=round['items'][0]['id'],kind='replace_paragraph',location_id=p['id'],text='n = '+fact['value']+('; Table 1.' if p.get('cross_references') else ''),evidence_ids=[b['result']['id']],numeric_bindings=[dict(fact_id=fact['id'],value=fact['value'])],reason='Explicit exact B numeric prose.') for section in parent['snapshot']['sections'] for p in section['paragraphs'] if a['result']['id'] in p.get('source_ids',[])]
    assert {s['id'] for s in parent['snapshot']['sections'] if any(o['location_id']==p['id'] for p in s['paragraphs'] for o in ops)}>={'abstract','results','discussion'},'Actual parent must exercise all three numeric sections'
    data=dict(plan_revision=round['revision'],expected_current_revision=parent['revision'],operations=ops,analysis_adoption_ids=[analysis.json()['id']],figure_adoption_ids=[adopted['id']])
    old_numbers=deepcopy(data);old_numbers['operations']=[]
    # Figure-only adoption cannot silently replace old statistical statements.
    blocked=post(client,path+'/revisions/preview',data|dict(operations=[dict(item_id=round['items'][0]['id'],kind='figure_caption',location_id=b['figure']['id'],text=b['figure']['caption'],evidence_ids=[b['figure']['id']],reason='Only caption.')]),'blocked')
    assert blocked.status_code==200 and not blocked.json()['can_adopt'],blocked.text
    preview=post(client,path+'/revisions/preview',data,'preview')
    assert preview.status_code==200 and preview.json()['can_adopt'],preview.text
    assert not preview.json()['unexecuted'],preview.text
    revised=post(client,path+'/revisions',data|dict(preview_sha256=preview.json()['preview_sha256']),'revision')
    assert revised.status_code==202,revised.text
    assert run_task(revised.json()['task']['id'],1)['status']=='succeeded'
    result=client.get(url+'/revisions/'+revised.json()['id']).json()['result'];assert run_task(result['output']['task_id'],1)['status']=='succeeded'
    public=client.get(root+'/versions/'+str(result['output']['revision']));assert public.status_code==200,public.text
    new=public.json()['snapshot'];figure=new['results_groups'][0]['figures'][0]
    assert figure['id']==b['figure']['id'] and figure['sha256']==sha256(b['png']).hexdigest()
    exports=[]
    for revision,pixels in [(parent['revision'],a['png']),(result['output']['revision'],b['png'])]:
        response=post(client,root+f'/versions/{revision}/exports',{},'docx-'+str(revision));assert response.status_code==201,response.text
        exp=response.json();assert run_task(exp['task_id'],1)['status']=='succeeded'
        exp=client.get(root+'/exports/'+exp['id']).json()
        raw=client.get(exp['download_url']).content
        with ZipFile(BytesIO(raw)) as archive:
            assert pixels in [archive.read(n) for n in archive.namelist() if n.startswith('word/media/')]
            assert ('Synthetic B' if revision==result['output']['revision'] else 'Synthetic A') in archive.read('word/document.xml').decode()
        exports.append(raw)
    assert client.get(root+'/versions/'+str(parent['revision'])).json()['snapshot']==parent['snapshot']
    assert a['workbench'].assets.figure_png(a['figure'])==a['png']
    with database_connection() as db:assert all(c['invalid']==0 for c in audit_review_science(db))
    # Optional runtime evidence mount: normal tests never depend on ignored files.
    import os
    if os.environ.get('PAPERASSIST_BII_EVIDENCE_DIR'):
        from pathlib import Path
        out=Path(os.environ['PAPERASSIST_BII_EVIDENCE_DIR']);out.mkdir(parents=True,exist_ok=True)
        for name,raw in [('a.png',a['png']),('b.png',b['png']),('parent.docx',exports[0]),('revised.docx',exports[1])]: (out/name).write_bytes(raw)
        (out/'context.json').write_text(json.dumps(dict(synthetic=True,external_execution=False,project_id=a['project'],file_a=a['file']['id'],file_b=b['file']['id'],run_a=a['result']['id'],run_b=b['result']['id'],config_a=a['config_id'],config_b=b['config_id'],figure_a=a['figure']['id'],figure_b=b['figure']['id'],round_id=round['id'],item_id=round['items'][0]['id'],parent_version_id=parent['id'],output=result['output'],local_renderer='test-only Pillow geometry',a_statistics=a['result']['statistics'],b_statistics=b['result']['statistics'],a_projection=a['projection'],b_projection=b['projection'],parent_snapshot=parent['snapshot'],new_snapshot=new),indent=2,default=str))


def test_figure_adoption_rejects_unready_projection_foreign_stale_and_tampered_bytes(client,monkeypatch):
    from app.db.database import database_connection
    a,b,root,parent,url,path,round,body=scenario(client,monkeypatch)
    with database_connection() as db:
        projection=db.execute("SELECT id FROM tasks WHERE task_type='figure_projection' AND input_snapshot->'result'->>'id'=%s",(b['result']['id'],)).fetchone()
    linked=post(client,path+'/task-links',dict(plan_revision=round['revision'],item_id=round['items'][0]['id'],task_id=projection['id'],purpose='projection'),'projection-link')
    assert linked.status_code==201,linked.text
    assert post(client,path+'/figure-adoptions',body|dict(task_link_id=linked.json()['id']),'projection-has-no-png').status_code==409
    from tests.api.test_projects import create_project
    other=create_project(client)
    assert post(client,f'/api/v1/projects/{other["id"]}/reviews/rounds/{round["id"]}/figure-adoptions',body,'foreign-project').status_code==404
    for status in ('queued','failed','waiting_confirmation'):
        with database_connection(write=True) as db:db.execute('UPDATE tasks SET status=%s WHERE id=%s',(status,b['task']['id']))
        response=post(client,path+'/figure-adoptions',body,'unready-'+status)
        assert response.status_code==409,response.text
    with database_connection(write=True) as db:db.execute("UPDATE tasks SET status='succeeded' WHERE id=%s",(b['task']['id'],))
    with database_connection(write=True) as db:db.execute('UPDATE tasks SET result_figure_id=%s WHERE id=%s',(a['figure']['id'],b['task']['id']))
    assert post(client,path+'/figure-adoptions',body,'wrong-result-analysis').status_code==409
    with database_connection(write=True) as db:db.execute('UPDATE tasks SET result_figure_id=%s WHERE id=%s',(b['figure']['id'],b['task']['id']))
    assert post(client,path+'/figure-adoptions',body|dict(expected_current_revision=2),'stale-parent').status_code==409
    assert post(client,path+'/figure-adoptions',body|dict(supersedes_figure_id='foreign'),'foreign-old').status_code==422
    assert post(client,path+'/figure-adoptions',body|dict(plan_revision=round['revision']+1),'stale-plan').status_code==409
    with database_connection(write=True) as db:db.execute('UPDATE analysis_setups SET revision=revision+1 WHERE file_id=%s',(b['file']['id'],))
    assert post(client,path+'/figure-adoptions',body,'stale-analysis').status_code==409
    with database_connection(write=True) as db:db.execute('UPDATE analysis_setups SET revision=revision-1 WHERE file_id=%s',(b['file']['id'],))
    file=b['workbench'].assets.figures_dir/(b['figure']['id']+'.png');raw=file.read_bytes();file.write_bytes(raw+b'tampered')
    assert post(client,path+'/figure-adoptions',body,'tampered').status_code==409
    file.write_bytes(raw);file.rename(file.with_suffix('.preserved'))
    assert post(client,path+'/figure-adoptions',body,'missing').status_code in (409,410)
    file.with_suffix('.preserved').rename(file)
    from app.domain.figure_workbench.contracts import SaveConfiguration
    with database_connection() as db:
        version=db.execute('SELECT * FROM figure_config_versions WHERE id=%s',(b['config_id'],)).fetchone()
    config=deepcopy(version['config_json']);config['style']['title']='Changed current style'
    b['workbench'].save(b['project'],b['file']['id'],b['result']['id'],SaveConfiguration(configuration_id=version['configuration_id'],expected_revision=1,config=config))
    assert post(client,path+'/figure-adoptions',body,'stale-config').status_code==409


def test_old_revision_request_and_preview_survive_0053_upgrade_without_resealing(client):
    """Only this test's pa_test schema is downgraded/upgraded; old data stays exact."""
    from tests.api.test_review_revisions import context_and_request
    from app.db.database import database_connection,migration_connection,get_migration_database_config,alembic_config
    from app.domain.tasks.execution import run_task
    from alembic import command
    import re
    url,round,parent,context,body=context_and_request(client,'1. Clarify the method.')
    path=url+'/rounds/'+round['id']+'/revisions'
    preview=post(client,path+'/preview',body,'legacy-preview').json()
    assert preview['can_adopt']
    request=body|dict(preview_sha256=preview['preview_sha256'])
    created=post(client,path,request,'historical-revision');assert created.status_code==202,created.text
    identity=created.json()['id']
    with database_connection() as db:
        before=db.execute('SELECT row_to_json(r)::text AS raw FROM review_revision_runs r WHERE id=%s',(identity,)).fetchone()['raw']
        frozen=db.execute('SELECT request_json,snapshot_json FROM review_revision_runs WHERE id=%s',(identity,)).fetchone()
        assert 'figure_adoption_ids' not in frozen['request_json'] and 'figure_adoption_ids' not in frozen['snapshot_json']
    config=get_migration_database_config()
    assert config.environment=='test' and config.url.database=='paperassist_system_test' and re.fullmatch(r'pa_test_[a-f0-9]{32}',config.schema)
    with migration_connection(write=True,config=config) as db:
        settings=alembic_config();settings.attributes.update(connection=db.raw_connection,database_config=config)
        command.downgrade(settings,'0053_storage_governance')
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()['version_num']=='0053_storage_governance'
        before_tables={r['tablename'] for r in db.execute('SELECT tablename FROM pg_tables WHERE schemaname=%s',(config.schema,)).fetchall()}
        at_0053=db.execute('SELECT row_to_json(r)::text AS raw FROM review_revision_runs r WHERE id=%s',(identity,)).fetchone()['raw']
        command.upgrade(settings,'head')
        after_tables={r['tablename'] for r in db.execute('SELECT tablename FROM pg_tables WHERE schemaname=%s',(config.schema,)).fetchall()}
        assert after_tables-before_tables=={'review_figure_adoptions'} and not before_tables-after_tables
        after=db.execute('SELECT row_to_json(r)::text AS raw FROM review_revision_runs r WHERE id=%s',(identity,)).fetchone()['raw']
        assert before==at_0053==after
    replay=post(client,path,request|dict(figure_adoption_ids=[]),'historical-revision')
    assert replay.status_code==200 and replay.json()['id']==identity,replay.text
    assert post(client,path+'/preview',body,'legacy-preview-again').json()['preview_sha256']==preview['preview_sha256']
    assert run_task(created.json()['task']['id'],1)['status']=='succeeded'
    result=client.get(url+'/revisions/'+identity).json()['result'];assert run_task(result['output']['task_id'],1)['status']=='succeeded'
    root=url.rsplit('/reviews',1)[0]+'/manuscripts/'+result['output']['manuscript_id']
    assert client.get(root+'/versions/'+str(result['output']['revision'])).status_code==200
    exp=post(client,root+'/versions/'+str(result['output']['revision'])+'/exports',{},'historical-docx').json()
    assert run_task(exp['task_id'],1)['status']=='succeeded'
    download=client.get(root+'/exports/'+exp['id']).json()['download_url']
    assert client.get(download).status_code==200
