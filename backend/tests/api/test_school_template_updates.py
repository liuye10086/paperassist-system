from copy import deepcopy
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_school_templates import setup,post,analysis
from app.domain.school_templates.execution import run_school_template_task
from app.db.database import database_connection


def text_analysis(*args):
    value=analysis();source=dict(part='word/document.xml',path='/w:document/w:body/w:p[1]',text='明确文字')
    value['notes']=[dict(id='latin',text='英文一律采用Times New Roman。',source=source),dict(id='line',text='一级标题1.5倍行距。',source=source)]
    value['rules']+=[dict(id='body.font_latin',category='body',label='Latin',value='Calibri',source=source),dict(id='heading1.line_spacing',category='heading1',label='line',value='240',source=source)]
    return value


def test_new_text_decisions_are_explicit_and_preserved_without_old_json_rewrite(client):
    path,request=setup(client)
    first=post(client,path+'/school-templates',request,'first').json()
    assert run_school_template_task(first['task']['id'],1,parser=text_analysis)['status']=='succeeded'
    first=client.get(path+'/school-templates').json()['items'][0]
    options=first['text_decision_options'];assert len(options)==2
    assert all(o['suggested_choice'] is None for o in options)
    body=dict(analysis_sha256=first['analysis_sha256'],decisions=[dict(conflict_id=c['id'],option_id=c['options'][0]['id']) for c in first['analysis']['conflicts']],chapters=[dict(id='intro',title='绪论',level=1)])
    url=path+'/school-templates/'+first['id']+'/confirm'
    assert post(client,url,body,'missing').status_code==422
    body['text_decisions']=[dict(id=o['id'],choice='text',source_sha256=o['source_sha256']) for o in options]
    response=post(client,url,body,'confirm')
    assert response.status_code==201,response.text
    confirmed=response.json()
    with database_connection() as db:
        before=db.execute('SELECT request_json,request_digest,snapshot_json,snapshot_sha256 FROM school_template_confirmations WHERE id=%s',(confirmed['id'],)).fetchone()
    second=post(client,path+'/school-templates',request|dict(previous_version_id=first['id']),'next').json()
    assert run_school_template_task(second['task']['id'],1,parser=text_analysis)['status']=='succeeded'
    second=client.get(path+'/school-templates').json()['items'][0]
    assert all(o['suggested_choice']=='text' and not o['changed'] for o in second['text_decision_options'])
    assert post(client,path+'/school-templates/'+second['id']+'/confirm',{k:v for k,v in body.items() if k!='text_decisions'}|dict(analysis_sha256=second['analysis_sha256']),'must-select').status_code==422
    third=post(client,path+'/school-templates',request|dict(previous_version_id=first['id']),'missing-rule').json()
    assert run_school_template_task(third['task']['id'],1,parser=analysis)['status']=='succeeded'
    third=client.get(path+'/school-templates').json()['items'][0]
    assert all(o['changed'] and o['suggested_choice'] is None and o['choices']==['attributes'] for o in third['text_decision_options'])
    with database_connection() as db:
        assert db.execute('SELECT request_json,request_digest,snapshot_json,snapshot_sha256 FROM school_template_confirmations WHERE id=%s',(confirmed['id'],)).fetchone()==before


def test_previous_template_scope_and_default_request_compatibility(client):
    path,request=setup(client);first=post(client,path+'/school-templates',request,'first').json()
    other,other_request=setup(client)
    assert post(client,other+'/school-templates',other_request|dict(previous_version_id=first['id']),'foreign').status_code==404
    with database_connection() as db:
        body=db.execute('SELECT request_json FROM school_template_versions WHERE id=%s',(first['id'],)).fetchone()['request_json']
    assert 'previous_version_id' not in body
    assert post(client,path+'/school-templates',request|dict(previous_version_id=None),'first').status_code==200
