"""Future create contract and legacy reads; synthetic HTTP, no database or network."""
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.adapters.models.openai_responses import canonical_payload
from app.domain.literature_assistance.contracts import validate_result
from app.domain.literature_assistance.execution import INSTRUCTIONS, instructions_for, parse_response
from app.domain.literature_live.batch06 import Batch06Ledger, Batch06ModelProvider, input_allowance
from app.domain.literature_live.policy import LivePolicyError
from app.domain.model_usage.gateway import input_digest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


KINDS = ['search_plan', 'evidence_review', 'evidence_comparison']


def payload_for(kind):
    return dict(kind=kind, output_language='zh-CN', material=dict(evidence=[
        dict(id='selected-1', project_reference_id='ref-1', reading_scope='abstract'),
        dict(id='selected-2', project_reference_id='ref-2', reading_scope='abstract')]))


def snapshot_for(payload):
    return dict(input=dict(kind=payload['kind'], evidence_ids=['selected-1', 'selected-2']),
                material=payload['material'])


def result_for(kind):
    if kind == 'search_plan':
        return dict(direction='Topic', terms=['aspirin'], synonyms=['ASA'],
                    mesh_candidates=[dict(term='Aspirin', verified=False)], query='aspirin', explanation='Advice')
    value = dict(status='partial', relevance='related', reason='Selected excerpts only',
                 narrowed_statement='Bounded statement', limitations=['Abstract only'],
                 evidence_ids=['selected-1', 'selected-2'])
    if kind == 'evidence_comparison':
        value['comparison'] = 'consistent'
    return value


def response(value):
    return dict(id='resp_contract', object='response', created_at=1, model='gpt-6.1-sol', status='completed',
                usage=None, output=[dict(type='message', role='assistant', status='completed',
                    content=[dict(type='output_text', text=json.dumps(value), annotations=[])])])


def bound(tmp_path, payload, calls, value=None, instructions=INSTRUCTIONS, historical=False):
    schema = 'pa_test_' + uuid4().hex
    digest = input_digest(instructions=instructions, payload=payload)
    ledger = Batch06Ledger(tmp_path/'ledger.jsonl', batch_id='contract-test', schema=schema,
        public_inputs=[dict(task_id='task-1', input_digest='a'*64, payload_digest=digest)], pmcids=[])
    if historical:
        with ledger.locked() as state:
            attempt = ledger.reserve(state, 'model_create', state['public_inputs'][0])
            ledger.finish(attempt, receipt=dict(response_id='resp_contract', usage=None))
    def wire(request):
        calls.append(request)
        return httpx.Response(200, json=response(value))
    provider = Batch06ModelProvider(ledger, task_id='task-1', snapshot_digest='a'*64, api_key='synthetic-only',
        http_client=httpx.Client(transport=httpx.MockTransport(wire)))
    config = SimpleNamespace(environment='test', schema=schema, url=SimpleNamespace(database='paperassist_system_test'))
    try:
        provider.authorize_task(dict(id='task-1', input_digest='a'*64), config=config,
                                instructions=instructions, payload=payload)
    except Exception:
        provider.close()
        raise
    return ledger, provider


def assert_strict_objects(schema):
    if isinstance(schema, dict):
        if schema.get('type') == 'object':
            assert schema['additionalProperties'] is False
            assert set(schema['required']) == set(schema['properties'])
        for value in schema.values():
            assert_strict_objects(value)
    elif isinstance(schema, list):
        for value in schema:
            assert_strict_objects(value)


@pytest.mark.parametrize('kind', KINDS)
def test_future_create_sends_strict_typed_schema_and_accepts_valid_synthetic_result(tmp_path, kind):
    payload = payload_for(kind); value = result_for(kind); calls = []
    ledger, provider = bound(tmp_path, payload, calls, value)
    try:
        receipt = provider.create(policy=provider.policy, instructions=INSTRUCTIONS, payload=payload)
        body = json.loads(calls[0].content)
        fmt = body['text']['format']
        assert fmt['type'] == 'json_schema' and fmt['strict'] is True
        assert fmt['name'] == 'literature_' + kind + '_v1'
        schema = fmt['schema']; assert_strict_objects(schema); props = schema['properties']
        assert body['instructions'] == INSTRUCTIONS and body['input'] == canonical_payload(payload)
        assert body['model'] == 'gpt-6.1-sol' and body['service_tier'] == 'default'
        assert body['reasoning'] == {'effort': 'low'} and body['max_output_tokens'] == 3000
        assert body['background'] is True and body['store'] is True and 'tools' not in body
        if kind == 'search_plan':
            assert props['synonyms']['type'] == 'array'
            assert props['synonyms']['items']['type'] == 'string'
            mesh = schema['$defs']['MeshCandidate']['properties']
            assert mesh['verified']['enum'] == [False]
        else:
            assert props['status']['enum'] == ['supported', 'partial', 'unsupported', 'needs_review']
            assert props['relevance']['enum'] == ['related', 'unrelated', 'uncertain']
            assert props['limitations']['type'] == 'array' and props['limitations']['items']['type'] == 'string'
            assert props['evidence_ids']['items']['enum'] == ['selected-1', 'selected-2']
            assert all(word in props['status']['description'] for word in ['partial', 'unsupported', 'needs_review'])
        if kind == 'evidence_comparison':
            assert props['comparison']['enum'] == ['consistent', 'conflicting', 'incomparable', 'insufficient']
        assert parse_response(receipt['response'], snapshot_for(payload)) == value
        assert ledger.summary()['model_create_attempts'] == 1
    finally:
        provider.close()


