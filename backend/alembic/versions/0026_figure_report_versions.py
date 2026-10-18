"""Append figure configuration/projection and report collections without rewriting history."""
from alembic import op
import sqlalchemy as sa
from app.db.figure_workbench_schema import define_figure_workbench_tables
from app.db.report_collection_schema import define_report_collection_tables

revision = '0026_figure_report_versions'
down_revision = '0025_correlation_planning'
branch_labels = None
depends_on = None
OLD_TYPES = "'boxplot','explanation','word_report','parse_file','extract_dataset','prepare_dataset','review_ocr','analysis_plan','analysis_recommendation'"
NEW_TYPES = "'figure_projection','figure_workbench','figure_explanation','collection_word_report'"
OLD_WAITS = "'budget_confirmation','submission_unknown','unsupported_input','unsupported_confirmation','dataset_preparation_confirmation','ocr_review_confirmation','analysis_plan_confirmation','analysis_plan_input'"
TABLES = ('figure_configurations','figure_config_versions','figure_projection_decisions','figure_projection_results',
          'report_collections','report_collection_versions','report_collection_items','report_build_requests','collection_reports')


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '120s'")
    metadata = sa.MetaData()
    for name in ('projects','users','tasks','analysis_runs','figures','explanations'):
        sa.Table(name, metadata, sa.Column('id', sa.Text, primary_key=True))
    for table in (*define_figure_workbench_tables(metadata), *define_report_collection_tables(metadata)):
        table.create(op.get_bind())
    op.add_column('figures', sa.Column('figure_config_version_id', sa.Text, nullable=True))
    op.create_foreign_key('figures_figure_config_version_id_fkey', 'figures', 'figure_config_versions', ['figure_config_version_id'], ['id'])
    op.drop_constraint('figures_input_key', 'figures', type_='unique')
    op.create_index('figures_legacy_input_key', 'figures', ['analysis_run_id','renderer_version'], unique=True,
                    postgresql_where=sa.text('figure_config_version_id IS NULL'))
    op.create_index('figures_config_input_key', 'figures', ['figure_config_version_id','renderer_version'], unique=True,
                    postgresql_where=sa.text('figure_config_version_id IS NOT NULL'))
    op.drop_constraint('tasks_type_check', 'tasks', type_='check')
    op.create_check_constraint('tasks_type_check', 'tasks', f'task_type IN ({OLD_TYPES},{NEW_TYPES})')
    op.drop_constraint('task_waits_kind_check', 'task_waits', type_='check')
    op.create_check_constraint('task_waits_kind_check', 'task_waits', f"kind IN ({OLD_WAITS},'figure_projection_confirmation')")


def downgrade():
    # An empty isolated schema may be tested backwards. No published or pending
    # new work may be dropped; operational recovery keeps this schema in place.
    conditions = ' OR '.join(f'EXISTS (SELECT 1 FROM {name})' for name in TABLES)
    op.execute(f"DO $$ BEGIN IF {conditions} OR EXISTS (SELECT 1 FROM tasks WHERE task_type IN ({NEW_TYPES})) THEN RAISE EXCEPTION 'figure/report history requires preservation before downgrade'; END IF; END $$")
    op.drop_constraint('task_waits_kind_check', 'task_waits', type_='check')
    op.create_check_constraint('task_waits_kind_check', 'task_waits', f'kind IN ({OLD_WAITS})')
    op.drop_constraint('tasks_type_check', 'tasks', type_='check')
    op.create_check_constraint('tasks_type_check', 'tasks', f'task_type IN ({OLD_TYPES})')
    op.drop_index('figures_config_input_key', table_name='figures')
    op.drop_index('figures_legacy_input_key', table_name='figures')
    op.create_unique_constraint('figures_input_key', 'figures', ['analysis_run_id','renderer_version'])
    op.drop_constraint('figures_figure_config_version_id_fkey', 'figures', type_='foreignkey')
    op.drop_column('figures', 'figure_config_version_id')
    for name in reversed(TABLES):
        op.drop_table(name)
