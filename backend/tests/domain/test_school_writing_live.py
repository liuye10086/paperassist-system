"""Synthetic A/B school contracts; no database or supplier transport."""
from copy import deepcopy
import json
import pytest
from app.domain.literature.service import digest
from app.domain.manuscripts.school import seed_school_snapshot
from app.domain.manuscript_writing.bundle import build_bundle,validate_bundle
from app.domain.manuscript_writing.frozen import contract,initial_draft_workflow,validate_wire,wire_parts
from app.domain.manuscript_writing.live_execution import compose_live_candidate,validate_live_candidate
from tests.domain.test_thesis_chapters import sample

@pytest.fixture(autouse=True)
def postgres_schema():
    yield None

def material(bilingual=False):
    base,context=sample()
    base['title']='研究题名' if bilingual else 'Provided research title'
    base['output_language']='zh-CN' if bilingual else 'en'
    definitions=[('private-declaration','声明' if bilingual else 'Declaration','manual','zh-CN' if bilingual else 'en'),
                 ('private-refs','参考文献' if bilingual else 'Bibliography','references','zh-CN' if bilingual else 'en')]
    if bilingual:definitions += [('private-zh-abstract','中文摘要','abstract','zh-CN'),('private-en-abstract','English abstract','abstract','en')]
    definitions += [('private-intro','绪论' if bilingual else 'Research context','introduction',base['output_language']),
                    ('private-methods','研究方法' if bilingual else 'Study process','materials_and_methods',base['output_language']),
                    ('private-results','结果' if bilingual else 'Findings','results',base['output_language']),
                    ('private-conclusion','结论' if bilingual else 'Conclusion','conclusion',base['output_language'])]
    chapters=[dict(id=i,title=t,level=1,purpose=p,output_language=l,result_group_ids=['evidence'] if p=='results' else []) for i,t,p,l in definitions]
    analysis=dict(chapters=[dict(id=c['id'],title=c['title'],level=1,source=dict(path='/w:document/w:body/w:p[2]',part='word/document.xml',text='Synthetic heading')) for c in chapters],
                  sections=[dict(id='section-1',page=dict(width_cm=21,height_cm=29.7,margin_top_cm=2.5,margin_bottom_cm=2.5,margin_left_cm=2.5,margin_right_cm=2.5),source=dict(path='/w:document/w:body/w:p[100]/w:pPr/w:sectPr',part='word/document.xml',text='Synthetic section'),page_number=dict(format='decimal',start='1',mode='restart'),break_type=None,different_first_page=False,different_odd_even_pages=False,headers=[],footers=[])],raw_styles=[],notes=[])
    context['chapters']=chapters;context['confirmation'].update(chapters=[{k:c[k] for k in ('id','title','level')} for c in chapters],analysis_sha256=digest(analysis))
    context['confirmation_sha256']=digest(context['confirmation'])
    base=seed_school_snapshot(base,context)
    base['sections'][0]['paragraphs']=[dict(id='private-manual',text='PRIVATE AUTHOR SIGNATURE 2026-10-27',origin='user_provided',source_ids=[],citations=[],numeric_bindings=[])]
    request=dict(schema_version=3,base_revision=1,mode='full_draft',target_section=None,output_language=base['output_language'],instructions='',keywords=[],acknowledgements='',selected_source_ids=['run'],selected_evidence_ids=[])
    return base,request,analysis

def fixture(bilingual=False):
    base,request,analysis=material(bilingual)
    bundle=build_bundle(base,request,execution_contract=contract(schema_version=3));bundle['id']='bundle-school'
    snapshot=dict(input=request,base_snapshot=base,request_id='school-request',base_version_id='school-base')
    output=dict(sections=[dict(id=alias,paragraphs=[dict(id=alias+'-p1',text='正文待研究人员核对。' if row['output_language']=='zh-CN' else 'Researcher verification is required.',source_aliases=[],evidence_aliases=[],study_numeric_bindings=[])]) for alias,row in bundle['local_manifest']['school']['chapters'].items() if alias in bundle['local_manifest']['school']['writable_aliases']])
    return snapshot,bundle,output,analysis

