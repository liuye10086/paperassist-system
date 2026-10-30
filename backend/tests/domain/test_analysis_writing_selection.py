import json
import pytest
from app.domain.manuscripts.contracts import SourceSelection
from app.domain.manuscript_writing.bundle import build_bundle

@pytest.fixture(autouse=True)
def postgres_schema():yield None

@pytest.mark.parametrize('kind',['analysis_report','collection_report'])
def test_saved_analysis_report_has_narrow_noncomputed_role(kind):
    source=SourceSelection(kind=kind,id='report',file_id='file',role='user_results')
    assert source.kind==kind
    for role in ('computed_results','methods','literature','image_observation'):
        with pytest.raises(ValueError):SourceSelection(kind=kind,id='report',file_id='file',role=role)

def test_report_text_is_projected_but_never_becomes_numeric_facts_or_private_metadata():
    base=dict(title='User title',output_language='en',sources=[dict(id='report',kind='analysis_report',role='user_results',download_url='/private/download',content=dict(text='Saved report text 12',text_truncated=False,report={'id':'secret-report-identity'},input_sha256='a'*64))],methods=[],results_groups=[])
    bundle=build_bundle(base,dict(mode='full',target_section=None,output_language='en',instructions='',keywords=[],acknowledgements='',selected_source_ids=['report'],selected_evidence_ids=[]))
    source=json.loads(json.loads(bundle['wire_json'])['input'])['sources'][0]
    assert source['report_text']=='Saved report text 12'
    assert source['facts']==[]
    assert 'private' not in bundle['wire_json'] and 'secret-report-identity' not in bundle['wire_json']

def test_explicit_history_filters_only_setup_change_and_report_retains_all_child_files():
    from app.domain.manuscripts.sources import writing_changes
    from app.domain.file_lifecycle.references import file_ids,frozen_references
    from types import SimpleNamespace
    change=dict(kind='analysis_run',id='A',reasons=['analysis_configuration_changed'])
    source=dict(kind='analysis_run',id='A')
    service=SimpleNamespace(source_changes=lambda *_:[change])
    assert writing_changes(service,'project',dict(sources=[source]))==[change]
    assert writing_changes(service,'project',dict(sources=[source],analysis_handoff_run_ids=['A']))==[]
    for reasons in (['source_changed'],['analysis_configuration_changed','source_changed'],['source_unavailable_or_changed']):
        change['reasons']=reasons
        assert writing_changes(service,'project',dict(sources=[source],analysis_handoff_run_ids=['A']))==[change]
    report=dict(kind='collection_report',id='report',file_id='anchor',content=dict(collection_report_id='report',report_id='report',items=[dict(file_id='anchor',analysis_run_id='A'),dict(file_id='other',analysis_run_id='B')]))
    assert file_ids(dict(sources=[report]))=={'anchor','other'}
    refs=set(frozen_references(dict(sources=[report])))
    assert {('collection_reports','report'),('analysis_runs','A'),('analysis_runs','B')}<=refs and ('reports','report') not in refs
