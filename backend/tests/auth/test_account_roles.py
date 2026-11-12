import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time

import httpx
import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.auth.middleware import COOKIE_NAME
from app.auth.service import create_user, digest, password_hash, set_user_active
from app.db.database import alembic_config, database_connection, migration_connection
from app.main import app


PASSWORD = 'isolated-account-role-password'
HEADERS = {'X-PaperAssist-Client': 'web'}


def login(client, email, password=PASSWORD):
    return client.post('/api/v1/auth/login', headers=HEADERS, json={'email': email, 'password': password})


def write_headers(response):
    return {**HEADERS, 'X-CSRF-Token': response.json()['csrf_token']}


def test_upgrade_preserves_legacy_accounts_project_session_and_audit(postgres_migration_config):
    settings = alembic_config()
    settings.attributes['database_config'] = postgres_migration_config
    with migration_connection(write=True) as db:
        settings.attributes['connection'] = db.raw_connection
        command.downgrade(settings, '0074_tabular_import_file_limit')
        for user_id, role, active in [('owner', 'user', True), ('disabled', 'user', False), ('admin', 'admin', True)]:
            db.execute('''INSERT INTO users (id,email,password_hash,role,active,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,1,2)''', (user_id, f'{user_id}@roles.test', password_hash(PASSWORD), role, active))
        db.execute("""INSERT INTO projects (id,name,research_topic,project_type,owner_id,created_at,updated_at)
            VALUES ('old-project','Old project','','sci','owner','old','old')""")
        db.execute("""INSERT INTO admin_audit_events (id,source,target_user_id,after_role,after_active,reason,effective_at)
            VALUES ('old-audit','cli','owner','user',true,'Legacy account created',1)""")
        now = time.time()
        db.execute("""INSERT INTO sessions (token_hash,user_id,csrf_token,created_at,last_seen_at,expires_at)
            VALUES (%s,'owner','csrf',%s,%s,%s)""", (digest('legacy-session'), now, now, now + 3600))
        before = {row['id']: dict(row) for row in db.execute('SELECT * FROM users')}

        command.upgrade(settings, 'head')

        for row in db.execute('SELECT * FROM users'):
            expected = before[row['id']]
            assert dict(row) == {**expected, 'role': 'admin' if row['id'] == 'admin' else 'analyst', 'review_status': 'approved'}
        assert db.execute("SELECT after_role FROM admin_audit_events WHERE id='old-audit'").fetchone()['after_role'] == 'user'

    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, 'legacy-session')
        assert client.get('/api/v1/auth/me').json()['user']['role'] == 'analyst'
        assert client.get('/api/v1/projects/old-project').status_code == 200
        client.cookies.clear()
        assert login(client, 'disabled@roles.test').status_code == 401
        assert login(client, 'owner@roles.test').json()['user']['id'] == 'owner'


def test_approved_roles_and_legacy_role_input():
    roles = {'admin': 'admin', 'customer': 'customer', 'analyst': 'analyst', 'user': 'analyst'}
    for provided, expected in roles.items():
        email = f'{provided}@roles.test'
        account = create_user(email, PASSWORD, role=provided)
        assert account['role'] == expected
        with TestClient(app) as client:
            response = login(client, email)
            assert response.status_code == 200, response.text
            assert client.get('/api/v1/auth/me').json()['user']['role'] == expected
            if expected == 'admin':
                assert client.get('/api/v1/admin/users').status_code == 200
            else:
                assert client.get('/api/v1/admin/users').status_code == 403

    with TestClient(app) as client:
        login(client, 'admin@roles.test')
        page = client.get('/api/v1/admin/users', params={'role': 'user', 'review_status': 'approved'})
        assert page.status_code == 200, page.text
        assert {item['email'] for item in page.json()['items']} == {'user@roles.test', 'analyst@roles.test'}


