"""Actual exported text, explicit manual decisions and immutable publication."""
from copy import deepcopy
import pytest
from tests.api.test_manuscript_writing_live_review import client, pending, decision
from tests.api.test_literature_evidence import post
from app.domain.literature.service import digest


def reviewed(client):
    root,path,ctx=pending(client)
    response=post(client,path+'/reviews',decision(ctx),'science')
    assert response.status_code==201,response.text
    return root,path,response.json()


def approve(context):
    return dict(schema_version=2,review_id=context['review_id'],review_sha256=context['review_sha256'],
        edits=[],figure_versions=[],inventory_sha256=context['inventory_sha256'],
        decisions=[dict(location=i['location'],content_sha256=i['content_sha256'],decision='target_language',reason='Human checked exact exported text.',exceptions=[]) for i in context['inventory']])


def test_language_artifact_binds_every_exported_text_and_publishes_exact_snapshot(client):
    root,path,science=reviewed(client)
    response=client.get(path+'/reviews/'+science['id']+'/language-context')
    assert response.status_code==200,response.text
    ctx=response.json();assert ctx['inventory']
    assert any('Items requiring' in i.get('text','') for i in ctx['inventory'])
    assert any('SCI manuscript' in i.get('text','') for i in ctx['inventory'])
    body=approve(ctx)
    omitted=deepcopy(body);omitted['decisions'].pop()
    assert post(client,path+'/language-reviews',omitted,'omitted').status_code==422
    response=post(client,path+'/language-reviews',body,'language')
    assert response.status_code==201,response.text
    language=response.json()
    assert client.get(path+'/reviews/'+science['id']).json()==science
    assert post(client,path+'/language-reviews',body,'language').json()==language
    payload=dict(schema_version=2,expected_revision=1,review_id=science['id'],review_sha256=science['review_sha256'],language_review_id=language['id'],language_review_sha256=language['artifact_sha256'])
    response=post(client,path+'/publish',payload,'publish')
    assert response.status_code==201,response.text
    assert response.json()['versions'][0]['snapshot']==language['candidate']
    assert post(client,path+'/publish',payload,'publish').status_code==200
    from app.domain.tasks.execution import run_task
    version=response.json()['versions'][0]
    assert run_task(version['task_id'],1)['status']=='succeeded'
    export=post(client,root+'/versions/2/exports',{},'export').json()
    assert run_task(export['task_id'],1)['status']=='succeeded'
    from app.db.database import database_connection
    from app.maintenance.database_audit import audit_database
    with database_connection() as db:
        audit=audit_database(db)
        assert audit['ok'],audit['schema_issues'] or [c for c in audit['data_checks'] if c['invalid']]
    for sql in ('UPDATE manuscript_writing_language_reviews SET artifact_sha256=artifact_sha256','DELETE FROM manuscript_writing_language_reviews'):
        with pytest.raises(Exception):
            with database_connection(write=True) as db: db.execute(sql)


def test_language_rejects_text_drift_science_edits_and_blanket_exemptions(client):
    _,path,science=reviewed(client)
    response=client.get(path+'/reviews/'+science['id']+'/language-context')
    assert response.status_code==200,response.text
    body=approve(response.json())
    changed=deepcopy(body);changed['decisions'][0]['content_sha256']='0'*64
    assert post(client,path+'/language-reviews',changed,'drift').status_code==422
    changed=deepcopy(body);changed['edits']=[dict(path='/sections/2/paragraphs/0/text',original_sha256=digest(science['candidate']['sections'][2]['paragraphs'][0]['text']),text='Altered scientific claim.',reason='Language change')]
    assert post(client,path+'/language-reviews',changed,'body-change').status_code==422
    changed=deepcopy(body);changed['decisions'][0]['decision']='exception'
    assert post(client,path+'/language-reviews',changed,'blanket').status_code==422


def test_figure_language_history_is_audited_and_retained_in_file_lifecycle(client):
    from tests.api.test_manuscript_figure_language import setup
    from app.db.database import database_connection
    from app.maintenance.database_audit import audit_database
    from app.domain.file_lifecycle.references import read_references
    from app.adapters.storage import get_project_store
    project,file,path,body=setup(client)
    response=post(client,path,body,'retained')
    assert response.status_code==201,response.text
    with database_connection() as db:
        audit=audit_database(db)
        assert any(c['table']=='manuscript_figure_language_versions' and c['rows']==1 and c['invalid']==0 for c in audit['data_checks'])
        refs=read_references(db,file,get_project_store().owner_id)
        assert refs['counts']['manuscript_figure_language_versions']==1

from tests.api.test_boxplot import cloud


