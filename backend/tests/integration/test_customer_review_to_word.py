"""Exercise customer-owned manuscript revision, Word and next-round contracts."""

from hashlib import sha256
from io import BytesIO

from docx import Document
from fastapi.testclient import TestClient
import pytest

from app.domain.tasks.execution import run_task
from app.db.database import database_connection
from app.domain.manuscripts.school_changes import SchoolChangeService
from app.main import app
from tests.api.test_customer_sci_workflow import sci_project
from tests.api.test_customer_workspace import sign_in
from tests.api.test_manuscripts import body
from tests.api.test_review_continuations import next_request
from tests.api.test_review_rounds import upload_parsed
from tests.domain.test_school_writing_live import synthetic_layout_cache
from tests.integration.test_customer_sci_to_word import DOCX, create_fact, request, upload_research_material
from tests.integration.test_customer_thesis_to_word import (
    AUTHOR, DECLARATION, METHOD, SCHOOL, TITLE, export_word, freeze_citation, parse_template, review_language_and_freeze,
    review_science, school_options, start_template, template_confirmation, thesis_request,
    upload_illustration, write_candidate,
)


def sci_parent(client):
    project = sci_project(client)
    source, _, _ = upload_research_material(client, project)
    root, _ = create_fact(client, project, body(
        sources=[source], methods={'study_design': 'The method uses the supplied engineering records.'},
        method_source_ids={'study_design': [source['id']]},
    ))
    base = request(client, 'GET', root + '/versions/1')
    return project, root, base, {}


def thesis_parent(client):
    draft = request(client, 'POST', '/api/v1/projects', status=201, key='b04-thesis', json=dict(
        name=TITLE, research_topic='合成返修工程验收', project_type='thesis',
    ))
    project = '/api/v1/projects/' + draft['id']
    profile = request(client, 'PUT', project + '/thesis-profile', json=dict(
        expected_revision=0, school=SCHOOL, department='合成院系', major='工程核验',
        degree_type='学术学位', education_level='硕士', applicable_version='测试版',
    ))
    template = parse_template(client, project, start_template(client, project, 'b04-v1'))
    confirmation = request(client, 'POST', project + '/school-templates/' + template['id'] + '/confirm',
                           status=201, key='confirm-template', json=template_confirmation(template))
    profile = request(client, 'POST', project + '/thesis-template-binding', json=dict(
        confirmation_id=confirmation['id'], expected_revision=profile['revision'],
    ))
    sources, _ = upload_illustration(client, project)
    citation_draft, citation = freeze_citation(client, project)
    groups = [dict(id='fixture-figure', title='合成图片观察', analysis_run_ids=[], figure_ids=[sources[1]['id']])]
    data = thesis_request(confirmation, profile, sources=sources, methods=dict(study_design=METHOD),
                          method_source_ids=dict(study_design=[sources[0]['id']]),
                          citation_draft=dict(id=citation_draft['id'], revision=1), results_groups=groups)
    root, _ = create_fact(client, project, data)
    path, context = write_candidate(client, root, sources, citation_draft, citation[-1])
    science = review_science(client, path, context, citation)
    options = school_options(confirmation['chapters'])
    base = review_language_and_freeze(client, root, path, science, options)
    return project, root, base, {'school': options}


def start_round(client, reviews, root, base, *, thesis):
    version = dict(id=root.rsplit('/', 1)[-1], revision=base['revision'], version_id=base['id'])
    inputs = request(client, 'GET', reviews + '/inputs')
    available = next(m for m in inputs['manuscripts'] if m['id'] == version['id'])
    assert any(v['id'] == base['id'] and v['status'] == 'published' for v in available['versions'])
    if thesis:
        sources = [dict(role='advisor', label='合成导师', format='text', text='请澄清绪论措辞。'),
                   dict(role='evaluator', label='合成评阅', format='text', text='请保留现有局限性说明。'),
                   dict(role='defense', label='合成答辩', format='text', text='请补做独立实验。')]
        confirmation = base['snapshot']['thesis_context']['confirmation_id']
    else:
        sources = [dict(role='editor', label='Synthetic editor', format='text', text='Clarify the method wording.'),
                   dict(role='reviewer', label='Synthetic reviewer', format='text', text='Add an independent experiment.')]
        confirmation = None
    body = dict(title='合成返修轮次', project_type='thesis' if thesis else 'sci', synthetic=True,
                manuscript=version, sources=sources, materials=[], school_confirmation_id=confirmation)
    started = request(client, 'POST', reviews + '/rounds', status=202, key='b04-round', json=body)
    replay = request(client, 'POST', reviews + '/rounds', key='b04-round', json=body)
    assert started['id'] == replay['id'] and started['task']['id'] == replay['task']['id']
    assert run_task(started['task']['id'], 1)['status'] == 'waiting_input'
    path = reviews + '/rounds/' + started['id']
    review = request(client, 'GET', path)
    item, *_, pending = review['items']
    assert review['manuscript']['version_id'] == base['id'] and pending['status'] == 'waiting_material'
    assert item['original_text'] == sources[0]['text']
    request(client, 'POST', path + '/decisions', status=201, key='b04-decision', json=dict(
        expected_revision=review['revision'], decisions=[dict(item_id=item['id'], action='accept', reason='核对固定稿与依据')],
    ))
    return path, request(client, 'GET', path)


