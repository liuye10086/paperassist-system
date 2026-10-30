from copy import deepcopy

from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_school_templates import setup,post
from tests.adapters.test_school_front_matter import synthetic
from app.domain.school_templates.execution import run_school_template_task
from app.db.database import database_connection
from app.domain.literature.service import digest


def analyzed(client):
    path,request=setup(client);created=post(client,path+'/school-templates',request,'new-front').json()
    assert run_school_template_task(created['task']['id'],1,parser=lambda *a:synthetic())['status']=='succeeded'
    item=client.get(path+'/school-templates').json()['items'][0]
    body=dict(analysis_sha256=item['analysis_sha256'],decisions=[dict(conflict_id=c['id'],option_id=c['options'][0]['id']) for c in item['analysis']['conflicts']],chapters=[{k:c[k] for k in ('id','title','level')} for c in item['analysis']['chapters']])
    return path,item,body


def test_new_confirmation_freezes_bound_contract_and_rejects_forged_source(client):
    path,item,body=analyzed(client);url=path+'/school-templates/'+item['id']+'/confirm'
    sources=item['front_matter_sources'];s=sources[0]
    front=dict(schema_version=1,cover_section_id='section-1',fields=[dict(id='custom',label='培养类型',kind='identity',required=True,source_id='fake',style_source_id=s['id'],section_id='section-1',chapter_id=None)],content_requirements=[])
    assert post(client,url,body|dict(front_matter=front),'bad').status_code==422
    front['fields'][0]['source_id']=s['id']
    response=post(client,url,body|dict(front_matter=front),'good')
    assert response.status_code==201,response.text
    saved=response.json();assert saved['front_matter']==front
    assert post(client,url,body|dict(front_matter=front),'good').json()==saved
    changed=deepcopy(front);changed['fields'][0]['required']=False
    assert post(client,url,body|dict(front_matter=changed),'good').status_code==409


def test_preupgrade_confirmation_request_digest_replays_with_explicit_new_null(client):
    path,item,body=analyzed(client);url=path+'/school-templates/'+item['id']+'/confirm'
    first=post(client,url,body,'legacy');assert first.status_code==201,first.text
    with database_connection() as db:
        before=db.execute('SELECT request_json,request_digest,snapshot_json,snapshot_sha256 FROM school_template_confirmations WHERE id=%s',(first.json()['id'],)).fetchone()
    assert before['request_json']==body and before['request_digest']==digest(body)
    assert 'front_matter' not in before['snapshot_json']
    replay=post(client,url,body|dict(front_matter=None),'legacy')
    assert replay.status_code==200,replay.text
    with database_connection() as db:
        assert db.execute('SELECT request_json,request_digest,snapshot_json,snapshot_sha256 FROM school_template_confirmations WHERE id=%s',(first.json()['id'],)).fetchone()==before