@pytest.mark.parametrize('quote', ['Sequenced with GS FLX+ (454/Roche).', 'The range was −(12).'])
def test_school_keeps_literature_with_unusable_numeric_notation_as_qualitative_evidence(quote):
    base, request, _ = material()
    binding = dict(metadata={'title':'Independent evidence'}, evidence=[
        dict(id='excerpt', quote=quote, reading_scope='abstract'),
        dict(id='count', quote='There were 17 subjects.', reading_scope='abstract')])
    base['citation_snapshot'] = dict(paragraphs=[dict(id='p1', fragments=[dict(bindings=[binding])])])
    request['selected_evidence_ids'] = ['excerpt', 'count']
    bundle = build_bundle(base, request, execution_contract=contract(schema_version=3))
    payload = json.loads(json.loads(bundle['wire_json'])['input'])
    first, second = payload['evidence']
    assert first['quote'] == quote and first['numeric_facts'] == []
    assert second['numeric_facts'] == [dict(fact_path='/quote/numbers/0', value='17')]

@pytest.mark.parametrize('bilingual',[False,True])
def test_school_contract_freezes_dynamic_aliases_and_excludes_identity(bilingual):
    snapshot,bundle,output,_=fixture(bilingual)
    assert bundle['execution_contract']['numeric_contract_version']==2
    assert bundle['execution_contract']['schema_version']==3
    payload=json.loads(json.loads(bundle['wire_json'])['input'])
    assert payload['school_content_version']=='school-live-v1'
    assert 'PRIVATE AUTHOR' not in bundle['wire_json']
    assert all(c['id'] not in bundle['wire_json'] for c in snapshot['base_snapshot']['thesis_context']['chapters'])
    assert bundle['local_manifest']['protected_identity']['sha256']
    validate_wire(bundle['wire_json'],bundle['execution_contract'])
    validate_bundle(dict(bundle,base_snapshot=snapshot['base_snapshot'],request_json=snapshot['input']))
    candidate=compose_live_candidate(output,snapshot,bundle,'call','synthetic_fixture')
    assert candidate['title']==snapshot['base_snapshot']['title']
    assert candidate['sections'][0]==snapshot['base_snapshot']['sections'][0]
    assert candidate['sections'][1]==snapshot['base_snapshot']['sections'][1]
    assert [{k:s[k] for k in ('id','title','level','purpose','output_language','result_group_ids')} for s in candidate['sections']]==snapshot['base_snapshot']['thesis_context']['chapters']
    validate_live_candidate(candidate,snapshot,bundle)

def test_school_output_rejects_reordered_or_protected_chapters():
    snapshot,bundle,output,_=fixture()
    for changed in [dict(sections=list(reversed(output['sections']))),dict(sections=[dict(id='chapter1',paragraphs=output['sections'][0]['paragraphs'])])]:
        with pytest.raises(ValueError):compose_live_candidate(changed,snapshot,bundle,'call','synthetic_fixture')


def test_new_school_presentation_freezes_exact_aliases_without_changing_v1():
    from app.domain.manuscript_writing.school_live import output_schema

    snapshot, _, _, _ = fixture()
    base, request = snapshot['base_snapshot'], snapshot['input']
    options = dict(schema_version=3, source_selection_version=2)
    old = contract(**options, school_presentation_version='school-presentation-v1')
    legacy = build_bundle(base, request, execution_contract=old)
    validate_wire(legacy['wire_json'], old)
    legacy_format = json.loads(legacy['wire_json'])['text']['format']
    assert legacy_format['name'] == 'manuscript_school_presentation_v1'
    limits = legacy_format['schema']['$defs']['Presentation']['properties']
    assert limits['chapter_titles']['maxItems'] == limits['figure_titles']['maxItems'] == 300

    frozen = contract(**options, school_presentation_version='school-presentation-v2')
    bundle = build_bundle(base, request, execution_contract=frozen)
    validate_bundle(dict(bundle, base_snapshot=base, request_json=request))
    wire = json.loads(bundle['wire_json'])
    selected = json.loads(wire['input'])
    assert wire['text']['format']['name'] == 'manuscript_school_presentation_v2'
    assert 'If a list is empty, return an empty array' in wire['instructions']
    properties = wire['text']['format']['schema']['$defs']['Presentation']['properties']
    assert properties['chapter_titles']['maxItems'] == properties['figure_titles']['maxItems'] == 0
    assert properties['keywords']['minItems'] == properties['keywords']['maxItems'] == len(selected['draft_presentation']['abstracts'])

    selected['draft_presentation']['chapter_titles'] = ['chapter3']
    selected['draft_presentation']['figure_titles'] = [{'id': 'figure1', 'number': 1}, {'id': 'figure2', 'number': 2}]
    schema = output_schema(selected, presentation_version='school-presentation-v2')
    values = schema['$defs']['Presentation']['properties']
    assert values['chapter_titles']['items']['properties']['id']['enum'] == ['chapter3']
    assert values['figure_titles']['items']['properties']['id']['enum'] == ['figure1', 'figure2']
    assert values['figure_titles']['minItems'] == values['figure_titles']['maxItems'] == 2


