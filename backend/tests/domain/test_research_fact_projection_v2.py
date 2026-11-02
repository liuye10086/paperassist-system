"""Exact fact/method carrier de-duplication, preserving historical composition."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.domain.research_results.fact_draft import compose
from app.domain.bioinformatics.contracts import digest
from tests.domain.test_research_writing_bundle import source


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def payload(version=None):
    finding=source()
    finding['content']['methods']=[dict(id='same-method',title='Fixed method',description='Completed',executed=True,
        parameters={'target_sum':10000},software={'engine_version':'fixed'},
        source={'source_kind':'bio_insight_result_version','source_id':'origin','sha256':'c'*64,'locator':{'kind':'object'}})]
    report=deepcopy(finding);report.update(id='report',kind='research_report_version',sha256='d'*64)
    body=dict(project_id='project',output_language='en',base_snapshot=None,sources=[finding,report],selected_source_ids=['finding','report'],
        sections=['results','materials_and_methods'],manual_notes='',thesis_context=None,document_context={'delivery_id':'delivery','document_kind':'sci'})
    if version is not None:body['fact_projection_version']=version
    return body


def test_old_payload_keeps_original_candidate_bytes():
    old=compose(payload())
    assert len(old['results_groups'][0]['paragraphs'])==2 and len(old['methods'])==2
    assert 'fact_projection_version' not in old['research_bridge']
    assert digest(old)=='5419e3f8922c8918e41a057cc2760c841603176904bf1516d819dc76d852afa1'


def test_v2_combines_only_exact_fact_and_method_with_all_carrier_sources():
    body=payload(2);before=deepcopy(body);candidate=compose(body)
    paragraphs=candidate['results_groups'][0]['paragraphs']
    assert len(paragraphs)==1 and len(candidate['methods'])==1
    assert paragraphs[0]['source_ids']==candidate['methods'][0]['source_ids']==['finding','report']
    assert paragraphs[0]['research_fact']==body['sources'][0]['content']['facts'][0]
    assert paragraphs[0]['numeric_bindings']==[dict(source_id='finding',fact_id='research_finding_version:finding:/facts/0/raw_value',value='27')]
    assert candidate['sources']==body['sources'] and body==before
    assert candidate['research_bridge']['fact_projection_version']==2


@pytest.mark.parametrize('mutation',['locator','value','fact_id','source_id','method_id'])
def test_v2_preserves_distinct_complete_fact_or_method_records(mutation):
    body=payload(2);content=body['sources'][1]['content']
    if mutation=='locator':content['facts'][0]['locator']['field_path']='counts.other_spots'
    if mutation=='value':content['facts'][0].update(raw_value=28,display_value='28')
    if mutation=='fact_id':content['facts'][0]['id']='another-fact'
    if mutation=='source_id':content['facts'][0]['source_id']='another-origin'
    if mutation=='method_id':content['methods'][0]['id']='distinct-method-with-same-settings'
    candidate=compose(body)
    assert len(candidate['results_groups'][0]['paragraphs'])==(1 if mutation=='method_id' else 2)
    assert len(candidate['methods'])==(2 if mutation=='method_id' else 1)


def test_new_handoff_freezes_v2_projection(monkeypatch):
    from app.domain.research_results import handoff
    service=handoff.ResearchHandoffService.__new__(handoff.ResearchHandoffService)
    service.assets=object();service.store=SimpleNamespace(user_id='owner')
    monkeypatch.setattr(handoff,'require_phase',lambda *args:None)
    monkeypatch.setattr(handoff,'resolve_document_context',lambda *args,**kwargs:dict(delivery_id='delivery',document_kind='sci'))
    monkeypatch.setattr(handoff,'ManuscriptService',lambda *args:object())
    monkeypatch.setattr(handoff,'ResearchSourceReader',lambda *args:SimpleNamespace(_read_source_in_phase=lambda *args,**kwargs:source()))
    monkeypatch.setattr(handoff,'project_source',deepcopy)
    request=SimpleNamespace(delivery_id='delivery',manuscript_id=None,expected_revision=0,finding_version_ids=['finding'],figure_version_ids=[],
        report_version_ids=[],thesis=None,output_language='en',sections=['results','materials_and_methods'],manual_notes='')
    result=service._freeze_in_phase.__wrapped__(service,None,'project',request,phase=object())
    assert result['fact_projection_version']==2
