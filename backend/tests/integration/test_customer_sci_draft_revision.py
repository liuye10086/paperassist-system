"""Two independently readable, unpublished customer drafts with a synthetic model."""
import json
from datetime import datetime

from fastapi.testclient import TestClient

from app.adapters.docx_parser import parse_docx
from app.db.database import database_connection
from app.domain.manuscript_writing.execution import run_manuscript_writing_task
from app.domain.tasks.file_parse_execution import run_parse_file_task
from app.main import app
from tests.api.test_customer_sci_workflow import article_request, sci_project, upload_docx
from tests.api.test_customer_workspace import sign_in
from tests.api.test_manuscript_writing_live import LiveFixture
from tests.api.test_manuscripts import body
from tests.integration.test_customer_sci_to_word import SciFixtureProvider, create_fact, request


def queue_write(client, project, root, bundle, logical):
    ref = dict(bundle_id=bundle['id'], bundle_sha256=bundle['bundle_sha256'])
    auth = request(client, 'POST', project + '/writing-authorizations', status=201, key='auth-' + logical,
                   json=dict(schema_version=2, confirmed=True, tasks=[dict(logical_task_id=logical, bundles=[ref])]))
    payload = dict(schema_version=2, authorization_id=auth['id'], logical_task_id=logical, **ref)
    task = request(client, 'POST', root + '/writing-requests', status=202, key=logical, json=payload)['task']
    replay = request(client, 'POST', root + '/writing-requests', key=logical, json=payload)
    assert replay['id'] == task['id']
    return task


def write(client, project, root, bundle, logical, paragraphs):
    task = queue_write(client, project, root, bundle, logical)
    provider = SciFixtureProvider(paragraphs)
    finished = run_manuscript_writing_task(task['id'], task['revision'], provider=provider)
    assert finished['status'] == 'succeeded', finished
    assert provider.posts == [bundle['wire_json']]
    return request(client, 'GET', root + '/writing-requests/' + task['id'])


def first_preview_at(task_id):
    with database_connection() as db:
        row = db.execute("SELECT draft_chat_json->>'first_preview_at' AS first_preview_at "
                         "FROM manuscript_writing_requests WHERE task_id=%s", (task_id,)).fetchone()
    return datetime.fromisoformat(row['first_preview_at'])


class ChatStreamFixture(SciFixtureProvider):
    def __init__(self, *, observe, prefix, paragraphs=None, advice=None):
        super().__init__(paragraphs or {})
        self.observe = observe
        self.prefix = prefix
        self.advice = advice

    def create_frozen_events(self, *, wire_json, execution_contract):
        assert execution_contract['response_stream'] and json.loads(wire_json)['stream']
        self.posts.append(wire_json)
        completed = self.receipt() if self.advice is None else LiveFixture.receipt(self)
        item = completed['response']['output'][0]['content'][0]
        if self.advice is not None:
            item['text'] = json.dumps({'advice': self.advice}, ensure_ascii=False)
        text = item['text']
        boundary = text.index(self.prefix) + len(self.prefix)
        yield 'receipt', dict(completed, status='in_progress', usage=None, response=dict(status='in_progress', output=[]))
        address = dict(item_id='fixture-message', output_index=1, content_index=0)
        yield 'delta', dict(address, sequence_number=2, delta=text[:1])
        yield 'delta', dict(address, sequence_number=3, delta=text[1:boundary])
        self.observe()
        yield 'delta', dict(address, sequence_number=4, delta=text[boundary:])
        yield 'receipt', completed


