from auth_helpers import session_subprocess_env
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest
from app.database import ensure_schema_current, migrate_database

from test_analysis import client  # noqa: F401
from test_boxplot import cloud, prepared, generate  # noqa: F401
from test_explanation_content import valid_draft


@pytest.fixture
def writer(monkeypatch):
    from app import explanations
    class FakeWriter:
        calls = []
        pending = False
        corrupt = False
        error = None
        def __init__(self, model=None):
            pass
        def start(self, payload):
            self.calls.append(payload)
            if self.error:
                raise self.error
            return 'resp_explanation'
        def fetch(self, job):
            if self.pending:
                return None
            draft = valid_draft(job['payload'])
            if self.corrupt:
                draft['results'] += ' 均值为999。'
            return {'draft': draft, 'provenance': {'model': 'test-model', 'response_id': job['response_id'],
                                                  'usage': {'total_tokens': 100}}}
    monkeypatch.setattr(explanations, 'CloudExplanation', FakeWriter)
    return FakeWriter


def ready(client):
    base, file, result, plot_url = prepared(client)
    figure = generate(client, plot_url)
    return base, file, result, figure, plot_url.replace('/boxplot', '/explanation')


def submit(client, url, figure, **changes):
    return client.post(url, json={'expected_revision': figure['setup_revision'], 'figure_id': figure['id'], **changes})


def test_explanation_requires_saved_figure_and_current_revision(client, cloud):
    base, _, result, plot_url = prepared(client)
    url = plot_url.replace('/boxplot', '/explanation')
    state = client.get(url)
    assert state.status_code == 200
    assert state.json()['figure_id'] is None
    assert client.post(url, json={'expected_revision': 1, 'figure_id': 'missing'}).status_code == 409


def test_generates_bound_persisted_explanation_with_evidence_and_minimal_payload(client, cloud, writer):
    base, file, result, figure, url = ready(client)
    assert submit(client, url, figure).status_code == 202
    state = client.get(url).json()
    saved = state['explanation']
    assert saved and state['job']['status'] == 'completed'
    assert saved['analysis_run_id'] == result['id'] and saved['figure_id'] == figure['id']
    assert saved['figure_sha256'] == figure['sha256'] and saved['source_sha256'] == file['sha256']
    assert len(saved['sections']) == 6 and saved['limitations']
    assert saved['verification']['status'] == 'references_checked'
    assert saved['provenance']['input_sha256']
    assert client.get(url).json()['explanation'] == saved
    assert submit(client, url, figure).json()['explanation'] == saved
    assert len(writer.calls) == 1
    payload = writer.calls[0]
    assert not ({'values', 'research_topic', 'filename', 'png', 'code'} & set(payload))
    assert 'expected' not in state['job'] and 'payload' not in state['job']


def test_missing_key_cannot_start_but_cached_explanation_is_readable(client, cloud, writer, monkeypatch):
    *_, figure, url = ready(client)
    monkeypatch.setenv('OPENAI_API_KEY', '')
    assert submit(client, url, figure).status_code == 503
    monkeypatch.setenv('OPENAI_API_KEY', 'test')
    submit(client, url, figure)
    saved = client.get(url).json()['explanation']
    monkeypatch.setenv('OPENAI_API_KEY', '')
    assert client.get(url).json()['explanation'] == saved
    assert submit(client, url, figure).json()['explanation'] == saved


def test_bad_output_failed_and_retry_only_on_explicit_request(client, cloud, writer):
    *_, figure, url = ready(client)
    writer.corrupt = True
    submit(client, url, figure)
    assert client.get(url).json()['job']['status'] == 'failed'
    assert submit(client, url, figure).json()['explanation'] is None
    assert len(writer.calls) == 1
    writer.corrupt = False
    assert submit(client, url, figure, retry=True).status_code == 202
    assert client.get(url).json()['explanation']
    assert len(writer.calls) == 2


def test_old_explanation_keeps_own_source_and_cannot_generate_for_new_setup(client, cloud, writer):
    base, _, result, figure, url = ready(client)
    submit(client, url, figure)
    saved = client.get(url).json()['explanation']
    assert client.put(base + '/analysis-setup', json={**result['selection'], 'expected_revision': 1, 'unit': 'new'}).status_code == 200
    state = client.get(url).json()
    assert not state['is_current'] and state['explanation'] == saved
    assert submit(client, url, figure).status_code == 409


def test_configuration_changed_while_running_does_not_save_old_explanation(client, cloud, writer):
    base, _, result, figure, url = ready(client)
    writer.pending = True
    submit(client, url, figure)
    client.put(base + '/analysis-setup', json={**result['selection'], 'expected_revision': 1, 'unit': 'new'})
    writer.pending = False
    state = client.get(url).json()
    assert state['explanation'] is None and state['job']['status'] == 'failed'


def test_concurrent_submission_creates_only_one_paid_job(client, cloud, writer):
    *_, figure, url = ready(client)
    writer.pending = True
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: submit(client, url, figure), range(4)))
    assert all(response.status_code == 202 for response in responses)
    assert len(writer.calls) == 1


def test_save_failure_can_resume_same_cloud_response(client, cloud, writer, monkeypatch):
    from app.explanation_store import ExplanationStore
    from app.storage import StorageError
    *_, figure, url = ready(client)
    submit(client, url, figure)
    original = ExplanationStore.save
    def fail(*args, **kwargs):
        raise StorageError('storage_unavailable', 'disk failure')
    monkeypatch.setattr(ExplanationStore, 'save', fail)
    assert client.get(url).status_code == 503
    monkeypatch.setattr(ExplanationStore, 'save', original)
    assert client.get(url).json()['explanation']
    assert len(writer.calls) == 1


