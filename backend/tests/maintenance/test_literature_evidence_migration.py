"""Exercise additive evidence DDL against retained retrieval data in TEST only."""
import hashlib

from alembic import command
from alembic.script import ScriptDirectory

from app.db.database import (alembic_config, database_connection, get_migration_database_config,
                             migration_connection, verify_runtime_permissions)
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_literature import create, project
from tests.helpers.literature import SyntheticNcbi
from tests.integration.test_literature_workflow import execute


def fingerprints(db, tables):
    result = {}
    quote = db.raw_connection.dialect.identifier_preparer.quote
    for name in tables:
        values = sorted(row['value'] for row in db.execute(
            'SELECT to_jsonb(t)::text AS value FROM ' + quote(name) + ' t'))
        result[name] = (len(values), hashlib.sha256('\n'.join(values).encode()).hexdigest())
    return result


def test_evidence_upgrade_preserves_existing_retrieval_rows_sources_and_indexes(client):
    config = alembic_config()
    assert ScriptDirectory.from_config(config).get_heads() == ['0034_literature_pmc']
    pid = project(client)
    task = create(client, pid).json()
    assert execute(task, SyntheticNcbi(2))['status'] == 'succeeded'
    before_api = client.get(f'/api/v1/projects/{pid}/literature/references').json()
    source_url = before_api['items'][0]['source']['source_download_url']
    source_bytes = client.get(source_url).content
    with migration_connection(write=True) as db:
        config.attributes.update(connection=db.raw_connection, database_config=get_migration_database_config())
        command.downgrade(config, '0030_literature_search')
        tables = [r['tablename'] for r in db.execute(
            'SELECT tablename FROM pg_tables WHERE schemaname=current_schema()')
            if r['tablename'] != 'alembic_version']
        before = fingerprints(db, tables)
        indexes = {r['indexname']: r['indexdef'] for r in db.execute(
            'SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        command.upgrade(config, '0031_literature_evidence')
        assert fingerprints(db, tables) == before
        after_indexes = {r['indexname']: r['indexdef'] for r in db.execute(
            'SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        assert all(after_indexes.get(k) == v for k, v in indexes.items())
        command.upgrade(config, 'head')
    with database_connection() as db:
        from app.maintenance.database_audit import audit_database
        verify_runtime_permissions(db.raw_connection, db.config)
        result = audit_database(db)
        assert result['ok'], {'schema_issues': result['schema_issues'],
                              'invalid_checks': [c for c in result['data_checks'] if c['invalid']],
                              'review_checks': [dict(row) for row in db.execute("""SELECT conname,
                                  pg_get_constraintdef(oid) AS definition FROM pg_constraint
                                  WHERE conrelid='literature_claim_reviews'::regclass AND contype='c'""")]}
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0
    assert client.get(f'/api/v1/projects/{pid}/literature/references').json() == before_api
    assert client.get(source_url).content == source_bytes
