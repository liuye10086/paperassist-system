from app.core.paths import BACKEND_ROOT, PROJECT_ROOT
from tests.helpers.auth import session_subprocess_env
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest
from app.db.database import database_connection, ensure_schema_current, migrate_database

from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_boxplot import cloud, prepared, generate  # noqa: F401
from tests.domain.test_explanation_content import valid_draft


@pytest.fixture
def writer(monkeypatch):
    from app.domain import explanations, explanation_policy
    from app.domain.tasks import explanation_execution
    from tests.domain.test_explanation_policy import execution_policy
    class FakeWriter:
        calls = []
        pending = False
        corrupt = False
        error = None
        payloads = {}
        def __init__(self, model=None):
            pass
        def start(self, payload):
            self.calls.append(payload)
            if self.error:
                raise self.error
            response_id = 'resp_explanation_' + str(len(self.calls))
            self.payloads[response_id] = payload
            return response_id
        def fetch(self, job):
            if self.pending:
                return None
            draft = valid_draft(job['payload'])
            if self.corrupt:
                draft['results'] += ' 均值为999。'
            return {'draft': draft, 'provenance': {'model': 'test-model', 'response_id': job['response_id'],
                                                  'usage': {'total_tokens': 100}}}
    class FakeProvider:
        def create(self, *, policy, instructions, payload):
            response_id = FakeWriter().start(payload)
            return self.retrieve(response_id, policy=policy)
        def retrieve(self, response_id, *, policy):
            output = FakeWriter().fetch({'response_id': response_id, 'payload': FakeWriter.payloads[response_id]})
            status = 'queued' if output is None else 'completed'
            usage = None if output is None else {'input_tokens': 100, 'output_tokens': 10, 'total_tokens': 110,
                'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0}}
            response = {'id': response_id, 'model': policy.model, 'status': status, 'usage': usage,
                'output': [] if output is None else [{'type': 'message', 'content': [
                    {'type': 'output_text', 'text': json.dumps(output['draft'], ensure_ascii=False)}]}]}
            return {'response_id': response_id, 'request_id': 'req_test', 'model': policy.model,
                    'status': status, 'usage': usage, 'response': response}
        def close(self):
            pass
    def test_policy(payload):
        import os
        from app.core.exceptions import StorageError
        if not os.environ.get('OPENAI_API_KEY'):
            raise StorageError('explanation_not_configured', 'Test policy not configured.', 503)
        return execution_policy()
    monkeypatch.setattr(explanations, 'CloudExplanation', FakeWriter)
    monkeypatch.setattr(explanation_policy, 'get_execution_policy', test_policy)
    monkeypatch.setattr(explanation_execution, 'create_provider', FakeProvider)
    return FakeWriter


def ready(client):
    base, file, result, plot_url = prepared(client)
    figure = generate(client, plot_url)
    return base, file, result, figure, plot_url.replace('/boxplot', '/explanation')


def submit(client, url, figure, **changes):
    response = client.post(url, json={'expected_revision': figure['setup_revision'], 'figure_id': figure['id'], **changes})
    if response.status_code == 202 and response.json().get('task'):
        # Shared business fixtures explicitly execute unified work in the isolated
        # test schema. HTTP and production GET never run this test helper.
        from app.domain.model_usage.service import ModelUsageService
        from app.domain.tasks.explanation_execution import run_explanation_task
        owner = client.get('/api/v1/auth/me').json()['user']['id']
        service = ModelUsageService(owner)
        for scope, key in [('user', owner), ('project', url.split('/')[4])]:
            budget = service.get_budget(scope, key)
            if budget['limit_micro_usd'] is None:
                service.set_budget(scope, key, 1_000_000, 0)
        task = response.json()['task']
        run_explanation_task(task['id'], task['revision'])
    return response



def seed_legacy(client, url, figure, *, status='running', response_id='resp_legacy'):
    """Explicitly seed a pre-migration job; never synthesize a unified ledger."""
    from app.adapters.explanation_store import ExplanationStore
    from app.adapters.storage import get_project_store
    from app.domain.explanations import context
    from app.domain.explanation_content import build_payload
    parts = url.split('/')
    store = get_project_store()
    result, saved_figure, _ = context(store, parts[4], parts[6], parts[8])
    repository = ExplanationStore(store)
    job, _ = repository.begin(result, saved_figure, build_payload(result, saved_figure), 'test-model', False)
    return repository.update_job(job['id'], status=status, response_id=response_id)


def recover():
    from app.domain.explanations import poll_pending_explanations
    poll_pending_explanations()


def test_legacy_read_never_fetches_or_reconciles_before_scanner(client, cloud, writer):
    *_, figure, url = ready(client)
    job = seed_legacy(client, url, figure)
    state = client.get(url).json()
    assert state['job']['status'] == 'running' and state['explanation'] is None and state['task'] is None
    assert client.get(url).json() == state
    recover()
    saved = client.get(url).json()
    assert saved['job']['id'] == job['id'] and saved['job']['status'] == 'completed'
    assert saved['explanation']['verification']['status'] == 'references_checked'
    assert len(saved['explanation']['sections']) == 6
    assert not writer.calls
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0
        assert db.execute('SELECT count(*) AS n FROM model_budgets').fetchone()['n'] == 0


def test_legacy_cached_explanation_is_readable_without_key_or_policy(client, cloud, writer, monkeypatch):
    *_, figure, url = ready(client)
    seed_legacy(client, url, figure); recover()
    saved = client.get(url).json()['explanation']
    monkeypatch.setenv('OPENAI_API_KEY', '')
    assert client.get(url).json()['explanation'] == saved
    assert submit(client, url, figure).json()['explanation'] == saved
    assert not writer.calls


def test_legacy_bad_output_is_failed_with_no_automatic_new_call(client, cloud, writer):
    *_, figure, url = ready(client)
    seed_legacy(client, url, figure); writer.corrupt = True; recover()
    state = client.get(url).json()
    assert state['job']['status'] == 'failed' and state['job']['message_code'] == 'explanation_invalid'
    assert state['explanation'] is None
    assert submit(client, url, figure).json()['task'] is None
    assert not writer.calls
    writer.corrupt = False
    response = submit(client, url, figure, retry=True)
    assert response.status_code == 202 and response.json()['task']['status'] == 'queued'
    assert client.get(url).json()['explanation']
    assert len(writer.calls) == 1


def test_legacy_old_explanation_remains_readable_but_cannot_generate_new_setup(client, cloud, writer):
    base, _, result, figure, url = ready(client)
    seed_legacy(client, url, figure); recover()
    saved = client.get(url).json()['explanation']
    client.put(base + '/analysis-setup', json={**result['selection'], 'expected_revision': 1, 'unit': 'new'})
    state = client.get(url).json()
    assert not state['is_current'] and state['explanation'] == saved
    assert submit(client, url, figure).status_code == 409


def test_legacy_configuration_changed_while_running_does_not_save(client, cloud, writer):
    base, _, result, figure, url = ready(client)
    seed_legacy(client, url, figure)
    client.put(base + '/analysis-setup', json={**result['selection'], 'expected_revision': 1, 'unit': 'new'})
    recover()
    state = client.get(url).json()
    assert state['explanation'] is None and state['job']['status'] == 'failed'


def test_legacy_save_failure_resumes_same_response(client, cloud, writer, monkeypatch):
    from app.adapters.explanation_store import ExplanationStore
    from app.core.exceptions import StorageError
    *_, figure, url = ready(client)
    job = seed_legacy(client, url, figure)
    def fail(*args, **kwargs):
        raise StorageError('storage_unavailable', 'synthetic failure')
    with monkeypatch.context() as patch:
        patch.setattr(ExplanationStore, 'save', fail); recover()
    assert client.get(url).json()['job']['response_id'] == job['response_id']
    assert client.get(url).json()['explanation'] is None
    recover()
    assert client.get(url).json()['explanation'] and not writer.calls


@pytest.mark.parametrize('status', ['uncertain', 'submitting'])
def test_legacy_unknown_never_retries_even_when_old_retry_boolean_is_sent(client, cloud, writer, status):
    *_, figure, url = ready(client)
    seed_legacy(client, url, figure, status=status, response_id=None)
    for retry in (False, True):
        response = submit(client, url, figure, retry=retry)
        assert response.json()['task'] is None and response.json()['explanation'] is None
    assert not writer.calls


def test_stale_legacy_submitting_becomes_uncertain_only_in_scanner(client, cloud, writer):
    from app.adapters.explanation_store import ExplanationStore
    from app.adapters.storage import get_project_store
    *_, figure, url = ready(client)
    job = seed_legacy(client, url, figure, status='submitting', response_id=None)
    ExplanationStore(get_project_store()).update_job(job['id'],
        created_at=(datetime.now(timezone.utc) - timedelta(seconds=190)).isoformat())
    assert client.get(url).json()['job']['status'] == 'submitting'
    recover()
    assert client.get(url).json()['job']['status'] == 'uncertain'


def test_stale_legacy_submission_is_marked_unknown_even_without_key(client, cloud, writer, monkeypatch):
    from app.adapters.explanation_store import ExplanationStore
    from app.adapters.storage import get_project_store
    *_, figure, url = ready(client)
    job = seed_legacy(client, url, figure, status='submitting', response_id=None)
    ExplanationStore(get_project_store()).update_job(job['id'],
        created_at=(datetime.now(timezone.utc) - timedelta(seconds=190)).isoformat())
    monkeypatch.setenv('OPENAI_API_KEY', '')
    recover()
    assert client.get(url).json()['job']['status'] == 'uncertain'
    assert not writer.calls


@pytest.mark.parametrize('target,missing,status', [('source', False, 409), ('source', True, 410),
                                                ('figure', False, 409), ('figure', True, 410)])
def test_source_and_image_integrity_checked_before_read_or_generation(client, cloud, writer, target, missing, status):
    from app.adapters.storage import get_project_store
    _, file, _, figure, url = ready(client)
    store = get_project_store()
    path = store.files_dir / (file['id'] + '.xlsx') if target == 'source' else store.figures_dir / (figure['id'] + '.png')
    if missing:
        path.unlink()
    else:
        path.write_bytes(b'changed')
    assert client.get(url).status_code == status
    assert submit(client, url, figure).status_code == status
    assert not writer.calls


def test_legacy_transient_fetch_failure_keeps_response(client, cloud, writer, monkeypatch):
    from app.core.exceptions import PlotError
    *_, figure, url = ready(client)
    job = seed_legacy(client, url, figure)
    def fail(*args):
        raise PlotError('openai_request_failed', 'temporary', 503)
    with monkeypatch.context() as patch:
        patch.setattr(writer, 'fetch', fail); recover()
    state = client.get(url).json()
    assert state['job']['status'] == 'running' and state['job']['response_id'] == job['response_id']
    recover()
    assert client.get(url).json()['explanation'] and not writer.calls


def test_persisted_legacy_explanation_restores_in_fresh_process_without_credentials(client, cloud, writer, monkeypatch):
    *_, figure, url = ready(client)
    seed_legacy(client, url, figure); recover()
    saved = client.get(url).json()['explanation']
    monkeypatch.setenv('OPENAI_API_KEY', '')
    code = 'from fastapi.testclient import TestClient; from app.main import app; import json,sys; print(json.dumps(TestClient(app, cookies={"paperassist_session": __import__("os").environ["PAPERASSIST_TEST_SESSION_COOKIE"]}).get(sys.argv[1]).json()))'
    process = subprocess.run([sys.executable, '-c', code, url], cwd=BACKEND_ROOT,
                             env=session_subprocess_env(client), capture_output=True, text=True, check=True, timeout=30)
    assert json.loads(process.stdout)['explanation'] == saved


def test_startup_recovers_only_legacy_jobs_without_waiting_for_plot_scan(client, cloud, writer, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    from app.adapters.explanation_store import ExplanationStore
    from app.adapters.storage import get_project_store
    from threading import Event
    *_, figure, url = ready(client)
    seed_legacy(client, url, figure)
    release = Event()
    monkeypatch.setattr(main, 'poll_pending_figures', lambda: release.wait(5))
    monkeypatch.setenv('PAPERASSIST_PLOT_WORKER_ENABLED', '1')
    try:
        with TestClient(main.app):
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if ExplanationStore(get_project_store()).job(figure['id'])['status'] == 'completed':
                    break
                time.sleep(0.05)
            assert ExplanationStore(get_project_store()).job(figure['id'])['status'] == 'completed'
            release.set()
    finally:
        release.set()
    assert not writer.calls
