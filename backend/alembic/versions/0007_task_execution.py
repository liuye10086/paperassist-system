"""Link Word task results and index expiring worker leases."""
from alembic import op
import sqlalchemy as sa

revision = '0007_task_execution'
down_revision = '0006_unified_tasks'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tasks', sa.Column('result_report_id', sa.Text(), nullable=True))
    op.add_column('tasks', sa.Column('error_code', sa.Text(), nullable=True))
    op.create_foreign_key('tasks_result_report_id_fkey', 'tasks', 'reports', ['result_report_id'], ['id'])
    op.create_index('task_attempts_expiring', 'task_attempts', ['status', 'lease_expires_at'])


def downgrade():
    op.drop_index('task_attempts_expiring', table_name='task_attempts')
    op.drop_constraint('tasks_result_report_id_fkey', 'tasks', type_='foreignkey')
    op.drop_column('tasks', 'error_code')
    op.drop_column('tasks', 'result_report_id')