def test_customer_school_presentation_is_frozen_and_uses_exact_citation_sentences():
    from app.domain.sci_draft_reader import paragraph_parts
    from app.domain.manuscript_writing.school_presentation import PRESENTATION_VERSION

    snapshot, _, output, _ = fixture(True)
    base, request = snapshot['base_snapshot'], snapshot['input']
    binding = dict(project_reference_id='reference', metadata={'title':'Independent evidence'},
                   evidence=[dict(id='excerpt', quote='Clustering improved reproducibility.', reading_scope='abstract')])
    base['citation_snapshot'] = dict(paragraphs=[dict(id='source', fragments=[dict(bindings=[binding])])])
    request['selected_evidence_ids'] = ['excerpt']
    frozen = contract(schema_version=3, school_presentation_version=PRESENTATION_VERSION)
    bundle = build_bundle(base, request, execution_contract=frozen)
    bundle['id'] = 'school-presentation'
    validate_bundle(dict(bundle, base_snapshot=base, request_json=request))
    payload = json.loads(json.loads(bundle['wire_json'])['input'])
    assert payload['draft_presentation']['source_title'] == base['title']
    assert 'PRIVATE AUTHOR' not in bundle['wire_json']
    output['presentation'] = dict(english_title='Reproducibility of Clustering',
        keywords=[dict(id=c, values=['聚类'] if row['output_language']=='zh-CN' else ['clustering'])
                  for c,row in bundle['local_manifest']['school']['chapters'].items() if row['purpose']=='abstract'],
        chapter_titles=[], figure_titles=[])
    for s in output['sections']:
        s['paragraphs'][0]['citation_anchors'] = []
    item = output['sections'][0]['paragraphs'][0]
    item.update(text='已有研究观察到聚类表现改善。研究条件待核对。', evidence_aliases=['e1'],
                citation_anchors=[dict(sentence='已有研究观察到聚类表现改善。', evidence_aliases=['e1'])])
    candidate = compose_live_candidate(output, snapshot, bundle, 'call', 'synthetic_fixture')
    validate_live_candidate(candidate, snapshot, bundle)
    assert candidate['school_presentation']['english_title'] == 'Reproducibility of Clustering'
    para = next(p for s in candidate['sections'] for p in s['paragraphs'] if p.get('suggested_evidence_aliases'))
    parts = paragraph_parts(para, candidate, bundle['local_manifest']['evidence'], {'reference':dict(number=1)})
    assert [p['text'] for p in parts] == ['已有研究观察到聚类表现改善。', '研究条件待核对。']
    assert parts[0]['citations'][0]['number'] == 1 and not parts[1]['citations']
    item['citation_anchors'][0]['sentence'] = '聚类表现'
    with pytest.raises(ValueError):
        compose_live_candidate(output, snapshot, bundle, 'call', 'synthetic_fixture')


