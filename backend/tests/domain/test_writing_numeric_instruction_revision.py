"""Pure projection and numeric checks; no provider, database, or raw rewriting."""
from copy import deepcopy
import hashlib
import json
import re
from types import SimpleNamespace

import pytest

from app.domain.manuscript_writing.bundle import build_bundle, validate_bundle
from app.domain.manuscript_writing.frozen import contract, validate, validate_wire
from app.domain.manuscript_writing.numeric_contract import validate_bindings
from app.domain.manuscript_writing.numeric_review import numbers, value as numeric_value
from app.domain.manuscripts.illustrations import BODY_REFERENCE
from tests.domain.test_writing_numeric_contract_v2 import new_fixture


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def test_new_numeric_request_selects_explicit_guidance_and_rebuilds():
    snapshot, bundle, _ = new_fixture()
    assert bundle['execution_contract'].get('instruction_revision') == 'numeric2-exact-v1'
    wire = json.loads(bundle['wire_json'])
    # Execute the check given to the generator against separately authored cases.
    check = re.search(r'```python\n(.*?)\n```', wire['instructions'], re.S).group(1)
    payload = json.loads(wire['input'])
    binding = dict(source_alias='c1', fact_path='/numbers/4', value='-1')
    study = dict(source_alias='s1', fact_path='/statistics/coefficient', value='0.123456789')
    cases = [
        (dict(text='n−1 and (n-1)p; Figure 1.', study_numeric_bindings=[binding]), True),
        (dict(text='n−1.', study_numeric_bindings=[]), False),
        (dict(text='A qualitative comparison.', study_numeric_bindings=[study]), False),
        (dict(text='The coefficient is 0.123456789.', study_numeric_bindings=[study]), True),
    ]
    for paragraph, passes in cases:
        paragraph.update(source_aliases=['s1'], evidence_aliases=[])
        scope = dict(paragraph=paragraph, numbers=numbers, BODY_REFERENCE=BODY_REFERENCE,
                     numeric_value=numeric_value)
        if passes:
            exec(check, scope)
            validate_bindings(paragraph, payload)
        else:
            with pytest.raises(AssertionError):
                exec(check, scope)
            with pytest.raises(ValueError, match='Unbound or extraneous'):
                validate_bindings(paragraph, payload)
    validate_wire(bundle['wire_json'], bundle['execution_contract'])
    validate_bundle(dict(bundle, base_snapshot=snapshot['base_snapshot'], request_json=snapshot['input']))


def test_legacy_numeric_contract_dump_and_wire_stay_exact():
    snapshot, new_bundle, _ = new_fixture()
    old_contract = deepcopy(new_bundle['execution_contract'])
    old_contract.pop('instruction_revision', None)
    assert validate(old_contract) == old_contract
    old = build_bundle(snapshot['base_snapshot'], snapshot['input'], execution_contract=old_contract)
    assert old['wire_sha256'] == '8dec2bd85db80d9058ac69919ce204284a24577654c338e16d6adf168363e470'
    assert hashlib.sha256(old['wire_json'].encode()).hexdigest() == old['wire_sha256']
    assert old['wire_json'] != new_bundle['wire_json']
    validate_wire(old['wire_json'], old_contract)
    assert old['policy_json'] == new_bundle['policy_json']
    assert json.loads(old['wire_json'])['input'] == json.loads(new_bundle['wire_json'])['input']
    assert json.loads(old['wire_json'])['text'] == json.loads(new_bundle['wire_json'])['text']
    assert {k: v for k, v in new_bundle['execution_contract'].items() if k != 'instruction_revision'} == old_contract


def test_revision_is_finite_and_other_contracts_keep_existing_serialization():
    for version in (1, 3):
        assert 'instruction_revision' not in contract(schema_version=version)
    bad = contract(schema_version=2)
    bad['instruction_revision'] = 'unknown'
    with pytest.raises(ValueError):
        validate(bad)


@pytest.mark.parametrize('revision', [None, 'numeric2-exact-v1'])
def test_configured_bundle_reads_rebuild_its_frozen_revision(monkeypatch, revision):
    from app.domain.manuscript_writing import authorization
    snapshot, seed, _ = new_fixture()
    frozen = dict(seed['execution_contract'], origin='configuration')
    if revision is None:
        frozen.pop('instruction_revision', None)
    else:
        frozen['instruction_revision'] = revision
    bundle = build_bundle(snapshot['base_snapshot'], snapshot['input'], execution_contract=frozen)
    config = dict(bundle=dict(models=dict(writing=dict(execution=dict(
        policy=frozen['policy'], input_token_allowance=frozen['max_input_allowance'],
        task_limit_micro_usd=frozen['task_limit_micro_usd'])), batch_max_posts=frozen['batch_max_posts'],
        max_corrections=frozen['max_corrections'], batch_cap_micro_usd=frozen['batch_cap_micro_usd']),
        prompts=dict(writing_instruction=frozen['instruction'])))
    saved = dict(bundle, base_snapshot=snapshot['base_snapshot'], request_json=snapshot['input'])
    row = dict(id='fixture', project_id='project', bundle_json=saved)
    # A local value object returns one fixture row; no database driver is called.
    db = SimpleNamespace(execute=lambda *args: SimpleNamespace(fetchone=lambda: row))
    service = authorization.LiveWritingService.__new__(authorization.LiveWritingService)
    service.store = SimpleNamespace(require_project=lambda *args: None, user_id='fixture-user')
    monkeypatch.setattr(authorization, 'resolve', lambda *args, **kwargs: config)
    restored = service.bundle(db, 'project', 'fixture')
    assert restored['execution_contract'] == frozen
    assert restored['wire_json'] == bundle['wire_json']
    # Selecting an old revision must not bypass the original configuration binding.
    from app.core.exceptions import StorageError
    config['bundle']['models']['writing']['execution']['task_limit_micro_usd'] -= 1
    with pytest.raises(StorageError):
        service.bundle(db, 'project', 'fixture')
