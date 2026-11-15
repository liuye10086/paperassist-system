"""0085 has no rewrites of old exports and refuses loss of saved associations."""
from app.db.database import database_connection, get_database_config, verify_runtime_permissions
from tests.integration.test_account_deletion_migration import migrate


def test_0085_roundtrip_keeps_context_constraints_and_runtime_grants():
    migrate('0084_statistics_report_context',down=True)
    with database_connection() as db:
        assert db.execute("SELECT to_regclass('statistics_legacy_report_exports') AS name").fetchone()['name'] is None
        before=db.execute("SELECT conname FROM pg_constraint WHERE conname LIKE 'sr_context_%%' ORDER BY 1").fetchall()
    migrate('0085_statistics_legacy_exports')
    with database_connection() as db:
        verify_runtime_permissions(db.raw_connection,get_database_config())
        assert before==db.execute("SELECT conname FROM pg_constraint WHERE conname LIKE 'sr_context_%%' ORDER BY 1").fetchall()
        for name in ('statistics_legacy_report_exports','statistics_legacy_export_requests'):
            assert db.execute('SELECT to_regclass(%s) AS name',(name,)).fetchone()['name']==name
