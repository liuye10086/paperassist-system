"""Two independently readable, unpublished customer drafts with a synthetic model."""
import json

from fastapi.testclient import TestClient

from app.adapters.docx_parser import parse_docx
from app.domain.manuscript_writing.execution import run_manuscript_writing_task
from app.domain.tasks.file_parse_execution import run_parse_file_task
from app.main import app
from tests.api.test_customer_sci_workflow import article_request, sci_project, upload_docx
from tests.api.test_customer_workspace import sign_in
from tests.api.test_manuscripts import body
from tests.integration.test_customer_sci_to_word import SciFixtureProvider, create_fact, request


def write(client, project, root, bundle, logical, paragraphs):
    ref = dict(bundle_id=bundle['id'], bundle_sha256=bundle['bundle_sha256'])
    auth = request(client, 'POST', project + '/writing-authorizations', status=201, key='auth-' + logical,
                   json=dict(schema_version=2, confirmed=True, tasks=[dict(logical_task_id=logical, bundles=[ref])]))
    payload = dict(schema_version=2, authorization_id=auth['id'], logical_task_id=logical, **ref)
    task = request(client, 'POST', root + '/writing-requests', status=202, key=logical, json=payload)['task']
    replay = request(client, 'POST', root + '/writing-requests', key=logical, json=payload)
    assert replay['id'] == task['id']
    provider = SciFixtureProvider(paragraphs)
    finished = run_manuscript_writing_task(task['id'], task['revision'], provider=provider)
    assert finished['status'] == 'succeeded', finished
    assert provider.posts == [bundle['wire_json']]
    return request(client, 'GET', root + '/writing-requests/' + task['id'])


def test_customer_revises_generated_text_with_feedback_without_publishing_or_adding_materials():
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
        original_url = root + '/writing-requests/' + original['id']
        upload = {'file': ('comments.txt', b'Explain the comparison group.', 'text/plain')}
        assert foreign.post(original_url + '/draft-feedback', files=upload).status_code == 404
        feedback = request(client, 'POST', original_url + '/draft-feedback', files=upload)['text']
        assert feedback == 'Explain the comparison group.'
        assert [f['id'] for f in request(client, 'GET', project + '/files')] == [file_id]
        revise = selection | dict(revision_of_request_id=original['id'], instructions=feedback)
        second = request(client, 'POST', preview, status=201, key='revision-preview', json=revise)
        wire = json.loads(json.loads(second['wire_json'])['input'])
        assert wire['instructions'] == feedback and wire['original_draft'][0]['paragraphs'][0]['text'] == prose['title']['text']
        changed_text = 'The comparison group illustrates the reported pattern.'
        modified = write(client, project, root, second, 'revised', prose | {'discussion': {'text': changed_text}})
        assert original['id'] != modified['id'] and original['base_revision'] == modified['base_revision'] == 1
        assert original['published_revision'] is None and modified['published_revision'] is None
        assert request(client, 'GET', original_url)['candidate'] == original['candidate']
        assert modified['candidate']['writing_provenance']['verification_status'] == 'pending'
        assert modified['candidate']['sources'] == original['candidate']['sources']
        assert request(client, 'GET', root)['current_revision'] == 1
        first_read = request(client, 'GET', original_url + '/draft-reader?revision=1')
        assert first_read['previous_request_id'] is None and first_read['changes'] == []
        old_section = next(s for s in first_read['draft']['sections'] if s['id'] == 'discussion')
        assert old_section['paragraphs'][0]['parts'][0]['text'] == prose['discussion']['text']
        second_read = request(client, 'GET', root + '/writing-requests/' + modified['id'] + '/draft-reader?revision=1')
        assert second_read['previous_request_id'] == original['id']
        assert [c['section_id'] for c in second_read['changes']] == ['discussion']
        assert second_read['changes'][0]['before'] == [prose['discussion']['text']]
        assert second_read['changes'][0]['after'] == [changed_text]
