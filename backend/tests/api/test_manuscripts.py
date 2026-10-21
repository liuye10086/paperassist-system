"""Offline fact drafts use real isolated PostgreSQL and immutable source versions."""
import copy
import sys
import pytest
from tests.api.test_analysis import client, add_file, selection  # noqa: F401
from tests.api.test_literature_evidence import post
from app.db.database import database_connection


def body(**changes):
    return dict(title='Synthetic local fact draft', output_language='en', sources=[],
        methods={'study_design':'Synthetic laboratory comparison'}, results_groups=[]) | changes


def setup(client):
    base, file = add_file(client)
    return base.split('/files/')[0]+'/manuscripts', base, file


def test_missing_and_conflicting_methods_stay_pending_and_versions_are_immutable(client):
    path, _, _=setup(client)
    data=body(method_conflicts=[dict(field='study_design',values=['randomized','observational'])])
    preview=post(client,path+'/preview',data,'preview')
    assert preview.status_code==200,preview.text
    assert not preview.json()['methods']
    assert {'missing','conflict','limitation'}<={i['kind'] for i in preview.json()['issues']}
    first=post(client,path,data,'create')
    assert first.status_code==201,first.text
    first=first.json(); version=first['versions'][0]
    assert version['status']=='pending'
    assert post(client,path,data,'create').json()==first
    changed=body(expected_revision=1)
    second=post(client,path+'/'+first['id']+'/versions',changed,'next')
    assert second.status_code==201,second.text
    assert second.json()['versions'][0]['parent_version_id']==version['id']
    assert client.get(path+'/'+first['id']+'/versions/1').json()['snapshot']==version['snapshot']
    assert post(client,path+'/'+first['id']+'/versions',changed,'stale').status_code==409


def test_original_cannot_be_computed_result_and_foreign_sources_rejected(client):
    path, _, file=setup(client)
    source=dict(kind='original',id=file['id'],file_id=file['id'],role='computed_results')
    assert post(client,path+'/preview',body(sources=[source]),'bad').status_code==422
    source['role']='methods';source['id']='missing'
    assert post(client,path+'/preview',body(sources=[source]),'missing').status_code in (404,409,422)


def test_thesis_project_does_not_open_stage06_sci_workflow(client):
    project=client.post('/api/v1/projects',json=dict(name='Synthetic thesis',research_topic='Synthetic materials',project_type='thesis')).json()
    path=f'/api/v1/projects/{project["id"]}/manuscripts'
    assert client.get(path+'/config').status_code==422
    assert post(client,path+'/preview',body(),'preview').status_code==422
    assert post(client,path,body(),'create').status_code==422


def test_real_original_read_and_source_change_does_not_modify_history(client):
    path, _, file=setup(client)
    data=body(sources=[dict(kind='original',id=file['id'],file_id=file['id'],role='methods')])
    first=post(client,path,data,'first')
    assert first.status_code==201,first.text
    first=first.json(); saved=copy.deepcopy(first['versions'][0]['snapshot'])
    assert saved['sources'][0]['sha256']==file['sha256']
    with database_connection(write=True) as db:
        db.execute('UPDATE files SET sha256=%s WHERE id=%s',('a'*64,file['id']))
    old=client.get(path+'/'+first['id']).json()['versions'][0]
    assert old['snapshot']==saved
    assert old['current_changes']
    assert post(client,path,data,'changed').status_code==409


def test_unified_task_publication_checkpoints_export_and_replay(client):
    from app.domain.tasks.execution import run_task
    path, _, _=setup(client)
    first=post(client,path,body(),'first').json()
    version=first['versions'][0]
    public=client.get('/api/v1/tasks/'+version['task_id'])
    assert public.status_code==200,public.text
    assert public.json()['task_type']=='manuscript_draft'
    run_task(version['task_id'],1)
    run_task(version['task_id'],1)
    current=client.get(path+'/'+first['id']).json()['versions'][0]
    assert current['status']=='published'
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM task_checkpoints WHERE task_id=%s',(version['task_id'],)).fetchone()['n']==2
    export_path=path+'/'+first['id']+'/versions/1/exports'
    exported=post(client,export_path,{},'export')
    assert exported.status_code==201,exported.text
    exported=exported.json()
    assert post(client,export_path,{},'export').json()==exported
    run_task(exported['task_id'],1)
    complete=client.get(path+'/'+first['id']+'/exports/'+exported['id']).json()
    assert complete['status']=='succeeded',complete
    assert complete['pdf_status']=='not_requested'
    download=client.get(complete['download_url'])
    assert download.status_code==200 and download.content.startswith(b'PK')
    assert client.get(export_path).json()['items'][0]['sha256']==complete['sha256']
    summary=client.get(path.removesuffix('/manuscripts')+'/summary').json()
    assert summary['future']['writing']['state']=='available'
    assert summary['future']['writing']['current_manuscript']['id']==first['id']


