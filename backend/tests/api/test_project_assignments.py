"""Project grants, scope isolation and revocation in disposable PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api import projects
from app.auth.service import set_user_active
from app.db.database import database_connection
from app.main import app
from tests.api.test_analysis import selection
from tests.api.test_customer_workspace import create_customer_project, sign_in, write_requirements
from tests.api.test_excel import workbook_bytes
from tests.api.test_projects import create_project
from tests.helpers.evidence_samples import evidence_docx


ASSIGNMENTS = '/api/v1/admin/project-assignments'
ASSIGNED = '/api/v1/assigned-projects'


def assign(admin, project, analyst_id, revision, reason='Synthetic assignment'):
    return admin.patch(ASSIGNMENTS + '/' + project.rsplit('/', 1)[-1], json={
        'analyst_id': analyst_id, 'expected_revision': revision, 'reason': reason,
    })


def test_admin_assignment_revision_audit_and_role_rules():
    customer, admin, analyst, replacement = [TestClient(app) for _ in range(4)]
    owner_id = sign_in(customer, 'owner@assignments.test', 'customer')
    sign_in(admin, 'admin@assignments.test', 'admin')
    analyst_id = sign_in(analyst, 'analyst@assignments.test', 'analyst')
    other_id = sign_in(replacement, 'replacement@assignments.test', 'analyst')
    own = create_project(analyst)
    project = create_customer_project(customer)
    project_id = project.rsplit('/', 1)[-1]
    requirement = write_requirements(customer, project, 1, 'confirm')

    initial = admin.get(ASSIGNMENTS, params={'q': 'owner@assignments.test', 'page_size': 1})
    assert initial.status_code == 200, initial.text
    item = initial.json()['items'][0]
    assert initial.json()['total'] == 1
    assert (item['id'], item['revision'], item['analyst_id'], item['submitted_version'], item['progress_status']) == (
        project_id, 0, None, requirement['version'], 'pending_assignment')
    assert assign(customer, project, analyst_id, 0).status_code == 403
    assert analyst.get(ASSIGNMENTS).status_code == 403
    assert assign(admin, project, owner_id, 0).status_code == 422
    assert assign(admin, '/api/v1/projects/' + own['id'], analyst_id, 0).status_code == 404

    with database_connection(write=True) as db:
        db.execute('''INSERT INTO customer_requirement_progress (requirement_version_id,project_id,status)
            VALUES (%s,%s,'needs_materials')''', (requirement['id'], project_id))
    assert admin.get(ASSIGNMENTS).json()['items'][0]['progress_status'] == 'needs_materials'

    first = assign(admin, project, analyst_id, 0)
    assert first.status_code == 200, first.text
    assert (first.json()['revision'], first.json()['progress_status']) == (1, 'assigned')
    assert assign(admin, project, other_id, 0).status_code == 409
    assert assign(admin, project, other_id, 1, 'Replacement coverage').json()['revision'] == 2
    revoked = assign(admin, project, None, 2, 'Revoke after handoff').json()
    assert (revoked['revision'], revoked['progress_status']) == (3, 'pending_assignment')
    history = admin.get(f'{ASSIGNMENTS}/{project_id}/events', params={'page_size': 2})
    assert history.status_code == 200, history.text
    events = history.json()['items']
    assert history.json()['total'] == 3
    assert [(event['actor_email'], event['previous_analyst_email'], event['analyst_email'], event['revision'])
            for event in events] == [
        ('admin@assignments.test', 'replacement@assignments.test', None, 3),
        ('admin@assignments.test', 'analyst@assignments.test', 'replacement@assignments.test', 2),
    ]
    with database_connection() as db:
        assert db.execute('SELECT owner_id FROM projects WHERE id=%s', (project_id,)).fetchone()['owner_id'] == owner_id
        privileges = db.execute("""SELECT has_table_privilege(current_user,'project_assignment_events','UPDATE') AS can_update,
            has_table_privilege(current_user,'project_assignment_events','DELETE') AS can_delete""").fetchone()
        assert dict(privileges) == {'can_update': False, 'can_delete': False}


def test_delegate_scope_checks_nested_files_tasks_and_actor():
    owner, admin, analyst, outsider = [TestClient(app) for _ in range(4)]
    owner_id = sign_in(owner, 'scope-owner@assignments.test', 'customer')
    sign_in(admin, 'scope-admin@assignments.test', 'admin')
    analyst_id = sign_in(analyst, 'scope-analyst@assignments.test', 'analyst')
    sign_in(outsider, 'scope-outsider@assignments.test', 'analyst')
    own_project = create_project(analyst)
    project = create_customer_project(owner)
    other = create_customer_project(owner, key='same-customer-other-project')
    requirement = write_requirements(owner, project, 1, 'confirm')
    content = workbook_bytes()
    response = owner.post(project + '/files', files={'file': ('assigned.xlsx', content)})
    assert response.status_code == 201, response.text
    file_id = response.json()['file']['id']
    response = owner.post(other + '/files', files={'file': ('other.xlsx', content)})
    assert response.status_code == 201, response.text
    other_file_id = response.json()['file']['id']

    assert analyst.get(project).status_code == 404
    assert assign(admin, project, analyst_id, 0).status_code == 200
    project_id = project.rsplit('/', 1)[-1]
    assert analyst.get(ASSIGNED, params={'type': 'research'}).json()['items'][0]['id'] == project_id
    assert analyst.get(ASSIGNED, params={'q': 'no match'}).json()['total'] == 0
    assert outsider.get(ASSIGNED).json()['total'] == 0
    assert [row['id'] for row in analyst.get('/api/v1/projects').json()] == [own_project['id']]
    assert analyst.get(project).json()['assignment_revision'] == 1
    assert 'assignment_revision' not in owner.get(project).json()
    assert analyst.get('/api/v1/auth/me').json()['user']['id'] == analyst_id
    assert analyst.get(project + '/requirements/' + requirement['id']).status_code == 200
    design = analyst.post(project + '/research-designs', headers={'Idempotency-Key': 'assigned-design'}, json={
        'expected_revision': 2, 'operation': 'save',
        'content': {'schema_version': 1, 'experiments': [{'id': 'e1', 'data_type': 'Synthetic design'}]},
    })
    assert design.status_code == 201, design.text
    design_version = design.json()['version']
    assert design_version['created_by'] == analyst_id
    catalog = analyst.get(project + '/bio-insights/sources', params={'source_kind': 'research_design_version'})
    assert catalog.status_code == 200, catalog.text
    assert [item['source_id'] for item in catalog.json()['items']] == [design_version['id']]
    source = project + '/bio-insights/sources/research_design_version/' + design_version['id'] + '/observations'
    assert analyst.get(source).status_code == 200
    for path in (other, project + f'/files/{other_file_id}/download',
                 project + '/research-results/writing-config?delivery_id=unknown',
                 project + f'/files/{file_id}/lifecycle/deletion-requests'):
        assert analyst.get(path).status_code == 404, path
    assert analyst.get(project + '/customer-workspace/progress').status_code == 403
    assert analyst.post(project + '/requirements', headers={'Idempotency-Key': 'analyst-cannot-submit'}, json={
        'expected_revision': 3, 'operation': 'confirm', 'content': {'schema_version': 1, 'services': ['analysis']},
    }).status_code == 404

    file_path = project + f'/files/{file_id}'
    assert analyst.get(file_path + '/download').content == content
    assert outsider.get(file_path + '/download').status_code == 404
    saved = analyst.put(file_path + '/analysis-setup', json=selection(
        expected_revision=0, sheet_name='研究数据', numeric_column='B', group_column=None,
    ))
    assert saved.status_code == 200, saved.text
    queued = analyst.post(file_path + '/analysis-runs', json={'expected_revision': 1})
    assert queued.status_code == 202, queued.text
    task_id = queued.json()['id']
    task = '/api/v1/tasks/' + task_id
    assert analyst.get(task).status_code == 200
    assert analyst.get(task + '/workspace').status_code == 200
    assert analyst.get(task + '/events').status_code == 200
    with database_connection(write=True) as db:
        for task_key, pid, task_type in (
            ('foreign-analysis-task', other.rsplit('/', 1)[-1], 'statistics_compute'),
            ('private-writing-task', project_id, 'manuscript_draft'),
        ):
            db.execute('''INSERT INTO tasks (id,project_id,user_id,task_type,idempotency_key,input_digest,
                input_snapshot,workflow_version,status,phase,revision,current_attempt,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,'{}','fixture_v1','queued','plan',1,0,now(),now())''',
                (task_key, pid, owner_id, task_type, task_key, 'a' * 64))
    assert analyst.get('/api/v1/tasks/foreign-analysis-task').status_code == 404
    assert analyst.get('/api/v1/tasks/private-writing-task/workspace').status_code == 404
    assert analyst.post('/api/v1/tasks/private-writing-task/retry', json={'expected_revision': 1}).status_code == 404
    assert analyst.get(project + '/tasks').json()['total'] == 1
    assert analyst.get(other + '/tasks').status_code == 404
    assert outsider.get(task).status_code == 404
    with database_connection() as db:
        assert db.execute('SELECT user_id FROM tasks WHERE id=%s', (task_id,)).fetchone()['user_id'] == owner_id
        audit = db.execute('SELECT user_id FROM operational_request_events WHERE request_id=%s',
                           (queued.headers['x-request-id'],)).fetchone()
        assert audit['user_id'] == analyst_id

    assert assign(admin, project, None, 1).status_code == 200
    assert analyst.get(project).status_code == 404
    assert analyst.get(file_path + '/download').status_code == 404
    assert analyst.get(task).status_code == 404
    assert assign(admin, project, analyst_id, 2).status_code == 200
    set_user_active('scope-analyst@assignments.test', False)
    assert analyst.get(project).status_code == 401
    assert assign(admin, project, analyst_id, 3).status_code == 422


def test_write_rechecks_assignment_after_concurrent_revocation(monkeypatch):
    owner, admin, analyst = [TestClient(app) for _ in range(3)]
    sign_in(owner, 'race-owner@assignments.test', 'customer')
    sign_in(admin, 'race-admin@assignments.test', 'admin')
    analyst_id = sign_in(analyst, 'race-analyst@assignments.test', 'analyst')
    project = create_customer_project(owner)
    assert assign(admin, project, analyst_id, 0).status_code == 200
    response = owner.post(project + '/files', files={'file': ('race.xlsx', workbook_bytes())})
    assert response.status_code == 201, response.text
    path = project + '/files/' + response.json()['file']['id']
    ready, released = Event(), Event()
    original = projects.assign_file_purposes

    def pause_before_write(store, project_id, file_id, changes):
        assert store.actor_id == analyst_id
        assert store.assignment.revision == 1
        ready.set()
        assert released.wait(10)
        return original(store, project_id, file_id, changes)

    monkeypatch.setattr(projects, 'assign_file_purposes', pause_before_write)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(analyst.put, path + '/purposes', json={'expected_revision': 1, 'purposes': ['methods']})
        try:
            assert ready.wait(10)
            assert assign(admin, project, None, 1).status_code == 200
        finally:
            released.set()
        result = pending.result(timeout=10)
    assert result.status_code == 409, result.text
    assert result.json()['detail']['code'] == 'project_assignment_stale'
    assert owner.get(project + '/files', params={'page': 1}).json()['items'][0]['metadata_revision'] == 1


def test_customer_materials_exclude_analyst_uploads_and_batches():
    owner, admin, analyst = [TestClient(app) for _ in range(3)]
    sign_in(owner, 'materials-owner@assignments.test', 'customer')
    sign_in(admin, 'materials-admin@assignments.test', 'admin')
    analyst_id = sign_in(analyst, 'materials-analyst@assignments.test', 'analyst')
    project = create_customer_project(owner)
    assert assign(admin, project, analyst_id, 0).status_code == 200
    original = workbook_bytes()
    sync_headers = {'Idempotency-Key': str(uuid4())}
    owner_upload = owner.post(project + '/files', headers=sync_headers, files={'file': ('customer.xlsx', original)})
    assert owner_upload.status_code == 201, owner_upload.text
    customer_file = owner_upload.json()['file']['id']
    private_upload = analyst.post(project + '/files', headers=sync_headers, files={'file': ('private.xlsx', original)})
    assert private_upload.status_code == 201, private_upload.text
    private_files = [private_upload.json()['file']['id']]
    assert owner.post(project + '/files', headers=sync_headers,
                      files={'file': ('customer.xlsx', original)}).json()['file']['id'] == customer_file
    resource = analyst.post(project + '/bio-resource-files', headers={'Idempotency-Key': 'private-resource'},
                            files={'file': ('resource.tsv', b'gene\tcount\ng1\t4\n')})
    assert resource.status_code == 201, resource.text
    private_files.append(resource.json()['file_id'])

    for route, filename, content in (
        ('file-batches', 'private.docx', evidence_docx()),
        ('bio-upload-batches', 'private.tsv', b'gene\tcount\ng1\t4\n'),
    ):
        base = project + '/' + route
        shared_key = {'Idempotency-Key': 'actor-scoped-' + route}
        customer_item_id, analyst_item_id = str(uuid4()), str(uuid4())
        customer_batch = owner.post(base, headers=shared_key, json={'items': [
            {'client_id': customer_item_id, 'filename': filename, 'size_bytes': len(content)},
        ]})
        assert customer_batch.status_code == 201, customer_batch.text
        analyst_batch = analyst.post(base, headers=shared_key, json={'items': [
            {'client_id': analyst_item_id, 'filename': filename, 'size_bytes': len(content)},
        ]})
        assert analyst_batch.status_code == 201, analyst_batch.text
        customer_batch_path = base + '/' + customer_batch.json()['id']
        analyst_batch_path = base + '/' + analyst_batch.json()['id']
        assert analyst.post(customer_batch_path + '/items/' + customer_item_id,
                            files={'file': (filename, content)}).status_code == 404
        private = analyst.post(analyst_batch_path + '/items/' + analyst_item_id, files={'file': (filename, content)})
        assert private.status_code == 202, private.text
        private_files.append(private.json()['file_id'])
        assert owner.get(analyst_batch_path).status_code == 404
        assert owner.post(analyst_batch_path + '/items/' + analyst_item_id,
                          files={'file': (filename, content)}).status_code == 404
        assert owner.get(base).json()['total'] == 1
        assert owner.get(customer_batch_path).status_code == 200

    assert owner.get(project).json()['file_count'] == 1
    assert [row['id'] for row in owner.get(project + '/files').json()] == [customer_file]
    assert [row['id'] for row in owner.get(project + '/files', params={'page': 1}).json()['items']] == [customer_file]
    assert owner.get(project + f'/files/{customer_file}/download').content == original
    assert analyst.get(project + '/bio-insights/sources', params={'source_kind': 'original_file'}).json()['total'] == 5
    for file_id in private_files:
        base = project + f'/files/{file_id}'
        assert owner.get(base + '/download').status_code == 404
        assert owner.get(base + '/preview').status_code == 404
        assert owner.put(base + '/purposes', json={'expected_revision': 1, 'purposes': ['methods']}).status_code == 404
        assert analyst.get(base + '/download').status_code == 200

    def submit_reference(file_id):
        return owner.post(project + '/requirements', headers={'Idempotency-Key': 'material-reference'}, json={
            'expected_revision': 1, 'operation': 'save',
            'content': {'schema_version': 1, 'services': ['analysis']},
            'material_refs': [{'availability': 'provided', 'purpose': 'raw_data', 'file_id': file_id}],
        })

    hidden_reference = submit_reference(private_files[0])
    assert hidden_reference.status_code == 422, hidden_reference.text
    assert hidden_reference.json()['detail']['code'] == 'research_material_invalid'
    assert submit_reference(customer_file).status_code == 201
