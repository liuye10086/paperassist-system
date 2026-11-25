import json

import pytest
from fastapi.testclient import TestClient

from app.adapters.docx_parser import parse_docx
from app.adapters.storage import ProjectStore
from app.core.config import get_data_dir
from app.core.errors import error_detail
from app.core.exceptions import StorageError
from app.db.database import database_connection
from app.domain.school_templates.execution import run_school_template_task
from app.domain.tasks.execution import run_task
from app.domain.tasks.file_parse_execution import run_parse_file_task
from app.main import app
from tests.api.test_customer_project_types import create, project_body, project_path
from tests.api.test_customer_sci_workflow import sci_project, upload_docx
from tests.api.test_customer_workspace import create_customer_project, sign_in
from tests.api.test_school_templates import analysis, post


def thesis_project(client, key='thesis'):
    return project_path(create(client, key, **project_body('thesis')))


def template_body(file_id, **extra):
    return dict(name='Synthetic school template', school='Synthetic university', template_file_id=file_id) | extra


def confirm_template(client, project, template, key):
    response = client.get(project + '/school-templates')
    assert response.status_code == 200, response.text
    parsed = next(item for item in response.json()['items'] if item['id'] == template['id'])
    path = f"{project}/school-templates/{template['id']}/confirm"
    chapters = [dict(id='results', title='Study Results', level=1)]
    body = dict(analysis_sha256=parsed['analysis_sha256'], chapters=chapters, decisions=[])
    assert post(client, path, body, key + '-unresolved').status_code == 409
    body['decisions'] = [dict(conflict_id='conflict-1', option_id='text-2')]
    response = post(client, path, body, key)
    assert response.status_code == 201, response.text
    return response.json(), path, body


def template(client, project, name, **extra):
    file = upload_docx(client, project, name + '.docx', 'Working template fixture: ' + name)
    drain_document_parse(file)
    body = template_body(file['id'], **extra)
    response = post(client, project + '/school-templates', body, name)
    assert response.status_code == 202, response.text
    return response.json(), file['id'], body


def drain_document_parse(file):
    task = file['task']
    assert run_parse_file_task(task['id'], task['revision'], parser=parse_docx)['status'] == 'succeeded'


def bind(client, project, confirmation, revision):
    response = client.post(project + '/thesis-template-binding', json=dict(
        confirmation_id=confirmation['id'], expected_revision=revision))
    assert response.status_code == 200, response.text
    return response.json()


def hide(file_id, actor):
    with database_connection(write=True) as db:
        db.execute('UPDATE files SET upload_actor_id=%s WHERE id=%s', (actor, file_id))


def test_customer_school_templates_and_parse_tasks_require_visible_project_sources():
    with TestClient(app) as client, TestClient(app) as other:
        sign_in(client, 'b03-template-owner@example.test', 'customer')
        actor = sign_in(other, 'b03-template-other@example.test', 'customer')
        project = thesis_project(client)
        sci = sci_project(client)
        research = create_customer_project(client)
        for wrong in (sci, research):
            assert client.get(wrong + '/school-templates').status_code == 403
            assert client.get(wrong + '/thesis-requirements').status_code == 403
        for endpoint in ('/thesis-profile', '/thesis-requirements', '/school-templates', '/manuscripts/config'):
            assert other.get(project + endpoint).status_code == 404
        for endpoint in ('/journals/config', '/pdf-exports'):
            assert client.get(project + endpoint).status_code == 403

        item, file_id, body = template(client, project, 'visible-template')
        task = item['task']
        task_url = '/api/v1/tasks/' + task['id']
        assert client.get(task_url).status_code == 200
        assert other.get(task_url).status_code == 404
        assert client.get(project + f"/school-templates/{item['id']}/rule-suggestions").status_code == 403

        def fail(*args):
            raise StorageError('parse_timeout', 'Synthetic parser error.', 422)

        assert run_school_template_task(task['id'], 1, parser=fail)['status'] == 'failed'
        retry_url = project + f"/school-templates/{item['id']}/retry"
        retry = client.post(retry_url, json={})
        assert retry.status_code == 200, retry.text
        assert run_school_template_task(task['id'], retry.json()['task']['revision'], parser=analysis)['status'] == 'succeeded'
        confirmation, confirm_url, confirmation_body = confirm_template(client, project, item, 'rules')
        profile = bind(client, project, confirmation, 0)

        requirements_url = project + '/thesis-requirements'
        basics = dict(education_level='硕士', school='Synthetic university', title='Synthetic thesis',
                      keywords=['cohort', 'sampling', 'observations', 'comparison'])
        section = dict(chapter_id='results', purpose='results', content='Describe the observed measurements.')
        plan = dict(confirmation_id=confirmation['id'], sections=[section])
        write = dict(expected_revision=profile['revision'], expected_language='zh-CN', language='en', basics=basics,
                     chapter_plan=plan)
        missing = plan | {'sections': [section | {'chapter_id': 'missing'}]}
        assert client.put(requirements_url, json=write | {'chapter_plan': missing}).status_code == 422
        saved = client.put(requirements_url, json=write)
        assert saved.status_code == 200, saved.text
        assert saved.json()['sections'] == [section]
        assert saved.json()['template']['chapters'] == confirmation['chapters']
        assert saved.json()['template']['source_file'] == dict(file_id=file_id, filename='visible-template.docx')
        assert client.put(requirements_url, json=write).json() == saved.json()

        hide(file_id, actor)
        assert client.get(project + '/school-templates').json()['items'] == []
        assert client.get(project + '/thesis-profile').json()['bound_confirmation_id'] is None
        restricted = client.get(requirements_url).json()
        assert restricted['title'] == basics['title'] and restricted['template'] is None and restricted['sections'] == []
        assert client.get(project + '/manuscripts/config').json()['thesis']['ready'] is False
        assert post(client, project + '/school-templates', body, 'hidden-template').status_code == 404
        visible = upload_docx(client, project, 'visible.docx', 'Other customer original.')
        assert post(client, project + '/school-templates', template_body(visible['id'], manuscript_file_ids=[file_id]), 'hidden-sample').status_code == 404
        assert post(client, project + '/school-templates', template_body(visible['id'], previous_version_id=item['id']), 'hidden-parent').status_code == 404
        assert post(client, confirm_url, confirmation_body, 'rules').status_code == 404
        assert client.post(retry_url, json={}).status_code == 404
        assert client.get(task_url + '/events').status_code == 404


