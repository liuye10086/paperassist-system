"""School templates retain original sources and require explicit immutable confirmation."""
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_file_batches import register
from app.db.database import database_connection


def post(client,path,body,key='template'):
    return client.post(path,json=body,headers={'Idempotency-Key':key})


def setup(client):
    from tests.helpers.document_samples import document_bytes
    project=client.post('/api/v1/projects',json=dict(name='合成学校',research_topic='合成材料',project_type='thesis')).json()
    base,batch,item,raw=register(client,project,document_bytes(),'school.docx')
    uploaded=client.post(base+'/'+batch['id']+'/items/'+item['client_id'],files={'file':(item['filename'],raw)}).json()
    path=f'/api/v1/projects/{project["id"]}'
    body=dict(name='合成模板',school='合成学校',version_label='',template_file_id=uploaded['file_id'],supplement_file_ids=[],manuscript_file_ids=[],supplement_text='附加要求：人工签名。')
    return path,body


def analysis(*args):
    source=dict(part='word/document.xml',path='/document/p[1]',text='合成规范')
    return dict(parser_version='school-template-openxml-v1',raw_styles=[],defaults={},sections=[],chapters=[],
        rules=[dict(id='body.font_east_asia',category='body',label='字体',value='宋体',source=source)],notes=[dict(id='normative',text='正文：黑体四号字。',source=source)],
        conflicts=[dict(id='conflict-1',rule_id='body.font_east_asia',label='字体',message='冲突',options=[dict(id='text-2',value='黑体',source=source),dict(id='openxml',value='宋体',source=source)])],
        missing=[dict(id='degree',message='学位待填写')],unsupported=[dict(id='manual',message='签名须人工处理')],identity_fields=['signature'])


def parsed(client):
    from app.domain.school_templates.execution import run_school_template_task
    path,body=setup(client);created=post(client,path+'/school-templates',body)
    assert created.status_code==202,created.text
    created=created.json()
    assert run_school_template_task(created['task']['id'],1,parser=analysis)['status']=='succeeded'
    return path,body,client.get(path+'/school-templates').json()['items'][0]


def test_school_profile_is_scoped_revisioned_and_never_implicitly_binds(client):
    path,_=setup(client)
    result=client.get(path+'/thesis-profile')
    assert result.status_code==200,result.text
    assert result.json()['revision']==0
    body=dict(expected_revision=0,school='合成学校',department='',major='',degree_type='学术学位',education_level='本科',applicable_version='未注明')
    saved=client.put(path+'/thesis-profile',json=body)
    assert saved.status_code==200,saved.text
    assert saved.json()['revision']==1 and saved.json()['bound_confirmation_id'] is None
    assert client.put(path+'/thesis-profile',json=body).status_code==409


def test_creation_replays_without_duplicate_source_or_task_and_does_not_parse_inline(client):
    path,body=setup(client)
    first=post(client,path+'/school-templates',body)
    assert first.status_code==202,first.text
    item=first.json()
    assert item['analysis'] is None and item['task']['status']=='queued'
    assert item['sources'][0]['sha256'] and item['sources'][0]['download_url'].endswith('/download')
    assert post(client,path+'/school-templates',body).json()==item
    assert post(client,path+'/school-templates',body|dict(name='changed')).status_code==409
    assert client.get('/api/v1/tasks/'+item['task']['id']).json()['input_version']['kind']=='school_template'
    assert client.get('/api/v1/tasks/'+item['task']['id']+'/workspace').status_code==200
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM school_template_sources').fetchone()['n']==1


