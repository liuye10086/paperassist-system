from base64 import b64decode
from io import BytesIO
import json

from docx import Document
from fastapi.testclient import TestClient
from PIL import Image

from app.adapters.research_figure_render import render_figure
from app.domain.manuscript_writing.frozen import wire_payload
from app.domain.research_results.execution import run_research_figure_task
from app.domain.tasks.execution import run_task
from app.main import app
from tests.api.test_customer_thesis_permissions import bind, drain_document_parse, thesis_project
from tests.api.test_customer_sci_workflow import upload_docx
from tests.api.test_customer_workspace import sign_in
from tests.api.test_manuscript_writing_live import LiveFixture, request_v2
from tests.api.test_school_writing_live import SchoolFixture
from app.domain.manuscript_writing.execution import run_manuscript_writing_task
from tests.domain.test_school_writing_live import synthetic_layout_cache
from tests.integration.test_customer_sci_draft_revision import ChatStreamFixture, queue_write
from tests.integration.test_customer_sci_to_word import request
from tests.integration.test_customer_thesis_to_word import (
    export_word, parse_template, school_options, start_template, template_confirmation, thesis_request,
)
from tests.integration.test_review_uploaded_figures import image_upload


class ThesisFigureChatFixture(ChatStreamFixture):
    def receipt(self):
        result = LiveFixture.receipt(self)
        sections = []
        for alias, text in self.paragraphs.items():
            paragraph = dict(id=alias + '-p1', text=text, source_aliases=[], evidence_aliases=[],
                             study_numeric_bindings=[], citation_anchors=[])
            sections.append(dict(id=alias, paragraphs=[paragraph]))
        result['response']['output'][0]['content'][0]['text'] = json.dumps(dict(sections=sections), ensure_ascii=False)
        return result