def test_saved_thesis_chapter_content_reaches_its_confirmed_chapter_in_initial_writing():
    with TestClient(app) as client:
        sign_in(client, 'thesis-author-chapters@example.test', 'customer')
        project = thesis_project(client)
        submitted, file_id, _ = template(client, project, 'author-content-template')
        assert run_school_template_task(submitted['task']['id'], 1, parser=analysis)['status'] == 'succeeded'
        parsed = client.get(project + '/school-templates').json()['items'][0]
        content = [
            ('abstract', 'Abstract', 'Summarize the scope of the observations.'),
            ('introduction', 'Introduction', 'The archive contains 42 background reports.'),
            ('materials_and_methods', 'Methods', 'Describe the coding framework.'),
            ('results', 'Results', 'Record the observations supplied by the author.'),
            ('discussion', 'Discussion', 'Consider uncertainty about recruitment.'),
            ('conclusion', 'Conclusion', 'Provide a summary of the remaining questions.'),
        ]
        chapters = [dict(id='school-' + role, title=title, level=1) for role, title, _ in content]
        response = post(client, f"{project}/school-templates/{submitted['id']}/confirm", dict(
            analysis_sha256=parsed['analysis_sha256'], chapters=chapters,
            decisions=[dict(conflict_id='conflict-1', option_id='text-2')]), 'chapter-rules')
        assert response.status_code == 201, response.text
        confirmation = response.json()
        profile = bind(client, project, confirmation, 0)
        sections = [dict(chapter_id='school-' + role, purpose=role, content=text) for role, _, text in content]
        requirements = project + '/thesis-requirements'
        edited = client.put(requirements, json=dict(
            expected_revision=profile['revision'], expected_language='zh-CN', language='en',
            basics=dict(education_level='硕士', school='Synthetic university', title='Synthetic thesis',
                        keywords=['cohort', 'sampling', 'observations', 'comparison']),
            chapter_plan=dict(confirmation_id=confirmation['id'], sections=sections)))
        assert edited.status_code == 200, edited.text
        assert edited.json()['sections'] == sections
        assert client.get(requirements).json()['template']['source_file'] == dict(
            file_id=file_id, filename='author-content-template.docx')
        plan = client.get(project + '/manuscripts/candidates').json()['paper_plan']
        assert [(row['chapter_id'], row['purpose'], row['text']) for row in plan['sections']] == [
            (row['chapter_id'], row['purpose'], row['content']) for row in sections]
        groups = {row['purpose']: row['id'] for row in plan['sections']}
        assert {row['label'] for row in client.get(project + '/paper-materials').json()['targets']} == {'Results'}
        mappings = [dict(chapter_id=row['chapter_id'], purpose=row['purpose'], output_language='project',
                         result_group_ids=[groups['results']] if row['purpose'] == 'results' else [])
                    for row in sections]
        draft = dict(title=plan['title'], output_language='en', paper_plan_token=plan['token'], thesis=dict(
            confirmation_id=confirmation['id'], profile_revision=edited.json()['revision'], chapter_mappings=mappings))
        wrong = dict(draft, thesis=dict(draft['thesis'], chapter_mappings=[
            row if row['purpose'] != 'introduction' else dict(row, purpose='discussion') for row in mappings]))
        assert post(client, project + '/manuscripts', wrong, 'wrong-purpose').status_code == 422
        created = post(client, project + '/manuscripts', draft, 'author-facts')
        assert created.status_code == 201, created.text
        root = created.json()
        version = root['versions'][0]
        assert run_task(version['task_id'], 1)['status'] == 'succeeded'
        snapshot = version['snapshot']
        assert [group['id'] for group in snapshot['results_groups']] == [groups['results']]
        for saved, (_, _, text) in zip(snapshot['sections'], content, strict=True):
            paragraph, = saved['paragraphs']
            assert paragraph['id'] == 'paper-finding:' + groups[saved['purpose']]
            assert paragraph['text'] == text and paragraph['origin'] == 'user_provided'

        url = project + '/manuscripts/' + root['id'] + '/writing-previews'
        preview = post(client, url, dict(schema_version=3, base_revision=1, mode='full_draft',
                                         output_language='en', selected_source_ids=[], selected_evidence_ids=[]),
                       'author-writing-preview')
        assert preview.status_code == 201, preview.text
        payload = json.loads(json.loads(preview.json()['wire_json'])['input'])
        aliases = {row['purpose']: row['alias'] for row in payload['chapters']}
        assert payload['paper_notes'] == [dict(section_id=aliases[role], text=text, source_aliases=[])
                                          for role, _, text in content]
        number, = payload['numeric_context']
        assert number['kind'] == 'provided_context' and number['location'] == 'paper_notes[1]'
        assert number['values'] == [dict(fact_path='/numbers/0', value='42')]
        assert {row['purpose'] for row in payload['chapters'] if number['alias'] in row['allowed_context_aliases']} == {
            'abstract', 'introduction', 'discussion', 'conclusion'}
        assert payload['sources'] == []
        with database_connection() as db:
            assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0


