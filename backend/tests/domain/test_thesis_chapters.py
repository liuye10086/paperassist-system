"""School structure reuses frozen facts, writing validation and material checks."""
from copy import deepcopy
import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def sample():
    source = dict(id='run', kind='analysis_run', role='computed_results', sha256='a'*64,
                  content=dict(statistics=dict(n=12)), file_id='research')
    paragraph = dict(id='results:run', text='n = 12', origin='computed_result', source_ids=['run'],
                     citations=[], numeric_bindings=[dict(value='12', source_id='run')])
    base = dict(schema_version=1, project_id='project', workflow_version='manuscript_fact_draft_v1',
                title='Provided research title', output_language='en', notice='Facts only',
                methods=[dict(id='methods:study_design', text='User supplied design', origin='user_provided',
                              source_ids=[], citations=[])],
                results_groups=[dict(id='evidence', title='Actual result', paragraphs=[paragraph], tables=[], figures=[])],
                references=[], citation_snapshot=None, issues=[], sources=[source])
    definitions = [('declaration','Declaration','manual'),('bibliography','Bibliography','references'),
                   ('background','Research context','introduction'),('procedure','Study process','materials_and_methods'),
                   ('outcomes','Observed findings','results'),('interpretation','Interpretation','discussion'),
                   ('closing','Closing observations','conclusion')]
    chapters = [dict(id=i, title=t, level=1, purpose=p, output_language='en',
                     result_group_ids=['evidence'] if p=='results' else []) for i,t,p in definitions]
    context = dict(schema_version=1, profile=dict(school='Actual school',revision=1),
                   template_version_id='template', confirmation_id='confirmation', confirmation_sha256='b'*64,
                   confirmation=dict(chapters=[{k:c[k] for k in ('id','title','level')} for c in chapters], rules=[], missing=[], unsupported=[]),
                   source_files=[dict(file_id='school-original',role='template',sha256='c'*64)], chapters=chapters)
    return base, context


def school():
    from app.domain.manuscripts.school import seed_school_snapshot
    return seed_school_snapshot(*sample())


def frozen(mode='full_draft', target=None, base=None):
    return dict(request_id='request', base_version_id='version', prompt_version='sci-writing-v1',
                policy_version='offline-only-v1',
                input=dict(base_revision=1,mode=mode,target_section=target,instructions='',keywords=[],acknowledgements=''),
                base_snapshot=base or school())


def output(snapshot):
    return dict(sections=[dict(id=s['id'],paragraphs=[{k:deepcopy(v) for k,v in p.items()
                            if k in ('id','text','source_ids','citations','numeric_bindings','origin')}
                            for p in s['paragraphs']]) for s in snapshot['base_snapshot']['sections']
                          if snapshot['input']['mode']=='full_draft' or s['id']==snapshot['input']['target_section']])


def test_school_order_roles_and_result_placement_preserve_shared_material():
    from app.domain.manuscripts.school import seed_school_snapshot
    base, context = sample(); old = deepcopy((base,context))
    result = seed_school_snapshot(base,context)
    assert (base,context)==old
    assert [s['id'] for s in result['sections']]==[c['id'] for c in context['chapters']]
    assert result['sections'][3]['paragraphs']==base['methods']
    assert result['sections'][4]['paragraphs']==base['results_groups'][0]['paragraphs']
    assert result['sections'][4]['result_group_ids']==['evidence']
    assert result['sources']==base['sources'] and result['results_groups']==base['results_groups']
    assert 'school-original' not in str(result['sources'])
    assert result['thesis_context']==context
    assert result['school_content_report']['scientifically_verified'] is False


@pytest.mark.parametrize('mutation',['duplicate_group','unknown_group','wrong_purpose','duplicate_chapter'])
def test_invalid_school_mapping_is_rejected_before_seed(mutation):
    from app.domain.manuscripts.school import seed_school_snapshot
    base,context=sample()
    if mutation=='duplicate_group': context['chapters'][2].update(purpose='results',result_group_ids=['evidence'])
    if mutation=='unknown_group': context['chapters'][4]['result_group_ids']=['alien']
    if mutation=='wrong_purpose': context['chapters'][4]['purpose']='manual'
    if mutation=='duplicate_chapter': context['chapters'][3]['id']='background'
    with pytest.raises(ValueError): seed_school_snapshot(base,context)


