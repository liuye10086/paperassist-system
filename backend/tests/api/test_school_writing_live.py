"""A/B synthetic school live chain with an injected provider, never OpenAI."""
from copy import deepcopy
import json
import pytest
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_school_templates import setup,analysis,post
from tests.api.test_manuscript_writing_live import LiveFixture
from tests.integration.test_literature_assistance import budgets
from app.domain.literature.service import digest
from app.domain.tasks.execution import run_task
from app.domain.manuscript_writing.execution import run_manuscript_writing_task
from app.db.database import database_connection

def prepared(client,bilingual):
    from app.domain.school_templates.execution import run_school_template_task
    path,template=setup(client);created=post(client,path+'/school-templates',template).json()
    def parser(*args):
        result=analysis()
        if bilingual:
            from tests.adapters.test_school_front_matter import synthetic
            result['front_matter_sources']=synthetic()['front_matter_sources']
        result['sections']=[dict(id='section-1',page=dict(width_cm=21,height_cm=29.7,margin_top_cm=2.5,margin_bottom_cm=2.5,margin_left_cm=2.5,margin_right_cm=2.5),source=dict(part='word/document.xml',path='/w:document/w:body/w:p[100]/w:pPr/w:sectPr',text='Synthetic section'),page_number=dict(format='decimal',start='1',mode='restart'),break_type=None,different_first_page=False,different_odd_even_pages=False,headers=[],footers=[])]
        return result
    assert run_school_template_task(created['task']['id'],1,parser=parser)['status']=='succeeded'
    item=client.get(path+'/school-templates').json()['items'][0]
    definitions=[('private-declaration','声明','manual','zh-CN'),('private-refs','参考文献','references','zh-CN')]
    if bilingual:definitions += [('private-zh-abstract','中文摘要','abstract','zh-CN'),('private-en-abstract','English abstract','abstract','en')]
    definitions += [('private-intro','绪论','introduction','zh-CN'),('private-methods','研究方法','materials_and_methods','zh-CN'),('private-results','结果','results','zh-CN'),('private-conclusion','结论','conclusion','zh-CN')]
    chapters=[dict(id=i,title=t,level=1) for i,t,p,l in definitions]
    confirmation_body=dict(analysis_sha256=item['analysis_sha256'],decisions=[dict(conflict_id='conflict-1',option_id='text-2')],chapters=chapters)
    if bilingual:
        source=item['front_matter_sources'][0]['id']
        confirmation_body['front_matter']=dict(schema_version=1,cover_section_id='section-1',fields=[dict(id=i,label=label,kind=kind,required=True,source_id=source,style_source_id=None,section_id='section-1',chapter_id=chapter) for i,label,kind,chapter in [('author-custom','作者','identity',None),('signature-custom','本人签名','signature','private-declaration'),('date-custom','提交日期','date',None)]],content_requirements=[dict(id='declaration',kind='declaration',required=True,chapter_id='private-declaration',source_id=source)])
    confirmed=post(client,path+'/school-templates/'+item['id']+'/confirm',confirmation_body)
    assert confirmed.status_code==201,confirmed.text
    confirmation=confirmed.json()
    profile=post(client,path+'/thesis-template-binding',dict(confirmation_id=confirmation['id'],expected_revision=0)).json()
    request=dict(title='合成研究题名',output_language='zh-CN',sources=[],thesis=dict(confirmation_id=confirmation['id'],profile_revision=profile['revision'],chapter_mappings=[dict(chapter_id=i,purpose=p,output_language=l,result_group_ids=[]) for i,t,p,l in definitions]))
    root=post(client,path+'/manuscripts',request,'base').json()
    assert run_task(root['versions'][0]['task_id'],1)['status']=='succeeded'
    return path,path+'/manuscripts/'+root['id'],root,confirmation

class SchoolFixture(LiveFixture):
    def receipt(self):
        payload=json.loads(json.loads(self.posts[-1])['input'])
        result=super().receipt()
        output=dict(sections=[dict(id=c['alias'],paragraphs=[dict(id=c['alias']+'-p1',text='Synthetic content requires explicit researcher review.' if c['output_language']=='en' else '合成正文须由研究人员明确核对。',source_aliases=[],evidence_aliases=[],study_numeric_bindings=[])]) for c in payload['chapters']])
        result['response']['output'][0]['content'][0]['text']=json.dumps(output)
        return result