def test_confirmation_requires_all_specific_options_and_freezes_chapters_and_limits(client):
    path,_,item=parsed(client);endpoint=path+'/school-templates/'+item['id']+'/confirm'
    body=dict(analysis_sha256=item['analysis_sha256'],decisions=[],chapters=[dict(id='intro',title='绪论',level=1)])
    assert post(client,endpoint,body,'unresolved').status_code==409
    assert post(client,endpoint,body|dict(decisions=[dict(conflict_id='conflict-1',option_id='unknown')]),'unknown').status_code==422
    body['decisions']=[dict(conflict_id='conflict-1',option_id='text-2')]
    confirmed=post(client,endpoint,body,'confirmed')
    assert confirmed.status_code==201,confirmed.text
    saved=confirmed.json()
    assert saved['chapters']==body['chapters'] and saved['rules'][0]['value']=='黑体'
    assert saved['missing'] and saved['unsupported']
    assert post(client,endpoint,body,'confirmed').json()==saved
    bound=post(client,path+'/thesis-template-binding',dict(confirmation_id=saved['id'],expected_revision=0))
    assert bound.status_code==200,bound.text
    assert bound.json()['revision']==1 and bound.json()['bound_confirmation_id']==saved['id']
    assert client.get(path+'/school-templates').json()['items'][0]['analysis']==item['analysis']
    assert client.get(path+'/summary').json()['thesis_profile']['template_name']=='合成模板'


def test_failed_parse_retry_uses_original_task_and_rejects_changed_sources(client):
    from app.domain.school_templates.execution import run_school_template_task
    from app.core.exceptions import StorageError
    path,body=setup(client);item=post(client,path+'/school-templates',body).json()
    def fail(*args): raise StorageError('parse_timeout','synthetic',422)
    assert run_school_template_task(item['task']['id'],1,parser=fail)['status']=='failed'
    retry=post(client,path+'/school-templates/'+item['id']+'/retry',{})
    assert retry.status_code==200,retry.text
    assert retry.json()['task']['id']==item['task']['id']
    assert run_school_template_task(item['task']['id'],retry.json()['task']['revision'],parser=analysis)['status']=='succeeded'
    with database_connection(write=True) as db: db.execute('UPDATE files SET sha256=%s WHERE id=%s',('a'*64,body['template_file_id']))
    current=client.get(path+'/school-templates').json()['items'][0]
    assert current['analysis'] and current['current_changes']
    confirmation=dict(analysis_sha256=current['analysis_sha256'],decisions=[dict(conflict_id='conflict-1',option_id='text-2')],chapters=[dict(id='x',title='正文',level=1)])
    assert post(client,path+'/school-templates/'+item['id']+'/confirm',confirmation).status_code==409


def test_foreign_owner_and_cross_project_confirmation_are_rejected(client):
    from tests.integration.test_project_ownership import account_client
    path,_,item=parsed(client)
    other_path,_=setup(client)
    confirmation=post(client,path+'/school-templates/'+item['id']+'/confirm',dict(analysis_sha256=item['analysis_sha256'],decisions=[dict(conflict_id='conflict-1',option_id='text-2')],chapters=[dict(id='x',title='正文',level=1)])).json()
    assert post(client,other_path+'/thesis-template-binding',dict(confirmation_id=confirmation['id'],expected_revision=0)).status_code==404
    with account_client('school-other@example.test')[0] as other:
        assert other.get(path+'/school-templates').status_code==404
        assert other.get(path+'/thesis-profile').status_code==404
        assert post(other,path+'/school-templates/'+item['id']+'/confirm',dict(analysis_sha256=item['analysis_sha256'],decisions=[],chapters=[])).status_code in (404,422)


def test_unparsed_supplement_is_not_silently_skipped(client):
    path,body=setup(client)
    assert post(client,path+'/school-templates',body|dict(supplement_file_ids=[body['template_file_id']]),'duplicate').status_code==422
    from tests.helpers.document_samples import document_bytes
    project=dict(id=path.rsplit('/',1)[1]);base,batch,item,raw=register(client,project,document_bytes(),'supplement.docx',key='supplement-batch')
    file=client.post(base+'/'+batch['id']+'/items/'+item['client_id'],files={'file':(item['filename'],raw)}).json()
    response=post(client,path+'/school-templates',body|dict(supplement_file_ids=[file['file_id']]),'pending')
    assert response.status_code==409,response.text
    from app.adapters.docx_parser import parse_docx
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    assert run_parse_file_task(file['task']['id'],1,parser=parse_docx)['status']=='succeeded'
    saved=post(client,path+'/school-templates',body|dict(supplement_file_ids=[file['file_id']]),'parsed')
    assert saved.status_code==202,saved.text
    assert saved.json()['sources'][1]['document_version_id'] and saved.json()['sources'][1]['evidence']


