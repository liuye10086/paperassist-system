"""Frozen candidate-to-candidate writing, with no database or model."""
import json
from types import SimpleNamespace

import pytest

from app.core.exceptions import StorageError
from app.domain.manuscript_writing import authorization
from app.domain.manuscript_writing.bundle import build_bundle, validate_bundle
from app.domain.manuscript_writing.live_execution import compose_live_candidate
from tests.domain.test_writing_w1 import generated, prepared, request


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def original():
    snapshot, bundle, payload = prepared()
    out = generated(payload)
    for section in out['sections']:
        section['paragraphs'][0]['text'] = 'Original ' + section['id'].replace('_', ' ') + '.'
    candidate = compose_live_candidate(out, snapshot, bundle, 'call', 'synthetic_fixture')
    return snapshot, bundle, out, candidate


def test_revision_pins_the_original_text_and_real_opinion_and_requires_changed_prose():
    snapshot, first, out, candidate = original()
    req = request(revision_of_request_id='original', instructions='Clarify the comparison in the discussion.')
    row = dict(candidate_json=candidate, base_version_id='v1', request_json=snapshot['input'], published_revision=None)
    service = SimpleNamespace(writing=SimpleNamespace(row=lambda *_: (row, {'status': 'succeeded'})))
    sections = authorization.LiveWritingService.revision_sections(service, None, 'p', 'm', 'v1', req)
    bundle = build_bundle(snapshot['base_snapshot'], req, execution_contract=first['execution_contract'],
                          revision_sections=sections)
    revised = dict(snapshot, input=req, request_id='revised')
    payload = json.loads(json.loads(bundle['wire_json'])['input'])
    assert payload['instructions'] == req['instructions']
    assert {s['id']: s['paragraphs'][0]['text'] for s in payload['original_draft']}['discussion'] == 'Original discussion.'
    assert 'original' not in json.dumps(payload['original_draft']).lower().replace('original ', '')
    validate_bundle(dict(bundle, request_json=req, base_snapshot=snapshot['base_snapshot']))
    bundle['id'] = 'second-bundle'
    # A model may generate entirely new paragraph IDs while merely repeating the original.
    for section in out['sections']:
        section['paragraphs'][0]['id'] += '-revised'
        section['paragraphs'][0]['text'] += '  '
    with pytest.raises(ValueError, match='unchanged'):
        compose_live_candidate(out, revised, bundle, 'second-call', 'synthetic_fixture')
    next(s for s in out['sections'] if s['id'] == 'discussion')['paragraphs'][0]['text'] = 'Updated discussion.'
    result = compose_live_candidate(out, revised, bundle, 'second-call', 'synthetic_fixture')
    assert result['writing_provenance']['verification_status'] == 'pending'
    assert result['sections'] != candidate['sections']


def test_scoped_revision_sends_only_selected_draft_text_and_merges_into_its_parent():
    from app.domain.manuscript_writing.live_execution import validate_live_candidate

    snapshot, first, original_output, candidate = original()
    req = request(revision_of_request_id='original', instructions='Clarify the discussion and shorten the abstract.',
                  target_sections=['discussion', 'abstract'])
    row = dict(candidate_json=candidate, base_version_id='v1', request_json=snapshot['input'], published_revision=None)
    service = SimpleNamespace(writing=SimpleNamespace(row=lambda *_: (row, {'status': 'succeeded'})))
    sections = authorization.LiveWritingService.revision_sections(service, None, 'p', 'm', 'v1', req)
    bundle = build_bundle(snapshot['base_snapshot'], req, execution_contract=first['execution_contract'],
                          revision_sections=sections)
    bundle['id'] = 'scoped-bundle'
    payload = json.loads(json.loads(bundle['wire_json'])['input'])
    assert payload['writing_scope']['output_section_ids'] == ['abstract', 'discussion']
    assert [s['id'] for s in payload['original_draft']] == ['abstract', 'discussion']
    assert 'Original introduction.' not in bundle['wire_json']
    validate_bundle(dict(bundle, request_json=req, base_snapshot=snapshot['base_snapshot']))
    revised = dict(snapshot, input=req, request_id='revised')
    with pytest.raises(ValueError, match='scope'):
        compose_live_candidate(original_output, revised, bundle, 'scoped-call', 'synthetic_fixture')
    selected = dict(sections=[s for s in original_output['sections'] if s['id'] in req['target_sections']])
    for section, wire_section in zip(selected['sections'], payload['original_draft']):
        section['paragraphs'][0]['id'] = wire_section['paragraphs'][0]['id']
    with pytest.raises(ValueError, match='unchanged'):
        compose_live_candidate(selected, revised, bundle, 'scoped-call', 'synthetic_fixture')
    selected['sections'][-1]['paragraphs'][0]['text'] = 'Updated discussion.'
    selected['sections'][-1]['paragraphs'].append(dict(selected['sections'][-1]['paragraphs'][0],
                                                     id='discussion:new', text='An added clarification.'))
    result = compose_live_candidate(selected, revised, bundle, 'scoped-call', 'synthetic_fixture')
    validate_live_candidate(result, revised, bundle)
    assert {s['id']: s for s in result['sections'] if s['id'] != 'discussion'} == {
        s['id']: s for s in candidate['sections'] if s['id'] != 'discussion'}
    assert result['title'] == candidate['title']
    assert authorization.revisable_draft(dict(row, candidate_json=result, request_json=req), {'status': 'succeeded'})