def school_chain(client,bilingual,*,include_toc=False,monkeypatch=None,real_layout=False,prior_cache_reference_count=0):
    import time
    if monkeypatch is not None and not real_layout:
        from tests.domain.test_school_writing_live import synthetic_layout_cache
        monkeypatch.setattr('app.adapters.pdf_renderer.update_layout_fields',synthetic_layout_cache)
    path,base,root,confirmation=prepared(client,bilingual)
    preview=post(client,base+'/writing-previews',dict(schema_version=3,base_revision=1,mode='full_draft',output_language='zh-CN',selected_source_ids=[],selected_evidence_ids=[]),'preview')
    assert preview.status_code==201,preview.text
    bundle=preview.json();assert bundle['execution_contract']['schema_version']==3
    assert 'private-' not in bundle['wire_json'] and confirmation['id'] not in bundle['wire_json']
    auth=post(client,path+'/writing-authorizations',dict(schema_version=2,confirmed=True,tasks=[dict(logical_task_id='actual-school',bundles=[dict(bundle_id=bundle['id'],bundle_sha256=bundle['bundle_sha256'])])]),'authorization')
    assert auth.status_code==201,auth.text
    created=post(client,base+'/writing-requests',dict(schema_version=2,bundle_id=bundle['id'],bundle_sha256=bundle['bundle_sha256'],authorization_id=auth.json()['id'],logical_task_id='actual-school'),'write')
    assert created.status_code==202,created.text
    task=created.json()['task'];budgets(client,task);provider=SchoolFixture()
    assert run_manuscript_writing_task(task['id'],task['revision'],provider=provider)['status']=='succeeded'
    assert provider.posts==[bundle['wire_json']]
    endpoint=base+'/writing-requests/'+task['id'];ctx=client.get(endpoint+'/review-context').json()
    raw=ctx['candidate'];original=root['versions'][0]['snapshot']
    assert raw['title']==original['title'] and raw['sections'][0]==original['sections'][0]
    body=dict(schema_version=3,candidate_sha256=ctx['candidate_sha256'],paragraphs=[dict(paragraph_id=p['id'],text_sha256=digest(p['text']),classification='non_claim',scientific_basis='Explicit synthetic manual review',numeric_bindings=[]) for s in raw['sections'] for p in s['paragraphs'] if p['id'] in ctx['required_paragraph_ids']],consistency=dict(body_sha256=ctx['body_sha256'],title=dict(subject=True,direction=True,strength=True,basis='Frozen title compared'),abstracts={s['id']:dict(objective=True,methods=True,key_results=True,conclusion=True,basis='Each abstract compared') for s in raw['sections'] if s['purpose']=='abstract'}))
    science=post(client,endpoint+'/reviews',body,'science')
    assert science.status_code==201,science.text
    review=science.json()
    preparation=dict(schema_version=3,review_id=review['id'],review_sha256=review['review_sha256'],school=dict(include_toc=include_toc,english_title='Explicit English title',manual_fields=dict(author='USER AUTHOR')))
    if bilingual:preparation['school'].update(field_values={'author-custom':'USER AUTHOR','signature-custom':'USER SIGNATURE','date-custom':'2026-10-27'},manual_chapters=[dict(chapter_id='private-declaration',text='本人明确提供的合成声明，仅供工程核验。')])
    started=time.monotonic();language_context=post(client,endpoint+'/reviews/'+review['id']+'/language-context',preparation,'language-context')
    elapsed=round(time.monotonic()-started,3)
    print('school first layout seconds:',elapsed,'bilingual:',bilingual,'include_toc:',include_toc)
    assert language_context.status_code==200,language_context.text
    inventory=language_context.json();assert inventory['schema_version']==3
    assert any(i.get('toc_target') for i in inventory['inventory']) is include_toc
    assert inventory['candidate']['writing_provenance']['school_final_render']['key']
    assert inventory['candidate']['writing_provenance']['school_final_render']['mapper_version']=='school-final-map-v2'
    assert inventory['candidate']['writing_provenance']['school_pagination_version']==2
    def no_renderer(*args,**kwargs):raise AssertionError('Final school bytes must be reused without another renderer call')
    if monkeypatch is not None:monkeypatch.setattr('app.adapters.pdf_renderer.update_layout_fields',no_renderer)
    assert any('USER AUTHOR' in i['text'] for i in inventory['inventory'])
    language=post(client,endpoint+'/language-reviews',dict(**preparation,inventory_sha256=inventory['inventory_sha256'],decisions=[dict(location=i['location'],content_sha256=i['content_sha256'],decision='provided_literal' if i.get('protected_identity') else 'target_language',reason='Explicit per-item synthetic language check',exceptions=[]) for i in inventory['inventory']]),'language')
    assert language.status_code==201,language.text
    artifact=language.json()
    if monkeypatch is not None:monkeypatch.setattr('app.adapters.pdf_renderer.renderer_identity',no_renderer)
    adopted=post(client,endpoint+'/publish',dict(schema_version=2,expected_revision=1,review_id=review['id'],review_sha256=review['review_sha256'],language_review_id=artifact['id'],language_review_sha256=artifact['artifact_sha256']),'adopt')
    assert adopted.status_code==201,adopted.text
    new_version=next(v for v in adopted.json()['versions'] if v['revision']==2)
    assert run_task(new_version['task_id'],1)['status']=='succeeded'
    with database_connection() as db:
        saved=db.execute('SELECT school_confirmation_id FROM manuscript_versions WHERE manuscript_id=%s AND revision=2',(root['id'],)).fetchone()
        assert saved['school_confirmation_id']==confirmation['id']
    exported=post(client,base+'/versions/2/exports',{},'export')
    assert exported.status_code==201,exported.text
    assert run_task(exported.json()['task_id'],1)['status']=='succeeded'
    from hashlib import sha256
    export=client.get(base+'/exports/'+exported.json()['id']).json()
    final_bytes=client.get(export['download_url']).content
    assert sha256(final_bytes).hexdigest()==artifact['candidate']['writing_provenance']['school_docx_sha256']
    toc_pages=[]
    if include_toc:
        from io import BytesIO
        from zipfile import ZipFile
        from lxml import etree
        ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        with ZipFile(BytesIO(final_bytes)) as archive:xml=etree.fromstring(archive.read('word/document.xml'))
        for link in xml.xpath('//w:hyperlink[starts-with(@w:anchor,"PATOC")]',namespaces=ns):toc_pages.append(int(link.xpath('.//w:t/text()',namespaces=ns)[-1]))
        assert len(toc_pages)>1 and all(b>a for a,b in zip(toc_pages,toc_pages[1:]))
        print('school v2 final exported TOC pages:',toc_pages,'bilingual:',bilingual)
    assert client.get(base+'/versions/2').status_code==200
    assert client.get(endpoint+'/language-reviews/'+artifact['id']).status_code==200
    changed=deepcopy(preparation['school'])
    if bilingual:changed['field_values']['author-custom']='CHANGED AUTHOR'
    else:changed['manual_fields']['author']='CHANGED AUTHOR'
    rejected=post(client,base+'/versions/2/exports',dict(school=changed),'changed-export')
    assert rejected.status_code==422,rejected.text
    assert len(provider.posts)==1
    with database_connection(write=True) as db:
        from app.domain.storage_governance.service import inventory as storage_inventory
        from app.core.config import get_data_dir
        scan=storage_inventory(db,get_data_dir())
        assert scan['typed_coverage']['school_language_artifact']['references']==prior_cache_reference_count+2
        assert scan['typed_coverage']['school_language_artifact']['errors']==0
        from app.domain.file_lifecycle.references import read_references
        from app.domain.storage_governance.deletion import file_object_keys
        file_id=artifact['candidate']['thesis_context']['source_files'][0]['file_id']
        file=db.execute('SELECT * FROM files WHERE id=%s',(file_id,)).fetchone()
        owner=db.execute('SELECT owner_id FROM projects WHERE id=%s',(root['project_id'],)).fetchone()['owner_id']
        refs=read_references(db,file,owner)
        assert refs['counts']['manuscript_school_language_artifacts']==1
        assert len(refs['public_groups']['manuscript_school_language_artifacts'])==1
        assert len([k for k in file_object_keys(db,refs) if k.startswith('manuscript_school_language/')])==2
    return dict(project_id=root['project_id'],manuscript_id=root['id'],writing_request_id=task['id'],review=review,language_artifact=artifact,export=export,first_layout_seconds=elapsed,toc_pages=toc_pages)

@pytest.mark.parametrize('bilingual',[False,True])
def test_school_frozen_provider_science_language_publish_export_chain(client,bilingual,monkeypatch):
    import os
    school_chain(client,bilingual,include_toc=True,monkeypatch=monkeypatch,real_layout=os.getenv('PAPERASSIST_SCHOOL_LAYOUT_TEST_REAL')=='1')