@pytest.mark.skipif(sys.platform!='linux',reason='Real numerical source production requires the existing Linux sandbox.')
def test_actual_statistics_group_and_methods_are_readable_and_have_real_source_fk(client):
    from tests.integration.test_correlation_plan import prepared_correlations,create_correlation
    from tests.helpers.analysis_plan import run_plan,review_plan,plan_decision,decide_plan
    from tests.helpers.statistics import statistics_post
    from app.domain.tasks.execution import run_task
    base,file,prepared=prepared_correlations(client)
    task,_=create_correlation(client,base,prepared);run_plan(task)
    approved=decide_plan(client,task,plan_decision(review_plan(client,task))).json();run_plan(approved)
    result=statistics_post(client,base+'/analysis-runs',json={'expected_revision':1}).json()
    path=base.split('/files/')[0]+'/manuscripts'
    candidate=client.get(path+'/candidates')
    assert candidate.status_code==200,candidate.text
    assert any(i['kind']=='analysis_run' and i['id']==result['id'] for i in candidate.json()['items'])
    source=dict(kind='analysis_run',id=result['id'],file_id=file['id'],role='computed_results')
    data=body(output_language='zh-CN',sources=[source],results_groups=[dict(id='main',title='相关分析',analysis_run_ids=[result['id']])])
    created=post(client,path,data,'computed')
    assert created.status_code==201,created.text
    version=created.json()['versions'][0];snapshot=version['snapshot']
    assert snapshot['sources'][0]['content']==result
    table=snapshot['results_groups'][0]['tables'][0]
    assert any(row[1]=='3' and '样本量' in row[0] for row in table['rows'])
    assert all('statistics.' not in row[0] for row in table['rows'])
    assert not any("{'" in p['text'] or 'correlation_dataset' in p['text'] for p in snapshot['methods'])
    assert all('：' in issue['message'] for issue in snapshot['issues'] if issue['kind']=='missing' and issue['field']!='results')
    run_task(version['task_id'],1)
    with database_connection() as db:
        row=db.execute('SELECT analysis_run_id FROM manuscript_sources WHERE version_id=%s',(version['id'],)).fetchone()
        assert row['analysis_run_id']==result['id']
        from app.maintenance.database_audit import audit_database
        audit=audit_database(db)
        assert audit['ok'],audit['schema_issues'] or [c for c in audit['data_checks'] if c['invalid']]
    workspace=client.get('/api/v1/tasks/'+version['task_id']+'/workspace')
    assert workspace.status_code==200,workspace.text
    assert workspace.json()['artifacts']['manuscript']['version_id']==version['id']
    summary=client.get(base.split('/files/')[0]+'/summary').json()
    assert summary['future']['writing']['state']=='available'
    assert summary['future']['writing']['current_manuscript']['id']==created.json()['id']