@pytest.mark.parametrize('kind,field,bad', [
    ('search_plan', 'synonyms', {'aspirin': ['ASA']}),
    ('search_plan', 'synonyms', [{'term': 'ASA'}]),
    ('evidence_review', 'relevance', '直接相关：中文解释'),
    ('evidence_comparison', 'relevance', '所选摘要相关'),
    ('evidence_comparison', 'limitations', '仅摘要'),
])
def test_observed_real_error_shapes_remain_rejected(tmp_path, kind, field, bad):
    payload = payload_for(kind); value = result_for(kind); value[field] = bad; calls = []
    _, provider = bound(tmp_path, payload, calls, value)
    try:
        receipt = provider.create(policy=provider.policy, instructions=INSTRUCTIONS, payload=payload)
        with pytest.raises(ValueError):
            parse_response(receipt['response'], snapshot_for(payload))
    finally:
        provider.close()


@pytest.mark.parametrize('mutation', ['foreign_id', 'duplicate_id', 'missing_ids', 'partial_without_statement',
                                     'uncertain_support', 'abstract_without_limits', 'comparison_conflict'])
def test_business_conditions_still_require_final_validator(mutation):
    kind = 'evidence_comparison' if mutation == 'comparison_conflict' else 'evidence_review'
    value = result_for(kind)
    if mutation == 'foreign_id': value['evidence_ids'] = ['unselected']
    if mutation == 'duplicate_id': value['evidence_ids'] = ['selected-1'] * 2
    if mutation == 'missing_ids': value['evidence_ids'] = []
    if mutation == 'partial_without_statement': value['narrowed_statement'] = ''
    if mutation == 'uncertain_support': value['relevance'] = 'uncertain'
    if mutation == 'abstract_without_limits': value['limitations'] = []
    if mutation == 'comparison_conflict': value['comparison'] = 'conflicting'
    with pytest.raises(ValueError): validate_result(value, snapshot_for(payload_for(kind)))


@pytest.mark.parametrize('kind', KINDS)
def test_input_allowance_counts_actual_text_schema_bytes(tmp_path, kind):
    payload = payload_for(kind); calls = []
    _, provider = bound(tmp_path, payload, calls, result_for(kind))
    try:
        provider.create(policy=provider.policy, instructions=INSTRUCTIONS, payload=payload)
        text = json.loads(calls[0].content)['text']
        legacy = input_allowance(INSTRUCTIONS, payload)
        assert input_allowance(INSTRUCTIONS, payload, text=text) == legacy + len(canonical_payload({'text': text}).encode('utf-8'))
    finally:
        provider.close()


def test_schema_overhead_denies_new_create_without_preventing_legacy_get(tmp_path):
    payload = payload_for('search_plan')
    payload['padding'] = 'x' * (11999 - input_allowance(INSTRUCTIONS, payload) - len(',"padding":""'))
    assert input_allowance(INSTRUCTIONS, payload) == 11999
    calls = []; ledger, provider = bound(tmp_path, payload, calls, result_for('search_plan'), historical=True)
    try:
        with pytest.raises(LivePolicyError, match='batch06_input_mismatch'):
            provider.create(policy=provider.policy, instructions=INSTRUCTIONS, payload=payload)
        assert calls == [] and ledger.summary()['model_create_attempts'] == 1
        # A pre-existing submission and receipt remain readable with the original input digest.
        receipt = provider.retrieve('resp_contract', policy=provider.policy)
        assert receipt['status'] == 'completed' and [r.method for r in calls] == ['GET']
    finally:
        provider.close()


def test_new_authorization_includes_schema_overhead_before_gateway_admission(tmp_path):
    payload = payload_for('search_plan')
    payload['padding'] = 'x' * (11999 - input_allowance(INSTRUCTIONS, payload) - len(',"padding":""'))
    calls = []
    with pytest.raises(LivePolicyError, match='batch06_input_mismatch'):
        bound(tmp_path, payload, calls)
    assert calls == []
    events = [json.loads(line) for line in (tmp_path/'ledger.jsonl').read_text().splitlines()]
    assert [e['event'] for e in events] == ['opened']


def test_old_instruction_versions_and_digest_stay_stable():
    # Frozen v1/v2 instruction bodies are independent of future request schema.
    import hashlib
    assert hashlib.sha256(INSTRUCTIONS.encode()).hexdigest() == 'bd4267b3b70244c04a70a070b6404023dce41bb243b0a031a221aaf7f44677b3'
    for version in ['literature_assistance_v1', 'literature_assistance_v2']:
        snapshot = dict(workflow_version=version, input=dict(kind='search_plan'))
        assert instructions_for(snapshot) == INSTRUCTIONS
        snapshot['input']['kind'] = 'evidence_comparison'
        assert hashlib.sha256(instructions_for(snapshot).encode()).hexdigest() == 'e822a5c41e0f0a48d652ba2640f8d048839addd001cd5af84af2c10ad372475a'


@pytest.mark.parametrize('ids', [[], ['same', 'same'], ['contains space'], [123]])
def test_invalid_selected_ids_deny_new_authorization_before_http(tmp_path, ids):
    payload = payload_for('evidence_review')
    payload['material']['evidence'] = [dict(id=value) for value in ids]
    calls = []
    with pytest.raises(LivePolicyError, match='batch06_input_mismatch'):
        bound(tmp_path, payload, calls)
    assert calls == []


def test_legacy_get_does_not_apply_future_output_schema_to_old_payload(tmp_path):
    calls = []; _, provider = bound(tmp_path, dict(kind='legacy_kind'), calls, historical=True)
    try:
        assert provider.retrieve('resp_contract', policy=provider.policy)['status'] == 'completed'
        assert [r.method for r in calls] == ['GET']
    finally:
        provider.close()
