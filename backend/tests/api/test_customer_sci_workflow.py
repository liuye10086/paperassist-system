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


def test_citation_candidates_and_todos_hide_quotes_from_invisible_materials():
    from app.domain.literature.execution import run_literature_task
    from tests.api.test_literature import create as create_search
    from tests.api.test_literature_citations import CitationNcbi
    from tests.api.test_literature_evidence import claim

    with TestClient(app) as customer, TestClient(app) as other:
        sign_in(customer, 'citation-reader@manuscript.test', 'customer')
        uploader = sign_in(other, 'citation-uploader@manuscript.test', 'customer')
        project = sci_project(customer)
        project_id = project.rsplit('/', 1)[-1]
        search = create_search(customer, project_id).json()
        assert run_literature_task(search['id'], search['revision'], client=CitationNcbi(2))['status'] == 'succeeded'
        literature = project + '/literature'
        reference = customer.get(literature + '/references').json()['items'][0]['id']
        evidence = literature + '/evidence'
        quote = 'A synthetic excerpt from a restricted report.'
        file = upload_docx(customer, project, 'restricted-report.docx', quote)
        task = file['task']
        assert run_parse_file_task(task['id'], task['revision'], parser=parse_docx)['status'] == 'succeeded'
        parse = customer.get(f"{project}/files/{file['id']}/document-versions").json()['items'][0]
        created = post(customer, evidence + '/materials', dict(project_reference_id=reference, file_id=file['id'],
            source_kind='document_version', version_id=parse['id'], source_description='Test material', match_note='Test link'))
        assert created.status_code == 201, created.text
        material = created.json()['id']
        source_url = f'{evidence}/materials/{material}/source'
        item = customer.get(source_url).json()['items'][0]['id']
        statement = claim(customer, evidence)
        excerpt = post(customer, f"{evidence}/claims/{statement['id']}/evidence", dict(
            claim_revision=statement['revision'], project_reference_id=reference, source_kind='material',
            material_id=material, item_id=item, quote=quote))
        assert excerpt.status_code == 201, excerpt.text

        candidates = literature + '/citations/candidates'
        assert quote in customer.get(candidates).text
        with database_connection(write=True) as db:
            db.execute('UPDATE files SET upload_actor_id=%s WHERE id=%s', (uploader, file['id']))

        assert customer.get(source_url).status_code == 404
        for url in (candidates, literature + '/citations/todos'):
            result = customer.get(url)
            assert result.status_code == 200, result.text
            visible = next(entry for entry in result.json()['items'] if entry['id'] == reference)
            assert visible['materials'] == []
            assert quote not in result.text


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


def test_planned_review_heading_language_is_checked_before_writing():
    with TestClient(app) as client:
        sign_in(client, 'sci-heading@manuscript.test', 'customer')
        project = sci_project(client, 'narrative_review')
        plan = client.get(project + '/manuscripts/candidates').json()['paper_plan']
        mismatch = post(client, project + '/manuscripts/preview', body(
            title=plan['title'], output_language='zh-CN', paper_plan_token=plan['token']), 'review-preview')
        assert mismatch.status_code == 422
        assert mismatch.json()['detail']['code'] == 'manuscript_review_heading_language'
        response = post(client, project + '/manuscripts', body(
            title=plan['title'], paper_plan_token=plan['token']), 'review-base')
        assert response.status_code == 201, response.text
        draft = response.json()
        assert run_task(draft['versions'][0]['task_id'], 1)['status'] == 'succeeded'
        path = project + '/manuscripts/' + draft['id'] + '/writing-previews'
        response = post(client, path, article_request('narrative_review', output_language='zh-CN'), 'language-mismatch')
        assert response.status_code == 422
        assert response.json()['detail']['code'] == 'manuscript_review_heading_language'
        assert client.get(path).json()['items'] == []


