"""Lifecycle decisions preserve history and enforce authoritative owner scope."""
import hashlib
import json

import pytest

from tests.api.test_projects import client, create_project, upload  # noqa: F401
from tests.api.test_document_versions import uploaded_docx
from app.db.database import database_connection


def lifecycle(client):
    project = create_project(client)
    saved = upload(client, project['id']).json()['file']
    base = f"/api/v1/projects/{project['id']}/files/{saved['id']}"
    return project, saved, base


def assessment(client, base, action='delete'):
    response = client.get(base + '/lifecycle/assessment', params={'action': action})
    assert response.status_code == 200, response.text
    return response.json()


def test_retained_request_replay_is_frozen_and_history_is_preserved(client):
    _, saved, base = lifecycle(client)
    original = client.get(base + '/download').content
    value = assessment(client, base)
    assert value['original_integrity'] == 'valid' and value['original_available']
    assert value['physical_deletion_available'] is False
    assert value['automatic_deletion'] is False
    assert value['operation_preserves_history'] is True
    assert value == assessment(client, base)
    body = {'expected_assessment_revision': value['assessment_revision'], 'reason': '  duplicate file  '}
    url = base + '/lifecycle/deletion-requests'
    first = client.post(url, headers={'Idempotency-Key': 'retain'}, json=body)
    assert first.status_code == 201, first.text
    assert first.json()['status'] == 'retained'
    assert first.json()['reason'] == 'duplicate file'
    with database_connection(write=True) as db:
        db.execute('UPDATE files SET metadata_revision=metadata_revision+1 WHERE id=%s', (saved['id'],))
    assert assessment(client, base)['assessment_revision'] != value['assessment_revision']
    replay = client.post(url, headers={'Idempotency-Key': 'retain'}, json=body)
    assert replay.status_code == 200 and replay.json() == first.json()
    stale = client.post(url, headers={'Idempotency-Key': 'stale'}, json=body)
    assert stale.status_code == 409 and stale.json()['detail']['code'] == 'file_assessment_conflict'
    changed = client.post(url, headers={'Idempotency-Key': 'retain'}, json={**body, 'reason': 'other'})
    assert changed.status_code == 409 and changed.json()['detail']['code'] == 'file_deletion_idempotency_conflict'
    assert client.get(url).json()['items'] == [first.json()]
    assert client.get(base + '/download').content == original
    assert client.get(base + '/details').status_code == 200


def test_lifecycle_http_validation_and_other_owner(client):
    from tests.integration.test_project_ownership import account_client
    project, saved, base = lifecycle(client)
    value = assessment(client, base)
    body = {'expected_assessment_revision': value['assessment_revision'], 'reason': 'retain'}
    for suffix in ('/assessment?action=other', '/tasks?page=0', '/tasks?page=1.0', '/tasks?page_size=51', '/deletion-requests?page=-1'):
        assert client.get(base + '/lifecycle' + suffix).status_code == 422
    for invalid in ({**body, 'reason': ' '}, {**body, 'reason': 'x'*501}, {**body, 'expected_assessment_revision': 'bad'}, {**body, 'extra': True}):
        assert client.post(base+'/lifecycle/deletion-requests', headers={'Idempotency-Key': 'x'}, json=invalid).status_code == 422
    assert client.post(base+'/lifecycle/deletion-requests', headers={'Idempotency-Key':'x'}, json=body).status_code == 201
    with account_client('lifecycle-other@example.test')[0] as other:
        own = create_project(other)
        for prefix in (base, f"/api/v1/projects/{own['id']}/files/{saved['id']}"):
            for suffix in ('/assessment', '/tasks', '/deletion-requests'):
                assert other.get(prefix+'/lifecycle'+suffix).status_code == 404
            assert other.post(prefix+'/lifecycle/deletion-requests', headers={'Idempotency-Key':'x'}, json=body).status_code == 404
    assert client.get(base+'/download').status_code == 200


