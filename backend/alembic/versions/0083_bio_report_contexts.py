"""Native fixed report contexts share the existing research report pipeline."""
import hashlib

from alembic import op
import sqlalchemy as sa

from app.db.bio_report_context_schema import TABLE_NAMES
from app.db.schema import metadata

revision = '0083_bio_report_contexts'
down_revision = '0082_reader_report_narratives'
branch_labels = depends_on = None

# Historical CHECK names hash this exact ordered collection. Future application
# source kinds must not change an already released 0082/0083 transition.
SOURCE_TARGETS_0082 = {
    'analysis_run': ('analysis_run_id', 'analysis_runs'),
    'bio_processed_dataset_version': ('processed_version_id', 'bio_processed_dataset_versions'),
    'bio_analysis_artifact': ('analysis_artifact_id', 'bio_analysis_artifacts'),
    'bio_figure_version': ('bio_figure_version_id', 'bio_figure_versions'),
    'original_file': ('file_id', 'files'),
    'external_evidence_version': ('external_evidence_version_id', 'external_evidence_versions'),
    'research_finding_version': ('source_finding_version_id', 'research_finding_versions'),
    'research_figure_version': ('research_figure_version_id', 'research_figure_versions'),
    'research_report_version': ('source_report_version_id', 'research_report_versions'),
    'bio_insight_result_version': ('bio_insight_result_version_id', 'bio_insight_result_versions'),
    'bio_insight_result_member': ('bio_insight_result_member_id', 'bio_insight_result_members'),
}
SOURCE_TARGETS_0083 = SOURCE_TARGETS_0082 | {'bio_report_context': ('bio_report_context_id', 'bio_report_context_versions')}


def check_clause(targets):
    columns = ','.join(column for column, _ in targets.values())
    choices = ' OR '.join(f"(source_kind='{kind}' AND {column} IS NOT NULL AND source_id={column})" for kind, (column, _) in targets.items())
    expression = f'num_nonnulls({columns})=1 AND ({choices})'
    return 'b03_ck_' + hashlib.sha256(expression.encode()).hexdigest()[:16], expression


def change_binding(table, adding):
    drop, _ = check_clause(SOURCE_TARGETS_0082 if adding else SOURCE_TARGETS_0083)
    name, expression = check_clause(SOURCE_TARGETS_0083 if adding else SOURCE_TARGETS_0082)
    op.drop_constraint(drop, table, type_='check')
    if adding:
        op.add_column(table, sa.Column('bio_report_context_id', sa.Text))
        op.create_foreign_key('brc_' + table + '_fk', table, 'bio_report_context_versions', ['bio_report_context_id', 'project_id'], ['id', 'project_id'])
        op.create_index(table + '_bio_report_context_id', table, ['bio_report_context_id'])
    else:
        op.drop_constraint('brc_' + table + '_fk', table, type_='foreignkey')
        op.drop_index(table + '_bio_report_context_id', table_name=table)
        op.drop_column(table, 'bio_report_context_id')
    op.create_check_constraint(name, table, expression)


def upgrade():
    for name in TABLE_NAMES:
        metadata.tables[name].create(op.get_bind())
    for table in ('research_source_bindings', 'manuscript_research_sources'):
        change_binding(table, True)
    op.execute("""CREATE FUNCTION bio_report_context_seal() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Saved native report contexts are immutable'; END $$""")
    for table in TABLE_NAMES:
        op.execute(f'CREATE TRIGGER {table}_seal BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION bio_report_context_seal()')


def downgrade():
    if op.get_bind().exec_driver_sql('SELECT EXISTS (SELECT 1 FROM bio_report_context_versions)').scalar_one():
        raise RuntimeError('Saved native report contexts exist; downgrade would erase fixed selections.')
    for table in ('research_source_bindings', 'manuscript_research_sources'):
        change_binding(table, False)
    for name in reversed(TABLE_NAMES):
        op.drop_table(name)
    op.execute('DROP FUNCTION bio_report_context_seal()')
