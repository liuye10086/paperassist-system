"""Customer project ownership, confirmed requirements and frozen delivery access."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from app.adapters.storage import ProjectStore
from app.auth.service import create_user, set_user_active
from app.core.config import get_data_dir
from app.db.database import database_connection
from app.domain.delivery_packages.contracts import SnapshotWrite
from app.domain.delivery_packages.service import DeliveryService, run_delivery_package_task
from app.main import app
from tests.api.test_excel import workbook_bytes
from tests.auth.test_account_roles import login, PASSWORD, write_headers


def sign_in(client, email, role):
    account = create_user(email, PASSWORD, role=role)
    response = login(client, email)
    assert response.status_code == 200, response.text
    client.headers.update(write_headers(response))
    return account['id']


def create_customer_project(client, key='customer-project'):
    response = client.post('/api/v1/projects', headers={'Idempotency-Key': key}, json={
        'name': 'Synthetic customer project', 'research_topic': 'Synthetic study',
        'project_type': 'research', 'delivery_kinds': ['analysis'],
    })
    assert response.status_code == 201, response.text
    return '/api/v1/projects/' + response.json()['id']


def write_requirements(client, project, revision, operation):
    response = client.post(project + '/requirements', headers={'Idempotency-Key': f'{operation}-{revision}'}, json={
        'expected_revision': revision, 'operation': operation,
        'content': {'schema_version': 1, 'services': ['analysis'], 'notes': 'Synthetic requirement'},
    })
    assert response.status_code == 201, response.text
    return response.json()['version']


def freeze_delivery(client, project, owner_id, requirement_id):
    """Fixture data for a real freeze, with the service acting inside the owner scope."""
    project_id = project.rsplit('/', 1)[-1]
    delivery = client.get(project + '/research-intake').json()['deliveries'][0]['id']
    content = workbook_bytes()
    upload = client.post(project + '/files', files={'file': ('synthetic.xlsx', content)})
    assert upload.status_code == 201, upload.text
    file_id = upload.json()['file']['id']
    service = DeliveryService(ProjectStore(get_data_dir(), owner_id=owner_id))
    snapshot, status = service.freeze(project_id, delivery, SnapshotWrite(
        stage='first', expected_revision=0, requirement_version_id=requirement_id,
        change_note='Internal fixture note', opinion_round='synthetic',
        members=[{'kind': 'file', 'file_id': file_id}],
    ), 'freeze-fixture')
    assert status == 201
    return service, snapshot, file_id, content


def publish_delivery(snapshot):
    with database_connection(write=True) as db:
        db.execute('''INSERT INTO customer_delivery_publications (snapshot_id,project_id,delivery_id,title)
            VALUES (%s,%s,%s,%s)''', (snapshot['id'], snapshot['project_id'], snapshot['delivery_id'], 'Synthetic analysis'))


def test_customer_intake_keeps_requirements_and_hides_internal_design():
    with TestClient(app) as client:
        owner_id = sign_in(client, 'former-analyst@workspace.test', 'analyst')
        project = create_customer_project(client)
        requirement = write_requirements(client, project, 1, 'save')
        design = client.post(project + '/research-designs', headers={'Idempotency-Key': 'private-design'}, json={
            'expected_revision': 2, 'operation': 'save',
            'content': {'schema_version': 1, 'experiments': [{'id': 'e1', 'data_type': 'Private design fixture'}]},
        })
        assert design.status_code == 201, design.text
        assert client.get(project + '/research-intake').json()['current_design']['id'] == design.json()['version']['id']

        with database_connection(write=True) as db:
            db.execute("UPDATE users SET role='customer' WHERE id=%s", (owner_id,))
        client.cookies.clear()
        assert login(client, 'former-analyst@workspace.test').status_code == 200
        intake = client.get(project + '/research-intake').json()
        assert intake['current_requirement']['id'] == requirement['id']
        assert intake['current_design'] is None
        assert intake['capabilities']['analysis'] is False
        assert 'Private design fixture' not in str(intake)
        assert 'created_by' not in intake['deliveries'][0]


def test_progress_follows_confirmed_version_and_its_publication():
    with TestClient(app) as client:
        owner_id = sign_in(client, 'progress@workspace.test', 'customer')
        project = create_customer_project(client)
        path = project + '/customer-workspace/progress'
        draft = {'status': 'draft', 'requirement_version': None, 'submitted_at': None,
                 'updated_at': None, 'note': None, 'feedback': []}
        assert client.get(path).json() == draft
        write_requirements(client, project, 1, 'save')
        assert client.get(path).json() == draft
        submitted = write_requirements(client, project, 2, 'confirm')
        waiting = client.get(path).json()
        submitted_at = datetime.fromisoformat(submitted['created_at'])
        assert {**waiting, 'submitted_at': None, 'updated_at': None} == {
            **draft, 'status': 'pending_assignment', 'requirement_version': 2,
        }
        assert datetime.fromisoformat(waiting['submitted_at']) == submitted_at
        assert datetime.fromisoformat(waiting['updated_at']) == submitted_at

        _, snapshot, _, _ = freeze_delivery(client, project, owner_id, submitted['id'])
        assert client.get(path).json() == waiting
        write_requirements(client, project, 3, 'save')
        assert client.get(path).json() == waiting
        project_id = snapshot['project_id']
        with database_connection(write=True) as db:
            db.execute('''INSERT INTO customer_requirement_progress (requirement_version_id,project_id,status,note)
                VALUES (%s,%s,'analyzing',NULL)''', (submitted['id'], project_id))
        assert client.get(path).json()['status'] == 'analyzing'
        with database_connection(write=True) as db:
            db.execute('''UPDATE customer_requirement_progress SET status='needs_materials',note=%s,
                updated_at=clock_timestamp() WHERE requirement_version_id=%s''', ('Please attach a sample sheet.', submitted['id']))
        needs = client.get(path).json()
        assert needs['status'] == 'needs_materials' and needs['note'] == 'Please attach a sample sheet.'

        publish_delivery(snapshot)
        delivered = client.get(path).json()
        assert delivered['status'] == 'delivered' and delivered['requirement_version'] == 2
        assert delivered['updated_at'] == client.get(project + '/customer-workspace/deliveries').json()['items'][0]['published_at']
        assert delivered['note'] is None
        write_requirements(client, project, 4, 'confirm')
        next_version = client.get(path).json()
        assert next_version['status'] == 'pending_assignment' and next_version['requirement_version'] == 4


def test_unpublished_and_foreign_delivery_routes_are_closed(monkeypatch, tmp_path):
    from app.domain.storage_governance import service as governance
    monkeypatch.setattr(governance.shutil, 'disk_usage', lambda _: SimpleNamespace(total=100 * 1024**3, free=90 * 1024**3))

    with TestClient(app) as customer, TestClient(app) as other:
        owner_id = sign_in(customer, 'delivery@workspace.test', 'customer')
        sign_in(other, 'other@workspace.test', 'customer')
        project = create_customer_project(customer)
        other_project = create_customer_project(other)
        submitted = write_requirements(customer, project, 1, 'confirm')
        service, snapshot, file_id, content = freeze_delivery(customer, project, owner_id, submitted['id'])
        workspace = project + '/customer-workspace'
        path = workspace + '/deliveries/' + snapshot['id']
        member_id = snapshot['members'][0]['id']
        download = path + f'/members/{member_id}/download'
        feedback = workspace + '/feedback'
        body = {'message': 'Synthetic feedback', 'snapshot_id': snapshot['id']}
        assert customer.get(workspace + '/deliveries').json() == {'items': []}
        for private in (path, path + '/download', download):
            assert customer.get(private).status_code == 404
        assert customer.post(feedback, headers={'Idempotency-Key': 'unpublished'}, json=body).status_code == 404

        legacy = project + f"/deliveries/{snapshot['delivery_id']}/snapshots"
        for internal in (legacy, legacy + '/' + snapshot['id'], snapshot['members'][0]['download_url'],
                         '/api/v1/tasks/unknown', project + '/summary', project + '/research-findings',
                         project + f'/files/{file_id}/analysis-runs', project + '/bio-analysis-runs'):
            assert customer.get(internal).status_code == 403, internal
        assert customer.post(project + '/bio-analysis-runs', json={}).status_code == 403
        assert customer.get(project + f'/files/{file_id}/download').content == content

        publish_delivery(snapshot)
        visible = customer.get(workspace + '/deliveries').json()['items']
        assert len(visible) == 1
        summary = visible[0]
        assert summary == {'id': snapshot['id'], 'title': 'Synthetic analysis', 'kind': 'analysis',
                           'revision': 1, 'published_at': summary['published_at'], 'member_count': 1}
        detail = customer.get(path).json()
        member = detail['members'][0]
        assert detail == {**summary, 'members': [member], 'package_url': None, 'feedback': []}
        assert member == {'id': member_id, 'name': member['name'], 'format': 'xlsx', 'size_bytes': len(content),
                          'download_url': download}
        assert customer.get(download).content == content
        assert customer.get(path + '/download').status_code == 409

        for foreign in (workspace + '/deliveries', path, path + '/download', download, workspace + '/progress'):
            assert other.get(foreign).status_code == 404
        assert other.post(feedback, headers={'Idempotency-Key': 'foreign'}, json=body).status_code == 404
        own_feedback = other_project + '/customer-workspace/feedback'
        assert other.post(own_feedback, headers={'Idempotency-Key': 'foreign'}, json=body).status_code == 404
        assert other.get(other_project + '/customer-workspace/deliveries/' + snapshot['id']).status_code == 404

        queued, status = service.package(snapshot['project_id'], snapshot['delivery_id'], snapshot['id'], 'customer-package')
        assert status == 201
        assert customer.get(path).json()['package_url'] is None
        result = run_delivery_package_task(queued['task_id'], queued['task']['revision'], staging_directory=tmp_path / 'staging')
        assert result['status'] == 'succeeded', result
        assert customer.get(path).json()['package_url'] == path + '/download'
        archive = customer.get(path + '/download')
        assert archive.status_code == 200, archive.text
        assert archive.headers['x-content-sha256'] == sha256(archive.content).hexdigest()
        with ZipFile(BytesIO(archive.content)) as package:
            assert package.namelist() == [member['name']]
            assert package.read(member['name']) == content
        assert customer.get(legacy + '/' + snapshot['id'] + '/download').status_code == 403
        with database_connection() as db:
            object_key = db.execute('SELECT object_key FROM files WHERE id=%s', (file_id,)).fetchone()['object_key']
        (get_data_dir() / object_key).write_bytes(b'corrupted bytes')
        assert customer.get(download).status_code == 409
        assert customer.get(path + '/download').status_code == 409


def test_feedback_is_scoped_idempotent_and_survives_reopen():
    with TestClient(app) as client:
        owner_id = sign_in(client, 'feedback@workspace.test', 'customer')
        project = create_customer_project(client)
        submitted = write_requirements(client, project, 1, 'confirm')
        _, snapshot, _, _ = freeze_delivery(client, project, owner_id, submitted['id'])
        publish_delivery(snapshot)
        workspace = project + '/customer-workspace'

        def send(key, body):
            return client.post(workspace + '/feedback', headers={'Idempotency-Key': key}, json=body)

        general = send('project-feedback', {'message': 'A follow-up material question'})
        assert general.status_code == 201, general.text
        assert send('blank', {'message': '   '}).status_code == 422
        assert send('oversized', {'message': 'x' * (64 * 1024)}).status_code == 413
        assert send('project-feedback', {'message': 'Another question'}).status_code == 409
        body = {'message': 'Please explain the workbook', 'snapshot_id': snapshot['id']}
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda _: send('delivery-feedback', body), range(2)))
        assert sorted(response.status_code for response in responses) == [200, 201]
        assert responses[0].json() == responses[1].json()
        saved = responses[0].json()
        assert set(saved) == {'id', 'message', 'created_at'}
        assert send('delivery-feedback', {'message': body['message']}).status_code == 409

        client.cookies.clear()
        assert login(client, 'feedback@workspace.test').status_code == 200
        assert client.get(workspace + '/progress').json()['feedback'] == [general.json()]
        path = workspace + '/deliveries/' + snapshot['id']
        assert client.get(path).json()['feedback'] == [saved]
        set_user_active('feedback@workspace.test', False)
        assert client.get(path).status_code == 401
        assert send('revoked', body).status_code == 401


def test_cloud_output_is_hidden_from_the_customers_material_routes():
    with TestClient(app) as client:
        owner_id = sign_in(client, 'files@workspace.test', 'customer')
        project = create_customer_project(client)
        project_id = project.rsplit('/', 1)[-1]
        files = project + '/files'
        material = client.post(files, files={'file': ('original.xlsx', workbook_bytes())}).json()['file']
        generated = client.post(files, files={'file': ('output.xlsx', workbook_bytes())}).json()['file']
        fake_sha = 'a' * 64
        with database_connection(write=True) as db:
            db.execute('''INSERT INTO tasks (id,project_id,user_id,task_type,idempotency_key,input_digest,
                input_snapshot,workflow_version,status,phase,revision,current_attempt,created_at,updated_at)
                VALUES ('cloud-task',%s,%s,'bio_cloud_run','cloud-task',%s,
                    jsonb_build_object('project_id',%s::text,'kind','bio_cloud_run','run_id','cloud-run'),
                    'bio_cloud_run_v1','succeeded','verify',1,0,now(),now())''', (project_id, owner_id, fake_sha, project_id))
            db.execute('''INSERT INTO bio_cloud_runs (id,project_id,task_id,request_key,request_digest,
                request_token,status,snapshot_json,created_at,updated_at)
                VALUES ('cloud-run',%s,'cloud-task','cloud-run',%s,'cloud-token','completed','{}',now(),now())''',
                (project_id, fake_sha))
            db.execute('''INSERT INTO bio_cloud_outputs (run_id,role,project_id,file_id,source_key,sha256,size_bytes)
                VALUES ('cloud-run','matrix',%s,%s,'synthetic-output',%s,%s)''',
                (project_id, generated['id'], generated['sha256'], generated['size_bytes']))

        assert client.get(files).json() == [material]
        page = client.get(files, params={'page': 1}).json()
        assert page['total'] == 1 and page['items'][0]['id'] == material['id']
        assert client.get(project).json()['file_count'] == 1
        assert client.get('/api/v1/projects').json()[0]['file_count'] == 1
        for action in ('download', 'preview'):
            assert client.get(files + f"/{generated['id']}/{action}").status_code == 404
        assert client.get(files + f"/{material['id']}/details").status_code == 403
        assert client.put(files + f"/{generated['id']}/purposes", json={'expected_revision': 1, 'purposes': []}).status_code == 404


@pytest.mark.parametrize('role', ['analyst', 'admin'])
def test_customer_routes_are_role_specific_and_legacy_delivery_still_reads(role):
    with TestClient(app) as client:
        owner_id = sign_in(client, f'{role}@workspace.test', role)
        project = create_customer_project(client)
        submitted = write_requirements(client, project, 1, 'confirm')
        _, snapshot, _, content = freeze_delivery(client, project, owner_id, submitted['id'])
        workspace = project + '/customer-workspace'
        assert client.get(workspace + '/progress').status_code == 403
        assert client.post(workspace + '/feedback', headers={'Idempotency-Key': 'wrong-role'}, json={'message': 'Hello'}).status_code == 403
        legacy = project + f"/deliveries/{snapshot['delivery_id']}/snapshots"
        assert client.get(legacy).json()['items'][0]['id'] == snapshot['id']
        assert client.get(snapshot['members'][0]['download_url']).content == content
