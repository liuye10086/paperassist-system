"""Rehearse an adjacent historical migration with real synthetic workflow records."""
from contextlib import contextmanager
import re
from uuid import uuid4

from alembic import command
from pytest import MonkeyPatch
from sqlalchemy import inspect

from app.db.database import DatabaseConnection, alembic_config, get_migration_database_config, migration_connection


# Insert in dependency order. The upload item and file reference one another.
WORKFLOW_TABLES = (
    'users', 'sessions', 'auth_login_attempts', 'session_revocations', 'auth_password_attempts',
    'projects', 'file_upload_batches', 'files', 'analysis_setups', 'analysis_runs',
    'figure_configurations', 'figure_config_versions', 'figures', 'explanations', 'reports', 'tasks',
    'file_upload_items', 'file_parse_results', 'file_structure_versions', 'dataset_versions',
    'task_attempts', 'task_events', 'task_outbox', 'task_waits', 'task_checkpoints', 'task_resume_requests',
    'model_budgets', 'model_calls', 'budget_reservations', 'ocr_review_decisions', 'ocr_review_versions',
    'dataset_preparation_decisions', 'prepared_dataset_versions',
    'analysis_plan_decisions', 'confirmed_analysis_plans', 'prepared_dataset_derivations',
    'prepared_dataset_derivations_v3', 'external_evidence_versions', 'file_deletion_requests',
    'report_collections', 'report_collection_versions', 'report_collection_items', 'report_build_requests',
    'collection_reports', 'literature_records', 'literature_searches', 'project_references',
    'literature_fetch_receipts', 'literature_search_hits', 'ncbi_rate_limits',
    'literature_materials', 'literature_claims', 'literature_claim_versions', 'literature_claim_evidence',
    'literature_claim_reviews', 'literature_claim_supplements', 'literature_citation_metadata_versions',
    'literature_material_confirmations', 'literature_citation_drafts', 'literature_citation_versions',
    'literature_check_receipts', 'literature_pmc_receipts', 'school_template_versions', 'school_template_sources',
    'school_template_confirmations', 'thesis_profiles', 'manuscripts', 'manuscript_versions',
    'manuscript_sources', 'manuscript_citations', 'manuscript_exports', 'pdf_exports', 'layout_exports', 'journal_profiles',
    'journal_recommendations', 'journal_guides', 'journal_material_refs', 'journal_targets', 'journal_format_checks',
    'review_rounds', 'review_round_events', 'review_revision_runs',
)


@contextmanager
def historical_workflow(migration, revision):
    """Copy predecessor columns into a transaction-local UUID test schema, leaving the source untouched."""
    assert migration.environment == 'test' and re.fullmatch(r'pa_test_[0-9a-f]{32}', migration.schema)
    target = 'pa_test_' + uuid4().hex
    with migration_connection(config=migration) as source:
        connection = source.raw_connection
        transaction = connection.begin_nested()
        try:
            source.execute('CREATE SCHEMA ' + target)
            with MonkeyPatch.context() as patch:
                patch.setenv('PAPERASSIST_DB_SCHEMA', target)
                historical = get_migration_database_config()
                settings = alembic_config()
                settings.attributes.update(connection=connection, database_config=historical)
                command.upgrade(settings, revision)
                db = DatabaseConnection(connection, historical)
                assert db.execute('SELECT version_num FROM alembic_version').fetchone()['version_num'] == revision
                _copy_predecessor_rows(db, migration.schema)
                yield db, settings
        finally:
            transaction.rollback()


def _copy_predecessor_rows(db, source):
    inspector = inspect(db.raw_connection)
    tables = set(inspector.get_table_names(schema=db.config.schema))
    # 0075 explicitly maps historical user to analyst. Customer and pending accounts have no inverse.
    assert not db.execute(f"SELECT 1 FROM {source}.users WHERE review_status <> 'approved' OR role IS NULL OR role NOT IN ('analyst','admin')").fetchone()
    quote = db.raw_connection.dialect.identifier_preparer.quote
    for table in WORKFLOW_TABLES:
        if table not in tables:
            continue
        columns = [c['name'] for c in inspector.get_columns(table, schema=db.config.schema)]
        expressions = {name: 's.' + quote(name) for name in columns}
        predicate = ''
        if table == 'users':
            expressions['role'] = "CASE s.role WHEN 'analyst' THEN 'user' ELSE s.role END"
        elif table == 'files':
            expressions['upload_item_id'] = 'NULL'
        elif table == 'tasks' and 'literature_records' not in tables:
            # Fixed-runtime statistics_compute did not exist before 0029. Its saved result does.
            predicate = " WHERE s.task_type <> 'statistics_compute'"
        elif table in ('task_attempts', 'task_events', 'task_outbox', 'task_resume_requests') and 'literature_records' not in tables:
            predicate = " WHERE EXISTS (SELECT 1 FROM tasks t WHERE t.id=s.task_id)"
        elif table in ('task_waits', 'task_checkpoints') and 'literature_records' not in tables:
            # The reader-report renderer has its own later checkpoints. Preserve the historical preparation and plan chains.
            predicate = """ WHERE EXISTS (SELECT 1 FROM tasks t WHERE t.id=s.task_id
                AND t.task_type IN ('prepare_dataset','analysis_plan'))"""
        db.execute(f"INSERT INTO {table} ({', '.join(map(quote, columns))}) "
                   f"SELECT {', '.join(expressions.values())} FROM {source}.{table} s{predicate}")
    if 'file_upload_items' in tables:
        db.execute(f"""UPDATE files AS restored SET upload_item_id=s.upload_item_id
            FROM {source}.files AS s WHERE s.id=restored.id AND s.upload_item_id IS NOT NULL""")


def assert_historical_runtime_grants(db):
    """Check the runtime role's exact privileges on every table present at the selected revision."""
    from app.db.database import _APPEND_ONLY_TABLES
    rows = db.execute("""SELECT c.relname, privilege, has_table_privilege(current_user, c.oid, privilege) AS granted
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER']) privilege
        WHERE n.nspname=current_schema() AND c.relkind='r'""").fetchall()
    assert any(row['relname'] == 'alembic_version' for row in rows)
    for row in rows:
        table, privilege = row['relname'], row['privilege']
        expected = privilege == 'SELECT' or (table != 'alembic_version' and (
            privilege == 'INSERT' or (privilege in ('UPDATE', 'DELETE') and table not in _APPEND_ONLY_TABLES)))
        assert row['granted'] == expected, (table, privilege)


def assert_saved_history_blocks(revision, message):
    """Exercise one deployed downgrade's data guard, in a read-only transaction over the saved test data."""
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    import pytest

    migration = get_migration_database_config()
    assert migration.environment == 'test' and re.fullmatch(r'pa_test_[0-9a-f]{32}', migration.schema)
    script = ScriptDirectory.from_config(alembic_config()).get_revision(revision)
    assert script.revision == revision
    with migration_connection(write=False, config=migration) as db:
        assert db.execute('SHOW transaction_read_only').fetchone()['transaction_read_only'] == 'on'
        with db.raw_connection.begin_nested(), Operations.context(MigrationContext.configure(db.raw_connection)):
            with pytest.raises(RuntimeError) as raised:
                script.module.downgrade()
            assert str(raised.value) == message
