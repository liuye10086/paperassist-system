"""Assigned analysts update the customer's confirmed work and release frozen results."""

from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.core.config import get_data_dir
from app.db.database import database_connection
from app.domain.delivery_packages.contracts import SnapshotWrite
from app.domain.delivery_packages.service import DeliveryService
from app.adapters.storage import ProjectStore
from app.main import app
from tests.api.test_customer_workspace import create_customer_project, sign_in, write_requirements
from tests.api.test_excel import workbook_bytes


def assign(admin, project, analyst_id, revision=0):
    project_id = project.rsplit('/', 1)[-1]
    response = admin.patch('/api/v1/admin/project-assignments/' + project_id, json={
        'analyst_id': analyst_id, 'expected_revision': revision, 'reason': 'Synthetic analysis assignment',
    })
    assert response.status_code == 200, response.text
    return response.json()['revision']


def upload_material(customer, project):
    content = workbook_bytes()
    response = customer.post(project + '/files', files={'file': ('synthetic.xlsx', content)})
    assert response.status_code == 201, response.text
    return response.json()['file']['id'], content


def freeze_body(requirement, file_id):
    return {
        'stage': 'first', 'expected_revision': 0, 'requirement_version_id': requirement['id'],
        'change_note': 'Internal freeze rationale', 'opinion_round': 'Synthetic validation',
        'members': [{'kind': 'file', 'file_id': file_id}],
    }


