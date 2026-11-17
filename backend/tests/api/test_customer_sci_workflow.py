import json
from io import BytesIO

from docx import Document
from fastapi.testclient import TestClient

from app.adapters.docx_parser import parse_docx
from app.core.exceptions import StorageError
from app.db.database import database_connection
from app.domain.tasks.execution import run_task
from app.domain.tasks.file_parse_execution import run_parse_file_task
from app.main import app
from tests.api.test_customer_project_types import SCI_SETTINGS, create, project_body, project_path
from tests.api.test_customer_workspace import create_customer_project, sign_in
from tests.api.test_file_batches import register
from tests.api.test_literature_evidence import post
from tests.api.test_manuscripts import body


def sci_project(client, kind='research', key='sci'):
    settings = SCI_SETTINGS.copy()
    if kind == 'narrative_review':
        settings['article_type'] = kind
        settings.pop('figure_findings')
        settings['review_sections'] = [dict(id='synthetic-section-1', heading='Research themes', content='Synthetic scope')]
    return project_path(create(client, key, **project_body('sci', sci_settings=settings)))


def upload_docx(client, project, filename, text):
    document = Document()
    document.add_paragraph(text)
    content = BytesIO()
    document.save(content)
    base, batch, item, raw = register(client, {'id': project.rsplit('/', 1)[-1]}, content.getvalue(), filename, key=filename)
    response = client.post(base + '/' + batch['id'] + '/items/' + item['client_id'], files={'file': (filename, raw)})
    assert response.status_code == 202, response.text
    return {'id': response.json()['file_id'], 'task': response.json()['task']}


def article_request(kind, **extra):
    return dict(schema_version=4, document_kind='sci', article_type=kind, base_revision=1,
                mode='full_draft', output_language='en', selected_source_ids=[], selected_evidence_ids=[]) | extra


def test_sci_customer_routes_are_owner_project_and_material_scoped():
    with TestClient(app) as owner, TestClient(app) as other:
        sign_in(owner, 'sci-b02-owner@manuscript.test', 'customer')
        actor = sign_in(other, 'sci-b02-foreign@manuscript.test', 'customer')
        sci = sci_project(owner)
        analysis = create_customer_project(owner)
        thesis = project_path(create(owner, 'thesis', **project_body('thesis')))
        visible = upload_docx(owner, sci, 'visible.docx', 'User-supplied result.')
        hidden = upload_docx(owner, sci, 'private.docx', 'Unreleased analyst material.')
        with database_connection(write=True) as db:
            db.execute('UPDATE files SET upload_actor_id=%s WHERE id=%s', (actor, hidden['id']))

        path = '/manuscripts/candidates'
        response = owner.get(sci + path)
        assert response.status_code == 200, response.text
        assert {item['file_id'] for item in response.json()['items']} == {visible['id']}
        assert other.get(sci + path).status_code == 404
        assert owner.get(analysis + path).status_code == 403
        assert owner.get(thesis + path).status_code == 200
        assert owner.get(thesis + '/journals/config').status_code == 403
        assert owner.get(sci + '/literature/evidence/material-options').json()['items'][0]['file_id'] == visible['id']
        forbidden_source = dict(kind='original', id=hidden['id'], file_id=hidden['id'], role='user_results')
        assert post(owner, sci + '/manuscripts/preview', body(sources=[forbidden_source]), 'hidden').status_code == 404
        assert owner.get(sci + f'/files/{hidden["id"]}/document-versions').status_code == 404
        assert owner.get(sci + '/reviews/rounds').status_code == 200
        for suffix in ('/thesis-profile', '/pdf-exports', '/journals/submission-events'):
            assert owner.get(sci + suffix).status_code == 403


