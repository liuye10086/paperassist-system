from hashlib import sha256

from fastapi.testclient import TestClient

from app.adapters.pdf_parser import parse_pdf
from app.adapters.storage import ProjectStore
from app.auth.service import create_user
from app.core.config import get_data_dir
from app.db.database import database_connection
from app.domain.tasks.execution import run_task
from app.domain.tasks.file_parse_execution import run_parse_file_task
from app.main import app
from tests.api.test_customer_sci_workflow import sci_project, upload_docx
from tests.api.test_customer_thesis_permissions import drain_document_parse
from tests.api.test_customer_workspace import create_customer_project, sign_in
from tests.api.test_file_batches import register
from tests.api.test_literature_evidence import post
from tests.api.test_manuscripts import body
from tests.api.test_projects import upload as upload_workbook
from tests.api.test_research_writing_handoff import publish_candidate
from tests.api.test_review_rounds import edits
from tests.auth.test_account_roles import PASSWORD, login, write_headers
from tests.helpers.pdf_samples import pdf_bytes


def test_customer_review_routes_and_tasks_require_visible_fixed_inputs():
    with TestClient(app) as owner, TestClient(app) as other, TestClient(app) as analyst, TestClient(app) as admin:
        owner_id = sign_in(owner, 'b04-review-owner@example.test', 'customer')
        sign_in(other, 'b04-review-other@example.test', 'customer')
        analyst_id = sign_in(analyst, 'b04-review-analyst@example.test', 'analyst')
        admin_id = sign_in(admin, 'b04-review-admin@example.test', 'admin')
        legacy = ProjectStore(get_data_dir(), owner_id=owner_id).create_project('Legacy SCI', 'Synthetic study', 'sci')
        project = '/api/v1/projects/' + legacy['id']
        sibling = sci_project(owner)
        research = create_customer_project(owner)
        reviews = project + '/reviews'
        with database_connection(write=True) as db:
            db.execute('''INSERT INTO project_assignments(project_id,owner_id,analyst_id,revision,updated_by)
                VALUES (%s,%s,%s,1,%s)''', (legacy['id'], owner_id, analyst_id, admin_id))

        assert owner.get(reviews + '/inputs').status_code == 200
        assert owner.get(research + '/reviews/inputs').status_code == 403
        for outsider in (other, analyst, admin):
            assert outsider.get(reviews + '/inputs').status_code == 404
        assert analyst.get(project).status_code == 200

        base_file = upload_docx(owner, project, 'review-base.docx', 'Synthetic laboratory method.')
        opinions = upload_docx(owner, project, 'review-opinions.docx',
                               '1. Add an independent validation experiment.\n2. Recalculate the statistic using the revised data.')
        sibling_file = upload_docx(owner, sibling, 'review-foreign.docx', '1. Private material from another project.')
        for file in (base_file, opinions, sibling_file):
            drain_document_parse(file)

        response = post(owner, project + '/manuscripts', body(sources=[dict(
            id=base_file['id'], file_id=base_file['id'], kind='original', role='methods')]), 'fixed-base')
        assert response.status_code == 201, response.text
        draft = response.json()
        version = draft['versions'][0]
        assert run_task(version['task_id'], 1)['status'] == 'succeeded'
        parent_task = '/api/v1/tasks/' + version['task_id']
        assert owner.get(parent_task + '/workspace').status_code == 200

        def parsed(project_path, file):
            response = owner.get(f'{project_path}/files/{file["id"]}/document-versions')
            assert response.status_code == 200, response.text
            return response.json()['items'][0]['id']

        selection = dict(role='reviewer', label='Reviewer 1', format='document', file_id=opinions['id'],
                         document_version_id=parsed(project, opinions))
        request = dict(title='Synthetic review', project_type='sci', synthetic=False, materials=[], sources=[selection],
                       manuscript=dict(id=draft['id'], revision=1, version_id=version['id']))
        invalid_source = selection | {'document_version_id': parsed(sibling, sibling_file)}
        assert owner.post(reviews + '/sources/preview', json=invalid_source).status_code == 404
        assert owner.post(reviews + '/sources/preview', json=selection | {'role': 'defense'}).status_code == 422
        prefix, batch, item, content = register(owner, legacy, pdf_bytes([
            b'BT /F1 12 Tf 20 350 Td (1. Clarify existing methods.) Tj ET']), 'editor.pdf', key='editor-pdf')
        upload = owner.post(f'{prefix}/{batch["id"]}/items/{item["client_id"]}', files={'file': ('editor.pdf', content)})
        assert upload.status_code == 202, upload.text
        pdf = upload.json()
        assert run_parse_file_task(pdf['task']['id'], 1, parser=parse_pdf)['status'] == 'succeeded'
        options = owner.get(reviews + '/inputs').json()['documents']
        parsed_pdf = next(item for item in options if item['file_id'] == pdf['file_id'])
        source_pdf = selection | {'role': 'editor', 'file_id': pdf['file_id'], 'document_version_id': parsed_pdf['document_version_id']}
        preview = owner.post(reviews + '/sources/preview', json=source_pdf)
        assert preview.status_code == 200, preview.text
        assert preview.json()['supported'] is True and 'Clarify existing methods' in preview.json()['original_text']

        response = post(owner, reviews + '/rounds', request, 'review-round')
        assert response.status_code == 202, response.text
        saved = response.json()
        task_id = saved['task']['id']
        round_path = reviews + '/rounds/' + saved['id']
        task_path = '/api/v1/tasks/' + task_id
        assert post(owner, reviews + '/rounds', request, 'review-round').status_code == 200
        assert owner.get(sibling + '/reviews/rounds/' + saved['id']).status_code == 404
        for outsider in (other, analyst, admin):
            assert outsider.get(round_path).status_code == 404
            assert outsider.get(task_path + '/workspace').status_code == 404
        for operation in ('statistics-tasks', 'projection-tasks', 'plot-tasks', 'task-links', 'analysis-adoptions', 'figure-adoptions'):
            assert post(owner, round_path + '/' + operation, {}, operation).status_code == 403

        assert run_task(task_id, 1)['status'] == 'waiting_input'
        workspace = owner.get(task_path + '/workspace')
        assert workspace.status_code == 200, workspace.text
        assert workspace.json()['allowed_actions'] == ['resume']
        round = owner.get(round_path).json()
        assert round['items'][0]['status'] == 'waiting_material'
        assert round['items'][1]['status'] == 'waiting_material'
        assert [need['kind'] for need in round['items'][1]['needs']] == ['analysis']
        ungrounded = edits(round)
        ungrounded[1]['needs'] = []
        save = post(owner, round_path + '/plans', dict(expected_revision=round['revision'], items=ungrounded), 'requires-analysis')
        assert save.status_code == 201, save.text
        assert save.json()['items'][1]['status'] == 'waiting_material'

        supplement = dict(kind='document_version', file_id=pdf['file_id'], id=parsed_pdf['document_version_id'])
        grounded = edits(save.json())
        grounded[1].update(evidence_ids=[supplement['id']], needs=[])
        save = post(owner, round_path + '/plans', dict(expected_revision=save.json()['revision'], items=grounded,
                                                      materials=[supplement]), 'fixed-supplement')
        assert save.status_code == 201, save.text
        round = save.json()
        assert round['items'][1]['status'] in ('pending', 'waiting_confirmation')
        science = owner.get(round_path + '/science')
        assert science.status_code == 200, science.text
        assert science.json()['pending'] and science.json()['task_links'] == []
        assert owner.post(round_path + '/revisions/preview', json=dict(
            plan_revision=round['revision'], expected_current_revision=1, figure_adoption_ids=['not-published'],
        )).status_code == 403
        progress = dict(status='revision', event_date='2026-11-17', synthetic=True, round_id=saved['id'],
                        manuscript=request['manuscript'])
        outcome = post(owner, reviews + '/progress', progress, 'progress')
        assert outcome.status_code == 201, outcome.text
        assert post(owner, reviews + '/progress', progress, 'progress').json() == outcome.json()
        assert owner.get(reviews + '/progress').json()['current']['id'] == outcome.json()['id']
        resume = dict(operation='resume', wait_id=round['wait']['id'], expected_task_revision=round['task']['revision'],
                      input_version=round['task']['input_version'])
        response = post(owner, task_path + '/resume', resume, 'visible-resume')
        assert response.status_code == 202, response.text
        assert run_task(task_id, response.json()['revision'])['status'] == 'waiting_input'

        for file in (base_file, opinions):
            with database_connection(write=True) as db:
                db.execute('UPDATE files SET upload_actor_id=%s WHERE id=%s', (analyst_id, file['id']))
            for path in (round_path, round_path + '/science', task_path, task_path + '/events', task_path + '/workspace'):
                assert owner.get(path).status_code == 404, path
            assert post(owner, task_path + '/resume', resume, 'visible-resume').status_code == 404
            assert post(owner, reviews + '/rounds', request, 'review-round').status_code == 404
            assert owner.get(reviews + '/rounds').json()['items'] == []
            assert owner.get(reviews + '/progress').json()['items'] == []
            inputs = owner.get(reviews + '/inputs').json()
            assert file['id'] not in {item['file_id'] for item in inputs['documents']}
            if file == base_file:
                assert inputs['manuscripts'] == []
            with database_connection(write=True) as db:
                db.execute('UPDATE files SET upload_actor_id=%s WHERE id=%s', (owner_id, file['id']))

        queued = post(owner, reviews + '/rounds', request | {'title': 'Queue visibility check'}, 'recheck')
        assert queued.status_code == 202, queued.text
        with database_connection(write=True) as db:
            db.execute('UPDATE files SET upload_actor_id=%s WHERE id=%s', (analyst_id, opinions['id']))
        blocked = run_task(queued.json()['task']['id'], 1)
        assert blocked['status'] == 'failed'
        assert blocked['error_code'] == 'manuscript_source_not_visible'