def test_assigned_analyst_releases_frozen_snapshot_and_reads_customer_feedback():
    with TestClient(app) as customer, TestClient(app) as analyst, TestClient(app) as admin:
        sign_in(customer, 'release-customer@workspace.test', 'customer')
        analyst_id = sign_in(analyst, 'release-analyst@workspace.test', 'analyst')
        sign_in(admin, 'release-admin@workspace.test', 'admin')
        project = create_customer_project(customer)
        file_id, content = upload_material(customer, project)
        requirement = write_requirements(customer, project, 1, 'confirm')
        draft = customer.post(project + '/requirements', headers={'Idempotency-Key': 'next-draft'}, json={
            'expected_revision': 2, 'operation': 'save',
            'content': {'schema_version': 1, 'services': ['sci_draft'], 'notes': 'Unsubmitted notes'},
        })
        assert draft.status_code == 201, draft.text
        path = project + '/analyst-workspace'
        workspace = project + '/customer-workspace'

        assert analyst.get(path).status_code == 404
        assert customer.get(path).status_code == 403
        assert customer.get(workspace + '/progress').json()['status'] == 'pending_assignment'
        revision = assign(admin, project, analyst_id)
        assert customer.get(workspace + '/progress').json()['status'] == 'assigned'
        source = f'{project}/files/{file_id}'
        assessment = analyst.get(source + '/lifecycle/assessment', params={'action': 'reparse'})
        assert assessment.status_code == 200, assessment.text
        assert assessment.json()['can_reparse']
        assert analyst.get(source + '/lifecycle/tasks').status_code == 200
        assert analyst.get(source + '/lifecycle/assessment', params={'action': 'delete'}).status_code == 403
        assert analyst.get(source + '/lifecycle/deletion-requests').status_code == 404
        structure = analyst.post(source + '/structure-versions', headers={'Idempotency-Key': 'assigned-structure'}, json={
            'expected_latest_version': 0, 'expected_assessment_revision': assessment.json()['assessment_revision'],
        })
        assert structure.status_code == 202, structure.text
        assert analyst.get(source + '/lifecycle/tasks').json()['items'][0]['task_type'] == 'extract_dataset'
        from app.domain.tasks.dataset_execution import run_dataset_task
        from tests.api.test_datasets import structure_parser
        extraction = structure.json()['task']
        assert run_dataset_task(extraction['id'], extraction['revision'], parser=structure_parser)['status'] == 'succeeded'
        version = analyst.get(source + '/structure-versions/' + structure.json()['id']).json()['datasets'][0]
        setup = analyst.put(source + '/analysis-setup', json={
            'task_type': 'descriptive_boxplot', 'sheet_name': version['sheet_name'], 'numeric_column': 'B',
            'unit': '', 'missing_policy': 'exclude_selected_missing', 'expected_revision': 0, 'dataset_id': version['id'],
        })
        assert setup.status_code == 200, setup.text
        queued = analyst.post(source + '/analysis-runs', json={'expected_revision': setup.json()['revision']})
        assert queued.status_code == 202, queued.text
        assert queued.json()['task_type'] == 'statistics_compute'
        initial = analyst.get(path)
        assert initial.status_code == 200, initial.text
        assert initial.json() == {
            'assignment_revision': revision, 'requirement': {'id': requirement['id'], 'version': requirement['version']},
            'status': 'assigned', 'note': None, 'feedback': [], 'publications': [],
        }
        intake = analyst.get(project + '/research-intake').json()
        assert intake['current_requirement']['id'] == requirement['id']
        assert [d['kind'] for d in intake['deliveries']] == ['analysis']
        assert intake['deliveries'][0]['active']
        flow = analyst.get(project + '/workflow-state').json()
        assert flow['requirements'] == {'saved': True, 'version': requirement['version'], 'services': ['analysis']}
        assert flow['next_step'] == 'analysis'
        versions = analyst.get(project + '/requirements').json()['items']
        assert [item['id'] for item in versions] == [requirement['id']]
        assert analyst.get(project + '/requirements/' + draft.json()['version']['id']).status_code == 404
        customer_deliveries = customer.get(project + '/research-intake').json()['deliveries']
        sci_id = next(delivery['id'] for delivery in customer_deliveries if delivery['kind'] == 'sci_draft')
        assert analyst.get(project + '/deliveries/' + sci_id + '/candidates').status_code == 404
        design = analyst.post(project + '/research-designs', headers={'Idempotency-Key': 'design'}, json={
            'expected_revision': intake['revision'], 'operation': 'save',
            'content': {'schema_version': 1, 'experiments': [{'id': 'experiment', 'data_type': 'Synthetic'}]},
        })
        assert design.status_code == 201, design.text
        assert design.json()['version']['created_by'] == analyst_id

        progress = {
            'assignment_revision': revision, 'requirement_version_id': requirement['id'],
            'status': 'needs_materials', 'note': ' Please attach sample groups. ',
        }
        updated = analyst.patch(path + '/progress', json=progress)
        assert updated.status_code == 200, updated.text
        assert updated.json()['status'] == 'needs_materials'
        waiting = customer.get(workspace + '/progress').json()
        assert waiting['status'] == 'needs_materials'
        assert waiting['note'] == 'Please attach sample groups.'
        feedback = customer.post(workspace + '/feedback', headers={'Idempotency-Key': 'material-feedback'},
                                 json={'message': 'The sample groups are attached.'})
        assert feedback.status_code == 201, feedback.text
        assert analyst.get(path).json()['feedback'] == [feedback.json()]

        delivery = project + '/deliveries/' + intake['deliveries'][0]['id']
        candidates = analyst.get(delivery + '/candidates')
        assert candidates.status_code == 200, candidates.text
        assert [item['id'] for item in candidates.json()['requirements']] == [requirement['id']]
        frozen = analyst.post(delivery + '/snapshots', headers={'Idempotency-Key': 'analyst-freeze'},
                              json=freeze_body(requirement, file_id))
        assert frozen.status_code == 201, frozen.text
        snapshot = frozen.json()
        assert customer.get(workspace + '/deliveries').json() == {'items': []}

        publication = {'assignment_revision': revision, 'snapshot_id': snapshot['id'], 'title': 'Analysis output'}
        with database_connection() as db:
            object_key = db.execute('SELECT object_key FROM files WHERE id=%s', (file_id,)).fetchone()['object_key']
        material = get_data_dir() / object_key
        material.write_bytes(b'changed after the snapshot was frozen')
        try:
            rejected = analyst.post(path + '/publish', json=publication)
            assert rejected.status_code == 409, rejected.text
            assert customer.get(workspace + '/deliveries').json() == {'items': []}
            assert customer.get(workspace + '/progress').json()['status'] == 'needs_materials'
        finally:
            material.write_bytes(content)

        with ThreadPoolExecutor(max_workers=2) as executor:
            releases = list(executor.map(lambda _: analyst.post(path + '/publish', json=publication), range(2)))
        assert sorted(response.status_code for response in releases) == [200, 201]
        assert releases[0].json() == releases[1].json()
        assert analyst.post(path + '/publish', json={**publication, 'title': 'Changed title'}).status_code == 409
        assert customer.get(workspace + '/progress').json()['status'] == 'delivered'
        assert analyst.patch(path + '/progress', json=progress).status_code == 409

        delivered = workspace + '/deliveries/' + snapshot['id']
        detail = customer.get(delivered).json()
        assert set(detail) == {'id', 'title', 'kind', 'revision', 'published_at', 'member_count',
                               'members', 'package_url', 'feedback'}
        assert detail['title'] == 'Analysis output' and len(detail['members']) == 1
        member = detail['members'][0]
        assert set(member) == {'id', 'name', 'format', 'size_bytes', 'download_url'}
        assert customer.get(member['download_url']).content == content
        reply = customer.post(workspace + '/feedback', headers={'Idempotency-Key': 'delivery-feedback'},
                              json={'message': 'Received and downloaded.', 'snapshot_id': snapshot['id']})
        assert reply.status_code == 201, reply.text
        assert analyst.get(path).json()['publications'] == [{**releases[0].json(), 'feedback': [reply.json()]}]

        assign(admin, project, None, revision)
        assert analyst.get(path).status_code == 404
        assert analyst.post(path + '/publish', json=publication).status_code == 404
        assert customer.get(workspace + '/progress').json()['status'] == 'delivered'
        assert customer.get(member['download_url']).content == content