def test_research_preview_carries_reported_results_with_current_fixed_sources():
    with TestClient(app) as client, TestClient(app) as other:
        sign_in(client, 'sci-b02-reported@manuscript.test', 'customer')
        private_actor = sign_in(other, 'sci-b02-private@manuscript.test', 'customer')
        sci = sci_project(client)
        result = 'The synthetic cohort included 4 observations.'
        material = upload_docx(client, sci, 'research-results.docx', result)
        parse_task = material['task']
        assert run_parse_file_task(parse_task['id'], parse_task['revision'], parser=parse_docx)['status'] == 'succeeded'
        file_id = material['id']
        selected = dict(kind='original', id=file_id, file_id=file_id, role='user_results')
        reported = dict(text=result, source_ids=[file_id])
        request = body(sources=[selected], reported_result=reported)
        response = post(client, sci + '/manuscripts', request, 'reported-draft')
        assert response.status_code == 201, response.text
        draft = response.json()
        version = draft['versions'][0]
        groups = version['snapshot']['results_groups']
        paragraph = next(paragraph for group in groups for paragraph in group['paragraphs'])
        assert paragraph['origin'] == 'user_provided' and paragraph['source_ids'] == [file_id]
        assert result in paragraph['text']
        assert run_task(version['task_id'], 1)['status'] == 'succeeded'
        root = sci + '/manuscripts/' + draft['id']
        url = root + '/writing-previews'
        assert post(client, url, article_request('research'), 'missing-evidence').status_code == 422
        assert post(client, url, article_request('narrative_review'), 'wrong-type').status_code == 422
        approved = article_request('research', selected_source_ids=[file_id])
        preview = post(client, url, approved, 'research-preview')
        assert preview.status_code == 201, preview.text
        assert preview.json()['execution_contract']['article_instruction_revision'] == 'sci-article-prose-v2'
        wire = json.loads(preview.json()['wire_json'])
        paragraphs = wire['text']['format']['schema']['$defs']['LiveSection']['properties']['paragraphs']
        assert paragraphs.get('minItems') == 1
        assert 'ordinary manuscript prose' in wire['instructions']
        assert 'Never invent results, methods, citations or literature claims' in wire['instructions']
        payload = json.loads(wire['input'])
        assert payload['sources'][0]['facts'] == []
        assert any(result in item['text'] for section in payload['context'] if section['id'] == 'results'
                   for item in section['paragraphs'])
        assert post(client, url, approved, 'research-preview').json() == preview.json()
        offline = dict(mode='full_draft', base_revision=1)
        assert post(client, root + '/writing-requests', offline, 'offline').status_code == 403

        with database_connection(write=True) as db:
            db.execute('UPDATE files SET upload_actor_id=%s WHERE id=%s', (private_actor, file_id))
        assert client.get(url + '/' + preview.json()['id']).status_code == 404
        assert client.get(url).json()['items'] == []


def test_narrative_review_without_verified_citations_cannot_prepare_writing():
    with TestClient(app) as client:
        sign_in(client, 'sci-b02-review@manuscript.test', 'customer')
        sci = sci_project(client, 'narrative_review')
        response = post(client, sci + '/manuscripts', body(), 'review-base')
        assert response.status_code == 201, response.text
        draft = response.json()
        assert run_task(draft['versions'][0]['task_id'], 1)['status'] == 'succeeded'
        path = sci + '/manuscripts/' + draft['id'] + '/writing-previews'
        response = post(client, path, article_request('narrative_review'), 'missing-literature')
        assert response.status_code == 422
        assert response.json()['detail']['code'] == 'manuscript_writing_evidence_required'


def test_sci_customer_retries_failed_word_with_its_fixed_input(monkeypatch):
    with TestClient(app) as client:
        sign_in(client, 'sci-b02-word-retry@manuscript.test', 'customer')
        sci = sci_project(client)
        response = post(client, sci + '/manuscripts', body(), 'fact')
        assert response.status_code == 201, response.text
        manuscript = response.json()
        version = manuscript['versions'][0]
        assert run_task(version['task_id'], 1)['status'] == 'succeeded'
        root = sci + '/manuscripts/' + manuscript['id']
        response = post(client, root + '/versions/1/exports', {}, 'word')
        assert response.status_code == 201, response.text
        export = response.json()

        def render_failed(*args, **kwargs):
            raise StorageError('report_render_failed', 'Synthetic first attempt failure.', 422)

        with monkeypatch.context() as patch:
            patch.setattr('app.adapters.manuscript_docx.build_manuscript_docx', render_failed)
            assert run_task(export['task_id'], 1)['status'] == 'failed'

        task_path = '/api/v1/tasks/' + export['task_id']
        response = client.get(task_path + '/workspace')
        assert response.status_code == 200, response.text
        workspace = response.json()
        task = workspace['task']
        assert 'retry' in workspace['allowed_actions']
        assert task['input_version']['manuscript_version_id'] == version['id']
        resume = dict(operation='retry', wait_id=None, expected_task_revision=task['revision'], input_version=task['input_version'])
        response = post(client, task_path + '/resume', resume, 'retry-word')
        assert response.status_code == 202, response.text
        queued = response.json()
        assert post(client, task_path + '/resume', resume, 'retry-word').json() == queued
        assert run_task(queued['id'], queued['revision'])['status'] == 'succeeded'
        saved = client.get(root + '/exports/' + export['id']).json()
        assert saved['version_id'] == version['id']
        assert client.get(saved['download_url']).status_code == 200