def test_dynamic_candidate_and_non_target_sections_use_frozen_school_ids():
    from app.domain.manuscript_writing.context import compose_candidate, validate_candidate
    snapshot=frozen(); candidate=compose_candidate(output(snapshot),snapshot)
    assert candidate['title']==snapshot['base_snapshot']['title']
    assert [s['title'] for s in candidate['sections']]==[s['title'] for s in snapshot['base_snapshot']['sections']]
    assert 'SCI' not in candidate['notice']
    validate_candidate(candidate,snapshot)
    rewrite=frozen('rewrite_section','interpretation',candidate); proposed=output(rewrite)
    proposed['sections'][0]['paragraphs'][0]['text']='Study interpretation requires review.'
    rewritten=compose_candidate(proposed,rewrite)
    assert rewritten['sections'][:5]==candidate['sections'][:5]
    assert rewritten['sections'][6:]==candidate['sections'][6:]
    assert rewritten['sections'][5]['paragraphs'][0]['id']==candidate['sections'][5]['paragraphs'][0]['id']


def test_manual_identity_or_signature_content_cannot_be_invented():
    from app.domain.manuscript_writing.context import compose_candidate
    snapshot=frozen(); result=output(snapshot)
    result['sections'][0]['paragraphs'][0]['text']='The author signed and approved this declaration.'
    with pytest.raises(ValueError): compose_candidate(result,snapshot)


def test_school_new_numerical_claims_keep_existing_exact_fact_gate():
    from app.domain.manuscript_writing.context import compose_candidate
    snapshot=frozen(); result=output(snapshot)
    result['sections'][6]['paragraphs'][0].update(text='n = 999',source_ids=['run'],numeric_bindings=[])
    with pytest.raises(ValueError): compose_candidate(result,snapshot)


def test_school_references_are_located_by_purpose_instead_of_seventh_index():
    from app.domain.manuscripts.school import seed_school_snapshot
    from app.domain.manuscript_writing.context import compose_candidate
    base,context=sample(); binding=dict(review_id='review',project_reference_id='ref',metadata_version_id='meta')
    base['references']=[dict(number=1,project_reference_id='ref',text='Verified reference')]
    base['citation_snapshot']=dict(output=dict(paragraphs=[dict(id='lit',text='Reviewed finding [1]')]),
        paragraphs=[dict(id='lit',fragments=[dict(kind='claim',bindings=[binding])])])
    snapshot=frozen(base=seed_school_snapshot(base,context)); result=output(snapshot)
    candidate=compose_candidate(result,snapshot)
    assert candidate['sections'][1]['paragraphs'][0]['text']=='Verified reference'
    assert candidate['references']==base['references']


def test_common_material_review_understands_school_structure_and_method_roles():
    from app.domain.manuscript_review.checks import check_snapshot
    from app.domain.manuscript_review.facts import relationships
    value=school(); issues=check_snapshot(value)
    assert not any(i['category']=='structure' and i['severity']=='error' for i in issues)
    assert relationships(value)['methods'][0]['id']=='methods:study_design'
    value['sections'][4]['title']='Silently changed heading'
    assert any(i['category']=='structure' and i['severity']=='error' for i in check_snapshot(value))


def test_school_prompt_does_not_request_sci_seven_parts():
    from app.domain.manuscript_writing.execution import writing_instructions
    instructions=writing_instructions(frozen())
    assert 'seven sections in exactly this order' not in instructions
    assert 'thesis_context' in instructions and 'manual' in instructions


@pytest.mark.parametrize('write_after_review',[False,True])
def test_explicit_review_precision_survives_school_report_and_unchanged_writing(write_after_review):
    from app.domain.manuscript_review.composition import compose
    value=school();value['sources'][0]['content']['statistics']['n']=12.345
    paragraph=value['sections'][4]['paragraphs'][0]
    paragraph.update(text='n = 12.345',numeric_bindings=[dict(value='12.345',source_id='run')])
    request=dict(base_revision=1,metadata=[dict(target_id='analysis_run:run:/statistics/n',field='display_precision',value='2',evidence='Explicit precision')],
                 corrections=[dict(paragraph_id='results:run',text='n = 12.35',source_ids=['run'],numeric_bindings=[dict(fact_id='analysis_run:run:/statistics/n',value='12.35')])])
    review=dict(input=request,base_snapshot=value,base_version_id='version',review_id='review',created_by='user',created_at='2026-10-21T00:00:00Z',source_state=dict(changes=[]),selected_sources=[])
    candidate,report=compose(review)
    assert report['can_publish'] is True
    if write_after_review:
        from app.domain.manuscript_writing.context import compose_candidate
        writing=frozen(base=candidate);candidate=compose_candidate(output(writing),writing)
    assert candidate['school_content_report']['can_publish'] is True
    assert not any(i['category']=='numeric' and i['severity']=='error' for i in candidate['school_content_report']['issues'])
    assert candidate['school_content_report']['scientifically_verified'] is False
