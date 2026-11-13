"""Permanent deletion through the admin API in an isolated PostgreSQL schema."""

from fastapi.testclient import TestClient

from app.auth.service import create_user
from app.core.config import get_data_dir
from app.core.exceptions import StorageError
from app.db.database import database_connection
from app.main import app
from tests.api.test_admin_operations import PASSWORD, login, seed_task
from tests.api.test_customer_workspace import create_customer_project, write_requirements
from tests.api.test_excel import workbook_bytes
from tests.api.test_project_assignments import assign


def delete(client, account, revision=1):
    return client.request('DELETE', '/api/v1/admin/users/' + account['id'],
                          json={'expected_revision': revision})


def test_delete_owned_project_files_and_local_account_history(monkeypatch):
    target = create_user('customer@account-deletion.test', PASSWORD, 'customer')
    operator = create_user('admin@account-deletion.test', PASSWORD, 'admin')
    retained, _ = seed_task(operator['id'])
    _, terminal_task = seed_task(target['id'])
    with TestClient(app) as customer, TestClient(app) as admin:
        login(customer, target)
        login(admin, operator)
        project = create_customer_project(customer)
        write_requirements(customer, project, 1, 'confirm')
        upload = customer.post(project + '/files', files={'file': ('data.xlsx', workbook_bytes())})
        assert upload.status_code == 201, upload.text
        file_id = upload.json()['file']['id']
        with database_connection(write=True) as db:
            key = db.execute('SELECT object_key FROM files WHERE id=%s', (file_id,)).fetchone()['object_key']
            db.execute("UPDATE tasks SET status='running' WHERE id=%s", (terminal_task,))
        path = get_data_dir() / key
        assert path.is_file()
        assert delete(customer, target).status_code == 403
        assert delete(admin, operator).status_code == 409
        assert delete(admin, target, revision=2).json()['detail']['code'] == 'admin_revision_conflict'
        assert delete(admin, target).json()['detail']['code'] == 'account_delete_blocked'
        assert path.is_file()
        with database_connection(write=True) as db:
            db.execute("UPDATE tasks SET status='failed' WHERE id=%s", (terminal_task,))
        from app.domain import account_deletion_assets

        def fail_cleanup(*_args):
            raise StorageError('account_delete_incomplete', 'Injected local cleanup error.')

        with monkeypatch.context() as patch:
            patch.setattr(account_deletion_assets, 'remove_account_assets', fail_cleanup)
            pending_response = delete(admin, target)
            assert pending_response.json()['detail']['code'] == 'account_delete_incomplete', pending_response.text
        pending = admin.get('/api/v1/admin/users', params={'q': target['email']}).json()['items'][0]
        assert pending['active'] is False and pending['admin_revision'] == 1
        assert pending['allowed_actions'] == ['delete']
        assert customer.get('/api/v1/auth/me').status_code == 401
        assert path.is_file()
        response = delete(admin, target)
        assert response.status_code == 200, response.text
        assert response.json() == {'id': target['id'], 'deleted': True}
        assert admin.get('/api/v1/admin/users', params={'q': target['email']}).json()['total'] == 0
        assert not path.exists()
        with database_connection() as db:
            assert db.execute('SELECT id FROM projects WHERE id=%s', (retained,)).fetchone()
            for table, column in (
                ('users', 'id'), ('projects', 'owner_id'), ('tasks', 'user_id'),
                ('sessions', 'user_id'), ('admin_audit_events', 'target_user_id'), ('storage_policies', 'scope_id'),
                ('account_deletions', 'user_id'),
            ):
                assert not db.execute(f'SELECT 1 FROM {table} WHERE {column}=%s', (target['id'],)).fetchone()
            assert not db.execute('SELECT id FROM files WHERE id=%s', (file_id,)).fetchone()
            assert not db.execute('SELECT id FROM storage_objects WHERE object_key=%s', (key,)).fetchone()


def test_delete_analyst_keeps_customer_project_and_delegated_files():
    analyst = create_user('analyst@account-deletion.test', PASSWORD, 'analyst')
    customer = create_user('owner@account-deletion.test', PASSWORD, 'customer')
    operator = create_user('admin@account-deletion.test', PASSWORD, 'admin')
    with TestClient(app) as owner, TestClient(app) as delegate, TestClient(app) as admin:
        login(owner, customer)
        login(delegate, analyst)
        login(admin, operator)
        project = create_customer_project(owner)
        project_id = project.rsplit('/', 1)[-1]
        write_requirements(owner, project, 1, 'confirm')
        assert assign(admin, project, analyst['id'], 0).status_code == 200
        upload = delegate.post(project + '/files', files={'file': ('delegated.xlsx', workbook_bytes())})
        assert upload.status_code == 201, upload.text
        file_id = upload.json()['file']['id']
        with database_connection() as db:
            receipt = db.execute('''SELECT r.id FROM storage_reservations r JOIN files f
                ON (r.project_id,r.object_key)=(f.project_id,f.object_key) WHERE f.id=%s''', (file_id,)).fetchone()['id']
        intent = get_data_dir() / '.storage-intents' / f'{receipt}.json'
        assert intent.is_file()
        design = delegate.post(project + '/research-designs', headers={'Idempotency-Key': 'draft'}, json={
            'expected_revision': 2, 'operation': 'save',
            'content': {'schema_version': 1, 'experiments': [{'id': 'e1', 'data_type': 'Synthetic design'}]},
        })
        assert design.status_code == 201, design.text
        response = delete(admin, analyst)
        assert response.status_code == 200, response.text
        assert owner.get(project).status_code == 200
        assert owner.get(project + '/files').json() == []
        assert not intent.exists()
        with database_connection() as db:
            assignment = db.execute('SELECT analyst_id,revision FROM project_assignments WHERE project_id=%s',
                                    (project_id,)).fetchone()
            assert dict(assignment) == {'analyst_id': None, 'revision': 2}
            assert not db.execute('SELECT 1 FROM project_assignment_events WHERE analyst_id=%s',
                                  (analyst['id'],)).fetchone()
            assert not db.execute('SELECT 1 FROM storage_reservations WHERE id=%s', (receipt,)).fetchone()
            file = db.execute('SELECT uploader_id,upload_actor_id,object_key FROM files WHERE id=%s', (file_id,)).fetchone()
            assert file['uploader_id'] == customer['id']
            assert file['upload_actor_id'] not in (None, customer['id'], analyst['id'])
            assert (get_data_dir() / file['object_key']).is_file()
            assert db.execute('SELECT 1 FROM research_design_versions WHERE project_id=%s', (project_id,)).fetchone()
        assert admin.get('/api/v1/admin/users').json()['total'] == 2
