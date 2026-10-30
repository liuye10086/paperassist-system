"""Original line English response; closed coordinate/population identities."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from app.core.exceptions import PlotError
from app.domain.figure_workbench import explanations as e
from app.domain.figure_workbench.explanation_v5 import validate_draft_v5,sentence_draft_v5

F=json.loads((Path(__file__).parents[1]/'fixtures/figure_b07/real-v5-response-line-en.json').read_text(encoding='utf8'))

@pytest.fixture(autouse=True)
def postgres_schema():yield None

def check(text,payload=None):
    payload=payload or F['payload'];draft=sentence_draft_v5(payload);draft['results']+=' '+text
    validate_draft_v5(draft,payload)

@pytest.mark.parametrize('section',F['draft'])
def test_original_line_each_complete_section(section):
    draft=sentence_draft_v5(F['payload']);draft[section]=F['draft'][section]
    validate_draft_v5(draft,F['payload'])

def test_original_line_complete_render_saved_and_exact_frozen_input():
    from app.domain.model_usage.gateway import input_digest
    payload=e.build_payload(F['bundle'])
    assert payload==F['payload'] and e.instructions_for(payload)==F['instructions']
    assert input_digest(instructions=F['instructions'],payload=payload)==F['model_input_digest']
    value=e.render(F['bundle'],F['draft'],{'model_call_id':'offline-r5-line','response_id':F['source_response_id']})
    assert e.validate_saved(F['bundle'],value)==value and value['draft']==F['draft']
    for section in value['sections']:
        for item in section['evidence']:
            fact=payload['facts'][item['key']]
            assert item=={'key':item['key'],'label':fact['label'],'value':fact['value']}
            assert fact['label']+': '+fact['value'] in section['text']

@pytest.mark.parametrize('text',[
    'This figure follows {{method.summary}}.',
    'Review of meaning and applicability must account for {{limitation.8}}.',
    'The saved projection results report the complete ordered coordinates and their valid and missing record counts as {{projection.0.coordinates}}.',
    'The saved results report the complete ordered coordinates as {{projection.0.coordinates}}.',
    'The original statistical record count is {{data.original_n}}, which is reported separately from the projection record counts rather than as an independent participant count.',
    'The distinction between statistical records, projection records and independent participants is governed by {{limitation.1}}.',
])
def test_normal_finite_prose_and_bound_population_caveats(text):check(text)

@pytest.mark.parametrize('text',[
    'The saved follow: {{method.summary}}.',
    'The saved account: {{limitation.8}}.',
    'This figure follows.',
    'The results must account for.',
    'The results are governed by.',
    'The saved projection results report the complete ordered coordinates and their valid and missing record counts as {{data.valid}}.',
    'The saved results report the complete ordered coordinates as {{data.original_n}}.',
    'The original statistical record count is {{data.valid}}, which is reported separately from the projection record counts rather than as an independent participant count.',
    'The original statistical record count is {{data.original_n}}, which confirms independence rather than as an independent participant count.',
    'The distinction between statistical records, projection records and independent participants is governed by {{limitation.7}}.',
    'The distinction between statistical records, projection records and verified independent participants is governed by {{limitation.1}}.',
    'Independence is verified and the distinction between statistical records, projection records and independent participants is governed by {{limitation.1}}.',
    'The distinction between statistical records, projection records and independent participants is governed by {{limitation.3}}.',
    'This figure follows {{method.summary}}, which proves causation.',
    'The saved results report weighted complete ordered coordinates as {{projection.0.coordinates}}.',
])
def test_wrong_metric_scope_or_affirmative_and_fragment_remains_rejected(text):
    with pytest.raises(PlotError):check(text)

@pytest.mark.parametrize('value,raw', [('', ''), ('Independent participant counts need not equal projection records',''), ('Causation cannot be inferred','Causation cannot be inferred')])
def test_population_distinction_requires_nonempty_specific_limit(value,raw):
    payload=deepcopy(F['payload']);payload['facts']['limitation.1'].update(value=value,raw=raw)
    with pytest.raises(PlotError):check('The distinction between statistical records, projection records and independent participants is governed by {{limitation.1}}.',payload)

@pytest.mark.parametrize('expired',[False,True])
def test_original_line_known_receipt_worker_stays_get_only(monkeypatch,expired):
    from tests.domain import test_explanation_v5_receipt_recovery as recovery
    monkeypatch.setattr(recovery,'FIXTURE',F)
    recovery.test_existing_worker_retrieves_same_receipt_without_reserving_or_posting(monkeypatch,expired)