def test_thesis_initial_draft_skills_preserve_selected_school_wire_and_replay(monkeypatch, tmp_path):
    from app.domain.manuscript_writing.school_presentation import PRESENTATION_VERSION
    from app.domain.runtime_skills import runtime

    snapshot, _, output, _ = fixture(True)
    base, request = snapshot['base_snapshot'], snapshot['input']
    base['acknowledgements'] = 'PRIVATE ACKNOWLEDGEMENT'
    base['sources'] += [dict(id=identity, kind='document_version', role='methods',
                             content=dict(items=[dict(kind='text', text=body)]))
                        for identity, body in [('local-selected', 'Selected school protocol.'),
                                               ('local-unselected', 'PRIVATE UNSELECTED DOCUMENT')]]
    original = contract(schema_version=3, source_selection_version=2, school_presentation_version=PRESENTATION_VERSION)
    request.update(document_context_version='selected-text-v1', selected_source_ids=['run', 'local-selected'])
    original_bundle = build_bundle(base, request, execution_contract=original)
    assert 'skills_snapshot' not in original_bundle['execution_contract']
    assert initial_draft_workflow(request) == 'thesis_initial_draft'
    monkeypatch.setenv('PAPERASSIST_SKILL_WORKFLOWS', 'thesis_initial_draft')
    monkeypatch.setenv('PAPERASSIST_SKILLS_DIR', str(runtime.PROJECT_ROOT / 'SKILLS'))
    monkeypatch.delenv('PAPERASSIST_SKILLS_MANIFEST_SHA256', raising=False)
    skills = runtime.load_step('thesis_initial_draft', 'initial_draft').freeze_writing()
    assert [ref.name for ref in skills.trace.skills] == [
        'scientific-writing', 'thesis-writing', 'citation-verification',
    ]
    frozen = contract(schema_version=3, source_selection_version=2, school_presentation_version=PRESENTATION_VERSION,
                      skills_snapshot=skills)
    bundle = build_bundle(base, request, execution_contract=frozen) | dict(id='school-skills')
    baseline_wire, skill_wire = (json.loads(item['wire_json']) for item in (original_bundle, bundle))
    assert skill_wire.pop('instructions') == baseline_wire.pop('instructions') + '\n\n' + skills.instructions
    assert skill_wire == baseline_wire
    assert bundle['local_manifest'] == original_bundle['local_manifest']
    assert bundle['omitted_manifest'] == original_bundle['omitted_manifest']
    assert skill_wire['text']['format']['name'] == 'manuscript_school_presentation_v1'
    assert bundle['bundle_sha256'] != original_bundle['bundle_sha256']
    payload = json.loads(skill_wire['input'])
    assert payload['sources'][1]['document_excerpt'] == 'Selected school protocol.'
    assert {chapter['output_language'] for chapter in payload['chapters']} == {'zh-CN', 'en'}
    assert all(secret not in bundle['wire_json'] for secret in (
        'PRIVATE AUTHOR', 'PRIVATE ACKNOWLEDGEMENT', 'PRIVATE UNSELECTED DOCUMENT',
        'school-original', 'private-methods', 'local-selected', 'local-unselected',
    ))
    output['presentation'] = dict(english_title='Example Thesis', chapter_titles=[], figure_titles=[],
        keywords=[dict(id=row['id'], values=['合成'] if row['output_language'] == 'zh-CN' else ['synthetic'])
                  for row in payload['draft_presentation']['abstracts']])
    for section in output['sections']:
        section['paragraphs'][0]['citation_anchors'] = []

    monkeypatch.setenv('PAPERASSIST_SKILL_WORKFLOWS', '')
    monkeypatch.setenv('PAPERASSIST_SKILLS_DIR', str(tmp_path / 'missing'))
    validate_wire(bundle['wire_json'], frozen)
    assert validate_bundle(dict(bundle, base_snapshot=base, request_json=request))['wire_json'] == bundle['wire_json']
    candidate = compose_live_candidate(output, snapshot, bundle, 'call', 'synthetic_fixture')
    assert candidate['writing_provenance']['skills_trace'] == skills.trace.model_dump(mode='json')
    assert candidate['sections'][0] == base['sections'][0]
    assert candidate['acknowledgements'] == base['acknowledgements']
    validate_live_candidate(candidate, snapshot, bundle)
    assert validate_bundle(dict(original_bundle, base_snapshot=base, request_json=request))['wire_json'] == original_bundle['wire_json']

    for change in (dict(mode='rewrite_section'), dict(revision_of_request_id='parent'), dict(draft_advice=True),
                   dict(original_draft=[]), dict(draft_revision_scope='selected_sections'), dict(draft_sections=[])):
        assert initial_draft_workflow(request | change) is None
        with pytest.raises(ValueError, match='initial draft workflow'):
            wire_parts(frozen, payload | change)
    old_request = {key: value for key, value in request.items() if key != 'document_context_version'}
    assert initial_draft_workflow(old_request) is None
    with pytest.raises(ValueError, match='initial draft workflow'):
        build_bundle(base, old_request, execution_contract=frozen)
    with pytest.raises(ValueError, match='initial draft skill contract'):
        contract(schema_version=3, source_selection_version=2, skills_snapshot=skills)


def test_school_rewrite_keeps_all_non_target_content():
    snapshot,bundle,output,_=fixture(True)
    original=compose_live_candidate(output,snapshot,bundle,'first','synthetic_fixture')
    request={**snapshot['input'],'mode':'rewrite_section','target_section':'private-methods'}
    replacement=build_bundle(original,request,execution_contract=contract(schema_version=3));replacement['id']='rewrite'
    target=next(a for a,c in replacement['local_manifest']['school']['chapters'].items() if c['chapter_id']=='private-methods')
    changed=dict(sections=[dict(id=target,paragraphs=[dict(id='new',text='修改后的方法仍须核对。',source_aliases=[],evidence_aliases=[],study_numeric_bindings=[])])])
    candidate=compose_live_candidate(changed,{**snapshot,'input':request,'base_snapshot':original},replacement,'next','synthetic_fixture')
    assert [s for s in candidate['sections'] if s['id']!='private-methods']==[s for s in original['sections'] if s['id']!='private-methods']

