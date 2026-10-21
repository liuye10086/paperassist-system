from copy import deepcopy
import pytest
from app.domain.manuscript_writing.bundle import build_bundle
from app.domain.manuscript_writing.live_execution import compose_live_candidate,validate_live_candidate
from tests.domain.test_manuscript_writing_live_bundle import material

@pytest.fixture(autouse=True)
def postgres_schema():
    yield None

def fixture():
    base,request=material()
    evidence=dict(id='local-evidence',quote='Public exact quote reports 42 observations.',reading_scope='abstract')
    binding=dict(project_reference_id='local-reference',metadata=dict(title='Public synthetic reference',year='2020'),evidence=[evidence])
    base['citation_snapshot']=dict(paragraphs=[dict(id='old-claim',fragments=[dict(bindings=[binding])])])
    base['review_provenance']=dict(status='reviewed');base['review']=dict(status='reviewed')
    request['selected_evidence_ids']=['local-evidence'];request['keywords']=['explicit keyword'];request['acknowledgements']='Explicit acknowledgement'
    bundle=build_bundle(base,request);bundle['id']='bundle'
    snapshot=dict(input=request,base_snapshot=base,request_id='writing',base_version_id='base')
    output=dict(sections=[dict(id=s,paragraphs=[dict(id=s,text='Needs verification.',source_aliases=[],evidence_aliases=[],study_numeric_bindings=[])]) for s in ('title','abstract','introduction','results','discussion','materials_and_methods')])
    return snapshot,bundle,output

def test_exact_study_facts_and_literature_numeric_aliases_are_distinct_pending_bindings():
    snapshot,bundle,output=fixture();p=output['sections'][3]['paragraphs'][0]
    p.update(text='n=12',source_aliases=['s1'],study_numeric_bindings=[dict(source_alias='s1',fact_path='/statistics/n',value='12')])
    output['sections'][2]['paragraphs'][0].update(text='The published study reports 42 observations.',evidence_aliases=['e1'])
    candidate=compose_live_candidate(output,snapshot,bundle,'call','synthetic_fixture')
    assert candidate['sections'][2]['paragraphs'][0]['citations']==[]
    assert candidate['sections'][2]['paragraphs'][0]['suggested_evidence_aliases']==['e1']
    assert candidate['sources']==snapshot['base_snapshot']['sources']
    assert 'review_provenance' not in candidate
    assert candidate['review_history'][0]['applies_to_current_text'] is False
    assert candidate['keywords']==['explicit keyword']
    assert candidate['acknowledgements']=='Explicit acknowledgement'
    validate_live_candidate(candidate,snapshot,bundle)

def test_wrong_numeric_path_cannot_reuse_value_from_other_fact():
    snapshot,bundle,output=fixture();p=output['sections'][3]['paragraphs'][0]
    p.update(text='n=12',source_aliases=['s1'],study_numeric_bindings=[dict(source_alias='s1',fact_path='/statistics/coefficient',value='12')])
    with pytest.raises(ValueError): compose_live_candidate(output,snapshot,bundle,'call','synthetic_fixture')

def test_rewrite_keeps_non_target_sections_and_all_saved_facts():
    snapshot,bundle,output=fixture()
    original=compose_live_candidate(output,snapshot,bundle,'call','synthetic_fixture')
    snapshot['base_snapshot']=deepcopy(original);snapshot['input'].update(mode='rewrite_section',target_section='discussion')
    output={'sections':[deepcopy(output['sections'][4])]};output['sections'][0]['paragraphs'][0]['text']='A revised pending discussion.'
    candidate=compose_live_candidate(output,snapshot,bundle,'next-call','synthetic_fixture')
    assert candidate['sections'][:4]==original['sections'][:4]
    assert candidate['sections'][5:]==original['sections'][5:]
    assert candidate['sources']==original['sources']

