from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.adapters.storage import ProjectStore
from app.core.config import get_data_dir
from app.core.exceptions import StorageError
from app.db.database import database_connection
from app.main import app
from tests.api.test_customer_workspace import freeze_delivery, publish_delivery, sign_in, write_requirements
from tests.auth.test_account_roles import login, write_headers


PROJECTS = '/api/v1/projects'
ASSIGNMENTS = '/api/v1/admin/project-assignments'
SCI_SETTINGS = {
    'article_type': 'research',
    'proposed_title': 'A synthetic cohort study',
    'target_journal': {'choice': 'other', 'name': 'Synthetic journal'},
    'keywords': ['cohort', 'expression', 'pathway', 'replication'],
    'figure_findings': [{'id': 'synthetic-figure-1', 'finding': 'Synthetic cohort flow'}],
}
LEGACY_SCI_SETTINGS = {
    'article_type': 'research',
    'main_results': 'Synthetic result',
    'target_journal': {'choice': 'nature_subjournal', 'name': None},
    'keywords': ['cohort', 'expression'],
    'figure_plan': [{'title': 'Figure 1', 'description': 'Synthetic cohort flow'}],
}


def project_body(kind, **fields):
    return {'name': f'Synthetic {kind} project', 'research_topic': 'Synthetic topic',
            'project_type': kind, **fields}


def create(client, key, **body):
    return client.post(PROJECTS, json=body, headers={'Idempotency-Key': key})


def project_path(response):
    assert response.status_code == 201, response.text
    return f'{PROJECTS}/{response.json()["id"]}'


def test_customer_creates_and_recovers_all_three_project_types():
    with TestClient(app) as client:
        owner = sign_in(client, 'create-types@manuscript.test', 'customer')
        for kind, delivery, fields in (
            ('research', 'analysis', {'delivery_kinds': ['analysis']}),
            ('sci', 'sci_draft', {'sci_settings': SCI_SETTINGS}),
            ('thesis', 'thesis_draft', {}),
        ):
            body = project_body(kind, **fields)
            first = create(client, kind, **body)
            path = project_path(first)
            replay = create(client, kind, **body)
            assert replay.status_code == 200, replay.text
            assert replay.json()['id'] == first.json()['id']
            assert client.get(f'/api/v1/project-create-requests/{kind}').json()['id'] == first.json()['id']
            assert client.get(path).json()['project_type'] == kind
            assert [row['kind'] for row in client.get(path + '/research-intake').json()['deliveries']] == [delivery]
        assert client.get(PROJECTS + '?page=1&page_size=5').json()['total'] == 3
        old = project_body('research', delivery_kinds=['analysis', 'sci_draft'])
        previous = ProjectStore(get_data_dir(), owner_id=owner).create_project(**old, idempotency_key='legacy')
        replay = create(client, 'legacy', **old)
        assert replay.status_code == 200, replay.text
        assert replay.json()['id'] == previous['id']


def test_customer_sci_creation_requires_valid_settings():
    with TestClient(app) as client:
        sign_in(client, 'invalid-sci@manuscript.test', 'customer')
        for change in (
            None,
            {'article_type': 'brief'},
            {'proposed_title': '  '},
            {'target_journal': {'choice': 'other', 'name': '  '}},
            {'target_journal': {'choice': 'nature_subjournal', 'name': None}},
            {'keywords': ['cohort', 'expression', 'pathway']},
            {'keywords': [*SCI_SETTINGS['keywords'], 'extra1', 'extra2', 'extra3']},
            {'keywords': [' cohort ', 'COHORT', 'pathway', 'expression']},
            {'figure_findings': [{'id': 'synthetic-figure-1', 'finding': '  '}]},
        ):
            fields = {} if change is None else {'sci_settings': SCI_SETTINGS | change}
            reply = create(client, 'invalid', **project_body('sci', **fields))
            assert reply.status_code == 422, reply.text
        assert client.get('/api/v1/project-create-requests/invalid').status_code == 404
        reply = create(client, 'legacy-format', **project_body('sci', sci_settings=LEGACY_SCI_SETTINGS))
        assert reply.status_code == 422, reply.text
        assert client.get(PROJECTS).json() == []


def test_customer_can_start_a_paper_without_a_target_journal_or_findings():
    with TestClient(app) as client:
        sign_in(client, 'sci-no-journal@manuscript.test', 'customer')
        for kind in ('research', 'narrative_review'):
            settings = {key: SCI_SETTINGS[key] for key in ('keywords', 'proposed_title')}
            settings['article_type'] = kind
            project = project_path(create(client, kind, **project_body('sci', sci_settings=settings)))
            assert client.get(project + '/sci-settings').json()['settings']['target_journal'] is None