@pytest.mark.parametrize('change', ['sources', 'evidence', 'base', 'state', 'published', 'language'])
def test_rejects_unrelated_or_incomplete_parent_and_changed_materials(change):
    snapshot, _, _, candidate = original()
    row = dict(candidate_json=candidate, base_version_id='v1', request_json=snapshot['input'], published_revision=None)
    task = {'status': 'succeeded'}
    selection = request(revision_of_request_id='previous', instructions='Clarify the discussion.')
    if change == 'sources':
        selection['selected_source_ids'] = ['unrelated']
    if change == 'evidence':
        selection['selected_evidence_ids'] = ['unrelated']
    if change == 'base':
        row['base_version_id'] = 'other-version'
    if change == 'state':
        task['status'] = 'failed'
    if change == 'published':
        row['published_revision'] = 2
    if change == 'language':
        selection['output_language'] = 'zh-CN'
    service = SimpleNamespace(writing=SimpleNamespace(row=lambda *_: (row, task)))
    with pytest.raises(StorageError):
        authorization.LiveWritingService.revision_sections(service, None, 'p', 'm', 'v1', selection)


def test_feedback_upload_reads_clean_word_text_and_tables_without_saving_project_material():
    from io import BytesIO
    from docx import Document
    from app.domain.manuscript_writing import draft_feedback

    document = Document()
    document.add_paragraph('Clarify the results.')
    document.add_table(1, 1).cell(0, 0).text = 'Distinguish the comparison groups.'
    raw = BytesIO()
    document.save(raw)
    assert draft_feedback.read_feedback('comments.docx', raw.getvalue()) == (
        'Clarify the results.\nDistinguish the comparison groups.')
    assert draft_feedback.read_feedback('notes.txt', '核对研究范围'.encode('utf-8-sig')) == '核对研究范围'
    with pytest.raises(StorageError):
        draft_feedback.read_feedback('notes.txt', b'a' * 10001)
    with pytest.raises(StorageError):
        draft_feedback.read_feedback('notes.exe', b'abc')


def test_feedback_pdf_reads_text_and_rejects_partial_extraction(monkeypatch):
    from app.domain.manuscript_writing import draft_feedback
    from app.adapters.pdf_parser import parse_pdf
    from tests.helpers.pdf_samples import TEXT, pdf_bytes

    monkeypatch.setattr(draft_feedback, 'parse_pdf_isolated', parse_pdf)
    assert draft_feedback.read_feedback('review.pdf', pdf_bytes([TEXT])) == '001.20 kg'
    with pytest.raises(StorageError):
        draft_feedback.read_feedback('partial.pdf', pdf_bytes([TEXT, b'']))


def test_revision_keeps_paragraph_source_and_evidence_aliases_without_local_identifiers():
    snapshot, _, _, candidate = original()
    selection = snapshot['input'] | dict(selected_source_ids=['private-local-source'], selected_evidence_ids=['local-evidence'])
    first = candidate['sections'][0]['paragraphs'][0]
    first.update(suggested_source_aliases=['s1'], suggested_evidence_aliases=['e1'])
    row = dict(candidate_json=candidate, base_version_id='v1', request_json=selection, published_revision=None)
    service = SimpleNamespace(writing=SimpleNamespace(row=lambda *_: (row, {'status': 'succeeded'})))
    sections = authorization.LiveWritingService.revision_sections(service, None, 'p', 'm', 'v1',
        selection | dict(revision_of_request_id='parent', instructions='Shorten the title.'))
    assert sections[0]['paragraphs'][0] == dict(text=first['text'], source_aliases=['s1'], evidence_aliases=['e1'])


