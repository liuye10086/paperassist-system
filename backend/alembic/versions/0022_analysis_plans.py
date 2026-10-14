"""Add durable analysis-plan decisions and confirmed plans."""
from alembic import op
import sqlalchemy as sa

from app.db.analysis_plan_schema import define_analysis_plan_tables

revision = '0022_analysis_plans'
down_revision = '0021_ocr_review'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('tasks_type_check', 'tasks', type_='check')
    op.create_check_constraint('tasks_type_check', 'tasks',
        "task_type IN ('boxplot','explanation','word_report','parse_file','extract_dataset','prepare_dataset','review_ocr','analysis_plan')")
    op.drop_constraint('task_waits_kind_check', 'task_waits', type_='check')
    op.create_check_constraint('task_waits_kind_check', 'task_waits',
        "kind IN ('budget_confirmation','submission_unknown','unsupported_input','unsupported_confirmation','dataset_preparation_confirmation','ocr_review_confirmation','analysis_plan_confirmation')")
    op.drop_constraint('task_checkpoints_node_check', 'task_checkpoints', type_='check')
    op.create_check_constraint('task_checkpoints_node_check', 'task_checkpoints',
        "node IN ('prepare_preview','check','await_confirmation','approve','revise','publish','done')")
    op.drop_constraint('task_checkpoints_next_check', 'task_checkpoints', type_='check')
    op.create_check_constraint('task_checkpoints_next_check', 'task_checkpoints',
        "next_node IN ('prepare_preview','check','await_confirmation','publish','done')")
    metadata = sa.MetaData()
    for name in ('tasks', 'users', 'projects', 'files'):
        sa.Table(name, metadata, sa.Column('id', sa.Text, primary_key=True))
    for name in ('task_waits', 'task_checkpoints'):
        sa.Table(name, metadata, sa.Column('id', sa.Text, primary_key=True), sa.Column('task_id', sa.Text))
    for table in define_analysis_plan_tables(metadata):
        table.create(op.get_bind())


def downgrade():
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM tasks WHERE task_type='analysis_plan') OR EXISTS (SELECT 1 FROM analysis_plan_decisions) OR EXISTS (SELECT 1 FROM confirmed_analysis_plans) THEN RAISE EXCEPTION 'analysis plan history requires preservation before downgrade'; END IF; END $$")
    op.drop_table('confirmed_analysis_plans')
    op.drop_table('analysis_plan_decisions')
    op.drop_constraint('task_checkpoints_next_check', 'task_checkpoints', type_='check')
    op.create_check_constraint('task_checkpoints_next_check', 'task_checkpoints',
        "next_node IN ('prepare_preview','await_confirmation','publish','done')")
    op.drop_constraint('task_checkpoints_node_check', 'task_checkpoints', type_='check')
    op.create_check_constraint('task_checkpoints_node_check', 'task_checkpoints',
        "node IN ('prepare_preview','await_confirmation','approve','revise','publish','done')")
    op.drop_constraint('task_waits_kind_check', 'task_waits', type_='check')
    op.create_check_constraint('task_waits_kind_check', 'task_waits',
        "kind IN ('budget_confirmation','submission_unknown','unsupported_input','unsupported_confirmation','dataset_preparation_confirmation','ocr_review_confirmation')")
    op.drop_constraint('tasks_type_check', 'tasks', type_='check')
    op.create_check_constraint('tasks_type_check', 'tasks',
        "task_type IN ('boxplot','explanation','word_report','parse_file','extract_dataset','prepare_dataset','review_ocr')")
