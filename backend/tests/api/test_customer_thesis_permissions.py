import json

from fastapi.testclient import TestClient

from app.adapters.docx_parser import parse_docx
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

        presentation_input = dict(base_version_id=version['id'], config=dict(blind=dict(identity_terms=['Student Name'])))
        presentation_path = root + '/presentations'
        presentation = post(client, presentation_path, presentation_input, 'blind-config')
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