def test_unreviewed_accounts_cannot_use_login_sessions_or_generic_account_edits():
    create_user('admin@roles.test', PASSWORD, role='admin')
    hashed = password_hash(PASSWORD)
    with database_connection(write=True) as db:
        assert 'review_status' in db.execute('SELECT * FROM users').fetchone()
        for status in ['pending', 'rejected']:
            db.execute('''INSERT INTO users (id,email,password_hash,role,active,created_at,updated_at,review_status)
                VALUES (%s,%s,%s,NULL,false,1,1,%s)''', (status, f'{status}@roles.test', hashed, status))
        now = time.time()
        db.execute("""INSERT INTO sessions (token_hash,user_id,csrf_token,created_at,last_seen_at,expires_at)
            VALUES (%s,'pending','csrf',%s,%s,%s)""", (digest('pending-session'), now, now, now + 3600))

    with TestClient(app) as client:
        for status, code in [('pending', 'account_pending_review'), ('rejected', 'account_review_rejected')]:
            wrong = login(client, f'{status}@roles.test', 'wrong password')
            assert wrong.status_code == 401 and wrong.json()['detail']['code'] == 'invalid_credentials'
            response = login(client, f'{status}@roles.test')
            assert response.status_code == 403 and response.json()['detail']['code'] == code
            assert 'set-cookie' not in response.headers
        client.cookies.set(COOKIE_NAME, 'pending-session')
        assert client.get('/api/v1/auth/me').status_code == 401
        client.cookies.clear()
        admin = login(client, 'admin@roles.test')
        listed = client.get('/api/v1/admin/users', params={'review_status': 'pending'})
        assert listed.status_code == 200
        assert listed.json()['items'][0]['allowed_actions'] == []
        change = client.patch('/api/v1/admin/users/pending', headers=write_headers(admin), json={
            'role': 'analyst', 'active': True, 'expected_revision': 1, 'reason': 'Edit unreviewed account',
        })
        assert change.status_code == 409 and change.json()['detail']['code'] == 'account_review_required'

    with pytest.raises(ValueError, match='审核'):
        set_user_active('pending@roles.test', True)
    with pytest.raises(IntegrityError):
        with database_connection(write=True) as db:
            db.execute("UPDATE users SET role='analyst', active=true WHERE id='pending'")


def test_customer_can_submit_requirements_but_cannot_configure_or_run_analysis():
    account = create_user('customer@roles.test', PASSWORD, role='customer')
    with TestClient(app) as client:
        response = login(client, account['email'])
        client.headers.update(write_headers(response))
        created = client.post('/api/v1/projects', headers={'Idempotency-Key': 'customer-project'}, json={
            'name': 'Customer project', 'research_topic': 'Test research', 'project_type': 'research',
            'delivery_kinds': ['analysis'],
        })
        assert created.status_code == 201, created.text
        project = f"/api/v1/projects/{created.json()['id']}"
        requirement = client.post(project + '/requirements', headers={'Idempotency-Key': 'customer-requirement'}, json={
            'expected_revision': 1, 'operation': 'confirm',
            'content': {'schema_version': 1, 'services': ['analysis'], 'notes': 'Customer request'},
        })
        assert requirement.status_code == 201, requirement.text
        assert client.get(project + '/research-intake').json()['current_requirement']['content']['notes'] == 'Customer request'

        for method, path in [
            ('PUT', project + '/files/input/analysis-setup'),
            ('POST', project + '/files/input/analysis-runs'),
            ('POST', project + '/research-designs'),
            ('POST', project + '/bio-analysis-runs'),
            ('POST', project + '/bulk-workflow/sensitivity'),
            ('POST', '/api/v1/tasks/task/retry'),
        ]:
            denied = client.request(method, path, headers={'Idempotency-Key': 'customer-compute'}, json={})
            assert denied.status_code == 403, (path, denied.text)
            assert denied.json()['detail']['code'] == 'customer_operation_forbidden'

        assert client.post('/api/v1/auth/logout').status_code == 204

    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM tasks').fetchone()['n'] == 0


