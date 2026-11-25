"""Pure frozen-contract coverage for SCI chat suggestions and streamed revisions."""
from contextlib import nullcontext
from base64 import b64encode
from io import BytesIO
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from app.adapters.models.openai_responses import canonical_payload
from app.domain.manuscript_writing import authorization
from app.domain.manuscript_writing.bundle import build_bundle, validate_bundle
from app.domain.manuscript_writing.frozen import contract, validate_wire
from app.domain.manuscript_writing.live_contracts import DraftAdviceOutput
from tests.domain.test_sci_draft_revision import original
from tests.domain.test_writing_w1 import request


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def scoped_request(**updates):
    return request(**(dict(revision_of_request_id='original', instructions='What could I improve here?',
                           target_sections=['discussion']) | updates))


def test_advice_requires_a_scoped_sci_draft_and_preserves_legacy_request_json():
    assert 'draft_advice' not in scoped_request()
    assert scoped_request(draft_advice=True)['draft_advice'] is True
    for change in (dict(revision_of_request_id=None), dict(target_sections=[]), dict(document_kind='thesis'),
                   dict(mode='polish'), dict(draft_advice=False), dict(draft_advice=1)):
        with pytest.raises(ValueError):
            scoped_request(**(dict(draft_advice=True) | change))


def test_advice_sends_only_the_selected_prose_and_a_question():
    snapshot, _, _, candidate = original()
    req = scoped_request(draft_advice=True)
    parent = dict(candidate_json=candidate, base_version_id='v1', request_json=snapshot['input'], published_revision=None)
    service = SimpleNamespace(writing=SimpleNamespace(row=lambda *_: (parent, {'status': 'succeeded'})))
    sections = authorization.LiveWritingService.revision_sections(service, None, 'p', 'm', 'v1', req)
    frozen = contract(schema_version=4, response_stream=True)
    bundle = build_bundle(snapshot['base_snapshot'], req, execution_contract=frozen, revision_sections=sections)
    wire = json.loads(bundle['wire_json'])
    assert json.loads(wire['input']) == {
        'output_language': 'en',
        'instructions': 'What could I improve here?',
        'draft_sections': [{'heading': 'Discussion', 'paragraphs': ['Original discussion.']}],
    }
    assert wire['stream'] is True
    assert wire['text']['format']['strict'] is True
    schema = wire['text']['format']['schema']
    assert schema['required'] == ['advice']
    assert set(schema['properties']) == {'advice'}
    assert schema['additionalProperties'] is False
    assert DraftAdviceOutput.model_validate({'advice': 'Explain the comparison group.'}).advice
    for invalid in ({'advice': ' '}, {'advice': 'Explain the comparison group.', 'sections': []}):
        with pytest.raises(ValueError):
            DraftAdviceOutput.model_validate(invalid)
    assert bundle['local_manifest']['sources'] == bundle['local_manifest']['evidence'] == {}
    assert bundle['local_manifest']['writing_scope']['target_section_ids'] == ['discussion']
    assert bundle['revision_sections'] == candidate['sections']
    validate_wire(bundle['wire_json'], frozen)
    validate_bundle(dict(bundle, request_json=req, base_snapshot=snapshot['base_snapshot']))


def test_streamed_revision_retains_historical_wire_when_the_flag_is_absent():
    snapshot, legacy, _, candidate = original()
    req = scoped_request()
    args = (snapshot['base_snapshot'], req)
    frozen = legacy['execution_contract']
    historical = build_bundle(*args, execution_contract=frozen, revision_sections=candidate['sections'])
    streamed = build_bundle(*args, execution_contract=dict(frozen, response_stream=True), revision_sections=candidate['sections'])
    old_wire, new_wire = (json.loads(row['wire_json']) for row in (historical, streamed))
    assert 'response_stream' not in frozen
    assert 'stream' not in old_wire
    assert historical['wire_sha256'] == '0bb4fb81ab6f85e99c8a54ce3eecf9fc77112f0202bead279a1eb3707f8aee35'
    assert new_wire == dict(old_wire, stream=True)
    for row in (historical, streamed):
        validate_wire(row['wire_json'], row['execution_contract'])
        validate_bundle(dict(row, request_json=req, base_snapshot=snapshot['base_snapshot']))
    with pytest.raises(ValueError):
        validate_wire(canonical_payload(old_wire), streamed['execution_contract'])
    with pytest.raises(ValueError):
        validate_wire(canonical_payload(new_wire), frozen)


