"""Versioned school pagination; actual local renderer is explicitly opt-in."""
from copy import deepcopy
from io import BytesIO
import os
from zipfile import ZipFile

from lxml import etree
import pytest

from app.domain.literature.service import digest
from tests.domain.test_school_writing_live import fixture
from app.domain.manuscript_writing.live_execution import compose_live_candidate

@pytest.fixture(autouse=True)
def postgres_schema():
    yield None

NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
W='{'+NS['w']+'}'

def material(second_source=False):
    from app.domain.manuscripts.contracts import SchoolExportOptions
    from app.domain.manuscripts.school_export import compile_school_export
    snapshot,bundle,output,analysis=fixture()
    candidate=compose_live_candidate(output,snapshot,bundle,'pagination','synthetic_fixture')
    candidate['sections']=[s for s in candidate['sections'] if s['purpose'] in ('introduction','materials_and_methods')]
    context=candidate['thesis_context'];context['chapters']=[s for s in context['chapters'] if s['purpose'] in ('introduction','materials_and_methods')]
    context['confirmation']['chapters']=[{k:s[k] for k in ('id','title','level')} for s in context['chapters']]
    analysis['chapters']=[dict(id=s['id'],title=s['title'],level=s['level'],source=dict(part='word/document.xml',path='/w:document/w:body/w:p['+str(150 if second_source and i else 10+i)+']',text=s['title'])) for i,s in enumerate(context['chapters'])]
    if second_source:
        other=deepcopy(analysis['sections'][0]);other.update(id='section-2',source=dict(part='word/document.xml',path='/w:document/w:body/w:p[300]/w:pPr/w:sectPr',text='Second actual source section'),page_number=dict(format='decimal',start='7',mode='restart'))
        analysis['sections'].append(other)
    context['confirmation']['analysis_sha256']=digest(analysis);context['confirmation_sha256']=digest(context['confirmation'])
    candidate['writing_provenance']['school_pagination_version']=2
    plan=compile_school_export(candidate,analysis,SchoolExportOptions().model_dump(mode='json'))
    # The explicit opt-in must not be treated as a blanket legacy render change.
    plan['pagination_version']=2
    return candidate,analysis,plan

@pytest.mark.parametrize('second_source',[False,True])
def test_school_pagination_consumes_each_source_restart_once(second_source):
    from app.adapters.school_docx import build_school_docx
    candidate,_,plan=material(second_source)
    raw=build_school_docx(candidate,{},plan,source_map=[])
    with ZipFile(BytesIO(raw)) as archive:root=etree.fromstring(archive.read('word/document.xml'))
    starts=root.xpath('//w:sectPr/w:pgNumType/@w:start',namespaces=NS)
    assert starts==(['1','7'] if second_source else ['1'])
    headings=[p for p in root.xpath('//w:body/w:p',namespaces=NS) if p.xpath('w:pPr/w:pStyle[@w:val="Heading1"]',namespaces=NS)]
    assert len(headings)==2
    assert bool(headings[0].xpath('w:pPr/w:pageBreakBefore',namespaces=NS))
    assert bool(headings[1].xpath('w:pPr/w:pageBreakBefore',namespaces=NS)) is (not second_source)

def test_toc_source_section_is_active_and_body_restores_its_previous_source_without_restart():
    from app.domain.manuscripts.school_export import compile_school_export
    from app.domain.manuscripts.contracts import SchoolExportOptions
    from app.adapters.school_docx import build_school_docx
    candidate,analysis,_=material()
    for rows in (candidate['sections'],candidate['thesis_context']['chapters']):
        for row in rows:row['level']=2
    manual=dict(id='manual-front',title='Declaration',level=1,purpose='manual',output_language='en',result_group_ids=[])
    candidate['sections'].insert(0,dict(manual,paragraphs=[]));candidate['thesis_context']['chapters'].insert(0,manual)
    analysis['chapters']+=[dict(id='manual-front',title='Declaration',level=1,source=dict(part='word/document.xml',path='/w:document/w:body/w:p[5]',text='Declaration')),dict(id='toc-source',title='Contents',level=1,source=dict(part='word/document.xml',path='/w:document/w:body/w:p[150]',text='Contents'))]
    toc=deepcopy(analysis['sections'][0]);toc.update(id='toc-section',source=dict(part='word/document.xml',path='/w:document/w:body/w:p[300]/w:pPr/w:sectPr',text='TOC source section'),page_number=dict(format='lowerRoman',start='1',mode='restart'))
    analysis['sections'].append(toc)
    context=candidate['thesis_context'];context['confirmation']['chapters']=[{k:s[k] for k in ('id','title','level')} for s in context['chapters']]
    context['confirmation']['analysis_sha256']=digest(analysis);context['confirmation_sha256']=digest(context['confirmation'])
    plan=compile_school_export(candidate,analysis,SchoolExportOptions().model_dump(mode='json'))
    raw=build_school_docx(candidate,{},plan,source_map=[])
    with ZipFile(BytesIO(raw)) as archive:root=etree.fromstring(archive.read('word/document.xml'))
    assert root.xpath('//w:sectPr/w:pgNumType/@w:fmt',namespaces=NS)==['decimal','lowerRoman','decimal']
    assert root.xpath('//w:sectPr/w:pgNumType/@w:start',namespaces=NS)==['1','1']

@pytest.mark.skipif(os.getenv('PAPERASSIST_SCHOOL_LAYOUT_TEST_REAL')!='1',reason='Explicit local renderer run only')
@pytest.mark.parametrize('second_source',[False,True])
def test_real_toc_page_numbers_follow_continuation_and_actual_source_restart(second_source):
    from app.adapters.school_docx import build_school_docx
    from app.adapters.pdf_renderer import update_layout_fields
    candidate,_,plan=material(second_source)
    raw=build_school_docx(candidate,{},plan,source_map=[])
    cache=update_layout_fields(raw)
    pages=[int(line.rsplit('\t',1)[1]) for line in cache['toc_lines']]
    print('actual school pagination v2:',pages,'second source:',second_source)
    assert len(pages)==2
    assert pages[1]==(7 if second_source else pages[0]+1)
