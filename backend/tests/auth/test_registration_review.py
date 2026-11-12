from concurrent.futures import ThreadPoolExecutor
import json

from alembic import command
from fastapi.testclient import TestClient

from app.auth.service import bootstrap_admin, create_user, password_hash
from app.db.database import alembic_config, database_connection, migration_connection
from app.main import app
from tests.auth.test_account_roles import HEADERS, PASSWORD, login, write_headers


REGISTER = '/api/v1/auth/register'
USERS = '/api/v1/admin/users'
REGISTRATIONS = '/api/v1/admin/registrations'


def application(email='new@registration.test', **changes):
    return {'email': email, 'password': PASSWORD, 'display_name': '申请人', 'organization': '示例单位',
            'note': '申请查看自己的研究项目。', **changes}


def pending_account(admin, email):
    listing = admin.get(USERS, params={'q': email, 'review_status': 'pending'})
    assert listing.status_code == 200, listing.text
    item, = listing.json()['items']
    assert item['role'] is None and item['active'] is False and item['allowed_actions'] == ['review']
    return item


def registration_url(account):
    return f"{USERS}/{account['id']}/registration"


def test_signup_review_and_login_with_assigned_role():
    email = 'new@registration.test'
    with TestClient(app) as applicant, TestClient(app) as admin, TestClient(app) as analyst:
        before_bootstrap = applicant.post(REGISTER, headers=HEADERS, json=application('admin@registration.test'))
        assert before_bootstrap.status_code == 503
        assert before_bootstrap.json()['detail']['code'] == 'registration_unavailable'
        administrator = bootstrap_admin('admin@registration.test', PASSWORD)
        submitted = applicant.post(REGISTER, headers=HEADERS, json=application(email.upper()))
        assert submitted.status_code == 202, submitted.text
        assert 'set-cookie' not in submitted.headers
        assert applicant.get('/api/v1/auth/me').status_code == 401
        waiting = login(applicant, email)
        assert waiting.status_code == 403 and waiting.json()['detail']['code'] == 'account_pending_review'

        create_user('analyst@registration.test', PASSWORD, role='analyst')
        admin_login = login(admin, administrator['email'])
        account = pending_account(admin, email)
        url = registration_url(account)
        detail = admin.get(url).json()
        assert detail['display_name'] == '申请人' and detail['organization'] == '示例单位'
        assert detail['note'] == '申请查看自己的研究项目。' and detail['decision'] is None
        assert PASSWORD not in str(detail) and 'password_hash' not in detail

        review = {'decision': 'approve', 'role': 'customer', 'expected_revision': account['admin_revision']}
        assert admin.post(url + '/review', headers=HEADERS, json=review).status_code == 403
        analyst_login = login(analyst, 'analyst@registration.test')
        assert analyst.get(url).status_code == 403
        assert analyst.post(url + '/review', headers=write_headers(analyst_login), json=review).status_code == 403
        assert admin.post(url + '/review', headers=write_headers(admin_login),
                          json={**review, 'role': None}).status_code == 422
        approved = admin.post(url + '/review', headers=write_headers(admin_login), json=review)
        assert approved.status_code == 200, approved.text
        assert approved.json()['review_status'] == 'approved' and approved.json()['role'] == 'customer'
        assert approved.json()['active'] is True
        identity = login(applicant, email).json()['user']
        assert identity['role'] == 'customer' and identity['id'] == account['id']
        audit, = admin.get('/api/v1/admin/audit', params={'target_user_id': account['id']}).json()['items']
        assert audit['actor_user_id'] == administrator['id']
        assert audit['before_review_status'] == 'pending' and audit['after_review_status'] == 'approved'
        assert audit['before_role'] is None and audit['after_role'] == 'customer'
        assert audit['request_id'] == approved.headers['X-Request-ID']


