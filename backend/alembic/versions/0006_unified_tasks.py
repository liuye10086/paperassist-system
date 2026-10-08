"""Add unified task tables without rewriting existing tables or values.

Definitions are frozen in this revision; do not import application metadata.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0006_unified_tasks'
down_revision = '0005_ownership_indexes'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'tasks',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('project_id', sa.Text(), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('user_id', sa.Text(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('task_type', sa.Text(), nullable=False),
        sa.Column('idempotency_key', sa.Text(), nullable=False),
        sa.Column('input_digest', sa.Text(), nullable=False),
        sa.Column('input_snapshot', postgresql.JSONB(), nullable=False),
        sa.Column('workflow_version', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('phase', sa.Text(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('current_attempt', sa.Integer(), nullable=False),
        sa.Column('reason_code', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('user_id', 'project_id', 'task_type', 'idempotency_key', name='tasks_idempotency_key'),
        sa.CheckConstraint("task_type IN ('boxplot', 'explanation', 'word_report')", name='tasks_type_check'),
        sa.CheckConstraint("status IN ('queued', 'running', 'waiting_input', 'waiting_confirmation', 'succeeded', 'failed')", name='tasks_status_check'),
        sa.CheckConstraint("phase IN ('parse', 'plan', 'compute', 'search', 'interpret', 'write', 'export', 'verify')", name='tasks_phase_check'),
        sa.CheckConstraint("reason_code IN ('input_required', 'confirmation_required', 'submission_unknown', 'budget_exceeded', 'execution_failed', 'retry_requested', 'input_provided', 'confirmation_received')", name='tasks_reason_check'),
        sa.CheckConstraint('revision >= 1', name='tasks_revision_check'),
        sa.CheckConstraint('current_attempt >= 0', name='tasks_current_attempt_check'),
        sa.CheckConstraint('length(idempotency_key) >= 1 AND length(idempotency_key) <= 128', name='tasks_key_length_check'),
        sa.CheckConstraint("input_digest ~ '^[0-9a-f]{64}$'", name='tasks_digest_check'),
        sa.CheckConstraint('length(workflow_version) >= 1', name='tasks_workflow_version_check'),
        sa.CheckConstraint("jsonb_typeof(input_snapshot) = 'object'", name='tasks_snapshot_object_check'),
        sa.CheckConstraint('updated_at >= created_at', name='tasks_time_order_check'),
    )
    op.create_index('tasks_project_created', 'tasks', ['project_id', sa.text('created_at DESC'), 'id'])
    op.create_index('tasks_user_status', 'tasks', ['user_id', 'status'])
    op.create_table(
        'task_attempts',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('task_id', sa.Text(), sa.ForeignKey('tasks.id'), nullable=False),
        sa.Column('attempt_no', sa.Integer(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.Column('reason_code', sa.Text()),
        sa.Column('lease_owner', sa.Text()),
        sa.Column('lease_expires_at', sa.DateTime(timezone=True)),
        sa.Column('heartbeat_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('task_id', 'attempt_no', name='task_attempts_number_key'),
        sa.CheckConstraint('attempt_no >= 1', name='task_attempts_number_check'),
        sa.CheckConstraint("status IN ('running', 'waiting_input', 'waiting_confirmation', 'succeeded', 'failed')", name='task_attempts_status_check'),
        sa.CheckConstraint("reason_code IN ('input_required', 'confirmation_required', 'submission_unknown', 'budget_exceeded', 'execution_failed', 'retry_requested', 'input_provided', 'confirmation_received')", name='task_attempts_reason_check'),
        sa.CheckConstraint('finished_at >= started_at', name='task_attempts_time_order_check'),
        sa.CheckConstraint("(status = 'running' AND finished_at IS NULL) OR (status <> 'running' AND finished_at IS NOT NULL)", name='task_attempts_finish_check'),
    )
    op.create_table(
        'task_events',
        sa.Column('task_id', sa.Text(), sa.ForeignKey('tasks.id'), primary_key=True),
        sa.Column('seq', sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column('task_revision', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('phase', sa.Text(), nullable=False),
        sa.Column('reason_code', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('seq = task_revision AND task_revision >= 1', name='task_events_revision_check'),
        sa.CheckConstraint("event_type IN ('created', 'started', 'phase_changed', 'waiting', 'succeeded', 'failed', 'requeued')", name='task_events_type_check'),
        sa.CheckConstraint("status IN ('queued', 'running', 'waiting_input', 'waiting_confirmation', 'succeeded', 'failed')", name='task_events_status_check'),
        sa.CheckConstraint("phase IN ('parse', 'plan', 'compute', 'search', 'interpret', 'write', 'export', 'verify')", name='task_events_phase_check'),
        sa.CheckConstraint("reason_code IN ('input_required', 'confirmation_required', 'submission_unknown', 'budget_exceeded', 'execution_failed', 'retry_requested', 'input_provided', 'confirmation_received')", name='task_events_reason_check'),
    )
    op.create_table(
        'task_outbox',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('task_id', sa.Text(), sa.ForeignKey('tasks.id'), nullable=False),
        sa.Column('task_revision', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.Text(), nullable=False),
        sa.Column('available_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True)),
        sa.Column('publish_attempts', sa.Integer(), nullable=False),
        sa.UniqueConstraint('task_id', 'task_revision', 'event_type', name='task_outbox_event_key'),
        sa.CheckConstraint('task_revision >= 1', name='task_outbox_revision_check'),
        sa.CheckConstraint("event_type = 'task_ready'", name='task_outbox_type_check'),
        sa.CheckConstraint('publish_attempts >= 0', name='task_outbox_attempts_check'),
    )
    op.create_index('task_outbox_pending', 'task_outbox', ['published_at', 'available_at', 'id'])


def downgrade():
    op.drop_index('task_outbox_pending', table_name='task_outbox')
    op.drop_table('task_outbox')
    op.drop_table('task_events')
    op.drop_table('task_attempts')
    op.drop_index('tasks_user_status', table_name='tasks')
    op.drop_index('tasks_project_created', table_name='tasks')
    op.drop_table('tasks')
