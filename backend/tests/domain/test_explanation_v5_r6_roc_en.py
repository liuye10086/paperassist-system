from copy import deepcopy
import json
from pathlib import Path
import pytest
from app.core.exceptions import PlotError
from app.domain.figure_workbench.explanation_v5 import validate_draft_v5, sentence_draft_v5

F=json.loads((Path(__file__).parents[1]/'fixtures/figure_b07/real-v5-response-roc-en.json').read_text(encoding='utf8'))

@pytest.fixture(autouse=True)
def postgres_schema():yield None

def check(text,payload=None):
    payload=payload or F['payload']; draft=sentence_draft_v5(payload);draft['results']+=' '+text
    validate_draft_v5(draft,payload)

def test_original_full_roc():validate_draft_v5(F['draft'],F['payload'])

@pytest.mark.parametrize('text',[
    'Causal interpretation is restricted because {{limitation.5}}.',
    'Observation independence remains qualified by {{limitation.4}}.',
    'Independence is qualified by {{limitation.4}}.',
    'These counts describe data records rather than verified independent participants.',
    'Score direction is specified as {{modeling.direction}}.',
    'The analysis reports {{modeling.auc}}, with score direction specified as {{modeling.direction}}.',
    'The analysis applies {{method.summary}}.',
    'The saved results carry the warnings {{modeling.warnings}}.',
    'Research context remains subject to {{limitation.8}}.',
    'Local checking does not remove the review requirements in {{limitation.8}}.',
    'The horizontal axis displays {{axis.x.label}}, with unit {{axis.x.unit}}.',
    'The saved area under the curve is {{modeling.auc}}.',
    'The saved analysis reports an original statistical record count of {{modeling.n}}.',
])
def test_valid_variants(text):check(text)

@pytest.mark.parametrize('text',[
    'Causal interpretation is established because {{limitation.5}}.',
    'Causal interpretation is restricted because {{limitation.5}}, and treatment effectiveness is established.',
    'Causal interpretation is restricted because {{limitation.4}}.',
    'Observation independence is confirmed by {{limitation.4}}.',
    'Observation independence remains qualified by {{limitation.2}}.',
    'These counts describe verified independent participants.',
    'These counts describe data records rather than verified independent participants, and participant independence is confirmed.',
    'Score direction is specified as {{modeling.auc}}.',
    'Score direction is higher and clinically validated.',
    'The sample contains a score of participants.',
    'The horizontal axis displays.',
    'The analysis applies.',
    'The saved carry: {{modeling.warnings}}.',
    'The analysis applies regression and establishes causation.',
    'Local checking does not remove the review requirements and proves clinical utility.',
    'Causation is confirmed; independence is qualified by {{limitation.4}}.',
    'The saved area under the curve is {{modeling.n}}.',
    'The saved weighted area under the curve is {{modeling.auc}}.',
    'The analysis reports an original statistical record count of {{modeling.positive_n}}.',
])
def test_harmful_neighbours(text):
    with pytest.raises(PlotError):check(text)

@pytest.mark.parametrize('ref,changes,text',[
    ('modeling.direction',{'raw':''},'Score direction is specified as {{modeling.direction}}.'),
    ('modeling.direction',{'value':''},'Score direction is specified as {{modeling.direction}}.'),
    ('modeling.direction',{'raw':'unknown'},'Score direction is specified as {{modeling.direction}}.'),
    ('limitation.5',{'raw':''},'Causal interpretation is restricted because {{limitation.5}}.'),
    ('limitation.4',{'value':''},'Independence is qualified by {{limitation.4}}.'),
])
def test_bad_bound_facts(ref,changes,text):
    p=deepcopy(F['payload']);p['facts'][ref].update(changes)
    with pytest.raises(PlotError):check(text,p)

@pytest.mark.parametrize('text',[
    'Causal interpretation is restricted because {{limitation.5}}; treatment effectiveness is confirmed.',
    'Treatment efficacy is established.',
])
def test_m1_unsupported_therapeutic_assertion(text):
    with pytest.raises(PlotError):check(text)

@pytest.mark.parametrize('text',[
    'Causal interpretation is restricted because {{limitation.5}}; treatment effectiveness is not confirmed.',
    'Treatment efficacy remains subject to {{limitation.5}}.',
])
def test_m1_negative_or_fact_bound_meta_does_not_assert_efficacy(text):check(text)