def test_duplicate_submission_and_rejection_keep_original_application():
    create_user('admin@registration.test', PASSWORD, role='admin')
    email = 'existing@registration.test'
    other_password = 'isolated-replacement-password'
    with TestClient(app) as applicant, TestClient(app) as admin:
        first = applicant.post(REGISTER, headers=HEADERS, json=application(email))
        duplicate = applicant.post(REGISTER, headers=HEADERS,
                                   json=application(email.upper(), password=other_password, display_name='替换资料'))
        assert first.status_code == duplicate.status_code == 202 and first.json() == duplicate.json()
        assert login(applicant, email, other_password).status_code == 401
        admin_login = login(admin, 'admin@registration.test')
        account = pending_account(admin, email)
        url = registration_url(account)
        assert admin.get(url).json()['display_name'] == '申请人'
        review = {'decision': 'reject', 'expected_revision': account['admin_revision'], 'reason': '申请资料需补充后联系管理员'}
        assert admin.post(url + '/review', headers=write_headers(admin_login),
                          json={**review, 'role': 'analyst'}).status_code == 422
        assert admin.post(url + '/review', headers=write_headers(admin_login),
                          json={**review, 'reason': None}).status_code == 422
        rejected = admin.post(url + '/review', headers=write_headers(admin_login), json=review)
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()['review_status'] == 'rejected' and rejected.json()['role'] is None
        blocked = login(applicant, email)
        assert blocked.status_code == 403 and blocked.json()['detail']['code'] == 'account_review_rejected'
        assert 'set-cookie' not in blocked.headers
        assert admin.get(url).json()['decision']['reason'] == review['reason']
        assert admin.post(url + '/review', headers=write_headers(admin_login), json=review).status_code == 409
        assert applicant.post(REGISTER, headers=HEADERS, json=application(email)).status_code == 202
        assert login(applicant, email).json()['detail']['code'] == 'account_review_rejected'


def test_registration_applies_origin_validation_and_rate_limit():
    bootstrap_admin('admin@registration.test', PASSWORD)
    with TestClient(app) as client:
        assert client.post(REGISTER, json=application()).status_code == 403
        assert client.post(REGISTER, headers={**HEADERS, 'Origin': 'https://untrusted.test'},
                           json=application()).status_code == 403
        padded = b' ' * (32 * 1024) + json.dumps(application()).encode()
        too_large = client.post(REGISTER, headers={**HEADERS, 'Content-Type': 'application/json'},
                                content=iter([padded[:8192], padded[8192:]]))
        assert too_large.status_code == 413 and too_large.json()['detail']['code'] == 'auth_content_too_large'
        for bad in [{'role': 'admin'}, {'display_name': ' '}, {'email': 'invalid'}, {'password': 'short'}]:
            response = client.post(REGISTER, headers=HEADERS, json={**application(), **bad})
            assert response.status_code == 422 and PASSWORD not in response.text
        for index in range(10):
            response = client.post(REGISTER, headers=HEADERS, json=application(f'new{index}@registration.test'))
            assert response.status_code == 202
        limited = client.post(REGISTER, headers=HEADERS, json=application('limit@registration.test'))
        assert limited.status_code == 429 and limited.json()['detail']['code'] == 'registration_rate_limited'
        assert int(limited.headers['Retry-After']) > 0
        for _ in range(5):
            pending = login(client, 'new0@registration.test')
            assert pending.status_code == 403 and pending.json()['detail']['code'] == 'account_pending_review'
        assert login(client, 'new0@registration.test').status_code == 429