def test_confirmed_declaration_is_unavailable_for_research_requirements_and_materials():
    from psycopg.types.json import Jsonb
    from tests.adapters.test_school_front_matter import synthetic

    with TestClient(app) as client:
        sign_in(client, 'thesis-protected-chapter@example.test', 'customer')
        project = thesis_project(client)
        submitted, _, _ = template(client, project, 'protected-chapter-template')
        parsed = synthetic()
        assert run_school_template_task(submitted['task']['id'], 1, parser=lambda *args, **kwargs: parsed)['status'] == 'succeeded'
        item = client.get(project + '/school-templates').json()['items'][0]
        chapters = [dict(id='declaration', title='学位论文独创性声明', level=1),
                    dict(id='results', title='Study Results', level=1)]
        front = dict(schema_version=1, cover_section_id='section-1', fields=[], content_requirements=[
            dict(id='declaration', kind='declaration', required=True, chapter_id='declaration',
                 source_id=parsed['front_matter_sources'][2]['id'])])
        confirmation = post(client, f"{project}/school-templates/{item['id']}/confirm", dict(
            analysis_sha256=item['analysis_sha256'], chapters=chapters, decisions=[], front_matter=front), 'fixed-front')
        assert confirmation.status_code == 201, confirmation.text
        confirmation = confirmation.json()
        profile = bind(client, project, confirmation, 0)
        url = project + '/thesis-requirements'
        bad = dict(chapter_id='declaration', purpose='results', content='Legacy misplaced content')
        good = dict(chapter_id='results', purpose='results', content='Describe the observations.')
        request = dict(expected_revision=profile['revision'], expected_language='zh-CN', language='zh-CN',
                       basics=dict(education_level='硕士', school='Synthetic university', title='Synthetic thesis',
                                   keywords=['cohort', 'sampling', 'observations', 'comparison']),
                       chapter_plan=dict(confirmation_id=confirmation['id'], sections=[bad, good]))
        rejected = client.put(url, json=request)
        assert rejected.status_code == 422
        assert rejected.json()['detail']['code'] == 'thesis_chapter_protected'

        # A pre-upgrade requirement remains visible but cannot become a fresh results group or material target.
        stored = dict(title='Synthetic thesis', keywords=request['basics']['keywords'],
                      chapter_plans={confirmation['id']: [bad, good]})
        with database_connection(write=True) as db:
            db.execute('UPDATE thesis_profiles SET requirements_json=%s WHERE project_id=%s',
                       (Jsonb(stored), project.rsplit('/', 1)[-1]))
        requirements = client.get(url).json()
        assert requirements['sections'] == [bad, good]
        assert requirements['template']['protected_chapter_purposes'] == {'declaration': 'manual'}
        config = client.get(project + '/manuscripts/config').json()
        assert config['thesis']['protected_chapter_purposes'] == {'declaration': 'manual'}
        assert [row['chapter_id'] for row in config['paper_plan']['sections']] == ['results']
        assert [row['label'] for row in client.get(project + '/paper-materials').json()['targets']] == ['Study Results']


