"""Customers complete an analyst's material request; progress follows the current grant."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db.database import database_connection
from app.main import app
from tests.api.test_analyst_workspace import assign, upload_material
from tests.api.test_customer_project_types import SCI_SETTINGS, create, project_body, project_path
from tests.api.test_customer_workspace import create_customer_project, sign_in, write_requirements


def code(response):
    return response.json()['detail']['code']


def request_materials(customer, analyst, admin, prefix):
    sign_in(customer, f'{prefix}-customer@submissions.test', 'customer')
    analyst_id = sign_in(analyst, f'{prefix}-analyst@submissions.test', 'analyst')
    sign_in(admin, f'{prefix}-admin@submissions.test', 'admin')
    project = create_customer_project(customer)
    requirement = write_requirements(customer, project, 1, 'confirm')
    revision = assign(admin, project, analyst_id)
    progress = {'assignment_revision': revision, 'requirement_version_id': requirement['id'],
                'status': 'needs_materials', 'note': 'Please attach sample groups.'}
    assert analyst.patch(project + '/analyst-workspace/progress', json=progress).status_code == 200
    file_id, _ = upload_material(customer, project)
    return project, requirement, revision, file_id


def submit(client, project, key, version, file_ids, note=None):
    return client.post(project + '/customer-workspace/material-submissions', headers={'Idempotency-Key': key},
                       json={'requirement_version': version, 'file_ids': file_ids, 'note': note})


def test_submission_completes_request_replays_and_lets_analyst_continue():
    with TestClient(app) as customer, TestClient(app) as analyst, TestClient(app) as admin:
        project, requirement, revision, file_id = request_materials(customer, analyst, admin, 'complete')
        version = requirement['version']
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda key: submit(customer, project, key, version, [file_id], 'Groups attached.'),
                                          ('first-tab', 'second-tab')))
        assert sorted(r.status_code for r in responses) == [201, 409], [r.text for r in responses]
        created = next(r for r in responses if r.status_code == 201)
        assert code(next(r for r in responses if r.status_code == 409)) == 'materials_not_requested'
        saved = created.json()
        assert set(saved) == {'id', 'requirement_version', 'file_ids', 'files', 'note', 'created_at'}
        assert (saved['requirement_version'], saved['file_ids'], saved['note']) == (version, [file_id], 'Groups attached.')
        assert saved['files'] == [{'id': file_id, 'name': 'synthetic.xlsx'}]
        key = 'first-tab' if responses[0].status_code == 201 else 'second-tab'
        replay = submit(customer, project, key, version, [file_id], 'Groups attached.')
        assert (replay.status_code, replay.json()) == (200, saved)
        assert code(submit(customer, project, key, version, [file_id], 'Changed note')) == 'research_request_conflict'
        assert code(submit(customer, project, 'third-tab', version, [file_id])) == 'materials_not_requested'

        progress = customer.get(project + '/customer-workspace/progress').json()
        assert progress['status'] == 'materials_submitted' and progress['submissions'] == [saved]
        path = project + '/analyst-workspace'
        view = analyst.get(path)
        assert view.status_code == 200, view.text
        assert view.json()['status'] == 'materials_submitted' and view.json()['submissions'] == [saved]
        assignments = admin.get('/api/v1/admin/project-assignments').json()['items']
        assert assignments[0]['progress_status'] == 'materials_submitted'

        body = {'assignment_revision': revision, 'requirement_version_id': requirement['id'], 'status': 'materials_submitted'}
        assert analyst.patch(path + '/progress', json=body).status_code == 422
        resumed = analyst.patch(path + '/progress', json={**body, 'status': 'analyzing'})
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()['status'] == 'analyzing' and resumed.json()['submissions'] == [saved]
        assert customer.get(project + '/customer-workspace/progress').json()['status'] == 'analyzing'
        with database_connection() as db:
            assert db.execute('SELECT count(*) AS n FROM customer_material_submissions').fetchone()['n'] == 1


def test_submission_rejects_unrequested_stale_and_foreign_files():
    with TestClient(app) as customer, TestClient(app) as analyst, TestClient(app) as admin:
        sign_in(customer, 'reject-customer@submissions.test', 'customer')
        analyst_id = sign_in(analyst, 'reject-analyst@submissions.test', 'analyst')
        sign_in(admin, 'reject-admin@submissions.test', 'admin')
        project = create_customer_project(customer)
        other = create_customer_project(customer, key='other-project')
        foreign_file, _ = upload_material(customer, other)
        requirement = write_requirements(customer, project, 1, 'confirm')
        file_id, _ = upload_material(customer, project)
        version = requirement['version']
        assert code(submit(customer, project, 'early', version, [file_id])) == 'materials_not_requested'
        revision = assign(admin, project, analyst_id)
        assert code(submit(customer, project, 'assigned', version, [file_id])) == 'materials_not_requested'
        assert analyst.patch(project + '/analyst-workspace/progress', json={
            'assignment_revision': revision, 'requirement_version_id': requirement['id'], 'status': 'needs_materials',
        }).status_code == 200

        assert code(submit(customer, project, 'stale', version + 1, [file_id])) == 'research_revision_conflict'
        for key, files in (('foreign', [foreign_file]), ('mixed', [file_id, foreign_file]), ('missing', ['no-such-file'])):
            assert submit(customer, project, key, version, files).status_code == 422, key
        for key, files in (('empty', []), ('duplicate', [file_id, file_id]), ('many', [f'f{i}' for i in range(51)])):
            assert submit(customer, project, key, version, files).status_code == 422, key
        assert submit(customer, project, 'long-note', version, [file_id], 'x' * 4001).status_code == 422
        assert customer.post(project + '/customer-workspace/material-submissions',
                             json={'requirement_version': version, 'file_ids': [file_id]}).status_code == 422
        assert customer.get(project + '/customer-workspace/progress').json()['submissions'] == []

        with database_connection(write=True) as db:
            owner = db.execute('SELECT owner_id FROM projects WHERE id=%s', (project.rsplit('/', 1)[-1],)).fetchone()['owner_id']
            db.execute('''INSERT INTO storage_deletion_operations(id,project_id,owner_id,scope_kind,reason,manifest,manifest_sha256,state)
                VALUES(%s,%s,%s,'project','synthetic barrier only','{}'::jsonb,%s,'partial_retained')''',
                (str(uuid4()), project.rsplit('/', 1)[-1], owner, 'a' * 64))
        blocked = submit(customer, project, 'blocked', version, [file_id])
        assert (blocked.status_code, code(blocked)) == (409, 'storage_deletion_pending')
        assert customer.get(project + '/customer-workspace/progress').json()['status'] == 'needs_materials'


def test_submission_route_is_research_only_customer_only_and_owner_scoped():
    with TestClient(app) as customer, TestClient(app) as other, TestClient(app) as analyst:
        sign_in(customer, 'scope-customer@submissions.test', 'customer')
        sign_in(other, 'scope-other@submissions.test', 'customer')
        sign_in(analyst, 'scope-analyst@submissions.test', 'analyst')
        project = create_customer_project(customer)
        sci = project_path(create(customer, 'sci-project', **project_body('sci', sci_settings=SCI_SETTINGS)))
        denied = submit(customer, sci, 'sci', 1, ['any-file'])
        assert (denied.status_code, code(denied)) == (403, 'customer_project_type_forbidden')
        foreign = submit(other, project, 'foreign', 1, ['any-file'])
        assert (foreign.status_code, code(foreign)) == (404, 'project_not_found')
        own = create_customer_project(analyst, key='analyst-project')
        wrong_role = submit(analyst, own, 'analyst', 1, ['any-file'])
        assert (wrong_role.status_code, code(wrong_role)) == (403, 'permission_denied')


def test_reassignment_after_submission_returns_to_assigned_and_keeps_history():
    with TestClient(app) as customer, TestClient(app) as analyst, TestClient(app) as admin, \
            TestClient(app) as replacement:
        project, requirement, revision, file_id = request_materials(customer, analyst, admin, 'reassign')
        replacement_id = sign_in(replacement, 'reassign-replacement@submissions.test', 'analyst')
        saved = submit(customer, project, 'submitted', requirement['version'], [file_id])
        assert saved.status_code == 201, saved.text
        progress = project + '/customer-workspace/progress'

        withdrawn = assign(admin, project, None, revision)
        assert customer.get(progress).json()['status'] == 'pending_assignment'
        assign(admin, project, replacement_id, withdrawn)
        current = customer.get(progress).json()
        assert current['status'] == 'assigned' and current['submissions'] == [saved.json()]
        path = project + '/analyst-workspace'
        assert analyst.get(path).status_code == 404
        assert analyst.patch(path + '/progress', json={
            'assignment_revision': revision, 'requirement_version_id': requirement['id'], 'status': 'analyzing',
        }).status_code == 404
        view = replacement.get(path).json()
        assert view['status'] == 'assigned' and view['submissions'] == [saved.json()]
        resubmit = submit(customer, project, 'after-reassign', requirement['version'], [file_id])
        assert code(resubmit) == 'materials_not_requested'
