"""Add statistics reader report contexts without rewriting prior reports."""
import hashlib

from alembic import op
import sqlalchemy as sa

from app.db.schema import metadata
from app.db.statistics_report_context_schema import DEPENDENCY_KEYS, TABLE_NAMES

revision = '0084_statistics_report_context'
down_revision = '0083_bio_report_contexts'
branch_labels = depends_on = None

SOURCE_COLUMNS_0083 = (
    ('analysis_run', 'analysis_run_id'), ('bio_processed_dataset_version', 'processed_version_id'),
    ('bio_analysis_artifact', 'analysis_artifact_id'), ('bio_figure_version', 'bio_figure_version_id'),
    ('original_file', 'file_id'), ('external_evidence_version', 'external_evidence_version_id'),
    ('research_finding_version', 'source_finding_version_id'), ('research_figure_version', 'research_figure_version_id'),
    ('research_report_version', 'source_report_version_id'), ('bio_insight_result_version', 'bio_insight_result_version_id'),
    ('bio_insight_result_member', 'bio_insight_result_member_id'), ('bio_report_context', 'bio_report_context_id'),
)
SOURCE_COLUMNS_0084 = (*SOURCE_COLUMNS_0083, ('statistics_report_context', 'statistics_report_context_id'))


def check_clause(targets):
    columns = ','.join(column for _, column in targets)
    choices = ' OR '.join(f"(source_kind='{kind}' AND {column} IS NOT NULL AND source_id={column})"
                          for kind, column in targets)
    clause = f'num_nonnulls({columns})=1 AND ({choices})'
    return 'b03_ck_' + hashlib.sha256(clause.encode()).hexdigest()[:16], clause


def change_binding(table, *, adding):
    before, after = (SOURCE_COLUMNS_0083, SOURCE_COLUMNS_0084) if adding else (SOURCE_COLUMNS_0084, SOURCE_COLUMNS_0083)
    op.drop_constraint(check_clause(before)[0], table, type_='check')
    column = 'statistics_report_context_id'
    fk = 'src_' + table + '_fk'
    index = 'src_' + table + '_context'
    if adding:
        op.add_column(table, sa.Column(column, sa.Text))
        op.create_foreign_key(fk, table, TABLE_NAMES[0], [column, 'project_id', 'user_id'], ['id', 'project_id', 'user_id'])
        op.create_index(index, table, [column])
    else:
        op.drop_constraint(fk, table, type_='foreignkey')
        op.drop_index(index, table_name=table)
        op.drop_column(table, column)
    name, clause = check_clause(after)
    op.create_check_constraint(name, table, clause)


def upgrade():
    for table, key, columns in DEPENDENCY_KEYS:
        op.create_unique_constraint(key, table, list(columns))
    for table in TABLE_NAMES:
        metadata.tables[table].create(op.get_bind())
    for table in ('research_source_bindings', 'manuscript_research_sources'):
        change_binding(table, adding=True)
    op.execute("""CREATE FUNCTION statistics_report_context_seal() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Saved statistics report contexts are immutable'; END $$""")
    for table in TABLE_NAMES:
        op.execute(f'CREATE TRIGGER {table}_seal BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION statistics_report_context_seal()')


def downgrade():
    if op.get_bind().exec_driver_sql(f'SELECT EXISTS (SELECT 1 FROM {TABLE_NAMES[0]})').scalar_one():
        raise RuntimeError('Saved statistics report contexts exist; downgrade would erase fixed selections.')
    for table in ('research_source_bindings', 'manuscript_research_sources'):
        change_binding(table, adding=False)
    for table in reversed(TABLE_NAMES):
        op.drop_table(table)
    op.execute('DROP FUNCTION statistics_report_context_seal()')
    for table, key, _ in reversed(DEPENDENCY_KEYS):
        op.drop_constraint(key, table, type_='unique')
