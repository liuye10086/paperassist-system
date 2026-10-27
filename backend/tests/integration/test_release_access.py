"""Independent download guards, synthetic fixtures and real isolated PostgreSQL.

These are authorization tests, not real OCR/NCBI/rendering or deployment evidence.
"""
from hashlib import sha256
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import get_data_dir
from app.db.database import database_connection
from app.main import app
from tests.api.test_analysis import client  # noqa: F401
from tests.integration.test_project_ownership import account_client


def assert_private_download(client, url, expected):
    assert expected
    response = client.get(url)
    assert response.status_code == 200, response.text
    assert response.content == expected
    for role in ('user', 'admin'):
        with account_client('release-'+role+'@example.test', role)[0] as other:
            assert other.get(url).status_code == 404
    with TestClient(app) as anonymous:
        assert anonymous.get(url).status_code == 401


def test_task_only_preparation_preview_download_is_owner_scoped(client):
    from tests.integration.test_dataset_preparation import create_preparation, run, review
    _, _, _, _, task = create_preparation(client)
    assert run(task)['status'] == 'waiting_confirmation'
    view = review(client, task)
    with database_connection() as db:
        state = db.execute('SELECT state_json FROM task_checkpoints WHERE id=%s',
            (view['checkpoint_id'],)).fetchone()['state_json']
    candidate = state['candidate']
    expected = (Path(get_data_dir())/candidate['object_key']).read_bytes()
    assert sha256(expected).hexdigest() == candidate['sha256']
    assert_private_download(client, view['preview_download_url'], expected)


def test_published_ocr_review_download_is_owner_scoped(client):
    from tests.integration.test_ocr_review import setup_review, execute, decide
    _, _, _, task, _ = setup_review(client)  # explicit synthetic OCR parser
    url = '/api/v1/tasks/'+task['id']+'/ocr-review'
    assert execute(task)['status'] == 'waiting_confirmation'
    revised = decide(client, client.get(url).json(), 'revise', 'save',
        [dict(block_id='text-1', action='accept_original')])
    assert revised.status_code == 202, revised.text
    assert execute(revised.json())['status'] == 'waiting_confirmation'
    view = client.get(url).json()
    expected = client.get(view['preview_download_url']).content
    approved = decide(client, view, 'approve', 'approve')
    assert approved.status_code == 202, approved.text
    assert execute(approved.json())['status'] == 'succeeded'
    result = client.get(url).json()['result']
    assert_private_download(client, result['download_url'], expected)


def test_figure_language_download_and_disabled_owner_old_session(client):
    from tests.api.test_manuscript_figure_language import setup
    from tests.api.test_literature_evidence import post
    project, file, path, body = setup(client)
    expected = client.get(f'/api/v1/projects/{project}/files/{file["id"]}/download').content
    created = post(client, path, body, 'release-language')
    assert created.status_code == 201, created.text
    version = created.json()
    assert sha256(expected).hexdigest() == version['sha256']
    assert_private_download(client, version['download_url'], expected)
    owner = client.get('/api/v1/auth/me').json()['user']['id']
    with database_connection(write=True) as db:
        db.execute('UPDATE users SET active=FALSE WHERE id=%s', (owner,))
    assert client.get(version['download_url']).status_code == 401
    assert client.get('/api/v1/admin/users').status_code == 401


def test_layout_export_download_is_owner_scoped(client, monkeypatch):
    from tests.api.test_layout_exports import prepared
    from app.domain.tasks.execution import run_task
    # Isolate authorization from the renderer; do not count as real layout evidence.
    for module in ('service', 'execution'):
        monkeypatch.setattr('app.domain.layout_exports.'+module+'.renderer_identity', lambda: {'contract':'test-v1'})
    monkeypatch.setattr('app.domain.layout_exports.execution.prepare_layout_docx', lambda raw, options, **kw: raw)
    path, source, request = prepared(client)
    expected = client.get(source['download_url']).content
    created = client.post(path, json=request)
    assert created.status_code == 201, created.text
    saved = created.json()
    assert run_task(saved['task_id'], 1)['status'] == 'succeeded'
    done = client.get(path+'/'+saved['id']).json()
    assert sha256(expected).hexdigest() == done['sha256']
    assert_private_download(client, done['download_url'], expected)


def test_saved_synthetic_pmc_raw_download_is_owner_scoped(client, tmp_path):
    from tests.integration.test_literature_pmc import prepare
    from tests.domain.test_literature_pmc import xml
    project, _, ref, service, adapter, calls, _ = prepare(client, tmp_path)
    receipt, status = service.acquire(project, ref['id'], 'PMC123', 'release-pmc', adapter=adapter)
    assert status == 201 and receipt['status'] == 'succeeded'
    assert len(calls) == 2  # local MockTransport only; no NCBI request
    url = f'/api/v1/projects/{project}/literature/pmc/receipts/{receipt["id"]}/raw/1'
    assert_private_download(client, url, xml(pmid=ref['record']['pmid']))
