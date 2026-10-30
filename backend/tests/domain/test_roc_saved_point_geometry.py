"""Saved ROC ties must keep their AUC and remain eligible for explanation reuse."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.domain.figure_workbench import explanations, presentation, prompts


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


@pytest.mark.parametrize('filename', [
    'a07372c8-318d-4fe2-8c8d-ce7db6b53189.json',
    'ef3611e3-298d-48a7-92fc-cf41045a58dc.json',
])
def test_tied_roc_contract_preserves_statistics_and_explanation_input(filename):
    folder = Path(__file__).resolve().parents[1] / 'fixtures/figure_b07/old-v4-bundles-native-order'
    old = json.loads((folder / filename).read_bytes())['bundle']
    pristine = deepcopy(old)
    frozen = old['projection']['result']['_material']
    payload = deepcopy(frozen['payload'])
    suffix = ' '.join(payload.pop('presentation')['statistical_notes'])
    if suffix:
        assert payload['labels']['caption'].endswith(' ' + suffix)
        payload['labels']['caption'] = payload['labels']['caption'][:-len(' ' + suffix)]
    payload, expected = presentation.enrich_material(
        payload, deepcopy(frozen['expected']), config=old['configuration']['config'],
        result=old['result'], projection=old['projection']['result'], fields={}, contract=4,
    )
    points = old['figure']['statistics']['points']
    pairs = list(zip(points, points[1:]))
    linear = sum((b['fpr'] - a['fpr']) * (a['tpr'] + b['tpr']) / 2 for a, b in pairs)
    stairs = sum((b['fpr'] - a['fpr']) * a['tpr'] for a, b in pairs)
    assert linear == pytest.approx(old['figure']['statistics']['auc'])
    assert linear != pytest.approx(stairs)
    text = prompts.instructions_for(payload)
    assert 'diagonal segment' in text and 'corners absent from the threshold points' in text
    new = deepcopy(old)
    new['figure'].update(expected)
    new['figure']['engine']['id'] = 'openai_figure_workbench_v4'
    new['configuration']['figure_contract'] = 4
    assert new['figure']['statistics'] == old['figure']['statistics']
    assert explanations.build_payload(old, version='figure_explanation_v5') == explanations.build_payload(new, version='figure_explanation_v5')
    assert old == pristine
