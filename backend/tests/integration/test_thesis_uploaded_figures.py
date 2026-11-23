from io import BytesIO
import json

from docx import Document
from fastapi.testclient import TestClient

from app.domain.tasks.execution import run_task
from app.main import app
from tests.api.test_customer_thesis_permissions import bind, drain_document_parse, thesis_project
from tests.api.test_customer_sci_workflow import upload_docx
from tests.api.test_customer_workspace import sign_in
from tests.api.test_manuscript_writing_live import request_v2
from tests.api.test_school_writing_live import SchoolFixture
from app.domain.manuscript_writing.execution import run_manuscript_writing_task
from tests.domain.test_school_writing_live import synthetic_layout_cache
from tests.integration.test_customer_sci_to_word import request
from tests.integration.test_customer_thesis_to_word import (
    export_word, parse_template, school_options, start_template, template_confirmation, thesis_request,
)
from tests.integration.test_review_uploaded_figures import image_upload


def test_figure_choices_exclude_template_front_and_back_matter_and_their_children():
    from app.domain.paper_materials import thesis_figure_chapters

    chapters = [
        ('toc', '目  录', 1), ('summary', '摘   要', 1), ('keywords', '关键词', 2),
        ('method', '第二章 基于摘要的文献分类方法', 1), ('flow', '2.1 分类流程', 2),
        ('bibliography', '文献目录', 1), ('records', 'References by year', 2),
        ('appendix', '附录（根据实际情况填写）', 1), ('form', 'A 调查表', 2),
    ]
    template = dict(protected_chapter_purposes={}, chapters=[dict(id=id, title=title, level=level)
                                                             for id, title, level in chapters])
    assert [c['id'] for c in thesis_figure_chapters(template)] == ['method', 'flow']


def test_fixed_chapter_finding_preserves_its_explicit_figure_source_when_freezing_a_new_draft():
    from app.domain.manuscripts.paper_plan import freeze_groups

    plan = dict(kind='thesis', sections=[dict(id='finding', chapter_id='ch3', label='研究结果', purpose='results', text='观察记录。')],
                figure_chapters=[dict(id='images', label='研究结果', chapter_id='ch3')],
                materials=[dict(section_id='images', chapter_id='ch3', finding_section_id='finding', kind='figure',
                                selection={'id': 'fig'}, result='作者配图。')])
    groups, _ = freeze_groups(None, None, plan, {}, lambda identity, **kw: dict(id=identity, caption_status='supplied'), 'zh-CN')
    assert groups[0]['paragraphs'][0]['source_ids'] == ['fig']
    assert [g['id'] for g in groups if g['figures']] == ['images']