def test_school_science_checks_each_abstract_and_preserves_nonterminal_references():
    from app.domain.manuscript_writing.live_review_candidate import body_digest,target_ids,prepare,finish
    snapshot,bundle,output,_=fixture(True)
    raw=compose_live_candidate(output,snapshot,bundle,'call','synthetic_fixture')
    body=dict(schema_version=3,candidate_sha256=digest(raw),paragraphs=[dict(paragraph_id=p['id'],text_sha256=digest(p['text']),corrected_text=None,classification='non_claim',scientific_basis='Manual synthetic check',claim=None,numeric_bindings=[]) for s in raw['sections'] for p in s['paragraphs'] if p['id'] in target_ids(raw,snapshot)],consistency=dict(body_sha256=body_digest(raw),title=dict(subject=True,direction=True,strength=True,basis='Frozen title checked'),abstracts={s['id']:dict(objective=True,methods=True,key_results=True,conclusion=True,basis='Each language abstract checked') for s in raw['sections'] if s['purpose']=='abstract'}))
    candidate,fragments=prepare(raw,snapshot,bundle,body,lambda *a:None)
    reviewed,report=finish(candidate,raw,snapshot,body,None,{},'review')
    assert reviewed['title']==raw['title'] and reviewed['sections'][0]==raw['sections'][0] and reviewed['sections'][1]==raw['sections'][1]
    assert report['schema_version']==3
    body['consistency']['abstracts'].pop('private-en-abstract')
    with pytest.raises(ValueError):prepare(raw,snapshot,bundle,body,lambda *a:None)

def test_school_actual_docx_inventory_has_per_chapter_language_and_option_binding():
    from app.domain.manuscripts.contracts import SchoolExportOptions
    from app.domain.manuscript_writing.school_language import inventory,validate_options_binding
    snapshot,bundle,output,analysis=fixture(True)
    candidate=compose_live_candidate(output,snapshot,bundle,'call','synthetic_fixture')
    options=SchoolExportOptions(include_toc=False,english_title='Provided English title',manual_fields=dict(author='USER AUTHOR')).model_dump(mode='json')
    items,plan=inventory(candidate,{},[],analysis,options)
    assert any(i.get('target_language')=='en' and i.get('chapter_id')=='private-en-abstract' for i in items)
    assert any(i.get('target_language')=='zh-CN' and i.get('chapter_id')=='private-zh-abstract' for i in items)
    assert any('USER AUTHOR' in i['text'] for i in items)
    validate_options_binding(candidate,options,plan)
    changed=deepcopy(options);changed['manual_fields']['author']='CHANGED AUTHOR'
    with pytest.raises(ValueError):validate_options_binding(candidate,changed,plan)

def test_reviewed_study_numbers_use_authoritative_school_science_context():
    from app.domain.manuscript_writing.live_review_candidate import body_digest,target_ids,prepare,finish
    snapshot,bundle,output,_=fixture()
    target=next(s for s in output['sections'] if bundle['local_manifest']['school']['chapters'][s['id']]['purpose']=='results')
    target['paragraphs'][0].update(text='n=12',source_aliases=['s1'],study_numeric_bindings=[dict(source_alias='s1',fact_path='/statistics/n',value='12')])
    raw=compose_live_candidate(output,snapshot,bundle,'call','synthetic_fixture')
    body=dict(schema_version=3,candidate_sha256=digest(raw),paragraphs=[dict(paragraph_id=p['id'],text_sha256=digest(p['text']),corrected_text=None,classification='study_claim' if p['text']=='n=12' else 'non_claim',scientific_basis='Synthetic explicit check',claim=None,numeric_bindings=[dict(occurrence=0,value='12',kind='study',source_alias='s1',fact_path='/statistics/n',evidence_id=None)] if p['text']=='n=12' else []) for s in raw['sections'] for p in s['paragraphs'] if p['id'] in target_ids(raw,snapshot)],consistency=dict(body_sha256=body_digest(raw),title=dict(subject=True,direction=True,strength=True,basis='Frozen title checked'),abstracts={}))
    candidate,parts=prepare(raw,snapshot,bundle,body,lambda *a:None)
    reviewed,_=finish(candidate,raw,snapshot,body,None,{},'review',school_bundle=bundle)
    assert reviewed['school_content_report']['can_publish'] is True

def test_school_contract_requires_explicit_numeric_two():
    from app.domain.manuscript_writing.frozen import validate
    value=contract(schema_version=3)
    for change in ({'numeric_contract_version':True},{'numeric_contract_version':2.0},{'numeric_contract_version':3}):
        with pytest.raises(ValueError):validate(dict(value,**change))
    value.pop('numeric_contract_version')
    with pytest.raises(ValueError):validate(value)

