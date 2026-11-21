"""Statistics context migration transitions in an isolated test schema."""
import pytest
from psycopg.types.json import Jsonb
from sqlalchemy.exc import IntegrityError

from app.db.database import database_connection, get_database_config, migration_connection, verify_runtime_permissions
from app.domain.bioinformatics.contracts import digest
from tests.api.test_projects import client, create_project  # noqa: F401
from tests.helpers.historical_migration import assert_historical_runtime_grants
from tests.integration.test_account_deletion_migration import migrate


@pytest.mark.initial_revision('0084_statistics_report_context')
def test_0084_roundtrip_retains_0083_bindings_and_runtime_grants():
    migrate('0083_bio_report_contexts', down=True)
    with database_connection() as db:
        assert db.execute("SELECT to_regclass('statistics_report_context_versions') AS name").fetchone()['name'] is None
        before = db.execute("SELECT conname FROM pg_constraint WHERE connamespace=current_schema()::regnamespace AND conname LIKE 'brc_%%' ORDER BY 1").fetchall()
    migrate('0084_statistics_report_context')
    with database_connection() as db:
        assert_historical_runtime_grants(db)
        assert before == db.execute("SELECT conname FROM pg_constraint WHERE connamespace=current_schema()::regnamespace AND conname LIKE 'brc_%%' ORDER BY 1").fetchall()
        for table in ('research_source_bindings', 'manuscript_research_sources'):
            assert db.execute('SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=%s '
                              "AND column_name='statistics_report_context_id'", (table,)).fetchone()
    migrate('head')
    with database_connection() as db:
        verify_runtime_permissions(db.raw_connection, get_database_config())


def test_saved_context_is_immutable_scoped_and_blocks_downgrade(client):
    project = create_project(client)['id']
    with database_connection() as db:
        owner = db.execute('SELECT owner_id FROM projects WHERE id=%s', (project,)).fetchone()['owner_id']
    statement = """INSERT INTO statistics_report_context_versions
        (id,project_id,user_id,created_at,content_sha256,content_json) VALUES(%s,%s,%s,now(),%s,%s)"""
    with pytest.raises(IntegrityError) as wrong_owner:
        with migration_connection(write=True) as db:
            db.execute(statement, ('bad-owner', project, 'other-owner', digest({}), Jsonb({})))
    assert wrong_owner.value.orig.sqlstate == '23503'
    with migration_connection(write=True) as db:
        db.execute(statement, ('fixed', project, owner, digest({}), Jsonb({})))
    with pytest.raises(RuntimeError, match='Saved statistics report contexts exist'):
        migrate('0083_bio_report_contexts', down=True)
    with pytest.raises(Exception, match='immutable'):
        with migration_connection(write=True) as db:
            db.execute("DELETE FROM statistics_report_context_versions WHERE id='fixed'")
