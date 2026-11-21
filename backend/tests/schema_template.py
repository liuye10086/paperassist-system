"""Clone each test's PostgreSQL schema from one migrated template per session.

Running all Alembic migrations takes about 8-9 seconds per test. Loading a
renamed ``pg_dump`` of an already migrated schema takes about 1-2 seconds and
keeps tables, sequences, functions, triggers, seed rows and grants identical.

Safety:
- The template is built with the real ``migrate_database`` on first use and
  reused only while the migration sources are unchanged (the template name is
  derived from a hash of ``alembic/versions``), so a changed migration builds a
  new template.
- Every clone is verified: Alembic head and object counts must match the
  template, otherwise the caller falls back to running migrations.
- ``PAPERASSIST_TEST_SCHEMA_TEMPLATE=0`` disables cloning entirely and restores
  the original per-test migration path.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

_SCHEMA = re.compile(r'pa_test_[0-9a-f]{32}\Z')
_VERSIONS = Path(__file__).resolve().parents[1] / 'alembic' / 'versions'
_state: dict = {}


def enabled() -> bool:
    return os.environ.get('PAPERASSIST_TEST_SCHEMA_TEMPLATE', '1') != '0' and bool(shutil.which('pg_dump')) and bool(shutil.which('psql'))


def template_name() -> str:
    digest = hashlib.sha256()
    for path in sorted(_VERSIONS.glob('*')):
        if path.suffix in {'.py', '.sql'} and path.is_file():
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
    return 'pa_test_' + digest.hexdigest()[:32]


def _pg_env(url) -> dict:
    env = dict(os.environ)
    env.update(PGHOST=url.host or 'localhost', PGPORT=str(url.port or 5432), PGUSER=url.username or '',
               PGPASSWORD=url.password or '', PGDATABASE=url.database or '')
    return env


def _counts(connection, schema: str) -> tuple:
    return tuple(connection.exec_driver_sql(sql, (schema,)).scalar_one() for sql in (
        "SELECT count(*) FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s",
        "SELECT count(*) FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=%s",
        "SELECT count(*) FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid "
        "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND NOT t.tgisinternal",
    ))


def _head(connection, schema: str):
    quoted = connection.dialect.identifier_preparer.quote(schema)
    return connection.exec_driver_sql(f'SELECT version_num FROM {quoted}.alembic_version').scalar_one()


def _build_template(engine, migration_url, build_schema) -> None:
    """Create the template once: migrate it for real, then cache its dump."""
    name = template_name()
    assert _SCHEMA.fullmatch(name)
    with engine.begin() as connection:
        exists = connection.exec_driver_sql(
            'SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname=%s', (name,)).scalar_one_or_none()
    if not exists:
        build_schema(name)
    dump = subprocess.run(['pg_dump', '--schema', name, '--no-owner', '--no-comments'],
                          env=_pg_env(migration_url), capture_output=True, timeout=300)
    if dump.returncode:
        raise RuntimeError('pg_dump failed: ' + dump.stderr.decode(errors='replace')[:300])
    with engine.begin() as connection:
        _state.update(name=name, sql=dump.stdout.decode(), counts=_counts(connection, name), head=_head(connection, name))


def drop_schema(engine, schema: str) -> None:
    """Drop a test schema; on lock-table exhaustion drop its tables in batches first.

    ``DROP SCHEMA ... CASCADE`` locks every object at once and can exceed
    ``max_locks_per_transaction`` (seen as OutOfMemory). That left schemas behind
    and failed teardown at random, so retry in small transactions instead.
    """
    assert _SCHEMA.fullmatch(schema)
    quote = engine.dialect.identifier_preparer.quote
    try:
        with engine.begin() as connection:
            assert connection.exec_driver_sql('SELECT current_database()').scalar_one() == 'paperassist_system_test'
            connection.exec_driver_sql(f'DROP SCHEMA {quote(schema)} CASCADE')
        return
    except Exception as error:  # noqa: BLE001
        if 'max_locks_per_transaction' not in str(error) and 'OutOfMemory' not in type(getattr(error, 'orig', error)).__name__:
            raise
    with engine.begin() as connection:
        tables = [row[0] for row in connection.exec_driver_sql(
            "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname=%s", (schema,))]
    for start in range(0, len(tables), 20):
        with engine.begin() as connection:
            names = ', '.join(f'{quote(schema)}.{quote(name)}' for name in tables[start:start + 20])
            connection.exec_driver_sql(f'DROP TABLE IF EXISTS {names} CASCADE')
    with engine.begin() as connection:
        connection.exec_driver_sql(f'DROP SCHEMA {quote(schema)} CASCADE')


def clone(engine, migration_url, schema: str, build_schema) -> bool:
    """Create ``schema`` as a copy of the template. Return False to fall back to migrations."""
    if not enabled() or not _SCHEMA.fullmatch(schema):
        return False
    try:
        if 'sql' not in _state:
            _build_template(engine, migration_url, build_schema)
        sql = _state['sql'].replace(_state['name'], schema)
        load = subprocess.run(['psql', '-q', '-X', '-v', 'ON_ERROR_STOP=1', '--single-transaction'],
                              input=sql.encode(), env=_pg_env(migration_url), capture_output=True, timeout=300)
        if load.returncode:
            raise RuntimeError('psql load failed: ' + load.stderr.decode(errors='replace')[:300])
        with engine.begin() as connection:
            if _counts(connection, schema) != _state['counts'] or _head(connection, schema) != _state['head']:
                raise RuntimeError('cloned schema does not match the template')
        return True
    except Exception as error:  # noqa: BLE001 - any failure falls back to the original path
        _state['last_error'] = repr(error)
        with engine.begin() as connection:
            quoted = connection.dialect.identifier_preparer.quote(schema)
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS {quoted} CASCADE')
        return False