def adopt_revision(client, reviews, path, root, base, review, *, thesis):
    context = request(client, 'GET', path + '/revision-context')
    section_id = next(s['id'] for s in base['snapshot']['sections'] if s['purpose'] == 'introduction') if thesis else 'materials_and_methods'
    location = next(row for row in context['locations'] if row['section_id'] == section_id and row['kind'] == 'paragraph')
    text = location['text'] + (' 该说明限于所提供的合成材料。' if thesis else ' The description remains limited to the supplied materials.')
    operations = [dict(item_id=review['items'][0]['id'], kind='replace_paragraph', location_id=location['id'],
                       text=text, evidence_ids=[context['evidence'][0]['id']], reason='核对指定材料后澄清现有表述。')]
    body = dict(plan_revision=review['revision'], expected_current_revision=context['expected_current_revision'], operations=operations)
    preview = request(client, 'POST', path + '/revisions/preview', json=body)
    assert preview['can_adopt'], preview
    assert preview['actual_changes'][0]['after'] == text
    run = request(client, 'POST', path + '/revisions', status=202, key='b04-adopt',
                  json=body | {'preview_sha256': preview['preview_sha256']})
    assert run_task(run['task']['id'], 1)['status'] == 'succeeded'
    run_path = reviews + '/revisions/' + run['id']
    output = request(client, 'GET', run_path)['result']['output']
    assert run_task(output['task_id'], 1)['status'] == 'succeeded'
    run = request(client, 'GET', run_path)
    assert run['result']['items'][0]['status'] == 'completed'
    assert run['result']['items'][-1]['status'] == 'waiting_material'
    fixed = request(client, 'GET', root + '/versions/' + str(output['revision']))
    assert fixed['parent_version_id'] == base['id']
    assert fixed['snapshot'].get('thesis_context') == base['snapshot'].get('thesis_context')
    return run, fixed, text


def export_review_document(client, reviews, run, kind, expected_text, monkeypatch, *, interrupt=False):
    document = request(client, 'POST', reviews + '/revisions/' + run['id'] + '/documents', status=201,
                       key='create-' + kind, json={'kind': kind})
    path = reviews + '/documents/' + document['id']
    request(client, 'POST', path + '/confirm', key='confirm-' + kind, json={'expected_version': document['version']})
    export = request(client, 'POST', path + '/exports', status=202, key='export-' + kind, json={})
    task = '/api/v1/tasks/' + export['task_id']
    attempt = 1
    if interrupt:
        def fail(_):
            raise OSError('Interrupted isolated Word export')

        with monkeypatch.context() as isolated:
            isolated.setattr('app.domain.review_rounds.document_execution.render_review_document', fail)
            assert run_task(export['task_id'], attempt)['status'] == 'failed'
        failed = request(client, 'GET', task)
        retry = request(client, 'POST', task + '/retry', status=202, json={'expected_revision': failed['revision']})
        attempt = retry['revision']
        request(client, 'POST', task + '/retry', status=409, json={'expected_revision': failed['revision']})
    assert run_task(export['task_id'], attempt)['status'] == 'succeeded'
    saved = request(client, 'GET', reviews + '/document-exports/' + export['id'])
    downloaded = client.get(saved['download_url'])
    assert downloaded.status_code == 200 and downloaded.headers['Content-Type'] == DOCX
    assert sha256(downloaded.content).hexdigest() == saved['sha256']
    rendered = Document(BytesIO(downloaded.content))
    paragraphs = ' '.join(p.text for p in rendered.paragraphs)
    tables = ' '.join(cell.text for table in rendered.tables for row in table.rows for cell in row.cells)
    assert expected_text in paragraphs + ' ' + tables
    expected_status = 'Status: Awaiting additional material' if document['language'] == 'en' else '处理状态：待补材料'
    assert expected_status in paragraphs
    assert saved['filename'] == document['snapshot']['title'] + '.docx'
    assert not any(marker in paragraphs for marker in (
        'SHA-256', 'Document version', 'Final manuscript version', '独立文档版本',
        '最终稿件版本', 'Synthetic engineering material', '合成工程材料', run['id'], document['id'],
    ))
    task_view = request(client, 'GET', task + '/workspace')
    assert task_view['task']['input_version']['document_id'] == document['id']
    return saved, downloaded.content