def test_citation_gate_frozen_binding_and_later_negative_review(client):
    from tests.api.test_literature_citations import seeded,binding,paragraph,draft_body
    pid,lit,task,refs=seeded(client)
    claim,bound,_,review=binding(client,lit,task,refs[0])
    draft=post(client,lit+'/citations/drafts',draft_body(paragraph(claim,bound)),'citation').json()
    path=f'/api/v1/projects/{pid}/manuscripts';data=body(citation_draft=dict(id=draft['id'],revision=1))
    created=post(client,path,data,'first')
    assert created.status_code==201,created.text
    version=created.json()['versions'][0];snapshot=version['snapshot']
    assert snapshot['references']==draft['snapshot']['output']['references']
    assert snapshot['methods'][-1]['origin']=='literature' and 'Literature finding' in snapshot['methods'][-1]['text']
    with database_connection() as db:
        row=db.execute('SELECT * FROM manuscript_citations WHERE version_id=%s',(version['id'],)).fetchone()
        assert row['review_id']==bound['review_id'] and row['citation_version_id']==draft['snapshot']['version_id']
        assert row['paragraph_id']==snapshot['methods'][-1]['id']
    import json
    from pathlib import Path
    fixture=Path(__file__).resolve().parents[3]/'script/.runtime/stage06-batch01/frontend-contract-fixtures.json'
    previous=json.loads(fixture.read_text(encoding='utf-8')) if fixture.exists() else {}
    previous['citation_manuscript']=created.json()
    fixture.parent.mkdir(parents=True,exist_ok=True);fixture.write_text(json.dumps(previous,ensure_ascii=False,indent=2),encoding='utf-8')
    negative={k:review[k] for k in ('claim_revision','project_reference_id','evidence_ids','relevance','reason','narrowed_statement','limitations')}
    assert post(client,lit+'/evidence/claims/'+claim['id']+'/reviews',negative|dict(status='unsupported'),'negative').status_code==201
    assert post(client,path,data,'blocked').status_code==409
    old=client.get(path+'/'+created.json()['id']).json()['versions'][0]
    assert old['snapshot']==snapshot and old['current_changes']
    from app.domain.tasks.execution import run_task
    run_task(version['task_id'],1)
    assert client.get(path+'/'+created.json()['id']).json()['versions'][0]['status']=='failed'


def test_lost_lease_is_fenced_and_recovered_without_duplicate_publication(client):
    from app.adapters.task_execution_store import TaskExecutionStore,LeaseLost
    from app.domain.tasks.execution import run_task
    import pytest
    path,_,_=setup(client);created=post(client,path,body(),'first').json();version=created['versions'][0]
    execution=TaskExecutionStore();lease=execution.claim(version['task_id'],1)
    assert lease
    with database_connection(write=True) as db:
        db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s",(version['task_id'],))
    assert execution.recover_expired()==1
    with execution.connection(write=True) as db:
        with pytest.raises(LeaseLost): execution.require_lease(db,lease)
    public=client.get('/api/v1/tasks/'+version['task_id']).json()
    assert public['status']=='queued'
    run_task(version['task_id'],public['revision'])
    run_task(version['task_id'],public['revision'])
    old=client.get(path+'/'+created['id']).json()['versions'][0]
    assert old['status']=='published'
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM manuscript_versions').fetchone()['n']==1
        assert db.execute('SELECT count(*) AS n FROM task_checkpoints').fetchone()['n']==2


