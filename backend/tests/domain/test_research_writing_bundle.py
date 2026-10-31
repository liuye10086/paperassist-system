"""Research values enter the existing exact numeric contract, never full sources."""
import json
from copy import deepcopy
import pytest
from app.domain.manuscript_writing.bundle import build_bundle
from app.domain.manuscript_writing.numeric_contract import validate_bindings


def source():
    return dict(kind='research_finding_version',id='finding',role='user_results',sha256='a'*64,label='fixed',locator={'kind':'object'},source_file_ids=['file'],content=dict(
        facts=[dict(id='fact',raw_value=27,display_value='27',unit='spots',observation_level='spot',comparison='',origin='public_reanalysis',verification_status='verified',source_id='processed',source_kind='bio_processed_dataset_version',source_sha256='b'*64,locator={'kind':'field','field_path':'counts.spots'},limitations=[])],
        methods=[],claims=[],conflicts=[],gaps=[],warnings=[],limitations=[],secret_path='C:\\private\\matrix.h5',email='identity@example.org'))


def base():
    return dict(schema_version=1,project_id='project',workflow_version='manuscript_fact_draft_v1',title='Study',output_language='en',sources=[source()],methods=[],results_groups=[],references=[],citation_snapshot=None,issues=[],notice='partial')


def request():
    return dict(mode='full_draft',target_section=None,output_language='en',instructions='',keywords=[],acknowledgements='',selected_source_ids=['finding'],selected_evidence_ids=[])


def test_bundle_projects_exact_research_values_and_excludes_raw_material():
    from app.domain.manuscript_writing.frozen import contract
    bundle=build_bundle(base(),request(),execution_contract=contract(schema_version=2));payload=json.loads(json.loads(bundle['wire_json'])['input'])
    value=payload['sources'][0]
    assert value['facts'][0]['fact_path']=='/facts/0/raw_value'
    assert value['facts'][0]['value']=='27'
    assert 'matrix.h5' not in bundle['wire_json'] and 'identity@example.org' not in bundle['wire_json']
    paragraph=dict(text='27 spots',source_aliases=['s1'],evidence_aliases=[],study_numeric_bindings=[dict(source_alias='s1',fact_path='/facts/0/raw_value',value='27')])
    assert validate_bindings(paragraph,payload)['study']
    paragraph['study_numeric_bindings'][0]['value']='28';paragraph['text']='28 spots'
    with pytest.raises(ValueError,match='Unknown exact study fact'):validate_bindings(paragraph,payload)


def test_review_facts_recognize_research_and_reject_wrong_numeric_binding():
    from app.domain.manuscript_review.facts import extract_facts
    from app.domain.manuscript_review.checks import check_snapshot
    frozen=base();facts=extract_facts(frozen)
    assert facts[0]['value']=='27'
    frozen['results_groups']=[dict(id='g',title='Results',tables=[],figures=[],paragraphs=[dict(id='p',text='28 spots',origin='computed_result',source_ids=['finding'],citations=[],numeric_bindings=[dict(fact_id=facts[0]['id'],value='28')])])]
    assert any(i['severity']=='error' and i['category']=='numeric' for i in check_snapshot(frozen))


def test_fact_composition_excludes_unresolved_assertions_and_preserves_other_sections():
    from app.domain.research_results.fact_draft import compose
    from app.domain.manuscript_writing.context import normalize_sections
    original=base();original['sections']=normalize_sections(original);original['sections'][2]['paragraphs']=[dict(id='manual',text='Keep exact\nbytes',origin='user_provided',source_ids=[],citations=[])]
    original['sources'][0]['content']['claims']=[dict(statement='This cures disease',origin='user_text',review_decision='adopt')]
    original['sources'][0]['content']['conflicts']=[dict(id='conflict',fact_ids=['fact','other'],decision='unresolved')]
    result=compose(dict(project_id='project',output_language='en',base_snapshot=original,sources=original['sources'],selected_source_ids=['finding'],sections=['results'],manual_notes='',thesis_context=None,document_context={'delivery_id':'delivery','document_kind':'sci'}))
    assert result['sections'][2]==original['sections'][2]
    assert result['results_groups'][0]['paragraphs']==[]
    assert result['research_claims'][0]['origin']=='user_text' and result['research_gaps']
    assert 'cures' not in str([s['paragraphs'] for s in result['sections']])