def test_rewrite_cannot_reuse_paragraph_identity_from_non_target_section():
    snapshot,bundle,output=fixture()
    snapshot['base_snapshot']=compose_live_candidate(output,snapshot,bundle,'call','synthetic_fixture')
    snapshot['input'].update(mode='rewrite_section',target_section='discussion')
    rewritten=deepcopy(output['sections'][4]);rewritten['paragraphs'][0]['id']='title'
    with pytest.raises(ValueError): compose_live_candidate({'sections':[rewritten]},snapshot,bundle,'call','synthetic_fixture')


def notice_fixture(language='en',mode='full_draft'):
    snapshot,bundle,output=fixture()
    base=snapshot['base_snapshot'];snapshot['input'].update(output_language=language,mode=mode,target_section='discussion' if mode=='rewrite_section' else None)
    base['notice']='Local deterministic fact draft; Results and Materials and methods only.'
    base['issues']=[dict(id='scope',kind='limitation',field='scope',message=base['notice'],values=[]),
        dict(id='origin',kind='limitation',field='origin',message='Study data provenance requires separate confirmation.',values=[])]
    if mode=='rewrite_section':
        base['sections']=deepcopy(output['sections'])+[dict(id='references',paragraphs=[])]
        output=dict(sections=[deepcopy(output['sections'][4])])
    return snapshot,bundle,output


@pytest.mark.parametrize('language',['en','zh-CN'])
@pytest.mark.parametrize('mode',['full_draft','rewrite_section'])
@pytest.mark.parametrize('provider',['synthetic_fixture','openai_live'])
def test_new_candidate_notice_states_scope_provider_and_pending_science(language,mode,provider):
    snapshot,bundle,output=notice_fixture(language,mode);before=deepcopy(snapshot)
    candidate=compose_live_candidate(output,snapshot,bundle,'call',provider)
    expected_scope=('Full manuscript candidate' if mode=='full_draft' else 'Single-section rewrite candidate: Discussion') if language=='en' else ('完整稿候选' if mode=='full_draft' else '单章重写候选：讨论')
    expected_provider=('synthetic provider fixture' if provider=='synthetic_fixture' else 'OpenAI live response') if language=='en' else ('合成模型调用替身' if provider=='synthetic_fixture' else 'OpenAI真实调用回执')
    assert expected_scope in candidate['notice']
    assert expected_provider in candidate['notice']
    assert ('Scientific review pending' if language=='en' else '科学审核待完成') in candidate['notice']
    assert candidate['writing_provenance']['composition_version']==2
    assert candidate['issues'][0]['message']==candidate['notice']
    assert candidate['issues'][1:]==snapshot['base_snapshot']['issues'][1:]
    assert candidate['sources']==snapshot['base_snapshot']['sources']
    assert candidate['results_groups']==snapshot['base_snapshot']['results_groups']
    if mode=='rewrite_section':
        assert [s for s in candidate['sections'] if s['id']!='discussion']==[s for s in snapshot['base_snapshot']['sections'] if s['id']!='discussion']
    assert snapshot==before
    validate_live_candidate(candidate,snapshot,bundle)


def test_legacy_v2_candidate_rebuild_keeps_original_notice_issues_and_provenance():
    snapshot,bundle,output=notice_fixture()
    legacy=compose_live_candidate(output,snapshot,bundle,'call','synthetic_fixture',composition_version=1)
    assert 'composition_version' not in legacy['writing_provenance']
    assert legacy['notice']==snapshot['base_snapshot']['notice']
    assert legacy['issues']==snapshot['base_snapshot']['issues']
    before=deepcopy(legacy);validate_live_candidate(legacy,snapshot,bundle)
    assert legacy==before


@pytest.mark.parametrize('version',[0,3,True,'2'])
def test_candidate_composition_version_is_strict_and_cannot_be_ignored(version):
    snapshot,bundle,output=notice_fixture()
    candidate=compose_live_candidate(output,snapshot,bundle,'call','synthetic_fixture')
    candidate['writing_provenance']['composition_version']=version
    with pytest.raises(ValueError): validate_live_candidate(candidate,snapshot,bundle)
