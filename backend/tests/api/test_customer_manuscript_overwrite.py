"""D2: a customer paper project keeps one manuscript; later drafts are new versions of it."""
from hashlib import sha256

from fastapi.testclient import TestClient

from app.domain.school_templates.execution import run_school_template_task
from app.domain.tasks.execution import run_task
from app.main import app
from tests.api.test_customer_sci_workflow import sci_project, upload_docx
from tests.api.test_customer_thesis_permissions import bind, confirm_template, drain_document_parse, template, thesis_project
from tests.api.test_customer_workspace import sign_in
from tests.api.test_literature_evidence import post
from tests.api.test_manuscripts import body
from tests.api.test_school_templates import analysis


def planned(client, project, **extra):
    plan = client.get(project + '/manuscripts/candidates').json()['paper_plan']
    return body(title=plan['title'], paper_plan_token=plan['token']) | extra


def assert_exists(response):
    assert response.status_code == 409, response.text
    detail = response.json()['detail']
    assert detail['code'] == 'manuscript_exists'
    assert detail['message'] == '这个项目已经有稿件。请覆盖之前的写作材料。'


def test_planned_customer_version_requires_plan_token():
    with TestClient(app) as client:
        sign_in(client, 'd2-plan-token@manuscript.test', 'customer')
        project = sci_project(client)
        created = post(client, project + '/manuscripts', planned(client, project), 'plan-first')
        assert created.status_code == 201, created.text
        root = project + '/manuscripts/' + created.json()['id']
        missing = post(client, root + '/versions', body(expected_revision=1), 'plan-missing')
        assert missing.status_code == 422, missing.text
        appended = post(client, root + '/versions', planned(client, project, expected_revision=1), 'plan-next')
        assert appended.status_code == 201, appended.text
        assert appended.json()['current_revision'] == 2


def test_sci_customer_second_manuscript_is_rejected_and_overwrite_keeps_history():
    with TestClient(app) as client:
        sign_in(client, 'd2-sci-owner@manuscript.test', 'customer')
        project = sci_project(client)
        path = project + '/manuscripts'
        request = planned(client, project)
        first = post(client, path, request, 'd2-first')
        assert first.status_code == 201, first.text
        manuscript = first.json()
        replay = post(client, path, request, 'd2-first')
        assert replay.status_code == 200, replay.text
        assert replay.json()['id'] == manuscript['id']
        assert_exists(post(client, path, request, 'd2-second'))
        assert_exists(post(client, path, body(), 'd2-unplanned'))

        version = manuscript['versions'][0]
        assert run_task(version['task_id'], 1)['status'] == 'succeeded'
        root = path + '/' + manuscript['id']
        export = post(client, root + '/versions/1/exports', {}, 'd2-word-1')
        assert export.status_code == 201, export.text
        assert run_task(export.json()['task_id'], 1)['status'] == 'succeeded'
        download = root + '/exports/' + export.json()['id'] + '/download'
        before = sha256(client.get(download).content).hexdigest()

        reviews = project + '/reviews'
        round_body = dict(title='Synthetic review', project_type='sci', synthetic=False, materials=[],
                          manuscript=dict(id=manuscript['id'], revision=1, version_id=version['id']),
                          sources=[dict(role='reviewer', label='Reviewer 1', format='text', text='1. Clarify the method.')])
        started = post(client, reviews + '/rounds', round_body, 'd2-round')
        assert started.status_code == 202, started.text

        current = client.get(root).json()['current_revision']
        assert current == 1
        appended = post(client, root + '/versions', planned(client, project, expected_revision=current), 'd2-overwrite')
        assert appended.status_code == 201, appended.text
        assert appended.json()['current_revision'] == 2
        items = client.get(path).json()['items']
        assert [item['id'] for item in items] == [manuscript['id']]
        assert items[0]['current_revision'] == 2
        old = client.get(root + '/versions/1')
        assert old.status_code == 200 and old.json()['id'] == version['id']
        assert sha256(client.get(download).content).hexdigest() == before
        saved = client.get(reviews + '/rounds/' + started.json()['id']).json()
        assert saved['manuscript']['version_id'] == version['id']
        assert saved['manuscript']['revision'] == 1


def test_thesis_customer_second_manuscript_is_rejected():
    with TestClient(app) as client:
        sign_in(client, 'd2-thesis-owner@manuscript.test', 'customer')
        project = thesis_project(client)
        first, _, _ = template(client, project, 'd2-school')
        assert run_school_template_task(first['task']['id'], 1, parser=analysis)['status'] == 'succeeded'
        confirmation, _, _ = confirm_template(client, project, first, 'd2-rules')
        profile = bind(client, project, confirmation, 0)
        material = upload_docx(client, project, 'd2-research.docx', 'The material reports 9 synthetic observations.')
        drain_document_parse(material)
        file_id = material['id']
        request = dict(title='Synthetic thesis', output_language='en',
                       sources=[dict(kind='original', id=file_id, file_id=file_id, role='user_results')],
                       thesis=dict(confirmation_id=confirmation['id'], profile_revision=profile['revision'], chapter_mappings=[
                           dict(chapter_id='results', purpose='results', output_language='project', result_group_ids=[])]))
        created = post(client, project + '/manuscripts', request, 'd2-thesis-first')
        assert created.status_code == 201, created.text
        replay = post(client, project + '/manuscripts', request, 'd2-thesis-first')
        assert replay.status_code == 200 and replay.json()['id'] == created.json()['id']
        assert_exists(post(client, project + '/manuscripts', request, 'd2-thesis-second'))
        assert run_task(created.json()['versions'][0]['task_id'], 1)['status'] == 'succeeded'
        root = project + '/manuscripts/' + created.json()['id']
        appended = post(client, root + '/versions', dict(request, expected_revision=1), 'd2-thesis-overwrite')
        assert appended.status_code == 201, appended.text
        assert appended.json()['current_revision'] == 2
        listed = client.get(project + '/manuscripts').json()['items']
        assert [item['id'] for item in listed] == [created.json()['id']]
        assert [v['revision'] for v in listed[0]['versions']][:2] == [2, 1]


def test_internal_roles_and_research_candidates_are_not_limited():
    with TestClient(app) as client:
        sign_in(client, 'd2-analyst@manuscript.test', 'admin')
        response = client.post('/api/v1/projects', json=dict(name='D2 internal', research_topic='Synthetic', project_type='sci'))
        assert response.status_code in (200, 201), response.text
        path = '/api/v1/projects/' + response.json()['id'] + '/manuscripts'
        assert post(client, path, body(), 'internal-first').status_code == 201
        assert post(client, path, body(), 'internal-second').status_code == 201
        assert len(client.get(path).json()['items']) == 2

