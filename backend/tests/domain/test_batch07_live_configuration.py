"""Persistent B07 live configuration regressions using synthetic, in-memory state.

No deployment configuration, credentials, runtime snapshots or database is needed.
The store substitutes persistence only; routing, confirmation, task creation,
configuration binding, gateway admission and budget/lease checks are production code.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.adapters.models.openai_responses import OpenAIResponsesProvider
from app.core.exceptions import StorageError
from app.domain.admin_configuration import bindings, catalog
from app.domain.admin_configuration.contracts import Models, parse_bundle
from app.domain.model_usage.contracts import CallRequest, ModelPolicy
from app.domain.model_usage.gateway import ModelGateway, ModelGatewayError, input_digest


TASK = 'synthetic-old-task'
OWNER = 'synthetic-owner'
PROJECT = 'synthetic-project'


def forbidden(*args, **kwargs):
    raise AssertionError('Real network, database, deployment or credential access is forbidden')


@pytest.fixture(autouse=True)
def postgres_schema(monkeypatch):
    """Override the repository PG autouse fixture before it can open an engine."""
    import socket
    import psycopg
    import sqlalchemy
    from app.core import config
    from app.db import database
    from app.domain import explanation_policy

    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(psycopg, 'connect', forbidden)
    monkeypatch.setattr(sqlalchemy, 'create_engine', forbidden)
    monkeypatch.setattr(sqlalchemy.engine, 'create_engine', forbidden)
    monkeypatch.setattr(sqlalchemy.engine.create, 'create_engine', forbidden)
    monkeypatch.setattr(database, 'database_connection', forbidden)
    monkeypatch.setattr(config, 'dotenv_values', forbidden)
    monkeypatch.setattr(config, 'local_config', lambda: {})
    # Installed defaults explicitly receive an empty deployment configuration.
    monkeypatch.setattr(catalog, 'local_config', lambda: {})
    monkeypatch.setattr(explanation_policy, 'local_config', forbidden)
    monkeypatch.setattr(explanation_policy, '_small_text', forbidden)
    monkeypatch.setattr(explanation_policy, 'explanation_api_key', forbidden)
    monkeypatch.setattr(OpenAIResponsesProvider, '__init__', forbidden)
    monkeypatch.setattr(OpenAIResponsesProvider, 'create', forbidden)
    yield None


def synthetic_policy():
    model = 'gpt-5.4-2026-03-05'
    return dict(policy=dict(model=model, prompt_version='analysis_explanation_v1',
        max_output_tokens=1000, timeout_seconds=45, tools=[],
        output_format='analysis_explanation_v1', price=dict(version='synthetic-v1',
            currency='USD', model=model, input_micro_usd_per_million=1000000,
            cached_input_micro_usd_per_million=0, output_micro_usd_per_million=2000000,
            cache_write_micro_usd_per_million=None)),
        input_token_allowance=50000, task_limit_micro_usd=100000)


def synthetic_version(identity, *, enabled=False):
    bundle, sources = catalog.defaults()
    bundle['models']['real_calls_enabled'] = enabled
    bundle['models']['explanation'] = dict(execution=synthetic_policy(),
        price_source='synthetic_fixture', price_status='synthetic')
    bundle = parse_bundle(bundle)
    return dict(id=identity, bundle=bundle, sources=sources, sha256=catalog.digest(bundle))


def synthetic_snapshot():
    """Hand-authored summary of values [1, 2, 3], with no original file."""
    statistics = dict(n=3, mean=2.0, std=1.0, min=1.0, q1=1.5, median=2.0,
                      q3=2.5, max=3.0, iqr=1.0)
    result = dict(id='synthetic-run', setup_revision=1, source_sha256='a' * 64,
        numeric_name='Synthetic measure', group_name=None,
        selection=dict(sheet_name='Synthetic sheet', unit='unit'),
        check=dict(row_count=3, valid_count=3, excluded_count=0),
        overall=statistics, groups=[])
    figure = dict(id='synthetic-figure', title='Synthetic figure', figure_number=1,
        sha256='b' * 64, series=[dict(label='Overall', outlier_count=0,
                                    whislo=1.0, whishi=3.0)])
    return dict(file=dict(id='synthetic-file', filename='synthetic.xlsx'),
        result=result, figure=figure, versions=dict(explanation='analysis_explanation_v1'),
        output_language='zh-CN', explanation_policy=synthetic_policy())


class Result:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return deepcopy(self.row)


class MemoryDB:
    """Only the SQL needed by real routing/create/bind is accepted."""
    def __init__(self):
        self.versions = {key: synthetic_version(key) for key in ('old-false', 'current-false')}
        self.pointer = dict(version_id='current-false')
        self.bindings = {('task', TASK): 'old-false'}
        self.tasks, self.calls, self.task_events, self.outbox, self.budgets = [], [], [], [], []

    def execute(self, sql, args=()):
        sql = ' '.join(sql.split())
        if sql.startswith('SELECT * FROM admin_configuration_versions'):
            return Result(self.versions.get(args[0]))
        if sql.startswith('SELECT version_id FROM admin_configuration_pointer'):
            return Result(self.pointer)
        if sql.startswith('SELECT b.version_id,v.sha256 FROM admin_configuration_bindings'):
            identity = self.bindings.get(tuple(args))
            return Result(dict(version_id=identity, sha256=self.versions[identity]['sha256']) if identity else None)
        if sql.startswith('INSERT INTO admin_configuration_bindings'):
            kind, obj, identity, _task = args
            assert (kind, obj) not in self.bindings
            self.bindings[kind, obj] = identity
            return Result()
        if sql.startswith('SELECT * FROM model_calls'):
            return Result(self.calls[-1] if self.calls else None)
        if sql.startswith('SELECT id,status,revision,input_snapshot FROM tasks'):
            return Result(self.tasks[-1] if self.tasks else None)
        if sql.startswith('INSERT INTO model_budgets'):
            self.budgets.append(args)
            return Result()
        raise AssertionError('Unplanned in-memory SQL: ' + sql)


@pytest.fixture
def submission(monkeypatch):
    from app.domain import explanation_tasks, explanations
    from app.domain.external_processing import default_labels, disclosure_version, source_digest
    from app.domain.tasks.service import TaskService

    db, snapshot = MemoryDB(), synthetic_snapshot()
    old = dict(id=TASK, project_id=PROJECT, user_id=OWNER, task_type='explanation',
        workflow_version='explanation_v1', status='failed', revision=3, current_attempt=1,
        error_code='model_configuration_disabled', input_snapshot=deepcopy(snapshot),
        input_digest='synthetic-original-digest')
    db.tasks.append(old)

    class Store:
        user_id = OWNER

        @contextmanager
        def connection(self, **kwargs):
            yield db

        def require_project(self, connection, identity):
            assert identity == PROJECT
            return dict(id=identity)

        def source_snapshot(self, connection, project, request):
            return deepcopy(snapshot)

        def find_request(self, connection, project, kind, key):
            return next((task for task in db.tasks if task.get('idempotency_key') == key), None)

        def public_task(self, task):
            return deepcopy(task)

        def insert_task(self, connection, task):
            db.tasks.append(deepcopy(task))

        def append_event(self, connection, task, kind):
            db.task_events.append((task['id'], kind))

        def enqueue(self, connection, task):
            db.outbox.append((task['id'], task['revision']))

    actual = object.__new__(TaskService)
    actual.store = Store()
    monkeypatch.setattr(explanation_tasks, 'TaskService', lambda *args: actual)
    monkeypatch.setattr(explanation_tasks, 'ExplanationStore',
                        lambda *args: SimpleNamespace(job=lambda *args: None))
    monkeypatch.setattr(explanations, 'context', lambda *args: (
        snapshot['result'], snapshot['figure'], dict(is_current=True, explanation=None)))
    monkeypatch.setattr(explanation_tasks, 'matching_task', lambda *args: deepcopy(db.tasks[-1]))
    retries = []

    def retry(store, identity, revision):
        retries.append((identity, revision))
        raise AssertionError('Disabled original task must never be requeued')

    monkeypatch.setattr(explanation_tasks, 'retry_explanation_task', retry)
    confirmation = dict(version=disclosure_version(snapshot), confirmed=True,
        source_digest=source_digest(snapshot, 'explanation', OWNER),
        labels=default_labels(snapshot, 'explanation'))
    request = explanations.ExplanationRequest(expected_revision=1,
        figure_id=snapshot['figure']['id'], retry=True, expected_predecessor_id=TASK,
        expected_predecessor_revision=3, external_processing=confirmation)

    def submit(req=request, key='synthetic-new-request'):
        return explanation_tasks.submit_explanation(PROJECT, snapshot['file']['id'],
            snapshot['result']['id'], req, SimpleNamespace(owner_id=OWNER), key)

    return SimpleNamespace(db=db, old=old, request=request, submit=submit,
        actual=actual, snapshot=snapshot, retries=retries)


def activate_true(fixture):
    version = synthetic_version('new-true', enabled=True)
    fixture.db.versions[version['id']] = version
    fixture.db.pointer['version_id'] = version['id']
    return version


def persistent_state(fixture):
    return deepcopy((fixture.db.tasks, fixture.db.bindings, fixture.db.task_events,
                     fixture.db.outbox, fixture.db.budgets, fixture.db.calls))


def test_default_false_and_explicit_true_are_strict():
    values = catalog.defaults()[0]['models']
    values.pop('real_calls_enabled')
    assert Models.model_validate(values).real_calls_enabled is False
    assert Models.model_validate({**values, 'real_calls_enabled': True}).real_calls_enabled is True


@pytest.mark.parametrize('value', [0, 1, 'true', 'false', None, [], {}])
def test_non_boolean_live_values_are_rejected(value):
    with pytest.raises(ValidationError):
        Models.model_validate({**catalog.defaults()[0]['models'], 'real_calls_enabled': value})


def test_catalog_declares_explicit_new_task_opt_in():
    metadata = catalog.metadata()
    assert metadata['default_bundle']['models']['real_calls_enabled'] is False
    assert metadata['default_bundle']['ncbi']['enabled'] is False
    assert metadata['field_effects']['models.real_calls_enabled'] == 'new_task'
    assert metadata['field_readonly']['models.real_calls_enabled'] is False
    assert metadata['restart_required']['models.real_calls_enabled'] is False


def test_offline_fixture_blocks_real_database_network_and_secret_reads():
    import socket
    import psycopg
    import sqlalchemy
    from app.core import config
    from app.domain import explanation_policy
    assert config.local_config() == {}
    for operation in (lambda: socket.create_connection(('127.0.0.1', 1)),
                      lambda: psycopg.connect('synthetic'),
                      lambda: sqlalchemy.create_engine('synthetic'),
                      lambda: config.dotenv_values('synthetic.env'),
                      lambda: explanation_policy._small_text('synthetic-secret', 1),
                      explanation_policy.explanation_api_key):
        with pytest.raises(AssertionError, match='access is forbidden'):
            operation()


@pytest.mark.parametrize('current', ['same_false', 'different_false', 'none', 'rolled_back_false'])
@pytest.mark.parametrize('error', ['model_configuration_disabled', 'internal_error'])
def test_false_bound_failed_call_zero_is_unchanged_without_current_true(submission, current, error):
    f = submission
    f.old['error_code'] = error
    if current == 'same_false':
        f.db.pointer['version_id'] = 'old-false'
    elif current == 'none':
        f.db.pointer['version_id'] = None
    elif current == 'rolled_back_false':
        activate_true(f)
        f.db.pointer['version_id'] = 'current-false'
    before = persistent_state(f)
    with pytest.raises(StorageError) as exc:
        f.submit()
    assert (exc.value.code, exc.value.status) == ('model_configuration_disabled', 409)
    assert persistent_state(f) == before and f.retries == []


@pytest.mark.parametrize('missing', ['key', 'predecessor', 'revision'])
def test_false_bound_recovery_requires_complete_new_intent(submission, missing):
    f = submission
    activate_true(f)
    request, key = f.request, 'synthetic-new-request'
    if missing == 'key':
        key = None
    elif missing == 'predecessor':
        request = request.model_copy(update={'expected_predecessor_id': None})
    else:
        request = request.model_copy(update={'expected_predecessor_revision': None})
    before = persistent_state(f)
    with pytest.raises(StorageError) as exc:
        f.submit(request, key)
    assert exc.value.code == 'model_configuration_disabled'
    assert persistent_state(f) == before and f.retries == []


def test_new_true_and_exact_intent_create_independent_task_and_binding(submission):
    f = submission
    version, before = activate_true(f), deepcopy(f.old)
    state, status = f.submit()
    task = state['task']
    assert status == 202 and task['id'] != TASK and task['status'] == 'queued'
    assert f.db.tasks[0] == before and f.retries == [] and f.db.calls == []
    assert bindings.resolve(f.db, kind='task', object_id=TASK)['id'] == 'old-false'
    assert bindings.resolve(f.db, kind='task', object_id=task['id'])['id'] == version['id']
    assert task['input_snapshot']['explanation_policy'] == before['input_snapshot']['explanation_policy']
    assert f.db.task_events == [(task['id'], 'created')]
    assert f.db.outbox == [(task['id'], 1)] and len(f.db.budgets) == 1
    repeated, repeated_status = f.submit()
    assert repeated_status == 202 and repeated['task']['id'] == task['id']
    assert len(f.db.tasks) == 2 and len(f.db.budgets) == 1
    with pytest.raises(StorageError) as exc:
        bindings.bind(f.db, kind='task', object_id=TASK, version=version)
    assert exc.value.code == 'configuration_binding_conflict'
    f.db.pointer['version_id'] = 'current-false'
    assert bindings.resolve(f.db, kind='task', object_id=task['id'])['id'] == version['id']
    assert f.db.tasks[0] == before


@pytest.mark.parametrize('change', ['predecessor_id', 'predecessor_revision', 'confirmation'])
def test_new_task_rechecks_predecessor_and_external_confirmation(submission, change):
    f = submission
    activate_true(f)
    updates = {'predecessor_id': dict(expected_predecessor_id='another-task'),
               'predecessor_revision': dict(expected_predecessor_revision=2),
               'confirmation': dict(external_processing=None)}
    before = persistent_state(f)
    with pytest.raises(StorageError) as exc:
        f.submit(f.request.model_copy(update=updates[change]))
    assert exc.value.code == ('task_input_invalid' if change == 'confirmation' else 'task_source_conflict')
    assert persistent_state(f) == before and f.retries == []


def test_current_configuration_cas_blocks_drift_before_writes(submission, monkeypatch):
    f = submission
    version = activate_true(f)
    actual_create = f.actual.create
    seen = []

    def race(*args, **kwargs):
        seen.append(kwargs['expected_configuration_id'])
        f.db.pointer['version_id'] = 'current-false'
        return actual_create(*args, **kwargs)

    monkeypatch.setattr(f.actual, 'create', race)
    before = persistent_state(f)
    with pytest.raises(StorageError) as exc:
        f.submit()
    assert exc.value.code == 'configuration_revision_conflict'
    assert seen == [version['id']] and persistent_state(f) == before


def test_old_key_and_non_retry_read_original_task_after_activation(submission):
    from app.domain.external_processing import request_digest
    from app.domain.tasks.contracts import TaskCreateRequest
    f = submission
    activate_true(f)
    typed = TaskCreateRequest(task_type='explanation', file_id=f.snapshot['file']['id'],
        analysis_run_id=f.snapshot['result']['id'], expected_revision=1,
        figure_id=f.snapshot['figure']['id'], external_processing=f.request.external_processing)
    f.old.update(idempotency_key='synthetic-old-key', input_digest=request_digest(typed))
    before = persistent_state(f)
    for request, key in [(f.request, 'synthetic-old-key'),
                         (f.request.model_copy(update={'retry': False}), 'synthetic-new-request')]:
        state, status = f.submit(request, key)
        assert status == 200 and state['task']['id'] == TASK and state['task']['status'] == 'failed'
    assert persistent_state(f) == before and f.retries == []


def gateway_fixture():
    db = MemoryDB()
    instructions, payload = 'Synthetic instructions.', {'facts': {'n': 3}}
    request = CallRequest(task_id=TASK, expected_task_revision=2, call_key='explanation:v1',
        input_digest=input_digest(instructions=instructions, payload=payload),
        policy=ModelPolicy.model_validate(synthetic_policy()['policy']), input_token_allowance=50000)

    class Store:
        @contextmanager
        def connection(self):
            yield db

        def require_task(self, connection, identity):
            return dict(id=identity)

    service = SimpleNamespace(store=Store(), reserve_call=forbidden)
    return db, service, request, instructions, payload


def test_old_false_gateway_blocks_before_reservation():
    _, service, request, instructions, payload = gateway_fixture()
    with pytest.raises(ModelGatewayError) as exc:
        ModelGateway(service, object.__new__(OpenAIResponsesProvider)).submit(
            request, instructions=instructions, payload=payload)
    assert exc.value.code == 'model_configuration_disabled'


def test_true_gateway_still_checks_digest_and_forwards_exact_lease():
    db, service, request, instructions, payload = gateway_fixture()
    db.versions['old-false']['bundle']['models']['real_calls_enabled'] = True
    gateway = ModelGateway(service, object.__new__(OpenAIResponsesProvider))
    with pytest.raises(ModelGatewayError) as exc:
        gateway.submit(request.model_copy(update={'input_digest': '0' * 64}),
                       instructions=instructions, payload=payload)
    assert exc.value.code == 'model_input_digest_mismatch'
    seen, lease = [], object()

    class ReachedReserve(Exception):
        pass

    def reserve(actual, **kwargs):
        seen.append((actual, kwargs))
        raise ReachedReserve()

    service.reserve_call = reserve
    with pytest.raises(ReachedReserve):
        gateway.submit(request, instructions=instructions, payload=payload, execution_lease=lease)
    assert seen == [(request, {'execution_lease': lease})]


@pytest.mark.parametrize('failure', ['missing_budget', 'insufficient_budget', 'lost_lease'])
def test_true_gateway_does_not_bypass_real_budget_or_lease_checks(failure):
    from app.adapters.task_execution_store import LeaseLost, TaskLease
    from app.domain.model_usage.service import ModelUsageService
    db, _, request, instructions, payload = gateway_fixture()
    db.versions['old-false']['bundle']['models']['real_calls_enabled'] = True

    class ReserveDB:
        def execute(self, sql, args):
            if 'SELECT a.id FROM task_attempts' in sql:
                return Result(None if failure == 'lost_lease' else dict(id='synthetic-attempt'))
            if 'SELECT * FROM model_calls' in sql:
                return Result()
            raise AssertionError('Unexpected reserve SQL: ' + sql)

    class Store:
        user_id = OWNER

        @contextmanager
        def connection(self, write=False):
            yield ReserveDB() if write else db

        def require_task(self, connection, identity):
            return dict(id=identity, input_snapshot={}, revision=2, status='running',
                task_type='explanation', workflow_version='explanation_v1',
                project_id=PROJECT, current_attempt=1)

        def budget(self, connection, scope, key):
            return None if failure == 'missing_budget' else dict(id=scope)

        def budget_view(self, connection, scope, budget):
            return dict(available_micro_usd=0)

        insert_call = staticmethod(forbidden)

    service = object.__new__(ModelUsageService)
    service.store = Store()
    with pytest.raises(LeaseLost if failure == 'lost_lease' else StorageError) as exc:
        ModelGateway(service, object.__new__(OpenAIResponsesProvider)).submit(request,
            instructions=instructions, payload=payload, execution_lease=TaskLease(TASK, 1, 'synthetic-lease'))
    if failure != 'lost_lease':
        assert exc.value.code == ('model_budget_missing' if failure == 'missing_budget' else 'model_budget_exceeded')


def test_configuration_disabled_remains_public_and_finishes_without_retry(monkeypatch):
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.core.errors import error_detail
    from app.domain.tasks.errors import classify_read_error, error_category
    code = 'model_configuration_disabled'
    assert error_detail(code, 'Synthetic public explanation')['code'] == code
    assert classify_read_error(code) == code and error_category(code) == 'configuration'
    task = dict(id=TASK, task_type='explanation', retry_count=0, status='running',
                revision=2, updated_at=datetime.now(timezone.utc))
    repo, finished = object.__new__(TaskExecutionStore), []

    @contextmanager
    def connection(**kwargs):
        yield object()

    monkeypatch.setattr(repo, 'connection', connection)
    monkeypatch.setattr(repo, 'require_lease', lambda db, lease: task)
    monkeypatch.setattr(repo, '_finish', lambda db, task, status, error: finished.append((status, error)))
    monkeypatch.setattr('app.adapters.task_execution_store.TaskStore.public_task', lambda value: value)
    repo.retry_failure(object(), code)
    assert finished == [('failed', code)] and task['retry_count'] == 0
