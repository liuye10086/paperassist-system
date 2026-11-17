from app.auth.service import create_user
from app.db.database import SCHEMA_HEAD, database_connection
from tests.integration.test_account_deletion_migration import migrate
from tests.auth.test_account_roles import PASSWORD


def test_sci_settings_upgrade_preserves_intakes_and_creation_receipts():
    owner_id = create_user('sci-migration@manuscript.test', PASSWORD, role='customer')['id']
    migrate('0085_statistics_legacy_exports', down=True)
    with database_connection(write=True) as db:
        for project_id, kind, key in (('legacy-sci', 'sci', None), ('legacy-analysis', 'research', 'saved-request')):
            db.execute("""INSERT INTO projects(id, name, research_topic, project_type, owner_id, created_at, updated_at)
                VALUES (%s, %s, 'Synthetic topic', %s, %s, '2026-11-01', '2026-11-01')""",
                (project_id, project_id, kind, owner_id))
            db.execute("""INSERT INTO research_intakes(project_id, owner_id, revision, creation_request_key, creation_digest, created_at, updated_at)
                VALUES (%s, %s, 2, %s, %s, now(), now())""", (project_id, owner_id, key, 'a' * 64 if key else None))
        before = [dict(row) for row in db.execute('SELECT * FROM research_intakes ORDER BY project_id').fetchall()]
        assert len(before) == 2 and all('sci_settings_json' not in row for row in before)
    migrate(SCHEMA_HEAD)
    with database_connection() as db:
        after = [dict(row) for row in db.execute('SELECT * FROM research_intakes ORDER BY project_id').fetchall()]
        assert all(row.pop('sci_settings_json') is None for row in after)
        assert after == before