def test_school_revision_only_sends_writable_chapter_aliases_and_requires_changed_prose():
    from app.domain.manuscript_writing.live_contracts import preview_data
    from tests.domain.test_school_writing_live import fixture

    snapshot, first, output, _ = fixture(True)
    candidate = compose_live_candidate(output, snapshot, first, 'call', 'synthetic_fixture')
    parent = dict(candidate_json=candidate, base_version_id='v1', request_json=snapshot['input'], published_revision=None)
    request = preview_data(snapshot['input'] | dict(revision_of_request_id='parent', instructions='根据导师意见修改结论。'))
    service = SimpleNamespace(writing=SimpleNamespace(row=lambda *_: (parent, {'status': 'succeeded'})))
    sections = authorization.LiveWritingService.revision_sections(service, None, 'p', 'm', 'v1', request)
    bundle = build_bundle(snapshot['base_snapshot'], request, execution_contract=first['execution_contract'],
                          revision_sections=sections)
    payload = json.loads(json.loads(bundle['wire_json'])['input'])
    assert [s['id'] for s in payload['original_draft']] == [c['alias'] for c in payload['chapters']]
    assert 'private-' not in bundle['wire_json'] and 'PRIVATE AUTHOR' not in bundle['wire_json']
    assert payload['instructions'] == request['instructions']
    validate_bundle(dict(bundle, request_json=request, base_snapshot=snapshot['base_snapshot']))
    bundle['id'] = 'revised'
    new_snapshot = snapshot | dict(input=request, request_id='new-request')
    with pytest.raises(ValueError, match='unchanged'):
        compose_live_candidate(output, new_snapshot, bundle, 'new-call', 'synthetic_fixture')
    output['sections'][-1]['paragraphs'][0]['text'] = '合成结论已根据反馈更新。'
    candidate2 = compose_live_candidate(output, new_snapshot, bundle, 'new-call', 'synthetic_fixture')
    assert candidate2['sections'][-1]['paragraphs'][0]['text'] != candidate['sections'][-1]['paragraphs'][0]['text']
    assert candidate2['sections'][:2] == candidate['sections'][:2]