def test_active_parse_blocks_request_and_reparse_guard_records_legacy_origin(client):
    from app.adapters.docx_parser import parse_docx
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    project, _, _, item, content = uploaded_docx(client)
    base = f"/api/v1/projects/{project['id']}/files/{item['file_id']}"
    before = assessment(client, base)
    assert before['counts']['parse_versions'] == 1 and before['counts']['active_tasks'] == 1
    request = client.post(base+'/lifecycle/deletion-requests', headers={'Idempotency-Key':'active'}, json={
        'expected_assessment_revision':before['assessment_revision'], 'reason':'active file'})
    assert request.status_code == 201 and request.json()['status'] == 'blocked'
    assert run_parse_file_task(item['task']['id'], 1, parser=parse_docx)['status'] == 'succeeded'
    after = assessment(client, base, 'reparse')
    assert after['can_reparse'] and after['impact_scope'] == 'file_wide'
    body = {'expected_latest_version':1, 'expected_assessment_revision':after['assessment_revision']}
    second = client.post(base+'/document-versions', headers={'Idempotency-Key':'second'}, json=body)
    assert second.status_code == 202, second.text
    assert client.post(base+'/document-versions', headers={'Idempotency-Key':'second'}, json=body).status_code == 200
    with database_connection() as db:
        row = db.execute('SELECT * FROM file_reparse_assessments WHERE task_id=%s', (second.json()['task_id'],)).fetchone()
        assert row['client_assessment_supplied'] is True
        assert row['assessment_revision'] == after['assessment_revision']
    assert run_parse_file_task(second.json()['task_id'], 1, parser=parse_docx)['status'] == 'succeeded'
    stale = client.post(base+'/document-versions', headers={'Idempotency-Key':'stale'}, json={**body,'expected_latest_version':2})
    assert stale.status_code == 409 and stale.json()['detail']['code'] == 'file_assessment_conflict'
    legacy = client.post(base+'/document-versions', headers={'Idempotency-Key':'legacy'}, json={'expected_latest_version':2})
    assert legacy.status_code == 202, legacy.text
    with database_connection() as db:
        row = db.execute('SELECT a.client_assessment_supplied,t.input_digest FROM file_reparse_assessments a JOIN tasks t ON t.id=a.task_id WHERE a.task_id=%s', (legacy.json()['task_id'],)).fetchone()
        assert row['client_assessment_supplied'] is False
        assert row['input_digest'] == hashlib.sha256(json.dumps(dict(file_id=item['file_id'],expected_latest_version=2),sort_keys=True).encode()).hexdigest()
    assert client.get(base+'/download').content == content


@pytest.mark.parametrize('integrity', ['missing', 'changed'])
def test_original_integrity_is_observed_not_promised(client, integrity):
    import os
    from pathlib import Path
    _, saved, base = lifecycle(client)
    with database_connection() as db:
        file = db.execute('SELECT * FROM files WHERE id=%s', (saved['id'],)).fetchone()

    path = Path(os.environ['PAPERASSIST_DATA_DIR']) / (file['object_key'] or f"files/{saved['id']}.xlsx")
    if integrity == 'missing':
        path.unlink()
    else:
        path.write_bytes(b'changed')
    value = assessment(client, base)
    assert value['original_integrity'] == integrity and value['original_available'] is False
    assert value['can_reparse'] is False
    response = client.post(base+'/lifecycle/deletion-requests', headers={'Idempotency-Key':'missing'}, json={
        'expected_assessment_revision':value['assessment_revision'], 'reason':'preserve record'})
    assert response.status_code == 201 and response.json()['status'] == 'blocked'


def test_lifecycle_disabled_and_anonymous_requests_are_rejected(client):
    from fastapi.testclient import TestClient
    from app.main import app
    _,_,base=lifecycle(client)
    token=assessment(client,base)['assessment_revision']
    body=dict(reason='request',expected_assessment_revision=token)
    endpoints=[base+'/lifecycle'+s for s in ('/assessment','/tasks','/deletion-requests')]
    with TestClient(app) as anonymous:
        assert all(anonymous.get(url).status_code==401 for url in endpoints)
        assert anonymous.post(endpoints[-1],json=body,headers={'Idempotency-Key':'anon'}).status_code==401
    owner=client.get('/api/v1/auth/me').json()['user']['id']
    with database_connection(write=True) as db:
        db.execute('UPDATE users SET active=false WHERE id=%s',(owner,))
    assert all(client.get(url).status_code==401 for url in endpoints)
    assert client.post(endpoints[-1],json=body,headers={'Idempotency-Key':'disabled'}).status_code==401


def test_concurrent_duplicate_request_and_multiple_requests_do_not_modify_assets(client):
    from concurrent.futures import ThreadPoolExecutor
    from tests.integration.test_file_lifecycle_permissions import fingerprint
    _,_,base=lifecycle(client)
    body=dict(reason='concurrent',expected_assessment_revision=assessment(client,base)['assessment_revision'])
    before,objects=fingerprint()
    def submit(key):
        return client.post(base+'/lifecycle/deletion-requests',json=body,headers={'Idempotency-Key':key})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(submit,['same','same']))
    assert sorted(r.status_code for r in results)==[200,201]
    assert results[0].json()==results[1].json()
    assert submit('another').status_code==201
    after,after_objects=fingerprint()
    assert after_objects==objects
    assert {k:v for k,v in before.items() if k!='file_deletion_requests'}=={k:v for k,v in after.items() if k!='file_deletion_requests'}
    assert client.get(base+'/lifecycle/deletion-requests?page_size=1').json()['total']==2


def test_storage_unavailable_is_blocked_and_not_claimed_readable(client,monkeypatch):
    from app.adapters.storage import ProjectStore
    from app.core.exceptions import StorageError
    _,_,base=lifecycle(client)
    def unavailable(*args):
        raise StorageError('storage_unavailable','unavailable')
    monkeypatch.setattr(ProjectStore,'original',unavailable)
    result=assessment(client,base)
    assert result['original_integrity']=='unavailable' and not result['original_available']
    assert result['deletion_status']=='blocked'