def test_saved_docx_images_are_observations_preserve_bytes_and_exact_panel_notes(client):
    from tests.api.test_document_versions import uploaded_docx
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    from app.adapters.docx_parser import parse_docx
    from app.domain.tasks.execution import run_task
    from io import BytesIO
    from zipfile import ZipFile
    from hashlib import sha256
    project,_,_,uploaded,_=uploaded_docx(client)
    assert run_parse_file_task(uploaded['task']['id'],1,parser=parse_docx)['status']=='succeeded'
    path=f'/api/v1/projects/{project["id"]}/manuscripts'
    candidates=client.get(path+'/candidates')
    assert candidates.status_code==200,candidates.text
    source=next(i for i in candidates.json()['items'] if i['kind']=='document_version')
    data=body(sources=[{k:source[k] for k in ('kind','id','file_id')}|dict(role='image_observation')])
    preview=post(client,path+'/preview',data,'preview')
    assert preview.status_code==200,preview.text
    figures=preview.json()['results_groups'][0]['figures']
    assert len(figures)==2
    assert all(f['id'].startswith(source['id']+':') and f['source_ids']==[source['id']] for f in figures)
    data['figure_notes']=[dict(figure_id=figures[0]['id'],caption='Explicit synthetic panel caption',panels=[dict(label='A',description='Synthetic observation')])]
    created=post(client,path,data,'create')
    assert created.status_code==201,created.text
    version=created.json()['versions'][0]
    assert version['snapshot']['results_groups'][0]['figures'][0]['panels'][0]['label']=='A'
    raw_images={f['id']:client.get(f['preview_url']).content for f in figures}
    assert all(sha256(raw_images[f['id']]).hexdigest()==f['sha256'] for f in figures)
    run_task(version['task_id'],1)
    exported=post(client,path+'/'+created.json()['id']+'/versions/1/exports',{},'export').json()
    run_task(exported['task_id'],1)
    status=client.get(path+'/'+created.json()['id']+'/exports/'+exported['id']).json()
    assert status['status']=='succeeded',status
    content=client.get(status['download_url']).content
    with ZipFile(BytesIO(content)) as archive:
        media=[archive.read(name) for name in archive.namelist() if name.startswith('word/media/')]
        assert all(raw in media for raw in raw_images.values())
    import json
    from pathlib import Path
    fixture=Path(__file__).resolve().parents[3]/'script/.runtime/stage06-batch01/frontend-contract-fixtures.json'
    previous=json.loads(fixture.read_text(encoding='utf-8')) if fixture.exists() else {}
    previous.update(candidates=candidates.json(),manuscript=client.get(path+'/'+created.json()['id']).json(),summary=client.get(path.removesuffix('/manuscripts')+'/summary').json(),workspace=client.get('/api/v1/tasks/'+version['task_id']+'/workspace').json())
    fixture.parent.mkdir(parents=True,exist_ok=True);fixture.write_text(json.dumps(previous,ensure_ascii=False,indent=2),encoding='utf-8')


def test_failed_export_can_be_retried_without_duplicate_versions_or_output(client,monkeypatch):
    import app.adapters.manuscript_docx as renderer
    from app.domain.tasks.execution import run_task
    path,_,_=setup(client);created=post(client,path,body(),'first').json();version=created['versions'][0]
    run_task(version['task_id'],1)
    endpoint=path+'/'+created['id']+'/versions/1/exports'
    exported=post(client,endpoint,{},'export').json()
    original=renderer.build_manuscript_docx
    def fail(*args): raise RuntimeError('synthetic render failure')
    monkeypatch.setattr(renderer,'build_manuscript_docx',fail)
    failed=run_task(exported['task_id'],1)
    assert failed['status']=='failed' and failed['error_code']=='report_render_failed'
    assert client.get(path+'/'+created['id']+'/exports/'+exported['id']).json()['download_url'] is None
    monkeypatch.setattr(renderer,'build_manuscript_docx',original)
    recovered=post(client,path+'/'+created['id']+'/recover',{},'recover')
    assert recovered.status_code==200 and recovered.json()['requeued']==1
    task=client.get('/api/v1/tasks/'+exported['task_id']).json()
    run_task(task['id'],task['revision'])
    complete=client.get(path+'/'+created['id']+'/exports/'+exported['id']).json()
    assert complete['status']=='succeeded'
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM manuscript_versions').fetchone()['n']==1
        assert db.execute('SELECT count(*) AS n FROM manuscript_exports').fetchone()['n']==1


def test_other_owner_cannot_read_mutate_or_download_manuscript(client):
    from tests.integration.test_project_ownership import account_client
    from app.domain.tasks.execution import run_task
    path,_,file=setup(client);created=post(client,path,body(),'first').json();version=created['versions'][0]
    run_task(version['task_id'],1)
    exported=post(client,path+'/'+created['id']+'/versions/1/exports',{},'export').json();run_task(exported['task_id'],1)
    with account_client('manuscript-other@example.test')[0] as other:
        for endpoint in (path,path+'/candidates',path+'/'+created['id'],path+'/'+created['id']+'/versions/1',path+'/'+created['id']+'/exports/'+exported['id'],path+'/'+created['id']+'/exports/'+exported['id']+'/download'):
            assert other.get(endpoint).status_code==404
        assert post(other,path+'/preview',body(),'preview').status_code==404
        assert post(other,path,body(),'create').status_code==404
        assert post(other,path+'/'+created['id']+'/recover',{},'recover').status_code==404


