from copy import deepcopy
import json
import pytest

from app.domain.manuscript_writing.bundle import build_bundle, validate_bundle
from app.domain.manuscript_writing.frozen import contract, validate_wire
from app.domain.manuscript_writing.live_execution import compose_live_candidate
from tests.domain.test_manuscript_writing_live_bundle import material
from tests.domain.test_writing_live_candidates import fixture as legacy_fixture


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def new_fixture():
    base, request = material()
    base['methods'] = [dict(id='method-local', text='The fixed values are 1, 2, 3, 4; the divisor is n−1.',
                            origin='user_provided', source_ids=[], citations=[], numeric_bindings=[])]
    bundle = build_bundle(base, request, execution_contract=contract(schema_version=2))
    bundle['id'] = 'new-bundle'
    snapshot = dict(input=request, base_snapshot=base, request_id='writing-new', base_version_id='base-new')
    output = dict(sections=[dict(id=s, paragraphs=[dict(id=s, text='Needs explicit verification.', source_aliases=[],
        evidence_aliases=[], study_numeric_bindings=[])]) for s in ('title','abstract','introduction','results','discussion','materials_and_methods')])
    return snapshot, bundle, output


def context_binding(bundle, value):
    for alias, row in bundle['local_manifest']['numeric_context'].items():
        for fact in row['values']:
            if fact['value'] == value:
                return dict(source_alias=alias, **fact)
    raise AssertionError('Expected provided-context value')


def test_legacy_wire_bytes_and_sha_remain_frozen():
    base, request = material()
    bundle = build_bundle(base, request)
    assert bundle['wire_bytes'] == 3501
    assert bundle['bundle_sha256'] == '21cfd8f75b6d9db13710cce574a1ac57ddc9e2a62c8d4f3cade44eeaefe14512'
    assert 'execution_contract' not in bundle
    validate_bundle(dict(bundle, base_snapshot=base, request_json=request))
    validate_wire(bundle['wire_json'], contract())


def test_new_contract_has_finite_fact_tuples_and_context_not_private_ids():
    snapshot, bundle, _ = new_fixture()
    assert bundle['execution_contract']['schema_version'] == 2
    assert bundle['execution_contract']['origin'] == 'installed'
    wire = json.loads(bundle['wire_json']); payload = json.loads(wire['input'])
    assert payload['numeric_contract_version'] == 2
    assert bundle['local_manifest']['numeric_context']
    schema_text = json.dumps(wire['text']['format']['schema'])
    assert '/statistics/coefficient' in schema_text and 'c1' in schema_text
    assert 'private-source' not in bundle['wire_json'] and 'method-local' not in bundle['wire_json']
    validate_wire(bundle['wire_json'], bundle['execution_contract'])
    validate_bundle(dict(bundle, base_snapshot=snapshot['base_snapshot'], request_json=snapshot['input']))


def test_provided_method_numbers_are_pending_context_not_computed_sources():
    snapshot, bundle, output = new_fixture()
    p = output['sections'][-1]['paragraphs'][0]
    binding = context_binding(bundle, '-1')
    p.update(text='The divisor is n−1.', study_numeric_bindings=[binding])
    candidate = compose_live_candidate(output, snapshot, bundle, 'call', 'synthetic_fixture')
    saved = candidate['sections'][-2]['paragraphs'][0]
    assert saved['source_ids'] == [] and saved['study_numeric_bindings'] == []
    assert saved['context_numeric_bindings'] == [binding]
    assert saved['verification_status'] == 'pending'
    assert candidate['writing_provenance']['numeric_contract_version'] == 2


@pytest.mark.parametrize('change', ['alias', 'path', 'value'])
def test_context_binding_cannot_invent_or_round_any_catalog_component(change):
    snapshot, bundle, output = new_fixture(); binding = context_binding(bundle, '-1')
    binding[{'alias':'source_alias','path':'fact_path','value':'value'}[change]] = {'alias':'c999','path':'/invented','value':'1'}[change]
    output['sections'][-1]['paragraphs'][0].update(text='The divisor is n−1.', study_numeric_bindings=[binding])
    with pytest.raises(ValueError): compose_live_candidate(output, snapshot, bundle, 'call', 'synthetic_fixture')


def test_figure_number_is_not_a_context_fact_or_study_path():
    base, request = material()
    base['results_groups'] = [dict(id='g', title='Results', paragraphs=[], tables=[], figures=[dict(id='f', number=1,
        source_ids=['private-source'], title='Figure 1', caption='Figure 1; multiplier 1.5.', panels=[])])]
    bundle = build_bundle(base, request, execution_contract=contract(schema_version=2))
    assert all(f['value'] != '1' for row in bundle['local_manifest']['numeric_context'].values() for f in row['values'])
    assert any(f['value'] == '1.5' for row in bundle['local_manifest']['numeric_context'].values() for f in row['values'])


def test_generated_history_is_not_promoted_to_provided_numeric_authority():
    base, request = material(); base['methods'] = [dict(id='generated', text='Invented result 99.', origin='model_generated', source_ids=[])]
    bundle = build_bundle(base, request, execution_contract=contract(schema_version=2))
    assert not bundle['local_manifest']['numeric_context']


def test_new_protocol_no_longer_uses_literature_alias_as_numeric_exemption():
    snapshot, legacy, output = legacy_fixture()
    bundle = build_bundle(snapshot['base_snapshot'], snapshot['input'], execution_contract=contract(schema_version=2)); bundle['id']='v2'
    output['sections'][2]['paragraphs'][0].update(text='The study reports 99 observations.', evidence_aliases=['e1'])
    with pytest.raises(ValueError): compose_live_candidate(output, snapshot, bundle, 'call', 'synthetic_fixture')


def test_literature_numeric_quote_can_be_suggested_but_stays_unreviewed():
    snapshot, _, output = legacy_fixture()
    bundle = build_bundle(snapshot['base_snapshot'], snapshot['input'], execution_contract=contract(schema_version=2)); bundle['id']='v2'
    output['sections'][2]['paragraphs'][0].update(text='The published quote reports 42 observations.', evidence_aliases=['e1'],
        study_numeric_bindings=[dict(source_alias='e1',fact_path='/quote/numbers/0',value='42')])
    candidate = compose_live_candidate(output, snapshot, bundle, 'call', 'synthetic_fixture')
    p = candidate['sections'][2]['paragraphs'][0]
    assert p['citations'] == [] and p['verification_status'] == 'pending'
    assert p['study_numeric_bindings'] == [] and len(p['literature_numeric_bindings']) == 1


def test_old_quote_numeric_exemption_and_wrong_path_rejection_are_unchanged():
    snapshot, bundle, output = legacy_fixture()
    output['sections'][2]['paragraphs'][0].update(text='The published study reports 42 observations.', evidence_aliases=['e1'])
    compose_live_candidate(output, snapshot, bundle, 'call', 'synthetic_fixture')
    output['sections'][3]['paragraphs'][0].update(text='n=12',source_aliases=['s1'],
        study_numeric_bindings=[dict(source_alias='s1',fact_path='/record_check/excluded',value='12')])
    with pytest.raises(ValueError, match='Unknown exact study fact'):
        compose_live_candidate(output, snapshot, bundle, 'call', 'synthetic_fixture')