@pytest.mark.parametrize('advice', [None, True])
def test_scoped_chat_freezes_visual_input_and_binds_it_to_the_wire(advice):
    snapshot, _, _, candidate = original()
    req = scoped_request(draft_advice=advice)
    frozen = contract(schema_version=4, source_selection_version=2, response_stream=True, scope_figure_input=True)
    image = BytesIO()
    Image.new('RGB', (64, 64), 'green').save(image, format='PNG')
    url = 'data:image/png;base64,' + b64encode(image.getvalue()).decode('ascii')
    context = dict(number=1, section_ids=['discussion'], title='Reference plot', caption='Comparison groups')
    args = dict(execution_contract=frozen, revision_sections=candidate['sections'])
    base = snapshot['base_snapshot']
    bundle = build_bundle(base, req, **args, revision_figures=[dict(context, image_url=url)])
    wire = json.loads(bundle['wire_json'])
    content = wire['input'][0]['content']
    assert wire['input'][0]['role'] == 'user'
    assert content[0]['type'] == 'input_text'
    assert json.loads(content[0]['text'])['revision_figure_context'] == [context]
    assert content[1:] == [dict(type='input_image', image_url=url, detail='high')]
    assert bundle['input_token_allowance'] == bundle['wire_bytes'] - len(url) + 4096 + 8192
    validate_wire(bundle['wire_json'], frozen)
    saved = dict(bundle, base_snapshot=base, request_json=req, revision_image_parent_sha256='0' * 64)
    validate_bundle(saved)
    with pytest.raises(ValueError):
        validate_wire(bundle['wire_json'], {key: value for key, value in frozen.items() if key != 'scope_figure_input'})
    with pytest.raises(ValueError):
        validate_bundle(dict(saved, wire_json=bundle['wire_json'].replace(url, url + 'A')))
    with pytest.raises(ValueError):
        build_bundle(base, req, **args, revision_figures=[dict(context, section_ids=['introduction'], image_url=url)])


@pytest.mark.parametrize('advice', [None, True])
def test_new_scoped_preview_restores_its_stream_flag_under_a_configuration_binding(monkeypatch, advice):
    snapshot, legacy, _, candidate = original()
    request_json = scoped_request(draft_advice=advice)
    policy = legacy['execution_contract']
    configuration = dict(bundle=dict(
        models=dict(writing=dict(execution=dict(policy=policy['policy'], input_token_allowance=policy['max_input_allowance'])),
                    batch_max_posts=policy['batch_max_posts'], max_corrections=policy['max_corrections']),
        prompts=dict(writing_instruction='Use simple language.')))
    parent = dict(candidate_json=candidate, base_version_id='v1', request_json=snapshot['input'], published_revision=None)
    saved = {}

    def execute(sql, params):
        if sql.startswith('INSERT INTO manuscript_writing_bundles'):
            keys = ('id', 'project_id', 'user_id', 'manuscript_id', 'base_version_id', 'request_key',
                    'request_digest', 'bundle_sha256', 'bundle_json', 'created_at')
            saved.update(zip(keys, params, strict=True))
            saved['bundle_json'] = saved['bundle_json'].obj
        elif sql.startswith(('SELECT * FROM manuscript_writing_bundles', 'SELECT id,request_digest')):
            return SimpleNamespace(fetchone=lambda: saved or None)
        else:
            raise AssertionError(sql)

    db = SimpleNamespace(execute=execute)
    service = authorization.LiveWritingService.__new__(authorization.LiveWritingService)
    service.store = SimpleNamespace(connection=lambda **_: nullcontext(db), user_id='owner',
                                    require_project=lambda *_: None, require_task=lambda *_: {'status': 'succeeded'})
    service.manuscripts = SimpleNamespace(
        assets=SimpleNamespace(customer=False), root=lambda *_: {'current_revision': 1},
        version=lambda *_: dict(id='v1', task_id='base-task', snapshot_json=snapshot['base_snapshot']))
    service.writing = SimpleNamespace(row=lambda *_: (parent, {'status': 'succeeded'}))
    monkeypatch.setattr(authorization, 'resolve_document_context', lambda *_, **__: {'document_kind': 'sci'})
    monkeypatch.setattr(authorization, 'changes', lambda *_: [])
    monkeypatch.setattr(authorization, 'resolve', lambda *_, **__: configuration)
    monkeypatch.setattr(authorization, 'bind', lambda *_, **__: None)

    preview, status = service.preview('p', 'm', request_json, 'scoped-request')
    assert status == 201
    assert preview['execution_contract']['response_stream'] is True
    assert preview['execution_contract']['origin'] == 'configuration'
    restored, replay_status = service.preview('p', 'm', request_json, 'scoped-request')
    assert replay_status == 200
    assert restored == preview