def test_customer_review_keeps_fixed_research_bridge_sources(tmp_path, monkeypatch):
    email = 'b04-review-bridge@example.test'
    with TestClient(app) as client:
        owner = sign_in(client, email, 'analyst')
        project = sci_project(client)
        project_id = project.rsplit('/', 1)[-1]
        file = upload_workbook(client, project_id).json()['file']
        receipt = post(client, project + '/research-findings', dict(title='Fixed engineering fact', sources=[dict(
            source_kind='original_file', source_id=file['id'], locator=dict(kind='cell', sheet='研究数据', cell='B2'),
        )]), 'bridge-finding')
        assert receipt.status_code == 201, receipt.text
        delivery = client.get(project + '/research-intake').json()['deliveries'][0]
        base = publish_candidate(client, project, dict(delivery_id=delivery['id'], finding_version_ids=[receipt.json()['id']],
                                                       output_language='en'), tmp_path)
        manuscript = project + '/manuscripts/' + base['manuscript_id']
        old_export = post(client, manuscript + '/versions/1/exports', {}, 'bridge-original')
        assert old_export.status_code == 201, old_export.text
        assert run_task(old_export.json()['task_id'], 1)['status'] == 'succeeded'
        old_download = manuscript + '/exports/' + old_export.json()['id'] + '/download'
        old_word = client.get(old_download)
        assert old_word.status_code == 200 and old_word.content.startswith(b'PK')
        layout_identity = lambda: {'contract': 'test-v1'}
        monkeypatch.setattr('app.domain.layout_exports.service.renderer_identity', layout_identity)
        monkeypatch.setattr('app.domain.layout_exports.execution.renderer_identity', layout_identity)
        monkeypatch.setattr('app.domain.layout_exports.execution.prepare_layout_docx', lambda raw, *_args, **_kwargs: raw)
        layout_path = project + '/layout-exports'
        layout_request = dict(source_kind='manuscript_export', source_id=old_export.json()['id'],
                              request_key='layout-one', layout={'source_sha256': sha256(old_word.content).hexdigest()})
        layout = client.post(layout_path, json=layout_request)
        assert layout.status_code == 201, layout.text
        layout = layout.json()
        assert run_task(layout['task_id'], 1)['status'] == 'succeeded'

        with database_connection(write=True) as db:
            db.execute("UPDATE users SET role='customer' WHERE id=%s", (owner,))
        client.cookies.clear()
        session = login(client, email)
        assert session.status_code == 200, session.text
        client.headers.update(write_headers(session))

        reviews = project + '/reviews'
        payload = dict(title='Research fact wording', project_type='sci', synthetic=True,
                       manuscript=dict(id=base['manuscript_id'], revision=1, version_id=base['version_id']),
                       sources=[dict(role='reviewer', label='Reviewer', format='text', text='Clarify result wording.')])
        started = post(client, reviews + '/rounds', payload, 'bridge-round')
        assert started.status_code == 202, started.text
        task = started.json()['task']
        assert run_task(task['id'], task['revision'])['status'] == 'succeeded'
        path = reviews + '/rounds/' + started.json()['id']
        review = client.get(path).json()
        context = client.get(path + '/revision-context')
        assert context.status_code == 200, context.text
        context = context.json()
        source = next(entry for entry in context['evidence'] if entry['kind'] == 'research_finding_version')
        paragraph = next(loc for loc in context['locations'] if loc['section_id'] == 'results' and loc['kind'] == 'paragraph')
        text = paragraph['text'] + ' The fixed observation is reported here.'
        request = dict(plan_revision=review['revision'], expected_current_revision=1, operations=[dict(
            item_id=review['items'][0]['id'], kind='replace_paragraph', location_id=paragraph['id'], text=text,
            evidence_ids=[source['id']], reason='Clarify the fixed observation.',
        )])
        preview = client.post(path + '/revisions/preview', json=request)
        assert preview.status_code == 200 and preview.json()['can_adopt'], preview.text
        adopted = post(client, path + '/revisions', request | {'preview_sha256': preview.json()['preview_sha256']}, 'bridge-revision')
        assert adopted.status_code == 202, adopted.text
        task = adopted.json()['task']
        result = run_task(task['id'], task['revision'])
        assert result['status'] == 'succeeded', result
        revision = client.get(reviews + '/revisions/' + adopted.json()['id']).json()['result']
        assert run_task(revision['output']['task_id'], 1)['status'] == 'succeeded'
        updated = client.get(manuscript + '/versions/2')
        assert updated.status_code == 200, updated.text
        assert updated.json()['snapshot']['sources'][0]['id'] == source['id']
        assert updated.json()['snapshot']['research_bridge']['delivery_id'] == delivery['id']
        assert client.get(old_download).content == old_word.content
        new_export = post(client, manuscript + '/versions/2/exports', {}, 'bridge-word')
        assert new_export.status_code == 201, new_export.text
        assert run_task(new_export.json()['task_id'], 1)['status'] == 'succeeded'
        output = client.get(manuscript + '/exports/' + new_export.json()['id']).json()
        new_word = client.get(output['download_url'])
        assert new_word.status_code == 200 and new_word.content != old_word.content

        view = client.get('/api/v1/tasks/' + layout['task_id'] + '/workspace')
        assert view.status_code == 200, view.text
        assert view.json()['allowed_actions'] == []
        layout_download = view.json()['artifacts']['report']['download_url']
        assert client.get(layout_download).content == old_word.content
        assert client.post(layout_path, json=layout_request).status_code == 403
        assert client.post('/api/v1/tasks/' + layout['task_id'] + '/retry', json={'expected_revision': 1}).status_code == 404
        analyst_id = create_user('b04-legacy-private@example.test', PASSWORD, role='analyst')['id']
        with database_connection(write=True) as db:
            db.execute('UPDATE files SET upload_actor_id=%s WHERE id=%s', (analyst_id, file['id']))
        assert client.get(layout_download).status_code == 404
        assert client.get('/api/v1/tasks/' + layout['task_id'] + '/workspace').status_code == 404