def test_role_change_revokes_analyst_request_still_receiving_body():
    analyst = create_user('analyst@roles.test', PASSWORD, role='analyst')
    create_user('admin@roles.test', PASSWORD, role='admin')

    with TestClient(app) as analyst_client, TestClient(app) as admin_client:
        analyst_login = login(analyst_client, analyst['email'])
        headers = write_headers(analyst_login)
        project = analyst_client.post('/api/v1/projects', headers={**headers, 'Idempotency-Key': 'role-race'}, json={
            'name': 'Role change project', 'research_topic': 'Isolated test', 'project_type': 'research',
            'delivery_kinds': ['analysis'],
        })
        assert project.status_code == 201
        admin_login = login(admin_client, 'admin@roles.test')

        async def send_after_role_change():
            body_requested = asyncio.Event()
            role_changed = asyncio.Event()

            async def body():
                body_requested.set()
                await role_changed.wait()
                yield b'{"expected_revision":1,"operation":"save","content":{"schema_version":1}}'

            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver',
                                         cookies={COOKIE_NAME: analyst_client.cookies[COOKIE_NAME]}) as client:
                submission = asyncio.create_task(client.post(
                    f"/api/v1/projects/{project.json()['id']}/research-designs", content=body(),
                    headers={**headers, 'Content-Type': 'application/json', 'Idempotency-Key': 'delayed-design'},
                ))
                try:
                    await asyncio.wait_for(body_requested.wait(), timeout=10)
                    changed = await asyncio.to_thread(
                        admin_client.patch, f"/api/v1/admin/users/{analyst['id']}", headers=write_headers(admin_login),
                        json={'role': 'customer', 'active': True, 'expected_revision': 1, 'reason': 'Update role to customer'},
                    )
                    assert changed.status_code == 200, changed.text
                finally:
                    role_changed.set()
                return await asyncio.wait_for(submission, timeout=10)

        denied = asyncio.run(send_after_role_change())
        assert denied.status_code == 401, denied.text
        assert denied.json()['detail']['code'] == 'authentication_required'


def test_role_change_fences_an_already_admitted_project_write(monkeypatch):
    from app.domain.research_intake import service

    analyst = create_user('writing-analyst@roles.test', PASSWORD, role='analyst')
    create_user('writing-admin@roles.test', PASSWORD, role='admin')
    admitted, release = Event(), Event()
    write_version = service.write_version

    def pause_before_transaction(*args, **kwargs):
        admitted.set()
        assert release.wait(10)
        return write_version(*args, **kwargs)

    with TestClient(app) as analyst_client, TestClient(app) as admin_client:
        analyst_headers = write_headers(login(analyst_client, analyst['email']))
        admin_headers = write_headers(login(admin_client, 'writing-admin@roles.test'))
        created = analyst_client.post('/api/v1/projects', headers={**analyst_headers, 'Idempotency-Key': 'role-fence'}, json={
            'name': 'Role fence project', 'research_topic': 'Isolated test', 'project_type': 'research',
            'delivery_kinds': ['analysis'],
        })
        assert created.status_code == 201, created.text
        project_id = created.json()['id']
        monkeypatch.setattr(service, 'write_version', pause_before_transaction)
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(analyst_client.post, f'/api/v1/projects/{project_id}/research-designs',
                headers={**analyst_headers, 'Idempotency-Key': 'admitted-design'}, json={
                    'expected_revision': 1, 'operation': 'save',
                    'content': {'schema_version': 1, 'experiments': [{'id': 'exp1', 'data_type': 'Synthetic data'}]},
                })
            try:
                assert admitted.wait(10)
                changed = admin_client.patch(f"/api/v1/admin/users/{analyst['id']}", headers=admin_headers,
                    json={'role': 'customer', 'active': True, 'expected_revision': 1, 'reason': 'Update project role'})
                assert changed.status_code == 200, changed.text
            finally:
                release.set()
            denied = pending.result(timeout=10)
        assert denied.status_code == 401, denied.text
        with database_connection() as db:
            assert db.execute('SELECT count(*) AS n FROM research_design_versions WHERE project_id=%s',
                              (project_id,)).fetchone()['n'] == 0
