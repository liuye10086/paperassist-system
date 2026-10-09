"""Bounded loopback server and file controls, entirely outside production app."""
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import socket
from threading import Lock, Thread
import time
from urllib.parse import urlencode

from app.db.database import database_connection


ROOT = Path(__file__).resolve().parents[3]
HOST, PORT = '127.0.0.2', 18015
URL = f'http://{HOST}:{PORT}'
ACTIONS = frozenset({'snapshot', 'fund_budget', 'execute_budget', 'execute_retry', 'shutdown'})
BUSINESS_TABLES = ('projects', 'files', 'analysis_setups', 'analysis_runs', 'figures', 'figure_jobs',
    'explanations', 'explanation_jobs', 'reports', 'tasks', 'task_events', 'task_attempts',
    'task_outbox', 'task_waits', 'task_resume_requests', 'model_calls', 'model_budgets',
    'budget_reservations', 'usage_events')


def business_fingerprints():
    """Hash all business rows; never persist user/session/credential records."""
    with database_connection() as db:
        return {table: sha256(json.dumps(sorted(
            [json.dumps(dict(row), sort_keys=True, default=str, ensure_ascii=False)
             for row in db.execute('SELECT * FROM ' + table).fetchall()]),
            ensure_ascii=False).encode('utf-8')).hexdigest() for table in BUSINESS_TABLES}


def save_json(path, value):
    temporary = path.with_suffix('.next.json')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, default=str)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def run_directory():
    raw = os.environ.get('PAPERASSIST_BROWSER_RUN_DIR', '')
    path = Path(raw)
    assert raw and path.is_absolute(), 'Absolute PAPERASSIST_BROWSER_RUN_DIR is required.'
    path = path.resolve()
    expected = (ROOT / 'script' / '.runtime' / 'step15' / 'browser').resolve()
    assert path == expected or expected in path.parents, 'Browser evidence must stay in step15/browser.'
    path.mkdir(parents=True, exist_ok=True)
    assert not (path / 'ready.json').exists(), 'Use a fresh run directory; do not replay old commands.'
    assert not (path / 'command.json').exists()
    return path


def deep_link(project_id, task_id=None):
    values = {'project': project_id, 'section': 'tasks'}
    if task_id:
        values['task'] = task_id
    return URL + '/#' + urlencode(values)


def port_open():
    with socket.socket() as sock:
        sock.settimeout(.25)
        return sock.connect_ex((HOST, PORT)) == 0


def block_real_providers(monkeypatch):
    """Block SDK aliases and provider constructors before any synthetic seeding."""
    from app.adapters.models import openai_responses, openai_plot
    from app.adapters import openai_plot as legacy_plot, openai_explanation
    from app.domain.tasks import boxplot_execution, explanation_execution, execution

    attempts = []

    def forbidden(*args, **kwargs):
        attempts.append('blocked_real_provider_construction')
        raise AssertionError('Real provider construction is forbidden in browser fixtures.')

    for module in (openai_responses, legacy_plot, openai_explanation):
        monkeypatch.setattr(module, 'OpenAI', forbidden)
    for provider in (openai_responses.OpenAIResponsesProvider, openai_plot.OpenAIPlotProvider,
                     legacy_plot.CloudPlot, openai_explanation.CloudExplanation):
        monkeypatch.setattr(provider, '__init__', forbidden)
    monkeypatch.setattr(boxplot_execution, 'create_provider', forbidden)
    monkeypatch.setattr(explanation_execution, 'create_provider', forbidden)
    monkeypatch.setattr(execution, 'run_task', forbidden)
    # A direct harmless assertion proves the guard is active; exclude this self-check.
    try:
        openai_responses.OpenAI(api_key='synthetic-guard-selfcheck')
    except AssertionError:
        assert attempts.pop() == 'blocked_real_provider_construction'
    else:
        raise AssertionError('Provider guard did not intercept the constructor.')
    return attempts