def test_invalid_failed_old_version_does_not_block_current_export_recovery(client,monkeypatch):
    import app.adapters.manuscript_docx as renderer
    from app.domain.tasks.execution import run_task
    path,_,file=setup(client)
    first=post(client,path,body(sources=[dict(kind='original',id=file['id'],file_id=file['id'],role='methods')]),'first').json()
    with database_connection(write=True) as db: db.execute('UPDATE files SET sha256=%s WHERE id=%s',('a'*64,file['id']))
    assert run_task(first['versions'][0]['task_id'],1)['status']=='failed'
    second=post(client,path+'/'+first['id']+'/versions',body(expected_revision=1),'second').json()['versions'][0]
    assert run_task(second['task_id'],1)['status']=='succeeded'
    exported=post(client,path+'/'+first['id']+'/versions/2/exports',{},'export').json()
    def fail(*args): raise RuntimeError('synthetic render failure')
    monkeypatch.setattr(renderer,'build_manuscript_docx',fail)
    assert run_task(exported['task_id'],1)['status']=='failed'
    recovered=post(client,path+'/'+first['id']+'/recover',{},'recover')
    assert recovered.status_code==200,recovered.text
    assert recovered.json()['requeued']==1
    assert recovered.json()['skipped'][0]['task_id']==first['versions'][0]['task_id']
    assert client.get('/api/v1/tasks/'+exported['task_id']).json()['status']=='queued'


def test_twenty_invalid_old_failures_do_not_starve_new_valid_recovery(client,monkeypatch):
    from app.domain.tasks.execution import run_task
    import app.adapters.manuscript_docx as renderer
    path,_,file=setup(client);source=dict(kind='original',id=file['id'],file_id=file['id'],role='methods')
    first=post(client,path,body(sources=[source]),'version-1').json();identity=first['id']
    old=[first['versions'][0]]
    for revision in range(2,21):
        old.append(post(client,path+'/'+identity+'/versions',body(sources=[source],expected_revision=revision-1),'version-'+str(revision)).json()['versions'][0])
    with database_connection(write=True) as db: db.execute('UPDATE files SET sha256=%s WHERE id=%s',('a'*64,file['id']))
    for version in old: assert run_task(version['task_id'],1)['status']=='failed'
    current=post(client,path+'/'+identity+'/versions',body(expected_revision=20),'current').json()['versions'][0]
    assert run_task(current['task_id'],1)['status']=='succeeded'
    exported=post(client,path+'/'+identity+'/versions/21/exports',{},'export').json()
    def fail(*args): raise RuntimeError('synthetic render failure')
    monkeypatch.setattr(renderer,'build_manuscript_docx',fail)
    assert run_task(exported['task_id'],1)['status']=='failed'
    response=post(client,path+'/'+identity+'/recover',{},'recover')
    assert response.status_code==200,response.text
    assert response.json()['requeued']==1
    assert len(response.json()['skipped'])==20


def test_historical_snapshot_and_export_survive_future_formatter_changes(client,monkeypatch):
    from app.domain.manuscripts import service as module
    from app.domain.tasks.execution import run_task
    path,_,_=setup(client);created=post(client,path,body(),'first').json();version=created['versions'][0]
    assert run_task(version['task_id'],1)['status']=='succeeded'
    original=module.freeze
    def next_formatter(service,*args,**kwargs):
        if service is None: raise AssertionError('Historical output must not be regenerated with a future formatter.')
        result=original(service,*args,**kwargs);result['notice']='Future formatter wording';return result
    monkeypatch.setattr(module,'freeze',next_formatter)
    historic=client.get(path+'/'+created['id'])
    assert historic.status_code==200,historic.text
    assert historic.json()['versions'][0]['snapshot']==version['snapshot']
    exported=post(client,path+'/'+created['id']+'/versions/1/exports',{},'export')
    assert exported.status_code==201,exported.text
    assert run_task(exported.json()['task_id'],1)['status']=='succeeded'
    downloaded=client.get(path+'/'+created['id']+'/exports/'+exported.json()['id']+'/download')
    assert downloaded.status_code==200
    assert client.get(path+'/'+created['id']).json()['versions'][0]['snapshot']==version['snapshot']
