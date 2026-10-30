"""Record validated recovery intent without guessing or rewriting history."""
from alembic import op
import sqlalchemy as sa

revision='0057_request_task_operation'
down_revision='0056_school_rule_suggestions'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('operational_request_events',sa.Column('task_operation',sa.Text,nullable=True))
    op.create_check_constraint('operational_task_operation_values','operational_request_events',
        "task_operation IS NULL OR (method='POST' AND route_template IS NOT NULL AND route_template='/api/v1/tasks/{task_id}/resume' AND task_operation IN ('retry','resume'))")


def downgrade():
    if op.get_bind().exec_driver_sql('SELECT EXISTS(SELECT 1 FROM operational_request_events WHERE task_operation IS NOT NULL)').scalar_one():
        raise RuntimeError('Recovery operation history exists; refusing destructive downgrade.')
    op.drop_constraint('operational_task_operation_values','operational_request_events',type_='check')
    op.drop_column('operational_request_events','task_operation')
