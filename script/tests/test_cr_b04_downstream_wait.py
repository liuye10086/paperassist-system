"""Exercise the real acceptance HTTP client using only an in-process transport."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import httpx


def test_login_task_wait_and_download_keep_two_hour_io_and_thirty_second_connect(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'dev/cr_b04_downstream.py'
    spec = importlib.util.spec_from_file_location('cr_b04_downstream_wait_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / 'credentials.json').write_text(json.dumps({'review': {
        'id': 'fixture-owner', 'email': 'fixture@example.test', 'password': 'fixture-only'}}))
    args = SimpleNamespace(project_id='fixture-project', result_id=['fixed-result'],
                           figure_result_id=[], retry_original=[], wait_seconds=14400)
    state = {'schema': 'fixture-only', 'url': 'https://fixture.invalid', 'assets': str(tmp_path / 'assets')}
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path == '/api/v1/auth/login':
            return httpx.Response(200, json={'csrf_token': 'fixture-token'})
        if request.url.path == '/api/v1/tasks/fixed-task':
            return httpx.Response(200, json={'id': 'fixed-task', 'status': 'succeeded'})
        assert request.url.path == '/api/v1/projects/fixture-project/members/fixed/download'
        return httpx.Response(200, content=b'fixed original bytes')

    real_client = httpx.Client

    def client(**kwargs):
        assert kwargs['trust_env'] is False
        return real_client(**kwargs, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(httpx, 'Client', client)
    run = module.Acceptance(args, state, tmp_path / 'output')
    try:
        assert run.wait('fixed-task') == {'id': 'fixed-task', 'status': 'succeeded'}
        assert run.bytes({'download_url': run.base + '/members/fixed/download',
                          'id': 'fixed', 'format': 'bin', 'sha256': module.sha(b'fixed original bytes')},
                         tmp_path / 'download') == b'fixed original bytes'
        assert [(r.method, r.url.path) for r in requests] == [
            ('POST', '/api/v1/auth/login'), ('GET', '/api/v1/tasks/fixed-task'),
            ('GET', '/api/v1/projects/fixture-project/members/fixed/download')]
        for request in requests:
            assert request.extensions['timeout'] == {'connect': 30, 'read': 7200, 'write': 7200, 'pool': 7200}
        assert args.wait_seconds == 14400
        assert run.record['actions'] == {}
        assert run.record['real_model_calls'] == 0
    finally:
        run.client.close()