def test_excel_paper_material_freezes_selected_sheet_display_and_exact_values():
    from uuid import uuid4
    from openpyxl import Workbook
    from app.adapters.excel import parse_workbook
    from app.core.config import ExcelSettings

    book = Workbook()
    book.active.title = 'Results'
    book.active.append(['Group', 'Proportion'])
    book.active.append(['A', 0.5])
    book.active['B2'].number_format = '0.00%'
    book.create_sheet('Working notes').append(['Internal notes', '=1+1'])
    book.create_sheet('Hidden').sheet_state = 'hidden'
    buf = BytesIO()
    book.save(buf)
    with TestClient(app) as client:
        sign_in(client, 'sci-worksheet@manuscript.test', 'customer')
        project = sci_project(client)
        base, batch, item, raw = register(client, {'id': project.rsplit('/', 1)[-1]}, buf.getvalue(), 'proportions.xlsx')
        upload = client.post(f"{base}/{batch['id']}/items/{item['client_id']}", files={'file': ('proportions.xlsx', raw)})
        assert upload.status_code == 202, upload.text
        file_id = upload.json()['file_id']
        task = upload.json()['task']
        def excel_parser(content, filename, settings):
            return parse_workbook(content, filename, ExcelSettings.model_validate(settings['excel']))
        assert run_parse_file_task(task['id'], task['revision'], parser=excel_parser)['status'] == 'succeeded'
        materials = project + '/paper-materials'
        preview = client.get(f'{materials}/worksheets/{file_id}')
        assert preview.status_code == 200, preview.text
        assert [(row['name'], row['values_ready']) for row in preview.json()['sheets']] == [
            ('Results', True), ('Working notes', False)]
        assert preview.json()['sheets'][0]['preview_rows'] == [['A', '50.00%']]
        target = client.get(materials).json()['targets'][0]['id']
        note_url = f'{materials}/{uuid4()}'
        note = dict(expected_revision=0, file_id=file_id, result='Observed proportions', target_id=target)
        assert client.put(note_url, json=note).status_code == 422
        saved = client.put(note_url, json=note | {'worksheet_names': ['Results']})
        assert saved.status_code == 200, saved.text
        assert client.put(note_url, json=note | {'worksheet_names': ['Results']}).json() == saved.json()
        plan = client.get(project + '/manuscripts/candidates').json()['paper_plan']
        response = post(client, project + '/manuscripts', body(
            title=plan['title'], paper_plan_token=plan['token']), 'selected-table')
        assert response.status_code == 201, response.text
        manuscript = response.json()
        version = manuscript['versions'][0]
        [table] = version['snapshot']['results_groups'][0]['tables']
        assert table['rows'] == [['A', '50.00%']]
        assert table['numeric_cells'] == [{'row': 1, 'column': 1, 'value': '0.5', 'number_format': '0.00%'}]
        assert 'Working notes' not in json.dumps(version['snapshot']['paper_plan'])
        assert run_task(version['task_id'], 1)['status'] == 'succeeded'
        root = f"{project}/manuscripts/{manuscript['id']}"
        writing = post(client, root + '/writing-previews', article_request(
            'research', selected_source_ids=[file_id]), 'worksheet-writing-preview')
        assert writing.status_code == 201, writing.text
        wire = json.loads(json.loads(writing.json()['wire_json'])['input'])
        rows = next(row['values'] for row in wire['numeric_context'] if row['location'] == 'illustrations[0].table_cells')
        assert rows == [dict(fact_path='/rows/0/1', value='50.00', display_text='50.00%')]
        word = post(client, root + '/versions/1/exports', {}, 'selected-table-word')
        assert word.status_code == 201, word.text
        assert run_task(word.json()['task_id'], 1)['status'] == 'succeeded'
        content = client.get(f"{root}/exports/{word.json()['id']}/download").content
        [table] = Document(BytesIO(content)).tables
        assert [cell.text for cell in table.rows[1].cells] == ['A', '50.00%']


def test_figures_and_panels_use_frozen_file_numbers_across_findings():
    from uuid import uuid4
    from PIL import Image

    with TestClient(app) as client:
        sign_in(client, 'sci-figure-binding@manuscript.test', 'customer')
        settings = SCI_SETTINGS | {'figure_findings': [
            {'id': 'finding-1', 'finding': 'Initial measurements'},
            {'id': 'finding-2', 'finding': 'Later measurements (Figure 2A).'},
        ]}
        project = project_path(create(client, 'numbering', **project_body('sci', sci_settings=settings)))
        materials = project + '/paper-materials'
        targets = client.get(materials).json()['targets']
        ids = []
        for index, target in enumerate([targets[0], targets[0], targets[1]]):
            raw = BytesIO()
            Image.new('RGB', (24, 24), (index * 70, 0, 0)).save(raw, format='PNG')
            filename = f'observations-{index}.png'
            base, batch, item, content = register(client, {'id': project.rsplit('/', 1)[-1]}, raw.getvalue(), filename, filename)
            upload = client.post(f"{base}/{batch['id']}/items/{item['client_id']}", files={'file': (filename, content)})
            assert upload.status_code == 202, upload.text
            ids.append(upload.json()['file_id'])
            saved = client.put(f'{materials}/{uuid4()}', json=dict(
                expected_revision=0, file_id=ids[-1], result='Synthetic observation', target_id=target['id']))
            assert saved.status_code == 200, saved.text

        plan = client.get(project + '/manuscripts/candidates').json()['paper_plan']
        preview = post(client, project + '/manuscripts/preview', body(
            title=plan['title'], paper_plan_token=plan['token'], figure_notes=[
                dict(figure_id=ids[-1], caption='', panels=[{'label': 'A', 'description': 'Later sample'}])]), 'numbering')
        assert preview.status_code == 200, preview.text
        first, second = preview.json()['results_groups']
        assert len(first['figures']) == 2
        assert [f['number'] for f in first['figures']] == [1, 2]
        assert second['figures'][0]['number'] == 3
        finding = second['paragraphs'][0]
        assert finding['text'] == 'Later measurements (Figure 3A).'
        assert finding['cross_references'] == [
            dict(kind='figure', target_id=ids[-1], number=3, panel_label='A')]


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
