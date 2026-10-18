"""The local node deadline includes parent CPU, pool checkout and TCP handshake."""
import socket
import sys
import threading
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='Linux worker deadline')


def test_deadline_interrupts_parent_cpu_and_restores_signal():
    import signal
    from app.domain.fixed_statistics_runtime import numeric_execution_scope
    from app.domain.regression.common import NumericError
    handler = signal.getsignal(signal.SIGALRM)
    started = time.monotonic()
    with pytest.raises(NumericError, match='期限'):
        with numeric_execution_scope(.08):
            until = time.monotonic() + 1
            while time.monotonic() < until:
                pass
    assert time.monotonic() - started < .8
    assert signal.getsignal(signal.SIGALRM) == handler
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0


def test_deadline_interrupts_pool_checkout(monkeypatch, postgres_schema):
    from sqlalchemy import create_engine
    from app.db import database
    from app.domain.fixed_statistics_runtime import numeric_execution_scope
    from app.domain.regression.common import NumericError
    engine = create_engine(postgres_schema.url, pool_size=1, max_overflow=0, pool_timeout=2,
                           pool_pre_ping=True, hide_parameters=True)
    monkeypatch.setattr(database, 'get_engine', lambda config: engine)
    try:
        with engine.connect():
            started = time.monotonic()
            with pytest.raises(NumericError) as caught:
                with numeric_execution_scope(.08):
                    with database.database_connection():
                        pytest.fail('No connection should be available')
            assert caught.value.code == 'numeric_timeout'
            assert time.monotonic() - started < .8
    finally:
        engine.dispose()


def test_deadline_interrupts_real_psycopg_handshake(postgres_schema):
    from app.db.database import DatabaseConfig, database_connection, _engine_for_url
    from app.domain.fixed_statistics_runtime import numeric_execution_scope
    from app.domain.regression.common import NumericError
    stop = threading.Event()
    with socket.socket() as server:
        server.bind(('127.0.0.1', 0)); server.listen(); server.settimeout(2)
        def blackhole():
            try:
                connection, _ = server.accept()
                with connection:
                    stop.wait(2)
            except OSError:
                pass
        thread = threading.Thread(target=blackhole, daemon=True); thread.start()
        config = DatabaseConfig('test', postgres_schema.url.set(host='127.0.0.1',
            port=server.getsockname()[1], username='synthetic', password='synthetic'), postgres_schema.schema)
        started = time.monotonic()
        try:
            with pytest.raises(NumericError) as caught:
                with numeric_execution_scope(.1):
                    with database_connection(config=config):
                        pytest.fail('The fake server never authenticates')
            assert caught.value.code == 'numeric_timeout'
            assert time.monotonic() - started < .8
        finally:
            stop.set(); thread.join(3); _engine_for_url(config.url).dispose()
