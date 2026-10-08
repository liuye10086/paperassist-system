"""Add the explanation result link and short-execution continuation event."""
from alembic import op
from sqlalchemy import Column, Text

revision = '0009_explanation_tasks'
down_revision = '0008_model_usage'
branch_labels = None
depends_on = None

OLD_EVENTS = "'created', 'started', 'phase_changed', 'waiting', 'succeeded', 'failed', 'requeued'"


def upgrade():
    op.add_column('tasks', Column('result_explanation_id', Text, nullable=True))
    op.create_foreign_key('tasks_result_explanation_id_fkey', 'tasks', 'explanations',
                          ['result_explanation_id'], ['id'])
    op.drop_constraint('task_events_type_check', 'task_events', type_='check')
    op.create_check_constraint('task_events_type_check', 'task_events',
                               f"event_type IN ({OLD_EVENTS}, 'deferred')")


def downgrade():
    # Existing deferred events intentionally block downgrade rather than erase history.
    op.drop_constraint('task_events_type_check', 'task_events', type_='check')
    op.create_check_constraint('task_events_type_check', 'task_events', f'event_type IN ({OLD_EVENTS})')
    op.drop_constraint('tasks_result_explanation_id_fkey', 'tasks', type_='foreignkey')
    op.drop_column('tasks', 'result_explanation_id')