def test_customer_rejects_settings_on_thesis_and_writing_deliveries_on_new_analysis():
    with TestClient(app) as client:
        sign_in(client, 'type-contract@manuscript.test', 'customer')
        invalid = (
            project_body('thesis', sci_settings=SCI_SETTINGS),
            project_body('research', delivery_kinds=['analysis', 'sci_draft']),
        )
        for body in invalid:
            reply = create(client, 'wrong-kind', **body)
            assert reply.status_code == 422, reply.text
        assert client.get(PROJECTS).json() == []


def test_concurrent_sci_create_replays_once_and_same_key_rejects_changed_settings():
    with TestClient(app) as client:
        sign_in(client, 'concurrent-sci@manuscript.test', 'customer')
        ready = Barrier(2)
        body = project_body('sci', sci_settings=SCI_SETTINGS)

        def submit():
            ready.wait(timeout=5)
            return create(client, 'same-sci', **body)

        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _: submit(), range(2)))
        assert sorted(response.status_code for response in results) == [200, 201]
        assert len({response.json()['id'] for response in results}) == 1
        changed = body | {'sci_settings': SCI_SETTINGS | {'proposed_title': 'Changed title'}}
        assert create(client, 'same-sci', **changed).status_code == 409
        assert len(client.get(PROJECTS).json()) == 1


def test_sci_settings_are_owner_scoped_and_old_sci_can_fill_them():
    with TestClient(app) as client, TestClient(app) as other, TestClient(app) as analyst, TestClient(app) as admin:
        owner = sign_in(client, 'sci-owner@manuscript.test', 'customer')
        sign_in(other, 'other-owner@manuscript.test', 'customer')
        sign_in(analyst, 'analyst@manuscript.test', 'analyst')
        sign_in(admin, 'admin@manuscript.test', 'admin')
        legacy = ProjectStore(get_data_dir(), owner_id=owner).create_project('Legacy SCI', 'Legacy topic', 'sci')
        settings_url = f'{PROJECTS}/{legacy["id"]}/sci-settings'
        blank = client.get(settings_url)
        assert blank.status_code == 200, blank.text
        assert blank.json() == {'revision': 1, 'settings': None}
        body = {'expected_revision': 1, 'settings': SCI_SETTINGS}
        for actor, status in ((other, 404), (analyst, 403), (admin, 403)):
            assert actor.get(settings_url).status_code == status
            assert actor.put(settings_url, json=body).status_code == status
        saved = client.put(settings_url, json=body)
        assert saved.status_code == 200, saved.text
        assert saved.json() == {'revision': 2, 'settings': SCI_SETTINGS}
        assert client.put(settings_url, json=body).json() == saved.json()
        assert client.get(settings_url).json() == saved.json()
        conflicting = body | {'settings': SCI_SETTINGS | {'proposed_title': 'Conflicting title'}}
        assert client.put(settings_url, json=conflicting).status_code == 409
        thesis = project_path(create(client, 'thesis', **project_body('thesis')))
        assert client.get(thesis + '/sci-settings').status_code == 403
        assert client.get(thesis + '/customer-workspace/progress').status_code == 403


def test_legacy_sci_replays_and_preserves_original_settings_when_updated():
    with TestClient(app) as client:
        owner = sign_in(client, 'sci-legacy-settings@manuscript.test', 'customer')
        old_body = project_body('sci', sci_settings=LEGACY_SCI_SETTINGS)
        existing = ProjectStore(get_data_dir(), owner_id=owner).create_project(**old_body, idempotency_key='old-sci')
        replay = create(client, 'old-sci', **old_body)
        assert replay.status_code == 200, replay.text
        assert replay.json()['id'] == existing['id']
        url = f'{PROJECTS}/{existing["id"]}/sci-settings'
        original = {'revision': 1, 'settings': LEGACY_SCI_SETTINGS}
        assert client.get(url).json() == original
        assert client.put(url, json={'expected_revision': 1, 'settings': LEGACY_SCI_SETTINGS}).json() == original
        update = {'expected_revision': 1, 'settings': SCI_SETTINGS}
        expected = {'revision': 2, 'settings': SCI_SETTINGS, 'legacy_settings': LEGACY_SCI_SETTINGS}
        assert client.put(url, json=update).json() == expected
        assert client.put(url, json=update).json() == expected
        assert client.get(url).json() == expected


