"""Capture-only DB budgets; all data lives in the per-test disposable schema."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event
import asyncio
import json
import socket
import time
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool
import pytest

from app.db.database import database_connection
from app.domain.admin_operations import record_request


def measured(request, **values):
    with request.getfixturevalue('capsys').disabled():
        request.config.pluginmanager.get_plugin('terminalreporter').write_line(
            'capture evidence ' + json.dumps(values, sort_keys=True))


def event():
    return dict(request_id=uuid4().hex, route_template='/api/v1/probe', method='GET',
                status=200, elapsed_ms=1, user_id=None, error_code=None,
                created_at=datetime.now(timezone.utc))


def test_capture_lock_timeout_rolls_back_and_next_capture_works(postgres_schema, request):
    captured = event()
    finished = Event()

    def collect():
        began = time.monotonic()
        try:
            record_request(captured)
            return None, time.monotonic() - began
        except SQLAlchemyError as exc:
            return exc.orig.sqlstate, time.monotonic() - began
        finally:
            finished.set()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with database_connection(write=True):
            future = executor.submit(collect)
            # The holder cannot release before this observation, even in RED.
            bounded = finished.wait(1.8)
        state, elapsed = future.result(timeout=5)
    assert bounded, f'collector still blocked after 1.8s; returned {state} after {elapsed:.3f}s'
    assert state == '55P03'
    assert elapsed < 2
    measured(request, lock_sqlstate=state, lock_seconds=elapsed)
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM operational_request_events').fetchone()['n'] == 0
    record_request(event())
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM operational_request_events').fetchone()['n'] == 1


def test_capture_statement_timeout_rolls_back_insert_and_releases_lock(postgres_schema, request):
    captured = event()
    began = time.monotonic()
    with pytest.raises(SQLAlchemyError) as error:
        with database_connection(write=True, capture=True) as db:
            db.execute('INSERT INTO operational_request_events(request_id,method,status,elapsed_ms,created_at) '
                       'VALUES(%s,%s,%s,%s,%s)',
                       (captured['request_id'], 'GET', 200, 1, captured['created_at']))
            db.execute('SELECT pg_sleep(3)')
    elapsed = time.monotonic() - began
    assert error.value.orig.sqlstate == '57014'
    assert .8 < elapsed < 2
    measured(request, statement_sqlstate=error.value.orig.sqlstate, statement_seconds=elapsed)
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM operational_request_events').fetchone()['n'] == 0
    record_request(event())


def test_capture_connect_timeout_has_no_checkout_or_preping_wait(postgres_schema, request):
    from app.db.database import DatabaseConfig, _capture_engine_for_url, get_engine
    # A local listener accepts TCP but never answers the libpq handshake.
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        listener.settimeout(5)
        port = listener.getsockname()[1]
        config = DatabaseConfig('test', postgres_schema.url.set(host='127.0.0.1', port=port), postgres_schema.schema)
        engine = _capture_engine_for_url(config.url)
        assert isinstance(engine.pool, NullPool) and engine.pool._pre_ping is False
        assert not isinstance(get_engine(postgres_schema).pool, NullPool)
        assert get_engine(postgres_schema).pool._pre_ping is True
        release = Event()

        def silent_peer():
            client, _ = listener.accept()
            with client:
                release.wait(5)

        with ThreadPoolExecutor(max_workers=1) as executor:
            peer = executor.submit(silent_peer)
            began = time.monotonic()
            try:
                with pytest.raises(SQLAlchemyError):
                    with database_connection(write=True, config=config, capture=True):
                        pytest.fail('silent endpoint must not yield a connection')
                elapsed = time.monotonic() - began
            finally:
                release.set()
                peer.result(timeout=5)
        assert 1.8 <= elapsed < 3.5
        measured(request, local_connect_seconds=elapsed, configured_connect_seconds=2)


def test_capture_numeric_deadline_uses_earliest_limits_and_checks_commit(postgres_schema, request):
    from app.domain.fixed_statistics_runtime import numeric_execution_scope
    from app.domain.regression.common import NumericError
    with numeric_execution_scope(5) as scope:
        with database_connection(write=True, capture=True) as db:
            assert db.execute('SHOW statement_timeout').fetchone()['statement_timeout'] == '1s'
            assert db.execute('SHOW lock_timeout').fetchone()['lock_timeout'] == '200ms'
            # Shorten the actual scope deadline after acquisition, on the main thread.
            scope.deadline = time.monotonic() + .15
            statement = db.execute('SHOW statement_timeout').fetchone()['statement_timeout']
            lock = db.execute('SHOW lock_timeout').fetchone()['lock_timeout']
            assert 0 < int(statement.removesuffix('ms')) <= 150
            assert 0 < int(lock.removesuffix('ms')) <= 150
            measured(request, short_numeric_statement=statement, short_numeric_lock=lock)
    with pytest.raises(NumericError) as error:
        with numeric_execution_scope(5) as scope:
            with database_connection(write=True, capture=True) as db:
                captured = event()
                db.execute('INSERT INTO operational_request_events(request_id,method,status,elapsed_ms,created_at) '
                           'VALUES(%s,%s,%s,%s,%s)',
                           (captured['request_id'], 'GET', 200, 1, captured['created_at']))
                scope.deadline = time.monotonic() - 1
    assert error.value.code == 'numeric_timeout'
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM operational_request_events').fetchone()['n'] == 0


def test_middleware_keeps_response_when_real_capture_lock_times_out(postgres_schema, caplog, request):
    from app.core.request_id import RequestIdMiddleware
    sent = []

    async def application(scope, receive, send):
        await send({'type': 'http.response.start', 'status': 422,
                    'headers': [(b'content-type', b'application/json')]})
        await send({'type': 'http.response.body', 'body':
                    b'{"detail":{"code":"invalid_request","message":"unchanged","details":{}}}'})

    async def send(message):
        sent.append(message)

    async def receive():
        return {'type': 'http.request', 'body': b'', 'more_body': False}

    scope = {'type': 'http', 'path': '/api/v1/probe', 'method': 'GET', 'headers': []}
    began = time.monotonic()
    with database_connection(write=True):
        asyncio.run(RequestIdMiddleware(application)(scope, receive, send))
    elapsed = time.monotonic() - began
    assert elapsed < 2
    request_id = scope['state']['request_id']
    assert sent[0]['status'] == 422
    assert dict(sent[0]['headers'])[b'x-request-id'] == request_id.encode()
    assert json.loads(sent[1]['body']) == {'detail': dict(
        code='invalid_request', message='unchanged', details={}, request_id=request_id)}
    warnings = [r.getMessage() for r in caplog.records if 'capture' in r.getMessage()]
    assert warnings == ['code=operational_capture_unavailable request_id=' + request_id]
    measured(request, middleware_seconds=elapsed, response_status=422)


def test_ordinary_writer_retains_long_statement_and_unlimited_lock_budget(postgres_schema, request):
    # First use the capture engine; its budgets must not leak to business writes.
    record_request(event())
    with database_connection(write=True) as db:
        assert db.execute('SHOW statement_timeout').fetchone()['statement_timeout'] == '0'
        assert db.execute('SHOW lock_timeout').fetchone()['lock_timeout'] == '0'
        began = time.monotonic()
        db.execute('SELECT pg_sleep(1.1)')
        elapsed = time.monotonic() - began
        assert elapsed >= 1.1
        measured(request, ordinary_statement_seconds=elapsed)