def test_provided_literal_cannot_exempt_ordinary_chapter_text_or_missing_reason():
    from app.domain.manuscript_writing.school_language import validate_decisions
    item=dict(location='word/document.xml:paragraph:1',kind='export_text',text='必须翻译的正文',content_sha256=digest('必须翻译的正文'),target_language='en',chapter_id='body',protected_identity=False,scope='narrative')
    decision=dict(location=item['location'],content_sha256=item['content_sha256'],decision='provided_literal',reason='Explicit user decision',exceptions=[])
    with pytest.raises(ValueError):validate_decisions([item],dict(inventory_sha256=digest([item]),decisions=[decision]))
    item['protected_identity']=True
    validate_decisions([item],dict(inventory_sha256=digest([item]),decisions=[decision]))
    decision['reason']=''
    with pytest.raises(ValueError):validate_decisions([item],dict(inventory_sha256=digest([item]),decisions=[decision]))

def test_results_chapter_cannot_borrow_another_chapters_illustration_number():
    base,request,_=material()
    first=base['results_groups'][0]
    first['figures']=[dict(id='figure-one',number=1,title='Figure 1',caption='Figure 1. Multiplier 1.5.',source_ids=['run'],panels=[])]
    second=deepcopy(first);second['id']='other-results';second['figures']=[dict(id='figure-two',number=2,title='Figure 2',caption='Figure 2. Multiplier 2.5.',source_ids=['run'],panels=[])]
    base['results_groups'].append(second)
    chapter=dict(id='private-other-results',title='Other findings',level=1,purpose='results',output_language='en',result_group_ids=['other-results'],paragraphs=[])
    base['sections'].append(chapter);base['thesis_context']['chapters'].append({k:v for k,v in chapter.items() if k!='paragraphs'})
    base['thesis_context']['confirmation']['chapters'].append({k:chapter[k] for k in ('id','title','level')})
    bundle=build_bundle(base,request,execution_contract=contract(schema_version=3));bundle['id']='scope'
    output=dict(sections=[dict(id=a,paragraphs=[dict(id=a,text='Needs review.',source_aliases=[],evidence_aliases=[],study_numeric_bindings=[])]) for a in bundle['local_manifest']['school']['writable_aliases']])
    binding=next(dict(source_alias=a,**v) for a,row in bundle['local_manifest']['numeric_context'].items() for v in row['values'] if v['value']=='2.5')
    target=next(s for s in output['sections'] if bundle['local_manifest']['school']['chapters'][s['id']]['chapter_id']=='private-results')
    target['paragraphs'][0].update(text='The multiplier is 2.5.',study_numeric_bindings=[binding])
    with pytest.raises(ValueError):compose_live_candidate(output,dict(input=request,base_snapshot=base,request_id='scope',base_version_id='base'),bundle,'call','synthetic_fixture')

def test_school_toc_is_generated_locally_and_inventory_remains_fully_mapped(monkeypatch):
    from app.domain.manuscripts.contracts import SchoolExportOptions
    from app.domain.manuscript_writing.school_language import inventory
    monkeypatch.setattr('app.adapters.pdf_renderer.update_layout_fields',synthetic_layout_cache)
    snapshot,bundle,output,analysis=fixture()
    candidate=compose_live_candidate(output,snapshot,bundle,'call','synthetic_fixture')
    items,plan=inventory(candidate,{},[],analysis,SchoolExportOptions(include_toc=True).model_dump(mode='json'))
    assert plan['toc']['enabled'] is True
    assert any(i.get('generated_field') for i in items)
    assert all(i['target_language'] in ('en','zh-CN') and i['location'] and i['content_sha256'] for i in items)

def synthetic_layout_cache(content):
    from hashlib import sha256
    from io import BytesIO
    from zipfile import ZipFile
    from lxml import etree
    with ZipFile(BytesIO(content)) as archive:
        manifest=json.loads(etree.fromstring(archive.read('customXml/paperassist-layout.xml')).text)
        root=etree.fromstring(archive.read('word/document.xml'))
    ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    lines=[]
    for i,target in enumerate(manifest['toc_targets']):
        node=root.xpath('//w:bookmarkStart[@w:name=$name]',namespaces=ns,name=target['bookmark'])[0].getparent()
        lines.append(''.join(node.xpath('.//w:t/text()',namespaces=ns))+'\t'+str(i+2))
    return dict(source_sha256=sha256(content).hexdigest(),fields={},toc_lines=lines)

