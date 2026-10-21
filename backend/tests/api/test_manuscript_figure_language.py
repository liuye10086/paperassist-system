"""Independent local language versions are selectable and exported as exact bytes."""
from hashlib import sha256
from io import BytesIO
import zipfile
import pytest

from PIL import Image
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_literature_evidence import post


def uploaded(client,project,color='white'):
    from tests.api.test_file_batches import register
    from app.adapters.storage import get_project_store
    output=BytesIO();Image.new('RGB',(300,200),color).save(output,format='PNG')
    base,batch,item,content=register(client,{'id':project},output.getvalue(),'image.png','upload-'+color)
    response=client.post(base+'/'+batch['id']+'/items/'+item['client_id'],files={'file':('image.png',content)})
    assert response.status_code==202,response.text
    return get_project_store().file(project,response.json()['file_id'])


def setup(client):
    project=client.post('/api/v1/projects',json=dict(name='Language images',research_topic='Synthetic only',project_type='sci')).json()['id']
    file=uploaded(client,project)
    path=f'/api/v1/projects/{project}/manuscript-figure-language-versions'
    body=dict(source=dict(kind='original',id=file['id'],file_id=file['id']),original_sha256=file['sha256'],
        mode='no_text_confirmation',output_language='en',reason='Inspected blank synthetic source; contains no text.',title='Blank synthetic image',caption='Synthetic blank image.')
    return project,file,path,body


def test_no_text_version_becomes_initial_fact_draft_source_and_exact_docx_media(client):
    from app.domain.tasks.execution import run_task
    project,file,path,body=setup(client)
    response=post(client,path,body,'language-1')
    assert response.status_code==201,response.text
    version=response.json();assert post(client,path,body,'language-1').json()==version
    candidates=client.get(f'/api/v1/projects/{project}/manuscripts/candidates').json()['items']
    assert any(c['kind']=='figure_language_version' and c['id']==version['id'] for c in candidates)
    assert version['original']['sha256']==file['sha256']
    raw=client.get(version['download_url']).content
    assert sha256(raw).hexdigest()==version['sha256']
    request=dict(title='Image language fact draft',output_language='en',sources=[dict(kind='figure_language_version',id=version['id'],file_id=file['id'],role='image_observation')])
    created=post(client,f'/api/v1/projects/{project}/manuscripts',request,'fact-1')
    assert created.status_code==201,created.text
    root=created.json();fact=root['versions'][0];image=fact['snapshot']['results_groups'][0]['figures'][0]
    assert image['sha256']==version['sha256'] and image['preview_url']==version['download_url']
    run_task(fact['task_id'],1)
    export=post(client,f'/api/v1/projects/{project}/manuscripts/{root["id"]}/versions/1/exports',{},'docx-1').json()
    run_task(export['task_id'],1)
    export=client.get(f'/api/v1/projects/{project}/manuscripts/{root["id"]}/exports/{export["id"]}').json()
    assert export['status']=='succeeded',export
    archive=zipfile.ZipFile(BytesIO(client.get(export['download_url']).content))
    assert raw in [archive.read(p) for p in archive.namelist() if p.startswith('word/media/')]


def test_replacement_requires_exact_source_sha_reason_and_immutable_asset(client,tmp_path):
    from app.adapters.storage import get_project_store
    project,file,path,body=setup(client);replacement=uploaded(client,project,'blue')
    request=body|dict(mode='uploaded_replacement',replacement_file_id=replacement['id'],text_items=[dict(location='axis',text='Value')])
    assert post(client,path,request|{'original_sha256':'0'*64},'bad-sha').status_code==409
    assert post(client,path,request|{'reason':''},'bad-reason').status_code==422
    response=post(client,path,request,'replacement')
    assert response.status_code==201,response.text
    version=response.json();assert version['sha256']==replacement['sha256']
    target=get_project_store().directory/'manuscript_figure_language_versions'/(version['id']+'.png')
    target.write_bytes(b'changed')
    assert client.get(version['download_url']).status_code==409
    assert client.get(path+'/'+version['id']).status_code==409