def test_thesis_figures_use_adopted_body_chapters_without_preregistering_results(monkeypatch):
    monkeypatch.setattr('app.adapters.pdf_renderer.update_layout_fields', synthetic_layout_cache)
    with TestClient(app) as client:
        owner = sign_in(client, 'thesis-placement@manuscript.test', 'customer')
        project = thesis_project(client)
        notes = project + '/paper-materials'
        auto, _ = image_upload(client, project, 'overview.png', 'PNG')
        specific, _ = image_upload(client, project, 'flow.jpg', 'JPEG')
        document_upload = upload_docx(client, project, 'methods.docx', 'Material supplied by the author.')
        drain_document_parse(document_upload)
        general = document_upload['id']
        assert request(client, 'GET', notes).get('figure_targets') == []
        template = parse_template(client, project, start_template(client, project, 'figure-test'))
        confirmation = request(client, 'POST', project + '/school-templates/' + template['id'] + '/confirm',
                               status=201, key='confirm', json=template_confirmation(template))
        profile = bind(client, project, confirmation, 0)
        view = request(client, 'GET', notes)
        assert view['template_source_file_ids'] == [template['sources'][0]['file_id']]
        targets = {row['label']: row['id'] for row in view['figure_targets']}
        assert set(targets) == {'1 绪论', '1.1 工程讨论', '2 研究方法', '3 结果', '4 结论'}
        target = targets['2 研究方法']
        changes = dict(file_id=specific, expected_revision=0, result='', target_id=target)
        assert request(client, 'PUT', notes + '/' + specific, json=changes)['target_available']
        assert request(client, 'PUT', notes + '/' + specific, json=changes)['revision'] == 1
        request(client, 'PUT', notes + '/' + general, json=dict(file_id=general, expected_revision=0,
                                                                result='Methods source', target_id=None))
        plan = request(client, 'GET', project + '/manuscripts/candidates')['paper_plan']
        chapter_ids = {row['title']: row['id'] for row in confirmation['chapters']}
        assert {row['selection']['id']: row['chapter_id'] for row in plan['materials']} == {
            auto: chapter_ids['3 结果'], specific: chapter_ids['2 研究方法']}
        assert plan['file_descriptions'] == {general: 'Methods source'}
        data = thesis_request(confirmation, profile, title=plan['title'], paper_plan_token=plan['token'])
        draft = request(client, 'POST', project + '/manuscripts', status=201, key='fact', json=data)
        fixed = draft['versions'][0]
        assert run_task(fixed['task_id'], 1)['status'] == 'succeeded'
        groups = fixed['snapshot']['results_groups']
        assert not any(i['id'] in {'missing:caption:' + auto, 'missing:caption:' + specific}
                       for i in fixed['snapshot']['issues'])
        assert [(g['illustration_chapter_id'], g['figures'][0]['id'], g['figures'][0]['number']) for g in groups] == [
            (chapter_ids['2 研究方法'], specific, 1), (chapter_ids['3 结果'], auto, 2)]
        base = project + '/manuscripts/' + draft['id']
        bundle = request(client, 'POST', base + '/writing-previews', status=201, key='preview', json=dict(
            schema_version=3, base_revision=1, mode='full_draft', output_language='zh-CN',
            document_context_version='selected-text-v1',
            selected_source_ids=[auto, specific], selected_evidence_ids=[]))
        wire = json.loads(json.loads(bundle['wire_json'])['input'])
        aliases = {row['title']: row['alias'] for row in wire['chapters']}
        assert [row['section_id'] for row in wire['illustrations']] == [aliases['2 研究方法'], aliases['3 结果']]
        assert not any(name in bundle['wire_json'] for name in ['overview.png', 'flow.jpg'])
        bundle_ref = dict(bundle_id=bundle['id'], bundle_sha256=bundle['bundle_sha256'])
        authorization = request(client, 'POST', project + '/writing-authorizations', status=201, key='auth', json=dict(
            schema_version=2, confirmed=True, tasks=[dict(logical_task_id='task-0', bundles=[bundle_ref])]))
        task = request(client, 'POST', base + '/writing-requests', status=202, key='draft',
                       json=request_v2(bundle, authorization))['task']
        assert run_manuscript_writing_task(task['id'], task['revision'], provider=SchoolFixture())['status'] == 'succeeded'
        reader = base + '/writing-requests/' + task['id'] + '/draft-reader'
        view = request(client, 'GET', reader + '?revision=1')['draft']
        assert view['english_title'] == 'Synthetic Thesis with Paired Expression'
        rendered = view['sections']
        figure_ids = {s['id']: [f['id'] for g in s['groups'] for f in g['figures']] +
                               [f['id'] for p in s['paragraphs'] for f in p.get('figures', [])] for s in rendered}
        assert {k: ids for k, ids in figure_ids.items() if ids} == {
            chapter_ids['2 研究方法']: [specific], chapter_ids['3 结果']: [auto]}
        response = client.get(reader + '/word?revision=1')
        assert response.status_code == 200
        assert len(Document(BytesIO(response.content)).inline_shapes) == 2
        assert any('供者内配对表达图' in p.text for p in Document(BytesIO(response.content)).paragraphs)
        edited = client.post(reader + '/word?revision=1', json={
            'chapter_titles': {chapter_ids['2 研究方法']: '2 供者内配对表达图解读'},
            'figure_titles': {specific: '供者内配对比较流程'},
        })
        assert edited.status_code == 200
        edited_paragraphs = [p.text for p in Document(BytesIO(edited.content)).paragraphs]
        assert '2 供者内配对表达图解读' in edited_paragraphs
        assert any(text.startswith('图 2.1') and '供者内配对比较流程' in text for text in edited_paragraphs)
        from app.adapters.task_store import DatasetTaskAssets, TaskStore
        from app.domain.manuscripts.school_draft_edits import SchoolDraftEdits
        from app.domain.sci_draft_reader import SciDraftReader

        service = SciDraftReader(DatasetTaskAssets(owner, TaskStore(owner).config))
        correction = SchoolDraftEdits(chapter_titles={chapter_ids['2 研究方法']: '2 供者内配对表达图解读'})
        service.save_school_edits(project.rsplit('/', 1)[-1], draft['id'], task['id'], 1, correction)
        reloaded = client.get(reader + '/word?revision=1')
        assert reloaded.status_code == 200
        assert '2 供者内配对表达图解读' in [p.text for p in Document(BytesIO(reloaded.content)).paragraphs]
        next_view = request(client, 'GET', reader + '?revision=1')['draft']
        assert next_view['english_title'] == view['english_title']
        assert any(s['heading'] == '2 供者内配对表达图解读' for s in next_view['sections'])
        _, raw = export_word(client, base, fixed, dict(school=school_options(confirmation['chapters'])), 'word')
        document = Document(BytesIO(raw))
        assert len(document.inline_shapes) == 2
        paragraphs = [p.text for p in document.paragraphs]
        method = paragraphs.index('2 研究方法')
        result = paragraphs.index('3 结果')
        assert any(text.startswith('图 2.1') for text in paragraphs[method:result])
        assert any(text.startswith('图 3.1') for text in paragraphs[result:])
        # Choosing automatic placement on an existing project changes only its next draft.
        credit = '研究方法流程，来源为作者绘制。'
        request(client, 'PUT', notes + '/' + specific, json=dict(file_id=specific, expected_revision=1, result=credit, target_id=None))
        next_plan = request(client, 'GET', project + '/manuscripts/candidates')['paper_plan']
        next_image = next(m for m in next_plan['materials'] if m['selection']['id'] == specific)
        assert next_image['chapter_id'] == chapter_ids['2 研究方法'] and next_image['result'] == credit
        assert next_plan['token'] != plan['token']
        assert request(client, 'GET', reader + '?revision=1')['draft']['sections'] == next_view['sections']
