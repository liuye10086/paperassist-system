import hashlib
import io

from PIL import Image
from tests.api.test_projects import client,create_project,upload


def selected_image(client,size=(80,40)):
    from tests.api.test_file_batches import register
    project=create_project(client);stream=io.BytesIO();Image.new('RGB',size,'red').save(stream,'PNG')
    base,batch,item,content=register(client,project,content=stream.getvalue(),filename='source.png')
    response=client.post(base+'/'+batch['id']+'/items/'+item['client_id'],files={'file':(item['filename'],content)})
    assert response.status_code==202,response.text
    return project['id'],response.json()['file_id']


def test_research_figure_task_is_immutable_replayable_and_atomically_published(client,tmp_path,monkeypatch):
    from app.domain.research_results.execution import run_research_figure_task
    from app.adapters.research_figure_render import render_figure
    project,file=selected_image(client);base=f'/api/v1/projects/{project}/research-figures'
    body=dict(mode='reuse',panels=[dict(source=dict(source_kind='original_file',source_id=file))],width_mm=85.0,dpi=150,formats=['png'])
    created=client.post(base,json=body,headers={'Idempotency-Key':'figure-one'});assert created.status_code==201,created.text
    value=created.json();assert value['members']==[] and value['task']['task_type']=='research_figure'
    replay=client.post(base,json=body,headers={'Idempotency-Key':'figure-one'});assert replay.status_code==200 and replay.json()['id']==value['id']
    conflict=client.post(base,json={**body,'title':'other'},headers={'Idempotency-Key':'figure-one'});assert conflict.status_code==409
    result=run_research_figure_task(value['task']['id'],value['task']['revision'],engine=render_figure,staging_directory=tmp_path/'staging')
    assert result['status']=='succeeded'
    assert run_research_figure_task(value['task']['id'],value['task']['revision'],engine=render_figure,staging_directory=tmp_path/'staging') is None
    saved=client.get(base+'/'+value['id']);assert saved.status_code==200,saved.text
    saved=saved.json();assert saved['manifest_sha256'] and saved['members']
    original=next(x for x in saved['members'] if x['role']=='original_panel')
    download=client.get(original['download_url']);assert download.status_code==200
    assert hashlib.sha256(download.content).hexdigest()==original['sha256']
    impact=client.get(f'/api/v1/projects/{project}/files/{file}/lifecycle/assessment');assert impact.status_code==200,impact.text
    assert impact.json()['counts']['research_figure_versions']==1
    assert impact.json()['counts']['research_figure_members']==len(saved['members'])
    assert 'research_results_history_retained' in [r['code'] for r in impact.json()['reasons']]
    from app.db.database import database_connection
    from app.maintenance.research_results_audit import audit_research_task_sources
    with database_connection() as db:
        checks=audit_research_task_sources(db)
    assert checks[0]['rows']==1 and checks[0]['invalid']==0
    other=create_project(client);assert client.get(f'/api/v1/projects/{other["id"]}/research-figures/{value["id"]}').status_code==404
    next_body={**body,'root_id':value['root_id'],'expected_revision':1}
    new=client.post(base+'/'+value['root_id']+'/versions',json=next_body,headers={'Idempotency-Key':'figure-next'});assert new.status_code==201,new.text
    assert client.post(base+'/'+value['root_id']+'/versions',json=next_body,headers={'Idempotency-Key':'stale'}).status_code==409


def test_failed_render_has_no_official_members(client,tmp_path):
    from app.domain.research_results.execution import run_research_figure_task
    project,file=selected_image(client);base=f'/api/v1/projects/{project}/research-figures'
    created=client.post(base,json=dict(mode='reuse',panels=[dict(source=dict(source_kind='original_file',source_id=file))]),headers={'Idempotency-Key':'fail-render'})
    assert created.status_code==201,created.text
    def broken(*args):raise ValueError('synthetic render failure')
    value=created.json();result=run_research_figure_task(value['task']['id'],value['task']['revision'],engine=broken,staging_directory=tmp_path/'stage')
    assert result['status']=='failed'
    saved=client.get(base+'/'+value['id']).json();assert saved['members']==[] and saved['manifest_sha256'] is None


def test_invalid_staging_configuration_is_recoverable_after_correction(client,tmp_path):
    from app.domain.research_results.execution import run_research_figure_task
    from app.adapters.research_figure_render import render_figure
    project,file=selected_image(client);base=f'/api/v1/projects/{project}/research-figures'
    value=client.post(base,json=dict(mode='reuse',panels=[dict(source=dict(source_kind='original_file',source_id=file))],formats=['png']),headers={'Idempotency-Key':'bad-staging'}).json()
    result=run_research_figure_task(value['task_id'],value['task']['revision'],engine=render_figure,staging_directory='relative-path')
    assert result['status']=='failed' and result['error_code']=='research_environment_unavailable'
    workspace=client.get('/api/v1/tasks/'+value['task_id']+'/workspace').json()
    assert 'retry' in workspace['allowed_actions']


