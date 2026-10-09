"""Persist bounded retries and safe error history without backfilling history."""
from alembic import op
import sqlalchemy as sa

revision = '0012_task_errors'
down_revision = '0011_task_waits'
branch_labels = None
depends_on = None

CATEGORIES = "'temporary','authentication','permission','configuration','source','output','submission_unknown','budget','interrupted','internal'"
REASONS = "'temporary_provider_error','worker_interrupted','manual_retry'"


def upgrade():
    op.add_column('tasks', sa.Column('retry_count', sa.Integer, nullable=False, server_default=sa.text('0')))
    op.create_check_constraint('tasks_retry_count_check', 'tasks', 'retry_count >= 0 AND retry_count <= 3')
    for table in ('task_attempts', 'task_events'):
        for column in ('error_code', 'error_category', 'retry_reason'):
            op.add_column(table, sa.Column(column, sa.Text))
        op.create_check_constraint(table + '_error_category_check', table, f'error_category IN ({CATEGORIES})')
        op.create_check_constraint(table + '_retry_reason_check', table, f'retry_reason IN ({REASONS})')
    op.add_column('task_events', sa.Column('retry_count', sa.Integer))
    op.add_column('task_events', sa.Column('retry_delay_seconds', sa.Integer))
    op.create_check_constraint('task_events_retry_count_check', 'task_events', 'retry_count >= 0 AND retry_count <= 3')
    op.create_check_constraint('task_events_retry_delay_check', 'task_events', 'retry_delay_seconds IN (10,30,90)')


def downgrade():
    for name in ('task_events_retry_delay_check', 'task_events_retry_count_check'):
        op.drop_constraint(name, 'task_events', type_='check')
    op.drop_column('task_events', 'retry_delay_seconds')
    op.drop_column('task_events', 'retry_count')
    for table in ('task_events', 'task_attempts'):
        for name in ('retry_reason', 'error_category'):
            op.drop_constraint(table + '_' + name + '_check', table, type_='check')
        for column in ('retry_reason', 'error_category', 'error_code'):
            op.drop_column(table, column)
    op.drop_constraint('tasks_retry_count_check', 'tasks', type_='check')
    op.drop_column('tasks', 'retry_count')