def return_and_continue(client, reviews, path, review, root, run, fixed, exported, raw, text, *, thesis):
    doc = Document(BytesIO(raw))
    paragraph = next(p for p in doc.paragraphs if p.text == text)
    paragraph.runs[-1].text += ' 已补充普通说明。' if thesis else ' The customer supplied an extra wording clarification.'
    buffer = BytesIO()
    doc.save(buffer)
    source = upload_parsed(client, review['project_id'], buffer.getvalue(), 'b04-revised-return.docx')
    payload = dict(manuscript=dict(id=root.rsplit('/', 1)[-1], revision=fixed['revision'], version_id=fixed['id']),
                   revision_id=run['id'], file_id=source['file_id'], document_version_id=source['document_version_id'],
                   base_export_id=exported['id'], synthetic=True)
    saved = request(client, 'POST', path + '/returns', status=201, key='b04-return', json=payload)
    assert saved['can_adopt'], saved['issues']
    return_path = reviews + '/returns/' + saved['id']
    preview = request(client, 'POST', return_path + '/preview', json={'mappings': saved['mappings']})
    assert preview['can_adopt'] and any(change['kind'] == 'text_changed' for change in preview['differences'])
    output = request(client, 'POST', return_path + '/adopt', status=201, key='b04-return-adopt', json=dict(
        mappings=saved['mappings'], expected_current_revision=fixed['revision'], preview_sha256=preview['preview_sha256'],
    ))['output']
    selection = dict(id=output['version_id'], revision=output['revision'])
    following = next_request(review, selection, return_id=saved['id'])
    request(client, 'POST', reviews + '/rounds', status=409, key='before-return-published', json=following)
    assert run_task(output['task_id'], 1)['status'] == 'succeeded'
    continued = request(client, 'POST', reviews + '/rounds', status=202, key='b04-next', json=following)
    assert run_task(continued['task']['id'], 1)['status'] == 'succeeded'
    assert continued['manuscript']['version_id'] == output['version_id']
    assert continued['continuation']['user_return_id'] == saved['id']
    assert client.get(saved['original_download_url']).content == buffer.getvalue()
    return saved


@pytest.mark.parametrize('kind', ['sci', 'thesis', 'thesis-legacy-migration'])
def test_customer_review_revises_exports_and_starts_next_round(kind, monkeypatch):
    thesis = kind != 'sci'
    monkeypatch.setattr('app.adapters.pdf_renderer.update_layout_fields', synthetic_layout_cache)
    with TestClient(app) as client, TestClient(app) as other:
        sign_in(client, f'{kind}-b04-revision@manuscript.test', 'customer')
        other_id = sign_in(other, 'b04-foreign@manuscript.test', 'customer')
        project, root, base, school = (thesis_parent if thesis else sci_parent)(client)
        original_export, original = export_word(client, root, base, school, 'b04-original')
        reviews = project + '/reviews'
        path, review = start_round(client, reviews, root, base, thesis=thesis)
        run, fixed, text = adopt_revision(client, reviews, path, root, base, review, thesis=thesis)
        revised, raw = export_word(client, root, fixed, {}, 'b04-revised')
        assert raw != original
        revised_doc = Document(BytesIO(raw))
        paragraphs = {p.text for p in revised_doc.paragraphs}
        assert text in paragraphs
        names = {'en': ('Revised manuscript.docx', 'Revised thesis.docx'),
                 'zh-CN': ('SCI论文修订稿.docx', '毕业论文修订稿.docx')}
        assert revised['filename'] == names[fixed['snapshot']['output_language']][thesis]
        assert not any(fixed['id'] in p or '学校论文工程稿' in p or 'School thesis engineering draft' in p for p in paragraphs)
        if thesis:
            assert revised_doc.styles['Normal'].font.size.pt == 14
            assert {METHOD, DECLARATION, '作者姓名：' + AUTHOR, '目录', 'Abstract'} <= paragraphs
            assert fixed['snapshot']['references'] == base['snapshot']['references']
        comparison, comparison_bytes = export_review_document(client, reviews, run, 'comparison', text, monkeypatch, interrupt=not thesis)
        if thesis:
            request(client, 'POST', reviews + '/revisions/' + run['id'] + '/documents', status=422,
                    key='invalid-thesis-reply', json={'kind': 'reply'})
        else:
            export_review_document(client, reviews, run, 'reply', text, monkeypatch)
        returned = return_and_continue(client, reviews, path, review, root, run, fixed, revised, raw, text, thesis=thesis)
        for url in (path, reviews + '/revisions/' + run['id'], comparison['download_url'], revised['download_url'],
                    returned['original_download_url'], '/api/v1/tasks/' + run['task']['id'] + '/workspace'):
            assert other.get(url).status_code == 404
        assert client.get(original_export['download_url']).content == original
        assert client.get(revised['download_url']).content == raw
        assert client.get(comparison['download_url']).content == comparison_bytes
        assert client.post(project + '/pdf-exports', json={}).status_code == 405
        if thesis:
            migrate_returned_thesis(client, project, root, revised, raw, monkeypatch, other_id,
                                    inherited_return=kind == 'thesis-legacy-migration')