def test_numeric_tsv_strings_and_method_parameters_remain_exact():
    from app.domain.manuscripts.research_sources import numeric
    from app.domain.research_results.fact_draft import compose
    fixed=source();fixed['content']['facts'][0]['raw_value']='1.20e-05';fixed['content']['facts'][0]['display_value']='1.20e-05'
    fixed['content']['facts'][0]['locator']={'kind':'row','row_key':{'feature_id':'GENE'},'column':'p_value','table':'markers'}
    fixed['content']['facts'][0]['comparison']='NPC vs other regions'
    fixed['content']['methods']=[dict(id='method',title='Normalization',description='Completed',executed=True,parameters={'target_sum':10000},software={'engine_version':'fixed'})]
    assert next(numeric(fixed))['value']=='1.20e-05'
    result=compose(dict(project_id='project',output_language='en',base_snapshot=None,sources=[fixed],selected_source_ids=['finding'],sections=['results','materials_and_methods'],manual_notes='',thesis_context=None,document_context={'delivery_id':'delivery','document_kind':'sci'}))
    assert 'p_value' in result['results_groups'][0]['paragraphs'][0]['text']
    assert 'GENE' in result['results_groups'][0]['paragraphs'][0]['text'] and 'NPC vs other regions' in result['results_groups'][0]['paragraphs'][0]['text']
    assert '10000' in result['methods'][0]['text']


def test_initial_school_methods_only_does_not_fill_results():
    from app.domain.research_results.fact_draft import compose
    chapters=[dict(id='m',title='Methods',level=1,purpose='materials_and_methods',output_language='en',result_group_ids=[]),dict(id='r',title='Results',level=1,purpose='results',output_language='en',result_group_ids=['research-results'])]
    context=dict(chapters=chapters,confirmation=dict(chapters=[{k:c[k] for k in ('id','title','level')} for c in chapters]))
    result=compose(dict(project_id='project',output_language='en',base_snapshot=None,sources=[source()],selected_source_ids=['finding'],sections=['materials_and_methods'],manual_notes='',thesis_context=context,document_context={'delivery_id':'delivery','document_kind':'thesis'}))
    assert result['results_groups'][0]['paragraphs']==[]
    assert result['sections'][1]['paragraphs'][0]['id'].endswith(':pending')


def test_replacing_results_retains_school_manual_export_inputs_without_old_approval():
    from app.domain.research_results.fact_draft import compose
    from app.domain.manuscripts.service import ManuscriptService
    from app.domain.manuscripts.contracts import SchoolExportOptions
    original=base();chapters=[dict(id='manual',purpose='manual')]
    original['thesis_context']={'chapters':chapters,'confirmation':{}}
    original['sections']=[dict(id='manual',purpose='manual',paragraphs=[{'text':'Keep declaration'}])]
    options=SchoolExportOptions(manual_chapters=[dict(chapter_id='manual',text='Signed declaration retained')]).model_dump(mode='json')
    original['writing_provenance']={'language_review_id':'old-approved','school_export_options':options}
    result=compose(dict(project_id='project',output_language='en',base_snapshot=original,sources=[source()],selected_source_ids=['finding'],sections=['results'],manual_notes='',thesis_context=original['thesis_context'],document_context={'delivery_id':'delivery','document_kind':'thesis'}))
    assert 'writing_provenance' not in result and result['sections']==original['sections']
    effective=ManuscriptService.school_options(None,{'snapshot_json':result},{})
    assert effective['manual_chapters']==options['manual_chapters']