def test_stale_lease_cannot_publish_rendered_bytes(client,tmp_path):
    from app.domain.research_results.execution import run_research_figure_task
    from app.adapters.research_figure_render import render_figure
    from app.db.database import database_connection
    project,file=selected_image(client);base=f'/api/v1/projects/{project}/research-figures'
    created=client.post(base,json=dict(mode='reuse',panels=[dict(source=dict(source_kind='original_file',source_id=file))],formats=['png']),headers={'Idempotency-Key':'stale-lease'})
    assert created.status_code==201,created.text
    value=created.json()
    def expired(payload,output):
        result=render_figure(payload,output)
        with database_connection(write=True) as db:db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s",(value['task_id'],))
        return result
    assert run_research_figure_task(value['task_id'],value['task']['revision'],engine=expired,staging_directory=tmp_path/'stage') is None
    saved=client.get(base+'/'+value['id']).json();assert saved['members']==[] and saved['manifest_sha256'] is None


def test_source_tampering_blocks_publication_and_research_figures_are_reusable(client,tmp_path):
    from app.domain.research_results.execution import run_research_figure_task
    from app.adapters.research_figure_render import render_figure
    project,file=selected_image(client);base=f'/api/v1/projects/{project}/research-figures'
    body=dict(mode='reuse',panels=[dict(source=dict(source_kind='original_file',source_id=file))],formats=['png'])
    original=client.post(base,json=body,headers={'Idempotency-Key':'reuse-original'}).json()
    assert run_research_figure_task(original['task_id'],original['task']['revision'],engine=render_figure,staging_directory=tmp_path/'stage')['status']=='succeeded'
    reuse_body={**body,'panels':[dict(source=dict(source_kind='research_figure_version',source_id=original['id']))]}
    reused=client.post(base,json=reuse_body,headers={'Idempotency-Key':'reuse-derived'});assert reused.status_code==201,reused.text
    value=reused.json();assert run_research_figure_task(value['task_id'],value['task']['revision'],engine=render_figure,staging_directory=tmp_path/'stage')['status']=='succeeded'
    first=client.get(base+'/'+original['id']).json()['manifest']['panels'][0]
    second=client.get(base+'/'+value['id']).json()['manifest']['panels'][0]
    assert second['resolution_warning'] is True
    assert second['effective_dpi']<first['effective_dpi']*1.1
    from app.core.config import get_data_dir
    from app.db.database import database_connection
    from pathlib import Path
    pending=client.post(base,json=body,headers={'Idempotency-Key':'tamper-source'}).json()
    with database_connection() as db:key=db.execute('SELECT object_key FROM files WHERE id=%s',(file,)).fetchone()['object_key']
    path=Path(get_data_dir())/key;path.write_bytes(path.read_bytes()+b'tamper')
    result=run_research_figure_task(pending['task_id'],pending['task']['revision'],engine=render_figure,staging_directory=tmp_path/'stage')
    assert result['status']=='failed'
    saved=client.get(base+'/'+pending['id']).json();assert saved['members']==[] and saved['manifest_sha256'] is None


def test_caption_fact_identity_is_resolved_from_explicit_sources(client):
    project,file=selected_image(client);base=f'/api/v1/projects/{project}/research-figures'
    body=dict(mode='reuse',panels=[dict(source=dict(source_kind='original_file',source_id=file))],caption='n=99',caption_fact_ids=['invented'])
    response=client.post(base,json=body,headers={'Idempotency-Key':'caption-fake'})
    assert response.status_code==422,response.text
    assert response.json()['detail']['code']=='research_fact_unresolved'


def test_figure_pixel_limit_is_rejected_before_task_admission(client):
    project,file=selected_image(client,(10,1000));base=f'/api/v1/projects/{project}/research-figures'
    body=dict(mode='reuse',width_mm=240.0,dpi=600,panels=[dict(source=dict(source_kind='original_file',source_id=file))])
    response=client.post(base,json=body,headers={'Idempotency-Key':'too-tall'})
    assert response.status_code==422,response.text
    assert response.json()['detail']['code']=='research_figure_limit_exceeded'