def migrate_returned_thesis(client, project, root, historical_export, historical_bytes, monkeypatch, other_id, *, inherited_return):
    parent = request(client, 'GET', root)['versions'][0]
    snapshot = parent['snapshot']
    assert snapshot['user_return_provenance']['return_id']
    if inherited_return:
        # The original migration writer retained its parent's return proof. Seal
        # the old shape through the normal registration, preview and adoption.
        candidate = SchoolChangeService.candidate
        def legacy_candidate(service, db, row, mappings):
            result = candidate(service, db, row, mappings)
            result[0]['user_return_provenance'] = snapshot['user_return_provenance']
            return result
        monkeypatch.setattr(SchoolChangeService, 'candidate', legacy_candidate)
    templates = project + '/school-templates'
    new = parse_template(client, project, start_template(client, project, 'after-return',
                         previous=snapshot['thesis_context']['template_version_id'], updated=True))
    confirmation = request(client, 'POST', templates + '/' + new['id'] + '/confirm', status=201,
                           key='confirm-after-return', json=template_confirmation(new))
    profile = request(client, 'GET', project + '/thesis-profile')
    request(client, 'POST', project + '/thesis-template-binding', json=dict(
        expected_revision=profile['revision'], confirmation_id=confirmation['id']))
    change = request(client, 'POST', root + f"/versions/{parent['revision']}/school-changes", status=201,
                     key='migrate-after-return', json=dict(kind='template_migration', target_confirmation_id=confirmation['id']))
    path = root + '/school-changes/' + change['id']
    preview = request(client, 'POST', path + '/preview', json=dict(mappings=change['mappings']))
    assert preview['can_adopt'], preview['issues']
    adoption = dict(mappings=preview['mappings'], expected_revision=parent['revision'], preview_sha256=preview['preview_sha256'])
    migrated = request(client, 'POST', path + '/adopt', status=201, key='save-after-return', json=adoption)['versions'][0]
    assert migrated['parent_version_id'] == parent['id']
    assert migrated['snapshot']['school_change_provenance']['change_id'] == change['id']
    assert ('user_return_provenance' in migrated['snapshot']) == inherited_return
    assert run_task(migrated['task_id'], 1)['status'] == 'succeeded'
    assert request(client, 'POST', path + '/adopt', key='save-after-return', json=adoption)['current_revision'] == migrated['revision']
    assert request(client, 'GET', root + f"/versions/{parent['revision']}")['snapshot'] == snapshot
    export_word(client, root, migrated, {}, 'word-after-return-migration')
    assert client.get(historical_export['download_url']).content == historical_bytes
    reviews = project + '/reviews'
    def options():
        result = request(client, 'GET', reviews + '/inputs')
        return {v['id'] for m in result['manuscripts'] for v in m['versions']}
    assert {parent['id'], migrated['id']} <= options()
    for item in request(client, 'GET', reviews + '/rounds')['items']:
        assert request(client, 'GET', reviews + '/rounds/' + item['id'])['manuscript'] == item['manuscript']
    load_change = SchoolChangeService.row
    with monkeypatch.context() as patch:
        def mismatched_candidate(service, *args):
            return {**load_change(service, *args), 'candidate_sha256': '0' * 64}
        patch.setattr(SchoolChangeService, 'row', mismatched_candidate)
        rejected = client.get(reviews + '/inputs')
        assert rejected.status_code == 409
        assert rejected.json()['detail']['code'] == 'task_source_conflict'
    with database_connection(write=True) as db:
        db.execute('UPDATE files SET upload_actor_id=%s WHERE id=%s',
                   (other_id, snapshot['user_return_provenance']['source']['file_id']))
    assert not {parent['id'], migrated['id']} & options()
