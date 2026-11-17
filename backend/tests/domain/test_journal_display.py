from copy import deepcopy
from app.domain.manuscript_writing.contracts import SECTION_IDS
from app.domain.journals.display import defaults,plan,apply
from app.domain.manuscript_review.checks import check_snapshot

def referenced():
    snap=dict(schema_version=1,title='Synthetic',output_language='en',methods=[],results_groups=[],sources=[],references=[],issues=[],sections=[])
    bindings=[dict(project_reference_id='r'+str(n),review_id='review'+str(n),metadata_version_id='metadata'+str(n)) for n in (1,2)]
    snap['citation_snapshot']=dict(paragraphs=[dict(fragments=[dict(kind='claim',bindings=bindings)])])
    snap['references']=[dict(project_reference_id=b['project_reference_id'],number=n,text='Synthetic reference') for n,b in enumerate(bindings,1)]
    for sid in SECTION_IDS:
        p=dict(id=sid+':p',text='Synthetic',source_ids=[],citations=[],numeric_bindings=[],origin='user_provided')
        if sid in ('results','materials_and_methods'):
            n=0 if sid=='results' else 1;p.update(text='Supported finding ['+str(n+1)+'].',citations=[bindings[n]])
        snap['sections'].append(dict(id=sid,paragraphs=[p]))
    return snap

def test_display_reorder_cannot_hide_nonempty_nlm_first_occurrence_error():
    snap=referenced()
    assert not [i for i in check_snapshot(snap) if i['category']=='reference' and i['severity']=='error']
    display=defaults(snap);order=['title','abstract','introduction','materials_and_methods','results','discussion','references']
    altered=deepcopy(snap);altered['journal_display_context']=display|dict(order=order)
    assert any(i['category']=='reference' and i['severity']=='error' for i in check_snapshot(altered))
    rule=dict(id='order',source_id='guide',key='section_order',value=[display['names'][k] for k in order],status='known',quote='explicit order',location='line:1')
    result=plan(snap,dict(selected_requirements=[rule],conflicts=[]),[])
    assert result['actions']==[] and 'NLM' in result['unexecuted'][0]['reason']

def test_display_metadata_preserves_every_nonempty_reference_and_paragraph():
    snap=referenced();before=deepcopy(snap)
    output=apply(snap,[dict(key='body_font_size_pt',after=12)])
    assert snap==before
    assert {k:v for k,v in output.items() if k!='journal_display_context'}==before

def test_matching_default_style_is_not_an_executable_difference():
    snap=referenced()
    rule=dict(id='body',source_id='guide',key='body_font_size_pt',value=11,status='known',quote='Body font size: 11 pt',location='line:1')
    result=plan(snap,dict(selected_requirements=[rule],conflicts=[]),[])
    assert result['actions']==[] and not any(s['changed'] for s in result['sections'])

def test_synthetic_input_provenance_cannot_be_upgraded_by_real_guide():
    from app.domain.journals.display import synthetic_input
    assert synthetic_input(dict(writing_provenance=dict(provider_provenance='synthetic_fixture')))
    assert synthetic_input(dict(journal_adaptation_provenance=dict(synthetic=True)))
    assert synthetic_input(dict(sources=[dict(content=dict(engine=dict(id='synthetic_fixture')))]))


def test_narrative_review_adaptation_applies_word_styles_with_canonical_content_and_order():
    from io import BytesIO
    from docx import Document
    from app.adapters.manuscript_docx import build_manuscript_docx
    from app.domain.journals.format_rules import check_format
    from app.domain.manuscript_writing.article_contract import STRUCTURES

    snap = referenced()
    snap.update(
        article_type='narrative_review', notice='Synthetic review',
        writing_provenance=dict(schema_version=2, verification_status='scientific_and_language_reviewed'),
        sections=[
            dict(id=section, paragraphs=[dict(id=section + ':1', text=snap['title'] if section == 'title' else section,
                                               source_ids=[], citations=[], origin='user_provided')])
            for section in STRUCTURES['narrative_review']
        ],
    )
    style = dict(id='font', key='body_font_size_pt', value=12, status='known', source_id='guide')
    order = dict(id='order', key='section_order', value=['Thematic synthesis', 'Abstract'], status='known', source_id='guide')
    result = plan(snap, dict(selected_requirements=[style, order], conflicts=[]), [])
    assert [action['id'] for action in result['actions']] == ['font']
    assert [rule['key'] for rule in result['unexecuted']] == ['section_order']
    adapted = apply(snap, result['actions'])
    assert {key: value for key, value in adapted.items() if key != 'journal_display_context'} == snap
    assert adapted['journal_display_context']['order'] == list(STRUCTURES['narrative_review'])
    style_check = next(item for item in check_format(adapted, [style], [])['items'] if item['key'] == style['key'])
    assert style_check['status'] == 'pass'

    doc = Document(BytesIO(build_manuscript_docx(adapted, {})))
    headings = [p.text for p in doc.paragraphs if p.style.name == 'Heading 1']
    assert headings == ['Abstract', 'Scope and background', 'Literature sources and inclusion scope', 'Thematic synthesis',
                        'Synthesis and limitations', 'Conclusion', 'References']
    assert doc.styles['Normal'].font.size.pt == 12