def test_school_revision_chat_reuses_the_parent_and_changes_only_its_selected_chapter():
    from app.domain.manuscript_writing.frozen import contract, validate_wire, wire_payload
    from app.domain.manuscript_writing.live_contracts import preview_data
    from app.domain.manuscript_writing.live_execution import validate_live_candidate
    from tests.domain.test_school_writing_live import fixture

    snapshot, first, output, _ = fixture(True)
    parent = compose_live_candidate(output, snapshot, first, 'call', 'synthetic_fixture')
    methods = next(s for s in parent['sections'] if s['purpose'] == 'materials_and_methods')
    other = next(s for s in parent['sections'] if s['purpose'] == 'introduction')
    other['paragraphs'][0]['text'] = '保留上轮已经修改过的绪论。'
    presentation = dict(english_title='Saved English Title', keywords=[])
    body = snapshot['input'] | dict(revision_of_request_id='parent', instructions='缩短研究方法。')
    request = preview_data(body | dict(target_sections=[methods['id']]))
    row = dict(candidate_json=parent, base_version_id='v1', request_json=snapshot['input'], published_revision=None)
    service = SimpleNamespace(writing=SimpleNamespace(row=lambda *_: (row, {'status': 'succeeded'})))
    frozen = contract(schema_version=3, source_selection_version=2, response_stream=True)
    originals = authorization.LiveWritingService.revision_sections(service, None, 'p', 'm', 'v1', request)
    assert originals == parent['sections']
    bundle = build_bundle(snapshot['base_snapshot'], request, execution_contract=frozen,
                          revision_sections=originals, revision_school_presentation=presentation)
    payload = wire_payload(bundle['wire_json'])
    [chapter] = payload['chapters']
    assert chapter['purpose'] == 'materials_and_methods'
    [original] = payload['original_draft']
    assert original['id'] == chapter['alias']
    assert original['paragraphs'][0]['text'] == methods['paragraphs'][0]['text']
    assert [section['id'] for section in payload['context']] == [chapter['alias']]
    assert '保留上轮已经修改过的绪论。' not in bundle['wire_json']
    assert 'Saved English Title' not in bundle['wire_json'] and 'PRIVATE AUTHOR' not in bundle['wire_json']
    assert methods['id'] not in bundle['wire_json']
    assert json.loads(bundle['wire_json'])['stream'] is True
    validate_wire(bundle['wire_json'], frozen)
    validate_bundle(dict(bundle, request_json=request, base_snapshot=snapshot['base_snapshot']))

    bundle['id'] = 'school-revision'
    new_snapshot = snapshot | dict(input=request, request_id='school-revision')
    new_text = '研究方法已经按意见精简。'
    paragraphs = [dict(id=original['paragraphs'][0]['id'], text=new_text, source_aliases=[], evidence_aliases=[],
                       study_numeric_bindings=[], citation_anchors=[])]
    revised = compose_live_candidate(dict(sections=[dict(id=chapter['alias'], paragraphs=paragraphs)]),
                                     new_snapshot, bundle, 'edited', 'synthetic_fixture')
    assert [s for s in revised['sections'] if s['id'] != methods['id']] == [s for s in originals if s['id'] != methods['id']]
    assert next(s for s in revised['sections'] if s['id'] == methods['id'])['paragraphs'][0]['text'] == new_text
    assert revised['school_presentation'] == presentation
    validate_live_candidate(revised, new_snapshot, bundle)

    advice = preview_data(request | dict(instructions='这章有什么问题？', draft_advice=True))
    advice_bundle = build_bundle(snapshot['base_snapshot'], advice, execution_contract=frozen,
                                 revision_sections=originals, revision_school_presentation=presentation)
    reply = wire_payload(advice_bundle['wire_json'])
    assert reply['draft_sections'][0]['paragraphs'] == [p['text'] for p in methods['paragraphs']]
    assert len(reply['draft_sections']) == 1 and 'original_draft' not in reply
    assert advice_bundle['local_manifest']['school']['writable_aliases'] == [chapter['alias']]
    validate_wire(advice_bundle['wire_json'], frozen)
    for malformed in (dict(target_sections=[]), dict(target_sections=[methods['id'], methods['id']]),
                      dict(target_sections=[methods['id']], revision_of_request_id=None), dict(draft_advice=True)):
        with pytest.raises(ValueError):
            preview_data(body | malformed)
    protected = preview_data(body | dict(target_sections=[parent['sections'][0]['id']]))
    with pytest.raises(StorageError, match='所选章节'):
        authorization.LiveWritingService.revision_sections(service, None, 'p', 'm', 'v1', protected)


def test_historical_school_candidate_keeps_frozen_chapters_and_is_read_only():
    from app.domain.manuscript_writing.context import compose_candidate
    from app.domain.sci_draft_reader import draft_content, paragraph_text
    from tests.domain.test_thesis_chapters import frozen, output

    old = frozen()
    candidate = compose_candidate(output(old), old)
    view = draft_content(candidate, {})
    chapters = candidate['thesis_context']['chapters']
    assert [(s['id'], s['heading'], s['purpose']) for s in view['sections']] == [
        (c['id'], c['title'], c['purpose']) for c in chapters]
    results = next(s for s in view['sections'] if s['purpose'] == 'results')
    assert paragraph_text(results['paragraphs'][0]) == 'n = 12'
    row = dict(candidate_json=candidate, request_json=old['input'], published_revision=None)
    assert not authorization.revisable_draft(row, {'status':'succeeded'})


def test_school_draft_footnotes_only_replace_the_precisely_linked_marker():
    from io import BytesIO
    from zipfile import ZipFile
    from docx import Document
    from docx.oxml.ns import qn
    from app.adapters.school_docx import Footnotes
    from app.adapters.manuscript_docx import _save_document

    document = Document()
    notes = Footnotes(document, {'references':[dict(number=1, text='Frozen bibliography entry.')]}, True)
    parts = [dict(text='The sample label (1) is preserved.', citations=[dict(number=1)])]
    paragraph = notes.paragraph(dict(text=parts[0]['text'], id='passage'), 1,
                                {'label_map':{'tables':{}, 'figures':{}}}, parts)
    assert paragraph.text == 'The sample label (1) is preserved.'
    assert len(list(paragraph._p.iter(qn('w:footnoteReference')))) == 1
    with ZipFile(BytesIO(notes.finish(_save_document(document)))) as archive:
        assert b'[1] Frozen bibliography entry.' in archive.read('word/footnotes.xml')
