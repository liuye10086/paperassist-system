"""0082/0083 transitions run only in the automatically isolated test schema."""
import pytest
from psycopg.types.json import Jsonb

from app.db.database import database_connection, migration_connection, verify_runtime_permissions, get_database_config
from app.domain.bioinformatics.contracts import digest
from tests.integration.test_account_deletion_migration import migrate
from tests.api.test_projects import client, create_project


def test_new_schema_roundtrip_retains_existing_fk_names_and_runtime_permissions(monkeypatch):
    with database_connection() as db:
        before = db.execute("SELECT conrelid::regclass::text AS table_name,conname FROM pg_constraint WHERE conname LIKE 'b03_scope_fk_%%' ORDER BY 1,2").fetchall()
        verify_runtime_permissions(db.raw_connection, get_database_config())
    from app.db.research_results_schema import SOURCE_TARGETS
    monkeypatch.setitem(SOURCE_TARGETS, 'future_source_kind', ('future_source_id', 'files'))
    migrate('0082_reader_report_narratives', down=True)
    with database_connection() as db:
        assert db.execute("SELECT to_regclass('bio_report_context_versions') AS name").fetchone()['name'] is None
    migrate('0083_bio_report_contexts')
    with database_connection() as db:
        after = db.execute("SELECT conrelid::regclass::text AS table_name,conname FROM pg_constraint WHERE conname LIKE 'b03_scope_fk_%%' ORDER BY 1,2").fetchall()
        assert before == after
        verify_runtime_permissions(db.raw_connection, get_database_config())
        for table in ('research_source_bindings', 'manuscript_research_sources'):
            assert db.execute('SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=%s AND column_name=%s', (table, 'bio_report_context_id')).fetchone()


def test_saved_context_refuses_downgrade_and_is_database_immutable(client):
    project = create_project(client)['id']
    with database_connection() as db:
        owner = db.execute('SELECT owner_id FROM projects WHERE id=%s', (project,)).fetchone()['owner_id']
    with migration_connection(write=True) as db:
        db.execute("INSERT INTO bio_report_context_versions(id,project_id,user_id,created_at,schema_version,content_sha256,content_json) VALUES('fixed',%s,%s,now(),1,%s,%s)", (project, owner, digest({}), Jsonb({})))
    with pytest.raises(RuntimeError, match='Saved native report contexts exist'):
        migrate('0082_reader_report_narratives', down=True)
    with migration_connection(write=True) as db:
        with pytest.raises(Exception, match='immutable'):
            db.execute("UPDATE bio_report_context_versions SET content_json='{}' WHERE id='fixed'")
    with database_connection() as db:
        assert db.execute("SELECT id FROM bio_report_context_versions WHERE id='fixed'").fetchone()