def test_customer_thesis_reported_results_and_hidden_fixed_versions():
    with TestClient(app) as client, TestClient(app) as other:
        sign_in(client, 'b03-manuscript-owner@example.test', 'customer')
        actor = sign_in(other, 'b03-manuscript-other@example.test', 'customer')
        project = thesis_project(client)
        first, _, _ = template(client, project, 'school-one')
        assert run_school_template_task(first['task']['id'], 1, parser=analysis)['status'] == 'succeeded'
        confirmation, _, _ = confirm_template(client, project, first, 'first-rules')
        profile = bind(client, project, confirmation, 0)

        material_text = 'The supporting material reports 17 synthetic observations.'
        material = upload_docx(client, project, 'research.docx', material_text)
        drain_document_parse(material)
        file_id = material['id']
        request = dict(title='Synthetic thesis', output_language='en', reported_result=dict(text=material_text, source_ids=[file_id]),
                       sources=[dict(kind='original', id=file_id, file_id=file_id, role='user_results')], thesis=dict(
                           confirmation_id=confirmation['id'], profile_revision=profile['revision'], chapter_mappings=[dict(
                               chapter_id='results', purpose='results', output_language='project', result_group_ids=['reported-result'])]))
        response = post(client, project + '/manuscripts', request, 'fact')
        assert response.status_code == 201, response.text
        draft = response.json()
        version = draft['versions'][0]
        assert run_task(version['task_id'], 1)['status'] == 'succeeded'
        root = project + '/manuscripts/' + draft['id']
        previews = root + '/writing-previews'
        writing_input = dict(schema_version=3, base_revision=1, mode='full_draft', output_language='en',
                             selected_source_ids=[file_id], selected_evidence_ids=[])
        response = post(client, previews, writing_input, 'school-preview')
        assert response.status_code == 201, response.text
        bundle = response.json()
        payload = json.loads(json.loads(bundle['wire_json'])['input'])
        assert any(material_text in item['text'] for section in payload['context'] for item in section['paragraphs'])
        reported = next(item for item in payload['numeric_context'] if item['location'] == 'reported_results')
        assert reported['values'] == [dict(fact_path='/numbers/0', value='17')]
        assert payload['sources'][0]['facts'] == []
        assert reported['alias'] in payload['chapters'][0]['allowed_context_aliases']
        assert post(client, root + '/writing-requests', dict(base_revision=1, mode='full_draft'), 'offline').status_code == 403

        presentation_input = dict(base_version_id=version['id'], config=dict(authors=[dict(name='Student Name', order=1, source='customer')]))
        presentation_path = root + '/presentations'
        presentation = post(client, presentation_path, presentation_input, 'signed-config')
        assert presentation.status_code == 201, presentation.text
        presentation_id = presentation.json()['id']

        second, second_file_id, _ = template(client, project, 'school-two', previous_version_id=first['id'])
        assert run_school_template_task(second['task']['id'], 1, parser=analysis)['status'] == 'succeeded'
        updated, _, _ = confirm_template(client, project, second, 'second-rules')
        change_input = dict(kind='template_migration', target_confirmation_id=updated['id'])
        changed = post(client, root + '/versions/1/school-changes', change_input, 'school-change')
        assert changed.status_code == 201, changed.text
        change_id = changed.json()['id']
        change_path = root + '/school-changes/' + change_id
        assert other.get(change_path).status_code == 404
        assert other.get(presentation_path + '/' + presentation_id).status_code == 404
        assert post(client, root + '/versions/1/school-changes', dict(
            kind='docx_return', file_id=file_id, document_version_id='unused'), 'return').status_code == 403

        hide(second_file_id, actor)
        assert client.get(change_path).status_code == 404
        assert client.get(root + '/school-changes').json()['items'] == []
        assert client.get(root + '/versions/1').status_code == 200

        hide(file_id, actor)
        assert client.get(root + '/versions/1').status_code == 404
        assert client.get(previews + '/' + bundle['id']).status_code == 404
        assert client.get(presentation_path + '/' + presentation_id).status_code == 404
        assert client.get(presentation_path).json()['items'] == []