class LoopbackServer:
    def __init__(self, dist):
        from app.main import app
        from starlette.staticfiles import StaticFiles
        import uvicorn

        assert (dist / 'index.html').is_file(), 'Build the actual frontend before opting in.'
        assert not port_open(), 'Dedicated browser port is already occupied.'
        self.requests, self.lock = [], Lock()
        static = StaticFiles(directory=dist, html=True)

        async def same_origin(scope, receive, send):
            async def safe_send(message):
                if message['type'] == 'http.response.start':
                    with self.lock:
                        self.requests.append({'method': scope['method'], 'path': scope['path'],
                                              'status': message['status']})
                await send(message)
            target = app if scope['type'] == 'lifespan' or scope.get('path', '').startswith('/api/') else static
            await target(scope, receive, safe_send)

        self.server = uvicorn.Server(uvicorn.Config(same_origin, host=HOST, port=PORT,
            access_log=False, log_level='warning', timeout_graceful_shutdown=5))
        self.thread = Thread(target=self.server.run, name='step15-browser-api', daemon=True)

    def start(self):
        self.thread.start()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and self.thread.is_alive():
            if self.server.started and port_open():
                return
            time.sleep(.05)
        raise AssertionError('Dedicated browser API failed to start.')

    def close(self):
        self.server.should_exit = True
        self.thread.join(timeout=10)
        if self.thread.is_alive():
            self.server.force_exit = True
            self.thread.join(timeout=5)
        assert not self.thread.is_alive(), 'API thread must exit before schema teardown.'
        assert not port_open(), 'Browser API port must close before schema teardown.'

    def safe_requests(self):
        with self.lock:
            return list(self.requests)