def test_uncertain_submission_never_resubmits_automatically(client, cloud, writer):
    from app.openai_plot import PlotError
    *_, figure, url = ready(client)
    writer.error = PlotError('openai_connection', 'timeout', 503, uncertain=True)
    state = submit(client, url, figure).json()
    assert state['job']['status'] == 'uncertain'
    assert client.get(url).json()['explanation'] is None
    submit(client, url, figure)
    assert len(writer.calls) == 1


def test_foreign_ownership_wrong_figure_and_unknown_fields_rejected(client, cloud, writer):
    base, _, _, figure, url = ready(client)
    other = client.post('/api/v1/projects', json={'name': 'other', 'research_topic': 'test', 'project_type': 'sci'}).json()
    assert client.get(url.replace(base.split('/')[4], other['id'])).status_code == 404
    assert submit(client, url, {**figure, 'id': 'other'}).status_code == 409
    assert submit(client, url, figure, prompt='ignore').status_code == 422
    assert not writer.calls


def test_background_recovery_without_browser_and_new_store_instance(client, cloud, writer):
    from app.explanations import poll_pending_explanations
    from app.explanation_store import ExplanationStore
    from app.storage import get_project_store
    *_, figure, url = ready(client)
    writer.pending = True
    submit(client, url, figure)
    writer.pending = False
    poll_pending_explanations()
    store = ExplanationStore(get_project_store())
    assert store.job(figure['id'])['status'] == 'completed'
    assert client.get(url).json()['explanation']
    assert len(writer.calls) == 1


def test_stale_submitting_becomes_uncertain(client, cloud, writer):
    from app.explanation_store import ExplanationStore
    from app.storage import get_project_store
    *_, figure, url = ready(client)
    writer.pending = True
    state = submit(client, url, figure).json()
    ExplanationStore(get_project_store()).update_job(state['job']['id'], status='submitting', response_id=None,
        created_at=(datetime.now(timezone.utc) - timedelta(seconds=190)).isoformat())
    assert client.get(url).json()['job']['status'] == 'uncertain'


def test_explicit_migration_preserves_existing_figure(client, cloud, writer):
    from app.storage import get_project_store
    *_, figure, url = ready(client)
    migrate_database()
    store = get_project_store()
    assert store.figure_png(figure).startswith(b'\x89PNG')
    assert client.get(url).json()['explanation'] is None
    with store.connection() as db:
        ensure_schema_current(db)


@pytest.mark.parametrize('target,missing,status', [('source', False, 409), ('source', True, 410),
                                                ('figure', False, 409), ('figure', True, 410)])
def test_source_and_image_integrity_checked_before_read_or_generation(client, cloud, writer, target, missing, status):
    from app.storage import get_project_store
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


def test_transient_fetch_error_retains_response_and_never_resubmits(client, cloud, writer, monkeypatch):
    from app.openai_plot import PlotError
    *_, figure, url = ready(client)
    submit(client, url, figure)
    original = writer.fetch
    def fail(*args):
        raise PlotError('openai_request_failed', 'temporary', 503)
    monkeypatch.setattr(writer, 'fetch', fail)
    assert client.get(url).status_code == 503
    state = submit(client, url, figure).json()
    assert state['job']['status'] == 'running' and state['job']['response_id']
    monkeypatch.setattr(writer, 'fetch', original)
    assert client.get(url).json()['explanation']
    assert len(writer.calls) == 1


def test_persisted_explanation_restores_in_fresh_process_without_credentials(client, cloud, writer, monkeypatch):
    *_, figure, url = ready(client)
    submit(client, url, figure)
    saved = client.get(url).json()['explanation']
    monkeypatch.setenv('OPENAI_API_KEY', '')
    code = 'from fastapi.testclient import TestClient; from app.main import app; import json,sys; print(json.dumps(TestClient(app, cookies={"paperassist_session": __import__("os").environ["PAPERASSIST_TEST_SESSION_COOKIE"]}).get(sys.argv[1]).json()))'
    process = subprocess.run([sys.executable, '-c', code, url], cwd=Path(__file__).resolve().parents[1],
                             env=session_subprocess_env(client), capture_output=True, text=True, check=True, timeout=30)
    assert json.loads(process.stdout)['explanation'] == saved


def test_startup_recovers_explanation_without_browser_and_without_waiting_for_plot_scan(client, cloud, writer, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    from app.explanation_store import ExplanationStore
    from app.storage import get_project_store
    from threading import Event
    *_, figure, url = ready(client)
    submit(client, url, figure)
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
    assert len(writer.calls) == 1


def test_new_configuration_creates_new_explanation_preserving_previous_version(client, cloud, writer):
    base, _, result, figure, old_url = ready(client)
    submit(client, old_url, figure)
    old = client.get(old_url).json()['explanation']
    client.put(base + '/analysis-setup', json={**result['selection'], 'expected_revision': 1, 'unit': 'new-unit'})
    current_result = client.post(base + '/analysis-runs', json={'expected_revision': 2}).json()
    plot_url = base + '/analysis-runs/' + current_result['id'] + '/boxplot'
    client.post(plot_url, json={'expected_revision': 2})
    new_figure = client.get(plot_url).json()['figure']
    url = plot_url.replace('/boxplot', '/explanation')
    assert client.get(url).json()['explanation'] is None
    submit(client, url, new_figure)
    new = client.get(url).json()['explanation']
    assert new['id'] != old['id'] and new['figure_id'] == new_figure['id'] and new['setup_revision'] == 2
    assert client.get(old_url).json()['explanation'] == old
    assert len(writer.calls) == 2