def test_customer_binding_preview_is_thesis_only_and_owner_scoped():
    with TestClient(app) as client, TestClient(app) as other:
        sign_in(client, 'b04-preview-owner@example.test', 'customer')
        sign_in(other, 'b04-preview-other@example.test', 'customer')
        project = thesis_project(client)
        item, _, _ = template(client, project, 'preview-template')
        assert run_school_template_task(item['task']['id'], 1, parser=analysis)['status'] == 'succeeded'
        parsed = next(i for i in client.get(project + '/school-templates').json()['items'] if i['id'] == item['id'])
        body = dict(template_version_id=item['id'], expected_revision=0, analysis_sha256=parsed['analysis_sha256'],
                    decisions=[dict(conflict_id='conflict-1', option_id='text-2')],
                    chapters=[dict(id='results', title='Study Results', level=1)])
        allowed = client.post(project + '/thesis-template-binding/preview', json=body)
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()['current'] is None and allowed.json()['manuscripts'] == []
        for wrong in (sci_project(client), create_customer_project(client)):
            denied = client.post(wrong + '/thesis-template-binding/preview', json=body)
            assert denied.status_code == 403 and denied.json()['detail']['code'] == 'customer_project_type_forbidden', denied.text
        foreign = other.post(project + '/thesis-template-binding/preview', json=body)
        assert foreign.status_code == 404 and foreign.json()['detail']['code'] == 'project_not_found', foreign.text


def test_thesis_requirement_conflicts_keep_their_public_codes():
    with TestClient(app) as client:
        owner = sign_in(client, 'thesis-codes@example.test', 'customer')
        project = thesis_project(client, 'thesis-codes')
        url = project + '/thesis-requirements'
        current = client.get(url)
        assert current.status_code == 200, current.text
        revision = current.json()['revision']
        basics = dict(education_level='硕士', school='Synthetic university', title='Synthetic thesis',
                      keywords=['cohort', 'sampling', 'observations', 'comparison'])
        write = dict(expected_revision=revision, expected_language='zh-CN', language='zh-CN', basics=basics)

        stale = client.put(url, json=write | {'expected_revision': revision + 3})
        assert stale.status_code == 409
        detail = stale.json()['detail']
        assert (detail['code'], detail['message']) == ('thesis_requirements_changed', '毕业论文需求或学校资料已更新，请核对后继续。')

        changed = client.put(url, json=write | {'chapter_plan': dict(confirmation_id='missing-confirmation', sections=[])})
        assert changed.status_code == 409
        detail = changed.json()['detail']
        assert (detail['code'], detail['message'], detail['params']) == (
            'thesis_template_changed', '学校模板绑定已变化，请核对当前模板和章节。', {})

        item, _, _ = template(client, project, 'template-readiness')
        assert run_school_template_task(item['task']['id'], 1, parser=analysis)['status'] == 'succeeded'
        confirmation, _, _ = confirm_template(client, project, item, 'confirmed-template')
        profile = bind(client, project, confirmation, revision)
        with database_connection(write=True) as db:
            db.execute("UPDATE tasks SET status='failed',error_code='parse_timeout' WHERE id=%s", (item['task']['id'],))
        unavailable = client.put(url, json=write | dict(expected_revision=profile['revision'],
                                 chapter_plan=dict(confirmation_id=confirmation['id'], sections=[])))
        assert unavailable.status_code == 409
        detail = unavailable.json()['detail']
        assert (detail['code'], detail['message'], detail['params']) == (
            'thesis_template_required', '请先确认并绑定可用的学校模板。', {})

        sci = sci_project(client)
        assert client.get(sci + '/thesis-requirements').json()['detail']['code'] == 'customer_project_type_forbidden'
        # HTTP validation answers first; the store guard still needs a public code for direct callers.
        store = ProjectStore(get_data_dir(), owner_id=owner, customer=True)
        with pytest.raises(StorageError) as error:
            store.create_project('Synthetic SCI', 'Synthetic topic', 'sci', thesis_requirements={'title': 'Synthetic'})
        assert error.value.code == 'thesis_requirements_unavailable'
        assert error_detail(error.value.code, error.value.message)['code'] == 'thesis_requirements_unavailable'