def test_paper_projects_cannot_be_newly_assigned_but_legacy_grants_can_be_revoked():
    with TestClient(app) as client, TestClient(app) as analyst, TestClient(app) as admin:
        owner = sign_in(client, 'assign-owner@manuscript.test', 'customer')
        analyst_id = sign_in(analyst, 'assign-analyst@manuscript.test', 'analyst')
        admin_id = sign_in(admin, 'assign-admin@manuscript.test', 'admin')
        analysis = project_path(create(client, 'analysis', **project_body('research', delivery_kinds=['analysis'])))
        sci = project_path(create(client, 'sci', **project_body('sci', sci_settings=SCI_SETTINGS)))
        thesis = project_path(create(client, 'thesis', **project_body('thesis')))
        analysis_id, sci_id, thesis_id = [path.rsplit('/', 1)[-1] for path in (analysis, sci, thesis)]

        def assign(identifier, revision, assigned):
            return admin.patch(f'{ASSIGNMENTS}/{identifier}', json={
                'expected_revision': revision, 'analyst_id': assigned, 'reason': 'Synthetic assignment',
            })

        assert {row['id'] for row in admin.get(ASSIGNMENTS).json()['items']} == {analysis_id}
        assert assign(analysis_id, 0, analyst_id).status_code == 200
        for identifier in (sci_id, thesis_id):
            assert assign(identifier, 0, analyst_id).status_code == 422
        with database_connection(write=True) as db:
            db.execute('''INSERT INTO project_assignments(project_id, owner_id, analyst_id, revision, updated_by)
                VALUES (%s,%s,%s,1,%s)''', (sci_id, owner, analyst_id, admin_id))
        assert analyst.get(sci).status_code == 200
        assert analyst.get(sci + '/sci-settings').status_code == 403
        assert analyst.get(sci + '/manuscripts').status_code == 404
        assert {row['id']: row['project_type'] for row in admin.get(ASSIGNMENTS).json()['items']} == {
            analysis_id: 'research', sci_id: 'sci',
        }
        assert assign(sci_id, 1, analyst_id).status_code == 422
        assert assign(sci_id, 1, None).status_code == 200
        assert analyst.get(sci).status_code == 404


def test_customer_existing_paper_history_and_tasks_are_scoped(monkeypatch):
    from app.domain.manuscripts.service import ManuscriptService
    from app.domain.storage_governance import service as governance
    from app.domain.tasks.execution import run_task
    from tests.api.test_excel import workbook_bytes
    from tests.api.test_manuscripts import body

    monkeypatch.setattr(governance.shutil, 'disk_usage', lambda _: SimpleNamespace(total=100 * 1024**3, free=90 * 1024**3))
    with TestClient(app) as owner, TestClient(app) as other:
        email = 'old-sci@manuscript.test'
        owner_id = sign_in(owner, email, 'analyst')
        other_id = sign_in(other, 'foreign-sci@manuscript.test', 'customer')
        project = project_path(owner.post(PROJECTS, json=project_body('sci')))
        path = project + '/manuscripts'
        draft = owner.post(path, json=body(), headers={'Idempotency-Key': 'old-fact-draft'})
        assert draft.status_code == 201, draft.text
        saved = draft.json()
        task_id = saved['versions'][0]['task_id']
        run_task(task_id, 1)
        detail = path + '/' + saved['id']
        export = owner.post(detail + '/versions/1/exports', json={}, headers={'Idempotency-Key': 'old-export'})
        assert export.status_code == 201, export.text
        run_task(export.json()['task_id'], 1)
        download_url = detail + '/exports/' + export.json()['id'] + '/download'
        before = owner.get(download_url)
        assert before.status_code == 200 and before.content.startswith(b'PK')
        material = owner.post(project + '/files', files={'file': ('unreleased.xlsx', workbook_bytes())})
        assert material.status_code == 201, material.text
        file_id = material.json()['file']['id']
        source = dict(kind='original', id=file_id, file_id=file_id, role='methods')
        hidden = owner.post(detail + '/versions', json=body(expected_revision=1, sources=[source]),
                            headers={'Idempotency-Key': 'restricted-version'})
        assert hidden.status_code == 201, hidden.text

        requirement = write_requirements(owner, project, 1, 'confirm')
        _, publication, _, public_bytes = freeze_delivery(owner, project, owner_id, requirement['id'])
        publish_delivery(publication)

        with database_connection(write=True) as db:
            db.execute('UPDATE files SET upload_actor_id=%s WHERE id=%s', (other_id, file_id))
            db.execute("UPDATE users SET role='customer' WHERE id=%s", (owner_id,))
        owner.cookies.clear()
        auth = login(owner, email)
        assert auth.status_code == 200
        owner.headers.update(write_headers(auth))

        assert owner.get(detail + '/versions/1').status_code == 200
        assert owner.get(detail + '/versions/2').status_code == 404
        history = owner.get(path)
        assert history.status_code == 200, history.text
        assert [version['revision'] for version in history.json()['items'][0]['versions']] == [1]
        assert owner.get(detail).json()['current_revision'] == 1
        after = owner.get(download_url)
        assert after.status_code == 200 and after.content == before.content
        assert other.get(download_url).status_code == 404
        candidates = owner.get(path + '/candidates')
        assert candidates.status_code == 200 and all(item['file_id'] != file_id for item in candidates.json()['items'])
        assert owner.get(path.replace('/manuscripts', '/pdf-exports')).status_code == 403
        task_url = '/api/v1/tasks/' + task_id
        assert owner.get(task_url).json()['task_type'] == 'manuscript_draft'
        assert owner.get(task_url + '/events').status_code == 200
        assert other.get(task_url).status_code == 404
        assert other.post(task_url + '/retry', json={'expected_revision': 1}).status_code == 404
        assert owner.post(task_url + '/retry', json={'expected_revision': 1}).status_code == 409
        assert owner.post(task_url + '/cancel', json={'expected_revision': 1}).status_code == 409
        assert owner.get(project).json()['has_analysis_history'] is True
        releases = owner.get(project + '/customer-workspace/deliveries')
        assert releases.status_code == 200 and releases.json()['items'][0]['id'] == publication['id']
        member = publication['members'][0]['id']
        assert owner.get(project + f'/customer-workspace/deliveries/{publication["id"]}/members/{member}/download').content == public_bytes

        project_id = project.rsplit('/', 1)[-1]
        manuscripts = ManuscriptService(ProjectStore(get_data_dir(), owner_id=owner_id, customer=True))
        with database_connection() as db:
            for snapshot in (
                {'sources': [{'kind': 'research_finding_version', 'source_file_ids': [file_id]}]},
                {'sources': [{'kind': 'collection_report', 'content': {'items': [{'file_id': file_id}]}}]},
                {'thesis_context': {'source_files': [{'file_id': file_id}]}},
                {'citation_snapshot': {'materials': [{'file_id': file_id}]}},
            ):
                with pytest.raises(StorageError) as error:
                    manuscripts.validate_version(db, {'id': 'synthetic', 'project_id': project_id, 'snapshot_json': snapshot})
                assert error.value.code == 'manuscript_source_not_visible'