def test_unified_resume_and_lost_lease_do_not_duplicate_analysis(client):
    from app.adapters.task_execution_store import TaskExecutionStore,LeaseLost
    from app.domain.school_templates.execution import run_school_template_task
    import pytest
    path,body=setup(client);item=post(client,path+'/school-templates',body).json()
    execution=TaskExecutionStore();lease=execution.claim(item['task']['id'],1)
    with database_connection(write=True) as db:
        db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s",(item['task']['id'],))
    assert execution.recover_expired()==1
    with execution.connection() as db:
        with pytest.raises(LeaseLost):execution.require_lease(db,lease)
    recovered=client.get('/api/v1/tasks/'+item['task']['id']).json()
    def failing(*args):raise RuntimeError('synthetic failure')
    failed=run_school_template_task(recovered['id'],recovered['revision'],parser=failing)
    assert failed['status']=='failed'
    workspace=client.get('/api/v1/tasks/'+failed['id']+'/workspace')
    assert workspace.status_code==200,workspace.text
    assert workspace.json()['allowed_actions']==['retry']
    request=dict(operation='retry',wait_id=None,expected_task_revision=failed['revision'],input_version=failed['input_version'])
    resumed=post(client,'/api/v1/tasks/'+failed['id']+'/resume',request,'resume-school')
    assert resumed.status_code==202,resumed.text
    assert post(client,'/api/v1/tasks/'+failed['id']+'/resume',request,'resume-school').json()==resumed.json()
    assert run_school_template_task(failed['id'],resumed.json()['revision'],parser=analysis)['status']=='succeeded'
    assert run_school_template_task(failed['id'],resumed.json()['revision'],parser=analysis) is None
    page=client.get(path+'/tasks',params={'task_type':'school_template_parse'})
    assert page.status_code==200,page.text
    assert page.json()['total']==1


def test_plaintext_supported_supplement_compares_against_actual_format(client):
    from app.domain.school_templates.execution import run_school_template_task
    from app.adapters.school_template_parser import inspect_school_template
    path,body=setup(client)
    body['supplement_text']='正文：黑体四号字。'
    created=post(client,path+'/school-templates',body).json()
    assert run_school_template_task(created['task']['id'],1,parser=inspect_school_template)['status']=='succeeded'
    current=client.get(path+'/school-templates').json()['items'][0]
    assert any(r['source']['part']=='supplement_text' for r in current['analysis']['rules'])
    assert any(n['source']['part']=='supplement_text' for n in current['analysis']['notes'])


def test_confirmation_and_binding_change_file_retention_assessment(client):
    path,body,item=parsed(client)
    assessment=path+'/files/'+body['template_file_id']+'/lifecycle/assessment'
    before=client.get(assessment).json()['assessment_revision']
    saved=post(client,path+'/school-templates/'+item['id']+'/confirm',dict(analysis_sha256=item['analysis_sha256'],decisions=[dict(conflict_id='conflict-1',option_id='text-2')],chapters=[dict(id='body',title='正文',level=1)])).json()
    confirmed=client.get(assessment).json()['assessment_revision']
    assert before!=confirmed
    assert post(client,path+'/thesis-template-binding',dict(confirmation_id=saved['id'],expected_revision=0)).status_code==200
    assert client.get(assessment).json()['assessment_revision']!=confirmed


def test_windows_worker_does_not_fall_back_to_inline_docx_parsing(client):
    import sys
    import pytest
    if sys.platform=='linux':pytest.skip('Windows-specific refusal contract')
    from app.domain.school_templates.execution import run_school_template_task
    path,body=setup(client);item=post(client,path+'/school-templates',body).json()
    failed=run_school_template_task(item['task']['id'],1)
    assert failed['status']=='failed' and failed['error_code']=='parse_environment_unavailable'
    assert client.get(path+'/school-templates').json()['items'][0]['analysis'] is None