def test_concurrent_review_records_one_decision():
    for name in ('first', 'second'):
        create_user(f'{name}@registration.test', PASSWORD, role='admin')
    with TestClient(app) as first, TestClient(app) as second:
        assert first.post(REGISTER, headers=HEADERS, json=application()).status_code == 202
        first_login = login(first, 'first@registration.test')
        second_login = login(second, 'second@registration.test')
        account = pending_account(first, 'new@registration.test')
        url = registration_url(account) + '/review'
        body = {'decision': 'approve', 'role': 'analyst', 'expected_revision': account['admin_revision']}
        with ThreadPoolExecutor(max_workers=2) as pool:
            requests = [pool.submit(client.post, url, headers=write_headers(identity), json=body)
                        for client, identity in [(first, first_login), (second, second_login)]]
            assert sorted(request.result(timeout=10).status_code for request in requests) == [200, 409]
        with database_connection() as db:
            assert db.execute('SELECT count(*) AS n FROM admin_audit_events WHERE target_user_id=%s',
                              (account['id'],)).fetchone()['n'] == 1


def test_registration_queue_is_admin_only_and_filters_application_summaries():
    administrator = create_user('admin@registration.test', PASSWORD, role='admin')
    customer = create_user('customer@registration.test', PASSWORD, role='customer')
    analyst = create_user('analyst@registration.test', PASSWORD, role='analyst')
    with TestClient(app) as admin, TestClient(app) as customer_client, TestClient(app) as analyst_client:
        for email in ('first@registration.test', 'second@registration.test'):
            assert admin.post(REGISTER, headers=HEADERS, json=application(email)).status_code == 202
        identity = login(admin, administrator['email'])
        first = admin.get(REGISTRATIONS, params={'page_size': 1})
        assert first.status_code == 200, first.text
        assert first.json()['total'] == 2
        item, = first.json()['items']
        assert set(item) == {'user_id', 'email', 'display_name', 'organization', 'submitted_at', 'review_status'}
        assert item['email'] == 'first@registration.test' and item['review_status'] == 'pending'
        assert item['display_name'] == '申请人' and item['organization'] == '示例单位'
        assert admin.get(REGISTRATIONS, params={'page': 2, 'page_size': 1}).json()['items'][0]['email'] == 'second@registration.test'
        assert admin.get(REGISTRATIONS, params={'q': '%'}).json()['items'] == []

        account = pending_account(admin, 'first@registration.test')
        reviewed = admin.post(registration_url(account) + '/review', headers=write_headers(identity), json={
            'decision': 'approve', 'role': 'analyst', 'expected_revision': account['admin_revision'],
        })
        assert reviewed.status_code == 200, reviewed.text
        assert admin.get(REGISTRATIONS).json()['total'] == 1
        approved = admin.get(REGISTRATIONS, params={'review_status': 'approved', 'q': 'FIRST'}).json()
        assert approved['total'] == 1 and approved['items'][0]['user_id'] == item['user_id']

        for client, account in [(customer_client, customer), (analyst_client, analyst)]:
            assert login(client, account['email']).status_code == 200
            assert client.get(REGISTRATIONS).status_code == 403


def test_registration_migration_retains_existing_account_and_audit(postgres_migration_config):
    settings = alembic_config()
    with migration_connection(write=True) as db:
        settings.attributes.update(connection=db.raw_connection, database_config=postgres_migration_config)
        command.downgrade(settings, '0075_account_roles')
        db.execute("""INSERT INTO users(id,email,password_hash,role,active,created_at,updated_at)
            VALUES ('legacy','legacy@registration.test',%s,'analyst',true,1,2)""", (password_hash(PASSWORD),))
        db.execute("""INSERT INTO admin_audit_events(id,source,target_user_id,after_role,after_active,reason,effective_at)
            VALUES ('audit','cli','legacy','analyst',true,'Existing account',1)""")
        user = dict(db.execute("SELECT * FROM users WHERE id='legacy'").fetchone())
        audit = dict(db.execute("SELECT * FROM admin_audit_events WHERE id='audit'").fetchone())
        command.upgrade(settings, 'head')
        assert dict(db.execute("SELECT * FROM users WHERE id='legacy'").fetchone()) == user
        assert dict(db.execute("SELECT * FROM admin_audit_events WHERE id='audit'").fetchone()) == {
            **audit, 'before_review_status': None, 'after_review_status': None,
        }
