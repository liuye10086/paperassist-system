"""The selected-document text contract uses local frozen sources only."""
import json

import pytest

from app.core.exceptions import StorageError
from app.domain.manuscript_writing.bundle import build_bundle, validate_bundle
from app.domain.manuscript_writing.frozen import contract, validate_wire
from app.domain.manuscript_writing.live_contracts import preview_data
from tests.domain.test_school_writing_live import material as school_material
from tests.domain.test_writing_w1 import base as sci_base, request as sci_request


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def materials(school=False):
    if school:
        base, request, _ = school_material()
    else:
        base, request = sci_base(), sci_request()
    base['sources'].extend([
        dict(id='selected', kind='document_version', role='methods', content=dict(items=[
            dict(kind='text', text='A frozen paragraph.', location={'path': '/private/location'}),
            dict(kind='image', text='PRIVATE IMAGE LABEL', preview_url='/internal/image'),
            dict(kind='text', text='Another paragraph.', uncertainties=['reading_order_candidate']),
            dict(kind='text', text='PRIVATE UNREADABLE', review_action='unreadable'),
        ])),
        dict(id='other', kind='document_version', role='methods', content=dict(items=[
            dict(kind='text', text='PRIVATE UNSELECTED')])),
    ])
    request['selected_source_ids'] = ['selected']
    return base, request, contract(schema_version=request['schema_version'])


@pytest.mark.parametrize('school', [True, False])
def test_selected_document_text_is_opt_in_and_replays_for_both_writing_protocols(school):
    base, old_request, frozen = materials(school)
    assert preview_data(old_request) == old_request
    old = build_bundle(base, old_request, execution_contract=frozen)
    assert 'A frozen paragraph.' not in old['wire_json']
    validate_bundle(dict(old, base_snapshot=base, request_json=old_request))
    request = preview_data(dict(old_request, document_context_version='selected-text-v1'))
    bundle = build_bundle(base, request, execution_contract=frozen)
    wire = json.loads(bundle['wire_json'])
    entry, = json.loads(wire['input'])['sources']
    assert entry['document_excerpt'] == 'A frozen paragraph.\nAnother paragraph.'
    assert entry['document_excerpt_truncated'] is False
    assert entry['document_excerpt_scope'] == 'user_provided_context'
    assert entry['facts'] == []
    assert 'PRIVATE' not in wire['input'] and '/private/location' not in wire['input']
    assert bundle['wire_sha256'] != old['wire_sha256']
    validate_wire(bundle['wire_json'], frozen)
    validate_bundle(dict(bundle, base_snapshot=base, request_json=request))


def test_document_excerpt_is_bounded_and_marked_before_authorization():
    base, request, frozen = materials()
    base['sources'][0]['content']['items'] = [dict(kind='text', text='文' * 16000)]
    request = preview_data(dict(request, document_context_version='selected-text-v1'))
    bundle = build_bundle(base, request, execution_contract=frozen)
    source, = json.loads(json.loads(bundle['wire_json'])['input'])['sources']
    assert source['document_excerpt'] == '文' * 12000
    assert source['document_excerpt_truncated'] is True


def test_document_excerpt_checks_outgoing_text_before_freezing():
    base, request, frozen = materials()
    base['sources'][0]['content']['items'] = [dict(kind='text', text='see /private/lab/note')]
    request = preview_data(dict(request, document_context_version='selected-text-v1'))
    with pytest.raises(StorageError) as error:
        build_bundle(base, request, execution_contract=frozen)
    assert error.value.code == 'manuscript_writing_material_blocked'


def test_only_the_readable_selected_external_items_are_projected():
    base, request, frozen = materials()
    base['sources'][0].update(kind='external_evidence_version', content=dict(
        user_note='PRIVATE DECLARATION', items=[
            dict(kind='text', text='Selected passage.'),
            dict(kind='cell', value=dict(kind='text', typed='selected cell')),
            dict(kind='text', text='PRIVATE UNREADABLE', uncertainties=['unreadable']),
        ]))
    request = preview_data(dict(request, document_context_version='selected-text-v1'))
    bundle = build_bundle(base, request, execution_contract=frozen)
    source, = json.loads(json.loads(bundle['wire_json'])['input'])['sources']
    assert source['document_excerpt'] == 'Selected passage.\nselected cell'
    assert 'PRIVATE' not in bundle['wire_json']
