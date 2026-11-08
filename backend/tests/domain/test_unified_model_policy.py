"""Current model selection must not relabel historical frozen writing requests."""
from copy import deepcopy
import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    # These policy/contract tests do not use a database or provider connection.
    yield None


def historical_writing_contract(**kwargs):
    from app.domain.manuscript_writing.frozen import contract
    value = contract(**kwargs)
    value['policy']['model'] = value['policy']['price']['model'] = 'gpt-5.4-2026-03-05'
    value['policy']['price'].update(version='openai-standard-2026-10-21',
        input_micro_usd_per_million=2500000,cached_input_micro_usd_per_million=250000,
        output_micro_usd_per_million=15000000,cache_write_micro_usd_per_million=None)
    return value


def test_new_writing_uses_requested_model_and_its_standard_prices():
    from app.domain.manuscript_writing.policy import installed_policy
    from app.domain.manuscript_writing.frozen import contract
    value = installed_policy()
    assert value.model == value.price.model == 'gpt-6.1-sol'
    assert value.price.input_micro_usd_per_million == 2_000_000
    assert value.price.cached_input_micro_usd_per_million == 100_000
    assert value.price.output_micro_usd_per_million == 10_000_000
    assert value.price.cache_write_micro_usd_per_million == 2_500_000
    assert contract()['policy'] == value.model_dump(mode='json')


def test_catalog_offers_only_current_model_and_matching_business_constraints(monkeypatch):
    from app.domain.admin_configuration import catalog
    monkeypatch.setattr(catalog, 'local_config', lambda: {})
    value = catalog.metadata()
    assert value['installed']['models'] == ['gpt-6.1-sol']
    for name in ('writing', 'recommendation', 'literature'):
        assert value['installed']['business_constraints'][name]['model'] == 'gpt-6.1-sol'


def test_recommendation_accepts_current_model_and_keeps_legacy_snapshot_readable():
    from app.domain.analysis_recommendation.policy import validate_execution_policy
    for model in ('gpt-6.1-sol', 'gpt-5.6-sol'):
        value = dict(policy=dict(model=model, prompt_version='analysis_recommendation_v1',
            output_format='analysis_recommendation_v1', max_output_tokens=2000,
            price=dict(version='synthetic',model=model,input_micro_usd_per_million=10,
                cached_input_micro_usd_per_million=1,output_micro_usd_per_million=20)),
            input_token_allowance=12000,task_limit_micro_usd=500000)
        before = deepcopy(value)
        assert validate_execution_policy(value)['policy']['model'] == model
        assert value == before


def test_historical_writing_policy_and_legacy_bundle_keep_original_model_and_price():
    from app.domain.manuscript_writing.frozen import validate, bundle_contract
    old = historical_writing_contract()
    before = deepcopy(old)
    assert validate(old)['policy'] == old['policy']
    bundle = {'policy_json': deepcopy(old['policy'])}
    assert bundle_contract(bundle)['policy'] == old['policy']
    assert old == before and bundle == {'policy_json': before['policy']}


def test_historical_bundle_without_execution_contract_rebuilds_from_saved_policy():
    from app.domain.manuscript_writing.bundle import build_bundle, validate_bundle
    from tests.domain.test_manuscript_writing_live_bundle import material
    base, request = material()
    bundle = build_bundle(base, request, execution_contract=historical_writing_contract())
    bundle.pop('execution_contract')
    row = dict(bundle, base_snapshot=base, request_json=request)
    before = deepcopy(row)
    assert validate_bundle(row) == before
    assert row == before


@pytest.mark.parametrize('model', ['gpt-6.1-sol', 'gpt-5.4-2026-03-05'])
def test_frozen_writing_wire_retains_its_model_when_defaults_change(model):
    from app.domain.manuscript_writing import policy
    from app.domain.manuscript_writing.bundle import build_bundle
    from app.domain.manuscript_writing.frozen import contract, validate_wire
    from tests.domain.test_manuscript_writing_live_bundle import material
    base, request = material()
    frozen = contract()
    frozen['policy']['model'] = frozen['policy']['price']['model'] = model
    bundle = build_bundle(base, request, execution_contract=frozen)
    assert json.loads(bundle['wire_json'])['model'] == model
    assert validate_wire(bundle['wire_json'], frozen).model == model
    assert policy.installed_policy().model == 'gpt-6.1-sol'


@pytest.mark.parametrize('name', ['analysis-recommendation-policy.example.json',
    'explanation-policy.example.json', 'plot-policy.example.json'])
def test_new_deployment_examples_use_the_requested_model(name):
    root = Path(__file__).resolve().parents[2]
    policy = json.loads((root/name).read_text(encoding='utf-8'))['policy']
    assert policy['model'] == policy['price']['model'] == 'gpt-6.1-sol'