def test_v2_binding_manuscript_export_worker_and_download_keep_frozen_sources(client):
    from app.domain.tasks.execution import run_task
    from io import BytesIO
    from zipfile import ZipFile
    path,item,body=analyzed(client);source=item['front_matter_sources'][0]
    chapter=body['chapters'][0]['id']
    front=dict(schema_version=1,cover_section_id='section-1',fields=[dict(id='custom',label='培养类型',kind='identity',required=True,source_id=source['id'],style_source_id=source['id'],section_id='section-1',chapter_id=None),dict(id='signature',label='作者签名',kind='signature',required=True,source_id=source['id'],style_source_id=None,section_id='section-1',chapter_id=chapter)],content_requirements=[dict(id='decl',kind='declaration',required=True,chapter_id=chapter,source_id=source['id']),dict(id='thanks',kind='acknowledgements',required=True,chapter_id=body['chapters'][1]['id'],source_id=source['id'])])
    confirm=post(client,path+'/school-templates/'+item['id']+'/confirm',body|dict(front_matter=front),'confirm').json()
    profile=post(client,path+'/thesis-template-binding',dict(confirmation_id=confirm['id'],expected_revision=0)).json()
    request=dict(title='合成前置规则',output_language='zh-CN',sources=[],thesis=dict(confirmation_id=confirm['id'],profile_revision=profile['revision'],chapter_mappings=[dict(chapter_id=c['id'],purpose='manual' if i==0 else 'acknowledgements',output_language='project',result_group_ids=[]) for i,c in enumerate(body['chapters'])]))
    root=post(client,path+'/manuscripts',request,'manuscript').json()
    assert run_task(root['versions'][0]['task_id'],1)['status']=='succeeded'
    base=path+'/manuscripts/'+root['id'];endpoint=base+'/versions/1/exports'
    options={'school':{'include_toc':False,'field_values':{'custom':'用户输入'},'manual_chapters':[dict(chapter_id=chapter,text='用户明确声明正文')]}}
    assert post(client,endpoint+'/preview',{'school':{'field_values':{'fake':'reject'}}}).status_code==422
    preview=post(client,endpoint+'/preview',options);assert preview.status_code==200,preview.text
    plan=preview.json()['school'];ids={i['id'] for i in plan['report']['issues']}
    assert 'school:field:signature' in ids and 'school:required-content:thanks' in ids and 'school:required-content:decl' not in ids
    original=client.get(base+'/versions/1').json()['snapshot']
    created=post(client,endpoint,options,'export');assert created.status_code==201,created.text
    saved=created.json();assert run_task(saved['task_id'],1)['status']=='succeeded'
    done=client.get(base+'/exports/'+saved['id']);assert done.status_code==200,done.text
    raw=client.get(done.json()['download_url']);assert raw.status_code==200,raw.text
    with ZipFile(BytesIO(raw.content)) as z:
        xml=z.read('word/document.xml').decode()
        assert '培养类型：用户输入' in xml and '作者签名：待填写' in xml
        assert '示例值不能作为本人信息' not in xml and '示例签名' not in xml
    assert post(client,endpoint,options,'export').json()['id']==saved['id']
    assert client.get(base+'/versions/1').json()['snapshot']==original
    current=client.get(path+'/school-templates').json()['items'][0]
    assert current['analysis']==item['analysis'] and current['confirmation']==confirm


def test_legacy_sealed_options_plan_and_docx_replay_read_list_download_are_byte_stable(client,monkeypatch):
    from tests.api.test_school_exports import published
    from app.domain.tasks.execution import run_task
    from hashlib import sha256
    _,base,_,_=published(client);endpoint=base+'/versions/1/exports'
    monkeypatch.setattr('app.adapters.school_docx.complete_school_fields',lambda raw,plan:(raw,dict(status='updated')))
    created=post(client,endpoint,{},'legacy-export').json()
    with database_connection() as db:
        before=db.execute('SELECT school_input_json,school_input_sha256 FROM manuscript_exports WHERE id=%s',(created['id'],)).fetchone()
    assert 'field_values' not in before['school_input_json']['request']['school']
    assert before['school_input_json']['plan']['schema_version']==1
    assert 'front_matter' not in before['school_input_json']['plan']
    def no_recompile(*a):raise AssertionError('Read historical sealed plan without recompiling')
    monkeypatch.setattr('app.domain.manuscripts.school_export.compile_school_export',no_recompile)
    assert post(client,endpoint,{'school':{'field_values':{}}},'legacy-export').status_code==200
    assert run_task(created['task_id'],1)['status']=='succeeded'
    view=client.get(base+'/exports/'+created['id']).json();raw=client.get(view['download_url']).content
    assert sha256(raw).hexdigest()==view['sha256']
    assert client.get(endpoint).json()['items'][0]['school']['plan']==before['school_input_json']['plan']
    assert client.get(view['download_url']).content==raw
    with database_connection() as db:
        assert db.execute('SELECT school_input_json,school_input_sha256 FROM manuscript_exports WHERE id=%s',(created['id'],)).fetchone()==before