@pytest.mark.parametrize('language',['en','zh-CN'])
def test_computed_boxplot_language_version_full_writing_science_language_export_chain(client,cloud,language):
    from tests.api.test_boxplot import prepared,generate
    from tests.domain.test_figure_language_renderer import labels
    from tests.api.test_manuscript_writing_live import authorize,request_v2,LiveFixture
    from tests.integration.test_literature_assistance import budgets
    from app.domain.manuscript_writing.execution import run_manuscript_writing_task
    from app.domain.tasks.execution import run_task
    from app.db.database import database_connection
    from app.maintenance.database_audit import audit_database
    from hashlib import sha256
    from io import BytesIO
    from zipfile import ZipFile
    base,file,result,url=prepared(client,[['Value','Group'],[1,'A'],[2,'A'],[3,'A'],[4,'A'],[2,'B'],[3,'B'],[4,'B'],[5,'B']])
    original=generate(client,url);project=base.split('/')[4]
    figure_path=f'/api/v1/projects/{project}/manuscript-figure-language-versions'
    translated=labels(language=='en')
    translated.update(title='Figure 1. Synthetic study' if language=='en' else '图 1. 合成研究',
        x_label='Value (mg/L)' if language=='en' else '数值（mg/L）',
        caption=('Figure 1. 8 complete records; 0 excluded. Boxes Q1–Q3; quantiles (n−1)p. Whiskers Q1−1.5×IQR to Q3+1.5×IQR; IQR=Q3−Q1. All observations retained; no significance tests.'
            if language=='en' else '图 1. 8行完整记录；0行排除。箱体Q1–Q3；分位数(n−1)p。须端Q1−1.5×IQR至Q3+1.5×IQR；IQR=Q3−Q1。保留所有观测，未检验显著性。'))
    response=post(client,figure_path,dict(source=dict(kind='figure',id=original['id'],file_id=file['id']),original_sha256=original['sha256'],output_language=language,mode='local_boxplot',texts=translated,reason='Translate all displayed labels preserving frozen group statistics.'),'figure-en')
    assert response.status_code==201,response.text
    figure=response.json();image=client.get(figure['download_url']).content
    selected=dict(kind='figure_language_version',id=figure['id'],file_id=file['id'],role='image_observation')
    root=f'/api/v1/projects/{project}/manuscripts'
    response=post(client,root,dict(title='Synthetic study' if language=='en' else '合成研究',output_language=language,sources=[selected]),'fact')
    assert response.status_code==201,response.text
    manuscript=response.json();root+='/'+manuscript['id']
    assert run_task(manuscript['versions'][0]['task_id'],1)['status']=='succeeded'
    response=post(client,root+'/writing-previews',dict(schema_version=2,base_revision=1,mode='full_draft',output_language=language,selected_source_ids=[figure['id']],selected_evidence_ids=[]),'bundle')
    assert response.status_code==201,response.text
    bundle=response.json();_,auth=authorize(client,root,bundle)
    response=post(client,root+'/writing-requests',request_v2(bundle,auth),'write')
    assert response.status_code==202,response.text
    task=response.json()['task'];budgets(client,task)
    class Fixture(LiveFixture):
        def receipt(self):
            import json
            value=super().receipt()
            if language=='zh-CN':
                output=json.loads(value['response']['output'][0]['content'][0]['text'])
                for section in output['sections']: section['paragraphs'][0]['text']='合成候选待人工核对。'
                value['response']['output'][0]['content'][0]['text']=json.dumps(output,ensure_ascii=False)
            return value
    assert run_manuscript_writing_task(task['id'],1,provider=Fixture())['status']=='succeeded'
    path=root+'/writing-requests/'+task['id'];ctx=client.get(path+'/review-context').json()
    response=post(client,path+'/reviews',decision(ctx),'science')
    assert response.status_code==201,response.text
    science=response.json();response=client.get(path+'/reviews/'+science['id']+'/language-context')
    assert response.status_code==200,response.text
    ctx=response.json();assert any(i['kind']=='figure_text' and i['text']=='n = 4' for i in ctx['inventory'])
    language_body=approve(ctx)
    if language=='zh-CN':
        import re
        for item,judgment in zip(ctx['inventory'],language_body['decisions']):
            for match in re.finditer(r'SCI|Results|Materials and methods|IQR|mg/L',item['text']):
                judgment['exceptions'].append(dict(start=match.start(),end=match.end(),kind='unit' if match[0]=='mg/L' else 'proper_name',reason='Fixed index, section, statistic or unit identifier; synthetic human review.'))
    response=post(client,path+'/language-reviews',language_body,'language')
    assert response.status_code==201,response.text
    language=response.json()
    payload=dict(schema_version=2,expected_revision=1,review_id=science['id'],review_sha256=science['review_sha256'],language_review_id=language['id'],language_review_sha256=language['artifact_sha256'])
    response=post(client,path+'/publish',payload,'publish')
    assert response.status_code==201,response.text
    version=response.json()['versions'][0]
    assert version['snapshot']==language['candidate'] and version['snapshot']['results_groups'][0]['figures'][0]['sha256']==figure['sha256']
    assert run_task(version['task_id'],1)['status']=='succeeded'
    export=post(client,root+'/versions/2/exports',{},'export').json()
    assert run_task(export['task_id'],1)['status']=='succeeded'
    export=client.get(root+'/exports/'+export['id']).json()
    with ZipFile(BytesIO(client.get(export['download_url']).content)) as archive:
        media=[archive.read(name) for name in archive.namelist() if name.startswith('word/media/')]
        assert image in media and sha256(image).hexdigest()==figure['sha256']
    with database_connection() as db:
        audit=audit_database(db)
        assert audit['ok'],audit['schema_issues'] or [c for c in audit['data_checks'] if c['invalid']]
    assert client.get(path+'/reviews/'+science['id']).json()==science


