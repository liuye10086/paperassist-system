"""Queue free statistics and preserve old result JSON and nullable legacy receipts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0029_statistics_execution'
down_revision = '0028_research_materials'
branch_labels = None
depends_on = None
OLD_TYPES = "'boxplot', 'explanation', 'word_report', 'parse_file', 'extract_dataset', 'prepare_dataset', 'review_ocr', 'analysis_plan', 'analysis_recommendation', 'figure_projection', 'figure_workbench', 'figure_explanation', 'collection_word_report'"
OLD_REASONS = "'input_required', 'confirmation_required', 'submission_unknown', 'budget_exceeded', 'execution_failed', 'retry_requested', 'input_provided', 'confirmation_received'"
OLD_WAIT_KINDS = "'budget_confirmation','submission_unknown','unsupported_input','unsupported_confirmation','dataset_preparation_confirmation','ocr_review_confirmation','analysis_plan_confirmation','analysis_plan_input','figure_projection_confirmation'"
RECEIPT_CHECK = "execution_receipt IS NULL OR ((jsonb_typeof(execution_receipt)='object' AND execution_receipt->'schema_version'='1'::jsonb AND jsonb_typeof(execution_receipt->'nodes')='array' AND execution_receipt->>'status' IN ('succeeded','failed')) IS TRUE)"


def upgrade():
    for table in ('tasks','task_attempts','task_events'):
        op.drop_constraint(table+'_reason_check',table,type_='check')
        op.create_check_constraint(table+'_reason_check',table,"reason_code IN ("+OLD_REASONS+", 'observation_expired')")
    op.drop_constraint('task_waits_kind_check','task_waits',type_='check')
    op.create_check_constraint('task_waits_kind_check','task_waits',"kind IN ("+OLD_WAIT_KINDS+",'remote_observation')")
    op.drop_constraint('tasks_type_check', 'tasks', type_='check')
    op.create_check_constraint('tasks_type_check', 'tasks', "task_type IN (" + OLD_TYPES + ", 'statistics_compute')")
    op.add_column('tasks', sa.Column('result_analysis_run_id', sa.Text, nullable=True))
    op.create_foreign_key('tasks_result_analysis_run_id_fkey', 'tasks', 'analysis_runs', ['result_analysis_run_id'], ['id'])
    op.create_index('tasks_result_analysis_run', 'tasks', ['result_analysis_run_id'])
    op.add_column('tasks', sa.Column('execution_receipt', JSONB(none_as_null=True), nullable=True))
    op.create_check_constraint('tasks_execution_receipt_check', 'tasks', RECEIPT_CHECK)


def downgrade():
    if op.get_bind().exec_driver_sql("SELECT EXISTS(SELECT 1 FROM tasks WHERE task_type='statistics_compute' OR execution_receipt IS NOT NULL OR result_analysis_run_id IS NOT NULL OR reason_code='observation_expired') OR EXISTS(SELECT 1 FROM task_waits WHERE kind='remote_observation') OR EXISTS(SELECT 1 FROM task_events WHERE reason_code='observation_expired') OR EXISTS(SELECT 1 FROM task_attempts WHERE reason_code='observation_expired')").scalar_one():
        raise RuntimeError('Cannot remove statistics execution history')
    for table in ('tasks','task_attempts','task_events'):
        op.drop_constraint(table+'_reason_check',table,type_='check')
        op.create_check_constraint(table+'_reason_check',table,'reason_code IN ('+OLD_REASONS+')')
    op.drop_constraint('task_waits_kind_check','task_waits',type_='check')
    op.create_check_constraint('task_waits_kind_check','task_waits','kind IN ('+OLD_WAIT_KINDS+')')
    op.drop_constraint('tasks_execution_receipt_check', 'tasks', type_='check')
    op.drop_column('tasks', 'execution_receipt')
    op.drop_index('tasks_result_analysis_run', table_name='tasks')
    op.drop_constraint('tasks_result_analysis_run_id_fkey', 'tasks', type_='foreignkey')
    op.drop_column('tasks', 'result_analysis_run_id')
    op.drop_constraint('tasks_type_check', 'tasks', type_='check')
    op.create_check_constraint('tasks_type_check', 'tasks', 'task_type IN (' + OLD_TYPES + ')')