@pytest.mark.parametrize('legacy',[False,True])
def test_frozen_chinese_boxplot_gets_selectable_english_version_without_changing_original(client,monkeypatch,legacy):
    from uuid import uuid4
    import json
    from app.db.database import database_connection
    from app.adapters.storage import get_project_store
    from tests.api.test_analysis import add_file
    from tests.domain.test_figure_language_renderer import frozen,labels
    base,file=add_file(client);project=base.split('/')[4]
    assets=get_project_store();analysis_id=str(uuid4());figure_id=str(uuid4())
    image=BytesIO();Image.new('RGB',(1600,1000),'white').save(image,format='PNG');raw=image.getvalue()
    figure=frozen()|dict(id=figure_id,analysis_run_id=analysis_id,title='中文原图',caption='原始图注',language='zh-CN',size_bytes=len(raw),sha256=sha256(raw).hexdigest())
    with database_connection(write=True) as db:
        db.execute('INSERT INTO analysis_runs(id,file_id,setup_revision,engine_version,completed_at,result_json) VALUES (%s,%s,1,%s,%s,%s)',(analysis_id,file['id'],'synthetic_fixture','2026-10-21T00:00:00Z','{}'))
        db.execute('INSERT INTO figures(id,analysis_run_id,renderer_version,figure_json) VALUES (%s,%s,%s,%s)',(figure_id,analysis_id,'openai_boxplot_v1',json.dumps(figure)))
    assets.figures_dir.mkdir(parents=True,exist_ok=True);original_path=assets.figures_dir/(figure_id+'.png');original_path.write_bytes(raw)
    path=f'/api/v1/projects/{project}/manuscript-figure-language-versions'
    request=dict(source=dict(kind='figure',id=figure_id,file_id=file['id']),original_sha256=figure['sha256'],output_language='en',mode='local_boxplot',texts=labels(),reason='Translate all labels; preserve frozen statistics.')
    from app.domain.manuscripts import figure_language
    render=figure_language.render_boxplot
    if legacy:
        monkeypatch.setattr(figure_language,'render_boxplot',lambda *a,**k: render(*a,**{**k,'renderer_version':'paperassist_horizontal_boxplot_language_v1'}))
    response=post(client,path,request,'local-en');assert response.status_code==201,response.text
    monkeypatch.setattr(figure_language,'render_boxplot',render)
    version=response.json();assert version['geometry']['orientation']=='horizontal'
    assert version['renderer_version']==('paperassist_horizontal_boxplot_language_v1' if legacy else 'paperassist_horizontal_boxplot_language_v2')
    assert client.get(path+'/'+version['id']).json()==version
    assert sha256(client.get(version['download_url']).content).hexdigest()==version['sha256']
    assert post(client,path,request,'local-en').json()==version
    assert original_path.read_bytes()==raw and version['sha256']!=figure['sha256']
    selected=dict(kind='figure_language_version',id=version['id'],file_id=file['id'],role='image_observation')
    response=post(client,f'/api/v1/projects/{project}/manuscripts',dict(title='English study',output_language='en',sources=[selected]),'english-initial')
    assert response.status_code==201,response.text
    assert response.json()['versions'][0]['snapshot']['results_groups'][0]['figures'][0]['sha256']==version['sha256']
    assert post(client,f'/api/v1/projects/{project}/manuscripts/preview',dict(title='Wrong language',output_language='zh-CN',sources=[selected]),'wrong-lang').status_code==409


def test_document_image_no_text_confirmation_binds_exact_image_and_project(client):
    from tests.api.test_document_versions import uploaded_docx
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    from app.adapters.docx_parser import parse_docx
    project,_,_,item,_=uploaded_docx(client)
    assert run_parse_file_task(item['task']['id'],1,parser=parse_docx)['status']=='succeeded'
    base=f'/api/v1/projects/{project["id"]}/files/{item["file_id"]}/document-versions'
    version=client.get(base).json()['items'][0]
    image=client.get(base+'/'+version['id']).json()['images'][0]
    raw=client.get(image['download_url']).content
    path=f'/api/v1/projects/{project["id"]}/manuscript-figure-language-versions'
    body=dict(source=dict(kind='document_version',id=version['id'],file_id=item['file_id'],image_id=image['id']),
        original_sha256=sha256(raw).hexdigest(),output_language='en',mode='no_text_confirmation',title='Synthetic image',
        caption='Local synthetic sample.',reason='Inspected this exact document image; no embedded text.')
    response=post(client,path,body,'doc-image')
    assert response.status_code==201,response.text
    saved=response.json();assert client.get(saved['download_url']).content==raw
    other,_,other_path,_=setup(client)
    assert client.get(other_path+'/'+saved['id']).status_code==404
    assert post(client,other_path,body,'foreign-image').status_code==409