def test_customer_revises_generated_text_with_feedback_without_publishing_or_adding_materials(monkeypatch):
    # The first displayable delta follows the JSON opening in the same flush interval.
    monkeypatch.setattr('app.domain.manuscript_writing.draft_chat.monotonic', lambda: 1)
    with TestClient(app) as client, TestClient(app) as foreign:
        sign_in(client, 'revision@draft.test', 'customer')
        sign_in(foreign, 'other@draft.test', 'customer')
        project = sci_project(client)
        observation = 'The fixture shows a directional observation.'
        material = upload_docx(client, project, 'results.docx', observation)
        parse = material['task']
        assert run_parse_file_task(parse['id'], parse['revision'], parser=parse_docx)['status'] == 'succeeded'
        file_id = material['id']
        root, _ = create_fact(client, project, body(
            sources=[dict(kind='original', id=file_id, file_id=file_id, role='user_results')],
            reported_result=dict(text=observation, source_ids=[file_id])))
        selection = article_request('research', selected_source_ids=[file_id])
        preview = root + '/writing-previews'
        first = request(client, 'POST', preview, status=201, key='preview', json=selection)
        sections = json.loads(json.loads(first['wire_json'])['input'])['writing_scope']['output_section_ids']
        prose = {s: {'text': 'Synthetic ' + s.replace('_', ' ') + '.'} for s in sections}
        original = write(client, project, root, first, 'original', prose)
        assert set(request(client, 'GET', preview + '?capabilities_only=true')) == {'capabilities'}
        assert foreign.get(preview + '?capabilities_only=true').status_code == 404
        original_url = root + '/writing-requests/' + original['id']
        upload = {'file': ('comments.txt', b'Explain the comparison group.', 'text/plain')}
        assert foreign.post(original_url + '/draft-feedback', files=upload).status_code == 404
        feedback = request(client, 'POST', original_url + '/draft-feedback', files=upload)['text']
        assert feedback == 'Explain the comparison group.'
        assert [f['id'] for f in request(client, 'GET', project + '/files')] == [file_id]
        revise = selection | dict(revision_of_request_id=original['id'], instructions=feedback,
                                  target_sections=['abstract', 'discussion'])
        request(client, 'POST', preview, status=422, key='outside-scope',
                json=revise | dict(target_sections=['references']))
        second = request(client, 'POST', preview, status=201, key='revision-preview', json=revise)
        wire = json.loads(json.loads(second['wire_json'])['input'])
        assert wire['instructions'] == feedback
        assert [s['id'] for s in wire['original_draft']] == ['abstract', 'discussion']
        assert prose['title']['text'] not in second['wire_json']
        changed_text = 'The comparison group illustrates the reported pattern.'
        task = queue_write(client, project, root, second, 'revised')
        modified_url = root + '/writing-requests/' + task['id']
        prefix = 'The comparison group'

        def observe_revision():
            partial = request(client, 'GET', modified_url + '/draft-reader?revision=1')
            assert partial['status'] == 'running' and partial['draft'] is None
            assert dict(section_id='discussion', text=prefix) in partial['partial_reply']
            assert foreign.get(modified_url + '/draft-reader?revision=1').status_code == 404

        provider = ChatStreamFixture(observe=observe_revision, prefix=prefix,
                                     paragraphs=prose | {'discussion': {'text': changed_text}})
        finished = run_manuscript_writing_task(task['id'], task['revision'], provider=provider)
        assert finished['status'] == 'succeeded', finished
        assert provider.posts == [second['wire_json']] and provider.gets == []
        assert first_preview_at(task['id']).tzinfo is not None
        modified = request(client, 'GET', modified_url)
        assert original['id'] != modified['id'] and original['base_revision'] == modified['base_revision'] == 1
        assert original['published_revision'] is None and modified['published_revision'] is None
        assert request(client, 'GET', original_url)['candidate'] == original['candidate']
        assert modified['candidate']['writing_provenance']['verification_status'] == 'pending'
        assert modified['candidate']['sources'] == original['candidate']['sources']
        assert request(client, 'GET', root)['current_revision'] == 1
        first_read = request(client, 'GET', original_url + '/draft-reader?revision=1')
        assert first_read['previous_request_id'] is None and first_read['changes'] == []
        assert first_read['editable_section_ids'] == sections
        old_section = next(s for s in first_read['draft']['sections'] if s['id'] == 'discussion')
        assert old_section['paragraphs'][0]['parts'][0]['text'] == prose['discussion']['text']
        second_read = request(client, 'GET', root + '/writing-requests/' + modified['id'] + '/draft-reader?revision=1')
        assert second_read['previous_request_id'] == original['id']
        assert [c['section_id'] for c in second_read['changes']] == ['discussion']
        assert second_read['changes'][0]['before'] == [prose['discussion']['text']]
        assert second_read['changes'][0]['after'] == [changed_text]
        assert second_read['can_revise'] and second_read['editable_section_ids'] == sections
        assert 'partial_reply' not in second_read
        next_selection = revise | dict(revision_of_request_id=modified['id'], target_sections=['abstract'],
                                       instructions='Shorten the abstract.')
        third = request(client, 'POST', preview, status=201, key='follow-up-preview', json=next_selection)
        follow_up = write(client, project, root, third, 'follow-up', {'abstract': {'text': 'Shortened abstract.'}})
        assert [s for s in follow_up['candidate']['sections'] if s['id'] != 'abstract'] == [
            s for s in modified['candidate']['sections'] if s['id'] != 'abstract']

        advice_input = next_selection | dict(revision_of_request_id=follow_up['id'], target_sections=['discussion'],
                                             instructions='这段有什么问题？', draft_advice=True)
        advice_bundle = request(client, 'POST', preview, status=201, key='advice-preview', json=advice_input)
        advice_task = queue_write(client, project, root, advice_bundle, 'advice')
        advice_url = root + '/writing-requests/' + advice_task['id']
        advice_prefix = '说明对照组'
        editorial_reply = advice_prefix + '的定义，再交代比较的局限。'
        assert request(client, 'GET', project + '/sci-current-draft')['draft']['request_id'] == follow_up['id']

        def observe_advice():
            detail = request(client, 'GET', advice_url + '/draft-reader?revision=1')
            assert detail['draft_advice'] and detail['draft'] is None
            assert detail['partial_reply'] == [dict(section_id=None, text=advice_prefix)]

        provider = ChatStreamFixture(observe=observe_advice, prefix=advice_prefix, advice=editorial_reply)
        finished = run_manuscript_writing_task(advice_task['id'], advice_task['revision'], provider=provider)
        assert finished['status'] == 'succeeded', finished
        assert first_preview_at(advice_task['id']).tzinfo is not None
        advice = request(client, 'GET', advice_url + '/draft-reader?revision=1')
        assert advice['advice'] == editorial_reply and advice['draft'] is None and advice['changes'] == []
        assert request(client, 'GET', advice_url)['candidate'] is None
        assert request(client, 'GET', project + '/sci-current-draft')['draft']['request_id'] == follow_up['id']
        assert advice_task['id'] not in {item['request_id'] for item in request(client, 'GET', project + '/draft-history')['items']}