def test_unknown_image_replacement_language_asset_and_final_docx_are_exact(client):
    from tests.api.test_manuscript_figure_language import setup,uploaded
    from tests.api.test_manuscript_writing_live import authorize,request_v2,LiveFixture
    from tests.integration.test_literature_assistance import budgets
    from app.domain.manuscript_writing.execution import run_manuscript_writing_task
    from app.domain.tasks.execution import run_task
    from app.adapters.storage import get_project_store
    from io import BytesIO
    from zipfile import ZipFile
    from hashlib import sha256
    project,file,figpath,figure_body=setup(client)
    root=f'/api/v1/projects/{project}/manuscripts'
    source=dict(kind='original',id=file['id'],file_id=file['id'],role='image_observation')
    created=post(client,root,dict(title='External image review',output_language='en',sources=[source]),'base').json()
    root+='/'+created['id'];assert run_task(created['versions'][0]['task_id'],1)['status']=='succeeded'
    bundle=post(client,root+'/writing-previews',dict(schema_version=2,base_revision=1,mode='full_draft',output_language='en',selected_source_ids=[file['id']],selected_evidence_ids=[]),'bundle').json()
    _,auth=authorize(client,root,bundle)
    task=post(client,root+'/writing-requests',request_v2(bundle,auth),'write').json()['task'];budgets(client,task)
    assert run_manuscript_writing_task(task['id'],1,provider=LiveFixture())['status']=='succeeded'
    path=root+'/writing-requests/'+task['id'];ctx=client.get(path+'/review-context').json()
    science=post(client,path+'/reviews',decision(ctx),'science').json()
    endpoint=path+'/reviews/'+science['id']+'/language-context'
    ctx=client.get(endpoint).json()
    assert post(client,path+'/language-reviews',approve(ctx),'unknown').status_code==422
    replacement=uploaded(client,project,'blue')
    figure_request=figure_body|dict(mode='uploaded_replacement',replacement_file_id=replacement['id'],text_items=[dict(location='axis',text='中文轴')])
    figure=post(client,figpath,figure_request,'bad-language').json()
    prep=dict(schema_version=2,review_id=science['id'],review_sha256=science['review_sha256'],edits=[],figure_versions=[dict(figure_id=file['id'],version_id=figure['id'],original_sha256=file['sha256'])])
    ctx=post(client,endpoint,prep,'preview-bad').json();body=approve(ctx)|prep
    assert post(client,path+'/language-reviews',body,'bad-axis').status_code==422
    figure_request['text_items']=[dict(location='axis',text='Value')]
    figure=post(client,figpath,figure_request,'good-language').json()
    prep['figure_versions'][0]['version_id']=figure['id']
    response=post(client,endpoint,prep,'preview-good');assert response.status_code==200,response.text
    body=approve(response.json())|prep
    response=post(client,path+'/language-reviews',body,'language');assert response.status_code==201,response.text
    language=response.json();payload=dict(schema_version=2,expected_revision=1,review_id=science['id'],review_sha256=science['review_sha256'],language_review_id=language['id'],language_review_sha256=language['artifact_sha256'])
    response=post(client,path+'/publish',payload,'publish');assert response.status_code==201,response.text
    version=response.json()['versions'][0];assert run_task(version['task_id'],1)['status']=='succeeded'
    export=post(client,root+'/versions/2/exports',{},'export').json();assert run_task(export['task_id'],1)['status']=='succeeded'
    export=client.get(root+'/exports/'+export['id']).json()
    with ZipFile(BytesIO(client.get(export['download_url']).content)) as archive:
        hashes=[sha256(archive.read(n)).hexdigest() for n in archive.namelist() if n.startswith('word/media/')]
        assert replacement['sha256'] in hashes and file['sha256'] not in hashes
    assert client.get(path+'/reviews/'+science['id']).json()==science
    asset=get_project_store().directory/'manuscript_figure_language_versions'/(figure['id']+'.png')
    asset.write_bytes(b'tampered replacement bytes')
    assert post(client,path+'/publish',payload,'publish').status_code==409
    assert client.get(root+'/exports/'+export['id']+'/download').status_code==409


def test_unsupported_program_image_returns_explicit_language_error(client):
    from tests.api.test_manuscript_figure_language import setup
    project,file,path,body=setup(client)
    from app.domain.manuscripts.figure_language import FigureLanguageService
    from app.core.exceptions import StorageError
    from unittest.mock import patch
    with patch.object(FigureLanguageService,'create',side_effect=StorageError('figure_language_unsupported','Only frozen boxplot supported.',422)):
        response=post(client,path,body,'unsupported')
    assert response.status_code==422
    assert response.json()['detail']['code']=='figure_language_unsupported'