def test_default_toc_inventory_seals_final_fields_and_exact_anchor_languages(monkeypatch):
    from hashlib import sha256
    from app.domain.manuscripts.contracts import SchoolExportOptions
    from app.domain.manuscript_writing.school_language import inventory
    from app.adapters.school_docx import build_school_docx,complete_school_fields
    monkeypatch.setattr('app.adapters.pdf_renderer.update_layout_fields',synthetic_layout_cache)
    snapshot,bundle,output,analysis=fixture(True)
    candidate=compose_live_candidate(output,snapshot,bundle,'call','synthetic_fixture')
    next(s for s in candidate['sections'] if s['purpose']=='introduction')['output_language']='en'
    next(s for s in candidate['thesis_context']['chapters'] if s['purpose']=='introduction')['output_language']='en'
    items,plan=inventory(candidate,{},[],analysis,SchoolExportOptions().model_dump(mode='json'))
    from app.domain.manuscripts.school_export import compile_school_export
    plan=compile_school_export(candidate,analysis,SchoolExportOptions().model_dump(mode='json'))
    pending=build_school_docx(candidate,{},plan,source_map=[])
    final,receipt=complete_school_fields(pending,plan)
    assert candidate['writing_provenance']['school_docx_sha256']==sha256(final).hexdigest()
    toc=[i for i in items if i.get('toc_target')]
    assert len(toc)==receipt['toc_entries']
    assert {i['target_language'] for i in toc}=={'en','zh-CN'}
    assert all(i['chapter_id'] and i['toc_target'].startswith('PATOC') for i in toc)

def test_final_school_cache_reuses_exact_bytes_without_renderer_and_binds_material(tmp_path,monkeypatch):
    from app.domain.manuscripts.contracts import SchoolExportOptions
    from app.domain.manuscript_writing.school_language import inventory
    from app.domain.manuscript_writing.school_render_cache import read,descriptors
    calls=[]
    def layout(content):calls.append(content);return synthetic_layout_cache(content)
    monkeypatch.setattr('app.adapters.pdf_renderer.update_layout_fields',layout)
    snapshot,bundle,output,analysis=fixture(True)
    candidate=compose_live_candidate(output,snapshot,bundle,'call','synthetic_fixture')
    options=SchoolExportOptions().model_dump(mode='json');cache=dict(root=tmp_path,owner='owner',project='project')
    items,plan=inventory(candidate,{},[],analysis,options,cache=cache)
    proof=deepcopy(candidate['writing_provenance']['school_final_render'])
    original,record=read(tmp_path,'owner','project',proof)
    assert record['field_update']['status']=='updated' and len(calls)==1
    def unavailable(*args,**kwargs):raise AssertionError('History must not need current renderer or layout')
    monkeypatch.setattr('app.adapters.pdf_renderer.update_layout_fields',unavailable)
    monkeypatch.setattr('app.adapters.pdf_renderer.renderer_identity',unavailable)
    monkeypatch.setattr('app.adapters.manuscript_docx.RENDERER_VERSION','later-installed-version')
    monkeypatch.setattr('app.domain.manuscript_writing.language.RENDERER_VERSION','later-installed-version')
    restored=deepcopy(candidate);restored['writing_provenance']['language_review_id']='later-audit-id'
    replay,_=inventory(restored,{},[],analysis,options,cache=cache,frozen=proof)
    assert items==replay and read(tmp_path,'owner','project',proof)[0]==original
    assert len(descriptors(proof,'owner','project'))==2
    changed=deepcopy(candidate);changed['sections'][-1]['paragraphs'][0]['text']+=' CHANGED'
    with pytest.raises(ValueError):inventory(changed,{},[],analysis,options,cache=cache,frozen=proof)
    with pytest.raises((OSError,ValueError)):read(tmp_path,'other-owner','project',proof)
    descriptor=descriptors(proof,'owner','project')[0]
    (tmp_path/descriptor['object_key']).write_bytes(b'CORRUPTED')
    with pytest.raises(ValueError):read(tmp_path,'owner','project',proof)

def test_first_school_layout_failure_creates_no_reviewed_cache(tmp_path,monkeypatch):
    from app.domain.manuscripts.contracts import SchoolExportOptions
    from app.domain.manuscript_writing.school_language import inventory
    def unavailable(content):raise ValueError('Synthetic local renderer unavailable')
    monkeypatch.setattr('app.adapters.pdf_renderer.update_layout_fields',unavailable)
    snapshot,bundle,output,analysis=fixture()
    candidate=compose_live_candidate(output,snapshot,bundle,'call','synthetic_fixture')
    with pytest.raises(ValueError):inventory(candidate,{},[],analysis,SchoolExportOptions().model_dump(mode='json'),cache=dict(root=tmp_path,owner='owner',project='project'))
    assert not list(tmp_path.rglob('*')) and 'school_final_render' not in candidate['writing_provenance'] and 'school_docx_sha256' not in candidate['writing_provenance']