def test_thesis_composed_figure_uses_the_school_chapter_and_replaces_its_raw_panels(tmp_path, monkeypatch):
    monkeypatch.setattr('app.adapters.pdf_renderer.update_layout_fields', synthetic_layout_cache)
    monkeypatch.setattr('app.domain.manuscript_writing.draft_chat.monotonic', lambda: 1)
    with TestClient(app) as client:
        sign_in(client, 'thesis-composed-word@example.test', 'customer')
        project = thesis_project(client)
        panels = [image_upload(client, project, 'panel-a.png', 'PNG')[0],
                  image_upload(client, project, 'panel-b.jpg', 'JPEG')[0]]
        other, _ = image_upload(client, project, 'independent.tiff', 'TIFF')
        figures_url = project + '/thesis-figures'
        resources_url = project + '/thesis-figure-resources'
        assert request(client, 'GET', resources_url)['template_id'] is None
        created = request(client, 'POST', figures_url, status=201, key='assembled', json={
            'title': '合成组合图', 'file_ids': panels, 'columns': 2,
        })
        task = created['task']
        result = run_research_figure_task(task['id'], task['revision'], engine=render_figure,
                                          staging_directory=tmp_path / 'staging')
        assert result['status'] == 'succeeded', result
        figure = request(client, 'GET', figures_url + '/' + created['id'])
        member = next(item for item in figure['members'] if (item['role'], item['format']) == ('figure', 'png'))
        assembled = client.get(member['download_url'])
        assert assembled.status_code == 200

        template = parse_template(client, project, start_template(client, project, 'assembled-figure'))
        confirmation = request(client, 'POST', project + '/school-templates/' + template['id'] + '/confirm',
                               status=201, key='confirm', json=template_confirmation(template))
        bind(client, project, confirmation, 0)
        current = request(client, 'GET', resources_url)
        assert current['template_id'] == confirmation['id']
        target = next(row for row in current['chapters'] if row['label'] == '2 研究方法')
        # A raw image that previously had its own placement becomes one panel in the new draft.
        request(client, 'PUT', project + '/paper-materials/' + panels[0], json={
            'file_id': panels[0], 'expected_revision': 0, 'result': '原图的旧位置', 'target_id': target['id'],
        })
        caption = '作者提供的合成组合图。'
        configured = request(client, 'PUT', resources_url, json={
            'expected_revision': current['revision'],
            'placements': [dict(figure_id=figure['id'], chapter_id=target['id'], caption=caption)],
        })
        plan = request(client, 'GET', project + '/manuscripts/candidates')['paper_plan']
        chapter_id = next(row['id'] for row in confirmation['chapters'] if row['title'] == '2 研究方法')
        assert [(row['figure_id'], row['chapter_id']) for row in plan['thesis_figures']] == [(figure['id'], chapter_id)]
        assert [row['selection']['id'] for row in plan['materials']] == [other]
        data = thesis_request(confirmation, configured, title=plan['title'], paper_plan_token=plan['token'])
        draft = request(client, 'POST', project + '/manuscripts', status=201, key='fact', json=data)
        fixed = draft['versions'][0]
        assert run_task(fixed['task_id'], 1)['status'] == 'succeeded'
        assert {row['id'] for row in fixed['snapshot']['sources']} == {figure['id'], other}
        base = project + '/manuscripts/' + draft['id']
        selection = dict(
            schema_version=3, base_revision=1, mode='full_draft', output_language='zh-CN',
            document_context_version='selected-text-v1',
            selected_source_ids=[figure['id'], other], selected_evidence_ids=[])
        previews = base + '/writing-previews'
        bundle = request(client, 'POST', previews, status=201, key='preview', json=selection)
        wire = json.loads(json.loads(bundle['wire_json'])['input'])
        aliases = {row['title']: row['alias'] for row in wire['chapters']}
        assert [row['section_id'] for row in wire['illustrations']] == [aliases['2 研究方法'], aliases['3 结果']]
        bundle_ref = dict(bundle_id=bundle['id'], bundle_sha256=bundle['bundle_sha256'])
        authorization = request(client, 'POST', project + '/writing-authorizations', status=201, key='auth', json=dict(
            schema_version=2, confirmed=True, tasks=[dict(logical_task_id='task-0', bundles=[bundle_ref])]))
        task = request(client, 'POST', base + '/writing-requests', status=202, key='draft',
                       json=request_v2(bundle, authorization))['task']
        result = run_manuscript_writing_task(task['id'], task['revision'], provider=SchoolFixture())
        assert result['status'] == 'succeeded', result
        original_path = base + '/writing-requests/' + task['id']
        reader = original_path + '/draft-reader'
        initial = request(client, 'GET', reader + '?revision=1')
        view = initial['draft']
        section = next(row for row in view['sections'] if row['id'] == chapter_id)
        assert [(row['id'], row['caption']) for group in section['groups'] for row in group['figures']] == [
            (figure['id'], caption),
        ]

        def check_word(reader_url=reader):
            response = client.get(reader_url + '/word?revision=1')
            assert response.status_code == 200, response.text
            doc = Document(BytesIO(response.content))
            assert len(doc.inline_shapes) == 2
            paragraphs = [p.text for p in doc.paragraphs]
            assert any(title.startswith('图 2.1  ') and legend == caption
                       for title, legend in zip(paragraphs, paragraphs[1:]))
            assert assembled.content in [part.blob for part in doc.part.related_parts.values() if part.content_type == 'image/png']
            return paragraphs

        check_word()
        original = request(client, 'GET', original_path)['candidate']
        revision = selection | dict(revision_of_request_id=task['id'], target_sections=[chapter_id],
                                    instructions='结合组合图说明研究方法。')
        revision_bundle = request(client, 'POST', previews, status=201, key='method-chat', json=revision)
        assert chapter_id in initial['editable_section_ids']
        frozen_wire = revision_bundle['wire_json']
        payload = wire_payload(frozen_wire)
        alias = aliases['2 研究方法']
        assert payload['draft_revision_scope'] == 'selected_sections'
        assert [chapter['alias'] for chapter in payload['chapters']] == [alias]
        assert [chapter['id'] for chapter in payload['original_draft']] == [alias]
        assert 'draft_presentation' not in payload and chapter_id not in frozen_wire
        [context] = payload['revision_figure_context']
        assert context['section_ids'] == [alias] and context['caption'] == caption
        [message] = json.loads(frozen_wire)['input']
        text_part, visual_part = message['content']
        assert message['role'] == 'user' and text_part['type'] == 'input_text'
        assert visual_part['type'] == 'input_image' and visual_part['detail'] == 'high'
        prefix, encoded = visual_part['image_url'].split(',', 1)
        assert prefix == 'data:image/png;base64'
        with Image.open(BytesIO(b64decode(encoded, validate=True))) as outbound, Image.open(BytesIO(assembled.content)) as saved:
            assert outbound.size == saved.size
            assert outbound.convert('RGB').tobytes() == saved.convert('RGB').tobytes()

        revised_task = queue_write(client, project, base, revision_bundle, 'thesis-figure-revision')
        revised_path = base + '/writing-requests/' + revised_task['id']
        revised_reader = revised_path + '/draft-reader'
        leading_text = '组合图展示了研究方法'
        revised_text = leading_text + '的两个示意环节。'

        def observe_revision():
            partial = request(client, 'GET', revised_reader + '?revision=1')
            assert partial['status'] == 'running' and partial['target_sections'] == [chapter_id]
            assert partial['partial_reply'] == [dict(section_id=chapter_id, text=leading_text)]

        provider = ThesisFigureChatFixture(observe=observe_revision, prefix=leading_text,
                                          paragraphs={alias: revised_text})
        finished = run_manuscript_writing_task(revised_task['id'], revised_task['revision'], provider=provider)
        assert finished['status'] == 'succeeded', finished
        assert provider.posts == [frozen_wire]
        revised = request(client, 'GET', revised_path)['candidate']
        assert revised['results_groups'] == original['results_groups']
        assert revised['school_presentation'] == original['school_presentation']
        assert [s for s in revised['sections'] if s['id'] != chapter_id] == [
            s for s in original['sections'] if s['id'] != chapter_id]
        revised_view = request(client, 'GET', revised_reader + '?revision=1')
        assert [(change['section_id'], change['after']) for change in revised_view['changes']] == [
            (chapter_id, [revised_text])]
        assert revised_text in check_word(revised_reader)
        assert request(client, 'GET', original_path)['candidate'] == original

        advice_input = revision | dict(revision_of_request_id=revised_task['id'], draft_advice=True,
                                       instructions='这张研究方法组合图还需要说明什么？')
        advice_bundle = request(client, 'POST', previews, status=201, key='method-advice', json=advice_input)
        advice_wire = advice_bundle['wire_json']
        assert wire_payload(advice_wire)['revision_figure_context'] == [context]
        assert json.loads(advice_wire)['input'][0]['content'][1:] == [visual_part]
        advice_task = queue_write(client, project, base, advice_bundle, 'thesis-figure-advice')
        advice_path = base + '/writing-requests/' + advice_task['id']
        advice_text = '请分别解释组合图中两个面板的作用。'
        provider = ChatStreamFixture(observe=lambda: None, prefix='请分别解释', advice=advice_text)
        finished = run_manuscript_writing_task(advice_task['id'], advice_task['revision'], provider=provider)
        assert finished['status'] == 'succeeded', finished
        assert provider.posts == [advice_wire]
        advice = request(client, 'GET', advice_path + '/draft-reader?revision=1')
        assert advice['advice'] == advice_text and advice['draft'] is None
        assert request(client, 'GET', revised_reader + '?revision=1') == revised_view

        replacement = request(client, 'POST', figures_url, status=201, key='overwrite', json={
            'root_id': figure['root_id'], 'expected_revision': figure['revision'], 'title': '更新后的组合图',
            'file_ids': panels, 'columns': 1,
        })
        result = run_research_figure_task(replacement['task_id'], replacement['task']['revision'], engine=render_figure,
                                          staging_directory=tmp_path / 'staging')
        assert result['status'] == 'succeeded', result
        current = request(client, 'GET', resources_url)
        assert current['placements'] == configured['placements']
        item, = current['figures']
        assert item['id'] == figure['root_id'] and replacement['id'] in item['preview_url']
        new_plan = request(client, 'GET', project + '/manuscripts/candidates')['paper_plan']
        assert [(row['figure_id'], row['chapter_id'], row['caption']) for row in new_plan['thesis_figures']] == [
            (replacement['id'], chapter_id, caption),
        ]
        check_word()
        cancelled = client.post(figures_url + '/' + figure['root_id'] + '/cancel',
                                json={'expected_revision': replacement['revision']})
        assert cancelled.status_code == 204, cancelled.text
        updated = request(client, 'GET', resources_url)
        assert updated['revision'] == configured['revision'] + 1
        assert not updated['figures'] and not updated['placements']
        next_plan = request(client, 'GET', project + '/manuscripts/candidates')['paper_plan']
        assert not next_plan.get('thesis_figures') and not next_plan.get('thesis_figures_need_configuration')
        check_word()


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