def test_sci_settings_errors_keep_their_public_codes():
    with TestClient(app) as client:
        sign_in(client, 'sci-codes@manuscript.test', 'customer')
        sci = project_path(create(client, 'sci-codes', **project_body('sci', sci_settings=SCI_SETTINGS)))
        url = sci + '/sci-settings'
        saved = client.put(url, json={'expected_revision': 1, 'settings': SCI_SETTINGS | {'proposed_title': 'Second title'}})
        assert saved.status_code == 200, saved.text
        stale = client.put(url, json={'expected_revision': 1, 'settings': SCI_SETTINGS | {'proposed_title': 'Stale title'}})
        assert stale.status_code == 409
        assert stale.json()['detail']['code'] == 'sci_settings_revision_conflict'
        assert stale.json()['detail']['message'] == 'SCI 建项资料已更新，请核对最新版本。'

        legacy = client.put(url, json={'expected_revision': 2, 'settings': LEGACY_SCI_SETTINGS})
        assert legacy.status_code == 422
        assert legacy.json()['detail']['code'] == 'sci_settings_required'

        thesis = project_path(create(client, 'sci-codes-thesis', **project_body('thesis')))
        for reply in (client.get(thesis + '/sci-settings'),
                      client.put(thesis + '/sci-settings', json={'expected_revision': 1, 'settings': SCI_SETTINGS})):
            assert reply.status_code == 403
            assert reply.json()['detail']['code'] == 'sci_settings_unavailable'


def test_paper_project_assignment_rejection_keeps_its_public_code():
    with TestClient(app) as client, TestClient(app) as analyst, TestClient(app) as admin:
        sign_in(client, 'assign-code-owner@manuscript.test', 'customer')
        analyst_id = sign_in(analyst, 'assign-code-analyst@manuscript.test', 'analyst')
        sign_in(admin, 'assign-code-admin@manuscript.test', 'admin')
        thesis = project_path(create(client, 'assign-code', **project_body('thesis')))
        rejected = admin.patch(f"{ASSIGNMENTS}/{thesis.rsplit('/', 1)[-1]}", json={
            'expected_revision': 0, 'analyst_id': analyst_id, 'reason': 'Synthetic assignment',
        })
        assert rejected.status_code == 422
        assert rejected.json()['detail']['code'] == 'project_assignment_type_invalid'