def test_school_cache_publication_never_overwrites_a_concurrent_different_receipt(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from app.domain.manuscript_writing.school_render_cache import _write_once
    path=tmp_path/'immutable.json'
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: _write_once(path,b'original'),range(2)))
    assert path.read_bytes()==b'original'
    with pytest.raises(ValueError):_write_once(path,b'different')
    assert path.read_bytes()==b'original' and [p.name for p in tmp_path.iterdir()]==['immutable.json']

def test_old_v1_school_artifact_reads_original_bytes_and_inventory_after_v2_upgrade(tmp_path,monkeypatch):
    from app.domain.manuscripts.contracts import SchoolExportOptions
    from app.domain.manuscripts.school_export import compile_school_export
    from app.domain.manuscript_writing.school_language import inventory,plan_digest
    from app.domain.manuscript_writing.school_render_cache import materialize,read
    monkeypatch.setattr('app.adapters.pdf_renderer.update_layout_fields',synthetic_layout_cache)
    snapshot,bundle,output,analysis=fixture(True)
    candidate=compose_live_candidate(output,snapshot,bundle,'legacy-v1','synthetic_fixture')
    options=SchoolExportOptions().model_dump(mode='json');p=candidate['writing_provenance']
    p.update(school_export_options=deepcopy(options),school_export_options_sha256=digest(options))
    old_plan=compile_school_export(candidate,analysis,options)
    assert 'pagination_version' not in old_plan
    p['school_render_plan_sha256']=plan_digest(old_plan);old_plan=compile_school_export(candidate,analysis,options)
    original,receipt,proof=materialize(tmp_path,'owner','project',candidate,{},old_plan)
    assert proof['mapper_version']=='school-final-map-v1'
    p.update(school_final_render=proof,school_docx_sha256=proof['docx_sha256'],school_language_renderer=proof['docx_renderer_version']+':school-final-map-v1')
    original_candidate=deepcopy(candidate)
    def no_render(*args,**kwargs):raise AssertionError('Old approval must never be re-rendered by v2')
    monkeypatch.setattr('app.domain.manuscript_writing.school_render_cache.build_school_docx',no_render)
    monkeypatch.setattr('app.domain.manuscript_writing.school_render_cache.complete_school_fields',no_render)
    monkeypatch.setattr('app.adapters.pdf_renderer.renderer_identity',no_render)
    items,new_plan=inventory(candidate,{},[],analysis,options,cache=dict(root=tmp_path,owner='owner',project='project'),frozen=proof)
    assert candidate==original_candidate and 'pagination_version' not in new_plan
    assert [i['text'] for i in items]==[i['text'] for i in receipt['source_map']]
    assert read(tmp_path,'owner','project',proof,candidate=candidate,images={},plan=new_plan)[0]==original

def test_composite_document_image_id_retains_complete_owner_and_chapter_language():
    from io import BytesIO
    from hashlib import sha256
    from PIL import Image
    from app.domain.manuscripts.contracts import SchoolExportOptions
    from app.domain.manuscript_writing.school_language import inventory
    snapshot,bundle,output,analysis=fixture()
    candidate=compose_live_candidate(output,snapshot,bundle,'call','synthetic_fixture')
    identity='document-version:embedded:image-1'
    stream=BytesIO();Image.new('RGB',(3,2),'white').save(stream,format='PNG');png=stream.getvalue();image_sha=sha256(png).hexdigest()
    candidate['results_groups'][0]['figures']=[dict(id=identity,number=1,title='合成图',caption='合成图说明',source_ids=['run'],sha256=image_sha,panels=[])]
    owner=next(s for s in candidate['sections'] if s['purpose']=='results');owner['output_language']='zh-CN'
    next(c for c in candidate['thesis_context']['chapters'] if c['id']==owner['id'])['output_language']='zh-CN'
    row=dict(location='image:'+identity,kind='image',text='',content_sha256=digest(dict(sha=image_sha)),asset_sha256=image_sha,language_known=True,no_text=True)
    items,_=inventory(candidate,{identity:png},[row],analysis,SchoolExportOptions(include_toc=False).model_dump(mode='json'))
    item=next(i for i in items if i['kind']=='image')
    assert item['figure_id']==identity and item['chapter_id']==owner['id'] and item['target_language']=='zh-CN'