class BrowserControls:
    def __init__(self, client, config, flow, old_snapshot, provider, server, attempts):
        self.client, self.config, self.flow = client, config, flow
        self.old_snapshot, self.before = old_snapshot, old_snapshot()
        self.provider, self.server, self.attempts = provider, server, attempts

    def snapshot(self):
        from app.domain.model_usage.service import ModelUsageService

        owner, project_id = self.flow['owner'], self.flow['project_id']
        service = ModelUsageService(owner, self.config)
        ids = [self.flow['budget_task_id'], self.flow['retry_task_id']]
        tasks = {}
        for task_id in ids:
            response = self.client.get('/api/v1/tasks/' + task_id + '/workspace')
            assert response.status_code == 200, response.text
            tasks[task_id] = {'workspace': response.json(), 'usage': service.task_usage(task_id)}
        with database_connection() as db:
            counts = {table: db.execute('SELECT count(*) AS n FROM ' + table).fetchone()['n']
                      for table in BUSINESS_TABLES}
            evidence = {}
            projections = {
                'task_attempts': 'task_id,attempt_no,status,reason_code,error_code,error_category',
                'task_waits': 'id,task_id,kind,status,task_revision,resolved_task_revision',
                'task_resume_requests': 'id,task_id,operation,wait_id,expected_task_revision,result_task_revision',
                'model_calls': 'id,task_id,user_id,project_id,attempt_no,status,provider_status,error_code',
                'task_events': 'task_id,seq,event_type,status,phase,reason_code,error_code,retry_reason',
            }
            for table, fields in projections.items():
                evidence[table] = [dict(row) for row in db.execute(
                    f'SELECT {fields} FROM {table} WHERE task_id=ANY(%s) ORDER BY task_id', (ids,)).fetchall()]
            evidence['budget_reservations'] = [dict(row) for row in db.execute('''
                SELECT r.call_id,c.task_id,b.scope_type,b.scope_key,r.status,
                    r.reserved_micro_usd,r.accounted_micro_usd
                FROM budget_reservations r JOIN model_calls c ON c.id=r.call_id
                JOIN model_budgets b ON b.id=r.budget_id WHERE c.task_id=ANY(%s)''', (ids,)).fetchall()]
            evidence['artifact_ownership'] = [dict(row) for row in db.execute('''
                SELECT t.id AS task_id,t.project_id,t.user_id,t.result_figure_id,t.result_report_id,
                    t.result_explanation_id,t.input_snapshot->'result'->>'id' AS analysis_run_id,
                    t.input_snapshot->'file'->>'id' AS file_id
                FROM tasks t WHERE id=ANY(%s)''', (ids,)).fetchall()]
            projects = [dict(row) for row in db.execute('SELECT * FROM projects WHERE owner_id=%s ORDER BY name',
                                                       (owner,)).fetchall()]
        old = self.old_snapshot()
        assert old == self.before, 'Historical PNG/explanation/Word bytes changed.'
        assert self.attempts == [], 'An unexpected real provider constructor was attempted.'
        requests = self.server.safe_requests()
        return {'database': 'paperassist_system_test', 'schema': self.config.schema, 'url': URL,
            'tasks': tasks, 'projects': projects, 'business_counts': counts, 'business_fingerprints': business_fingerprints(),
            'evidence': evidence, 'old_artifacts': old, 'old_artifacts_unchanged': True,
            'provider': {'synthetic': True, 'posts': list(self.provider.posts), 'gets': list(self.provider.gets),
                         'downloads': list(self.provider.downloads), 'real_constructor_attempts': 0},
            'safe_requests': requests, 'request_counts': [dict(method=method, path=path, status=status, count=count)
                for (method, path, status), count in sorted(Counter(
                    (item['method'], item['path'], item['status']) for item in requests).items())]}

    def execute(self, key, operation):
        from app.adapters.task_store import TaskStore
        from app.domain.tasks.execution import run_boxplot_task, run_word_task

        task_id = self.flow[key]
        task = TaskStore(self.flow['owner'], self.config).get(task_id)
        assert task['status'] == 'queued', 'Browser must recover this original task through actual HTTP first.'
        with database_connection() as db:
            receipt = db.execute('''SELECT * FROM task_resume_requests
                WHERE task_id=%s AND operation=%s AND result_task_revision=%s''',
                (task_id, operation, task['revision'])).fetchone()
            assert receipt, 'A real HTTP resume/retry receipt is required.'
        assert any(item == {'method': 'POST', 'path': '/api/v1/tasks/' + task_id + '/resume', 'status': 202}
                   for item in self.server.safe_requests()), 'Recovery must traverse the loopback HTTP server.'
        for _ in range(4):
            if key == 'budget_task_id':
                task = run_boxplot_task(task_id, task['revision'], config=self.config,
                                       provider_factory=lambda: self.provider)
            else:
                task = run_word_task(task_id, task['revision'], config=self.config)
            assert task and task['id'] == task_id
            if task['status'] == 'succeeded':
                break
        assert task['status'] == 'succeeded'
        assert task['current_attempt'] == 2
        return self.snapshot()

    def act(self, action):
        assert action in ACTIONS
        if action == 'fund_budget':
            from app.domain.model_usage.service import ModelUsageService
            service = ModelUsageService(self.flow['owner'], self.config)
            key = self.flow['budget_task_id']
            current = service.get_budget('task', key)
            service.set_budget('task', key, self.flow['required_budget'], current['revision'])
        elif action == 'execute_budget':
            return self.execute('budget_task_id', 'resume')
        elif action == 'execute_retry':
            return self.execute('retry_task_id', 'retry')
        return self.snapshot()

    def wait(self, directory, timeout=2700):
        deadline, seen = time.monotonic() + timeout, set()
        while time.monotonic() < deadline:
            path = directory / 'command.json'
            if not path.exists():
                time.sleep(.1)
                continue
            try:
                command = json.loads(path.read_text(encoding='utf-8-sig'))
            except (OSError, ValueError):
                time.sleep(.1)
                continue
            identifier = command.get('id') if isinstance(command, dict) else None
            if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', identifier):
                raise AssertionError('Control id must be a bounded safe identifier.')
            if identifier in seen:
                time.sleep(.1)
                continue
            seen.add(identifier)
            action = command.get('action')
            valid = set(command) == {'id', 'action'} and isinstance(action, str) and action in ACTIONS
            response = {'id': identifier, 'action': action, 'ok': valid}
            if not valid:
                response['error'] = 'invalid_control_command'
            else:
                try:
                    response['snapshot'] = self.act(action)
                except AssertionError:
                    response.update(ok=False, error='control_precondition_failed')
            save_json(directory / 'response.json', response)
            if valid and action == 'shutdown':
                return
        raise AssertionError('Browser fixture exceeded its bounded 2700 second lifetime.')