def test_interrupted_publish_resumes_exact_prepared_members_without_render(client,tmp_path,monkeypatch):
    from app.domain.research_results.execution import run_research_figure_task
    from app.adapters.research_figure_render import render_figure
    from app.adapters.research_objects import ResearchObjects
    project,file=selected_image(client);base=f'/api/v1/projects/{project}/research-figures'
    created=client.post(base,json=dict(mode='reuse',panels=[dict(source=dict(source_kind='original_file',source_id=file))],formats=['png']),headers={'Idempotency-Key':'publish-interrupted'})
    assert created.status_code==201,created.text
    value=created.json();original=ResearchObjects.write;calls=[]
    def interrupted(self,record,content):
        calls.append(record)
        if len(calls)==2:raise OSError('synthetic interruption')
        return original(self,record,content)
    monkeypatch.setattr(ResearchObjects,'write',interrupted)
    failed=run_research_figure_task(value['task_id'],value['task']['revision'],engine=render_figure,staging_directory=tmp_path/'stage')
    assert failed['status']=='failed' and failed['error_code']=='storage_unavailable'
    assert client.get(base+'/'+value['id']).json()['members']==[]
    monkeypatch.setattr(ResearchObjects,'write',original)
    workspace=client.get('/api/v1/tasks/'+value['task_id']+'/workspace');assert workspace.status_code==200,workspace.text
    assert 'retry' in workspace.json()['allowed_actions']
    resumed=client.post('/api/v1/tasks/'+value['task_id']+'/resume',json=dict(operation='retry',wait_id=None,expected_task_revision=failed['revision'],input_version=failed['input_version']),headers={'Idempotency-Key':'resume-prepared'})
    assert resumed.status_code==202,resumed.text
    def never_render(*args):raise AssertionError('prepared publication must not render again')
    queued=resumed.json()
    done=run_research_figure_task(value['task_id'],queued['revision'],engine=never_render,staging_directory=tmp_path/'stage')
    assert done['status']=='succeeded'
    assert client.get(base+'/'+value['id']).json()['members']


def test_quota_failure_cannot_restore_an_already_expired_renewal(client,tmp_path,monkeypatch):
    import time
    from app.domain.research_results import execution
    from app.adapters import task_execution_store
    from app.adapters.research_figure_render import render_figure
    from app.core.exceptions import StorageError
    project,file=selected_image(client);base=f'/api/v1/projects/{project}/research-figures'
    value=client.post(base,json=dict(mode='reuse',panels=[dict(source=dict(source_kind='original_file',source_id=file))],formats=['png']),headers={'Idempotency-Key':'expired-quota'}).json()
    monkeypatch.setattr(task_execution_store,'LEASE_SECONDS',2)
    def expired_admission(db,root,task,entries,*,progress):
        progress();time.sleep(2.2)
        raise StorageError('storage_quota_exceeded','Synthetic expired rejection',409)
    monkeypatch.setattr(execution,'admit_bio_manifest',expired_admission)
    result=execution.run_research_figure_task(value['task_id'],value['task']['revision'],engine=render_figure,staging_directory=tmp_path/'stage')
    assert result is None
    assert client.get(base+'/'+value['id']).json()['members']==[]


def test_quota_rejection_after_transaction_renewals_is_not_worker_interruption(client,tmp_path,monkeypatch):
    import time
    from app.domain.research_results import execution
    from app.adapters import task_execution_store
    from app.adapters.research_figure_render import render_figure
    from app.db.database import database_connection
    from app.domain.storage_governance.service import set_policy
    project,file=selected_image(client);base=f'/api/v1/projects/{project}/research-figures'
    value=client.post(base,json=dict(mode='reuse',panels=[dict(source=dict(source_kind='original_file',source_id=file))],formats=['png']),headers={'Idempotency-Key':'slow-quota'}).json()
    with database_connection(write=True) as db:set_policy(db,'project',project,1,'enforced')
    monkeypatch.setattr(task_execution_store,'LEASE_SECONDS',2)
    admit=execution.admit_bio_manifest
    def slow_admission(db,root,task,entries,*,progress):
        # Renew while holding the schema writer lock, past the last committed
        # lease. A rejected admission must not roll back those renewals and
        # thereby turn a deterministic quota denial into an interrupted job.
        for _ in range(6):
            time.sleep(.4);progress()
        return admit(db,root,task,entries,progress=progress)
    monkeypatch.setattr(execution,'admit_bio_manifest',slow_admission)
    result=execution.run_research_figure_task(value['task_id'],value['task']['revision'],engine=render_figure,staging_directory=tmp_path/'stage')
    assert result is not None
    assert result['status']=='failed' and result['error_code']=='storage_quota_exceeded'
    task_execution_store.TaskExecutionStore().recover_expired()
    saved=client.get('/api/v1/tasks/'+value['task_id']).json()
    assert saved['current_attempt']==1 and saved['status']=='failed'
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM storage_reservations WHERE task_id=%s',(value['task_id'],)).fetchone()['n']==0
    assert client.get(base+'/'+value['id']).json()['members']==[]