def test_reassignment_and_new_submission_reject_stale_progress_and_publication():
    with TestClient(app) as customer, TestClient(app) as analyst, TestClient(app) as admin:
        owner = sign_in(customer, 'stale-customer@workspace.test', 'customer')
        analyst_id = sign_in(analyst, 'stale-analyst@workspace.test', 'analyst')
        sign_in(admin, 'stale-admin@workspace.test', 'admin')
        project = create_customer_project(customer)
        requirement = write_requirements(customer, project, 1, 'confirm')
        file_id, _ = upload_material(customer, project)
        path = project + '/analyst-workspace'
        workspace = project + '/customer-workspace'
        revision = assign(admin, project, analyst_id)
        progress = {'assignment_revision': revision, 'requirement_version_id': requirement['id'],
                    'status': 'analyzing', 'note': 'Analysis is in progress.'}
        assert analyst.patch(path + '/progress', json=progress).status_code == 200
        delivery_id = analyst.get(project + '/research-intake').json()['deliveries'][0]['id']
        frozen = analyst.post(project + '/deliveries/' + delivery_id + '/snapshots',
                              headers={'Idempotency-Key': 'unpublished-freeze'}, json=freeze_body(requirement, file_id))
        assert frozen.status_code == 201, frozen.text
        publication = {'assignment_revision': revision, 'snapshot_id': frozen.json()['id'], 'title': 'Stale output'}

        withdrawn = assign(admin, project, None, revision)
        assert analyst.patch(path + '/progress', json=progress).status_code == 404
        assert customer.get(workspace + '/progress').json()['status'] == 'pending_assignment'
        reassigned = assign(admin, project, analyst_id, withdrawn)
        assert customer.get(workspace + '/progress').json()['status'] == 'assigned'
        assert analyst.patch(path + '/progress', json=progress).status_code == 409
        assert analyst.post(path + '/publish', json=publication).status_code == 409

        submitted = write_requirements(customer, project, 2, 'confirm')
        assert analyst.get(path).json()['requirement']['id'] == submitted['id']
        assert analyst.patch(path + '/progress', json={**progress, 'assignment_revision': reassigned}).status_code == 409
        assert analyst.post(path + '/publish', json={**publication, 'assignment_revision': reassigned}).status_code == 409

        foreign = create_customer_project(customer, key='second-customer-project')
        foreign_requirement = write_requirements(customer, foreign, 1, 'confirm')
        foreign_file, _ = upload_material(customer, foreign)
        foreign_id = foreign.rsplit('/', 1)[-1]
        foreign_delivery = customer.get(foreign + '/research-intake').json()['deliveries'][0]['id']
        service = DeliveryService(ProjectStore(get_data_dir(), owner_id=owner))
        other, status = service.freeze(foreign_id, foreign_delivery,
                                       SnapshotWrite(**freeze_body(foreign_requirement, foreign_file)), 'other-freeze')
        assert status == 201
        denied = analyst.post(path + '/publish', json={
            **publication, 'assignment_revision': reassigned, 'snapshot_id': other['id'],
        })
        assert denied.status_code == 404, denied.text
        with database_connection() as db:
            assert db.execute('SELECT count(*) AS count FROM customer_delivery_publications').fetchone()['count'] == 0
