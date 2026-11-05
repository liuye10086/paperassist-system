"""Export rechecks structured provenance without rewriting frozen candidates."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.domain.manuscripts.contracts import SchoolExportOptions
from app.domain.manuscripts.school import school_content_report
from app.domain.manuscripts.service import ManuscriptService
from app.domain.research_results.fact_draft import compose
from tests.adapters.test_school_docx import fixture
from tests.domain.test_research_fact_projection_v2 import payload


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def prepared():
    school, analysis = fixture()
    context = school['thesis_context']
    for chapter in context['chapters']:
        if chapter['purpose'] == 'results': chapter['result_group_ids'] = ['research-results']
    frozen = payload(2)
    frozen.update(thesis_context=context, document_context=dict(delivery_id='delivery', document_kind='thesis'))
    for source in frozen['sources']:
        fact = source['content']['facts'][0]
        fact['locator'].update(field_path='summary.family.a123456.size', row_key={'row_key':'abc123def456'})
        fact['comparison'] = 'cluster 0 versus other clusters'
        source['content']['methods'][0]['description'] = 'Fixed filters[1].threshold: 1.'
    snapshot = compose(frozen)
    service = ManuscriptService.__new__(ManuscriptService)
    service.school_analysis = lambda db, version: analysis
    service.store = SimpleNamespace(require_task=lambda db, task_id: dict(
        task_type='research_fact_draft', input_snapshot={'payload':frozen}))
    return service, frozen, snapshot


def compile_plan(service, snapshot):
    version = dict(task_id='producer', snapshot_json=snapshot)
    return service.compile_school_intent(None, version, SchoolExportOptions(include_toc=False).model_dump(mode='json'))['plan']


def test_export_reconciles_only_exact_research_identity_and_parameter_markers():
    service, frozen, snapshot = prepared()
    before = deepcopy(snapshot)
    errors = [i for i in snapshot['school_content_report']['issues'] if i['severity']=='error']
    assert {i['category'] for i in errors} == {'numeric', 'reference'}
    plan = compile_plan(service, snapshot)
    assert plan['report']['can_export']
    assert snapshot == before == compose(frozen)


@pytest.mark.parametrize('change', ['numeric_text', 'reference_text', 'other_error'])
def test_export_keeps_actual_content_errors_blocking(change):
    service, _, snapshot = prepared()
    section = next(s for s in snapshot['sections'] if s['purpose']==('materials_and_methods' if change=='reference_text' else 'results'))
    if change == 'numeric_text': section['paragraphs'][0]['text'] += ' Additional result: 999.'
    elif change == 'reference_text': section['paragraphs'][0]['text'] += ' Unsupported reference [9].'
    if change != 'other_error': snapshot['school_content_report'] = school_content_report(snapshot)
    else: snapshot['school_content_report']['issues'].append(dict(id='unrelated',category='structure',location='other',message='Unrelated required correction',severity='error'))
    assert not compile_plan(service, snapshot)['report']['can_export']
