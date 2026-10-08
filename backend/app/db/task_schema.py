"""Native PostgreSQL tables for the unified task persistence contract."""

from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer,
    Table, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB


TASK_TYPES = "'boxplot', 'explanation', 'word_report'"
STATUSES = "'queued', 'running', 'waiting_input', 'waiting_confirmation', 'succeeded', 'failed'"
ATTEMPT_STATUSES = "'running', 'waiting_input', 'waiting_confirmation', 'succeeded', 'failed'"
PHASES = "'parse', 'plan', 'compute', 'search', 'interpret', 'write', 'export', 'verify'"
REASONS = ("'input_required', 'confirmation_required', 'submission_unknown', "
           "'budget_exceeded', 'execution_failed', 'retry_requested', "
           "'input_provided', 'confirmation_received'")


def define_task_tables(metadata):
    tasks = Table(
        'tasks', metadata,
        Column('id', Text, primary_key=True),
        Column('project_id', Text, ForeignKey('projects.id'), nullable=False),
        Column('user_id', Text, ForeignKey('users.id'), nullable=False),
        Column('task_type', Text, nullable=False),
        Column('idempotency_key', Text, nullable=False),
        Column('input_digest', Text, nullable=False),
        Column('input_snapshot', JSONB, nullable=False),
        Column('workflow_version', Text, nullable=False),
        Column('status', Text, nullable=False),
        Column('phase', Text, nullable=False),
        Column('revision', Integer, nullable=False),
        Column('current_attempt', Integer, nullable=False),
        Column('reason_code', Text),
        Column('created_at', DateTime(timezone=True), nullable=False),
        Column('updated_at', DateTime(timezone=True), nullable=False),
        Column('result_report_id', Text, ForeignKey('reports.id', name='tasks_result_report_id_fkey')),
        Column('error_code', Text),
        Column('result_explanation_id', Text, ForeignKey('explanations.id', name='tasks_result_explanation_id_fkey')),
        Column('result_figure_id', Text, ForeignKey('figures.id', name='tasks_result_figure_id_fkey')),
        Column('figure_candidate', JSONB(none_as_null=True)),
        UniqueConstraint('user_id', 'project_id', 'task_type', 'idempotency_key', name='tasks_idempotency_key'),
        CheckConstraint(f'task_type IN ({TASK_TYPES})', name='tasks_type_check'),
        CheckConstraint(f'status IN ({STATUSES})', name='tasks_status_check'),
        CheckConstraint(f'phase IN ({PHASES})', name='tasks_phase_check'),
        CheckConstraint(f'reason_code IN ({REASONS})', name='tasks_reason_check'),
        CheckConstraint('revision >= 1', name='tasks_revision_check'),
        CheckConstraint('current_attempt >= 0', name='tasks_current_attempt_check'),
        CheckConstraint('length(idempotency_key) >= 1 AND length(idempotency_key) <= 128', name='tasks_key_length_check'),
        CheckConstraint("input_digest ~ '^[0-9a-f]{64}$'", name='tasks_digest_check'),
        CheckConstraint('length(workflow_version) >= 1', name='tasks_workflow_version_check'),
        CheckConstraint("jsonb_typeof(input_snapshot) = 'object'", name='tasks_snapshot_object_check'),
        CheckConstraint("figure_candidate IS NULL OR jsonb_typeof(figure_candidate) = 'object'",
                        name='tasks_figure_candidate_check'),
        CheckConstraint('updated_at >= created_at', name='tasks_time_order_check'),
    )
    Index('tasks_project_created', tasks.c.project_id, tasks.c.created_at.desc(), tasks.c.id)
    Index('tasks_user_status', tasks.c.user_id, tasks.c.status)

    attempts = Table(
        'task_attempts', metadata,
        Column('id', Text, primary_key=True),
        Column('task_id', Text, ForeignKey('tasks.id'), nullable=False),
        Column('attempt_no', Integer, nullable=False),
        Column('status', Text, nullable=False),
        Column('started_at', DateTime(timezone=True), nullable=False),
        Column('finished_at', DateTime(timezone=True)),
        Column('reason_code', Text),
        Column('lease_owner', Text),
        Column('lease_expires_at', DateTime(timezone=True)),
        Column('heartbeat_at', DateTime(timezone=True)),
        UniqueConstraint('task_id', 'attempt_no', name='task_attempts_number_key'),
        CheckConstraint('attempt_no >= 1', name='task_attempts_number_check'),
        CheckConstraint(f'status IN ({ATTEMPT_STATUSES})', name='task_attempts_status_check'),
        CheckConstraint(f'reason_code IN ({REASONS})', name='task_attempts_reason_check'),
        CheckConstraint('finished_at >= started_at', name='task_attempts_time_order_check'),
        CheckConstraint("(status = 'running' AND finished_at IS NULL) OR (status <> 'running' AND finished_at IS NOT NULL)", name='task_attempts_finish_check'),
    )

    Index('task_attempts_expiring', attempts.c.status, attempts.c.lease_expires_at)

    events = Table(
        'task_events', metadata,
        Column('task_id', Text, ForeignKey('tasks.id'), primary_key=True),
        Column('seq', BigInteger, primary_key=True, autoincrement=False),
        Column('task_revision', Integer, nullable=False),
        Column('event_type', Text, nullable=False),
        Column('status', Text, nullable=False),
        Column('phase', Text, nullable=False),
        Column('reason_code', Text),
        Column('created_at', DateTime(timezone=True), nullable=False),
        CheckConstraint('seq = task_revision AND task_revision >= 1', name='task_events_revision_check'),
        CheckConstraint("event_type IN ('created', 'started', 'phase_changed', 'waiting', 'succeeded', 'failed', 'requeued', 'deferred')", name='task_events_type_check'),
        CheckConstraint(f'status IN ({STATUSES})', name='task_events_status_check'),
        CheckConstraint(f'phase IN ({PHASES})', name='task_events_phase_check'),
        CheckConstraint(f'reason_code IN ({REASONS})', name='task_events_reason_check'),
    )

    outbox = Table(
        'task_outbox', metadata,
        Column('id', Text, primary_key=True),
        Column('task_id', Text, ForeignKey('tasks.id'), nullable=False),
        Column('task_revision', Integer, nullable=False),
        Column('event_type', Text, nullable=False),
        Column('available_at', DateTime(timezone=True), nullable=False),
        Column('created_at', DateTime(timezone=True), nullable=False),
        Column('published_at', DateTime(timezone=True)),
        Column('publish_attempts', Integer, nullable=False),
        UniqueConstraint('task_id', 'task_revision', 'event_type', name='task_outbox_event_key'),
        CheckConstraint('task_revision >= 1', name='task_outbox_revision_check'),
        CheckConstraint("event_type = 'task_ready'", name='task_outbox_type_check'),
        CheckConstraint('publish_attempts >= 0', name='task_outbox_attempts_check'),
    )
    Index('task_outbox_pending', outbox.c.published_at, outbox.c.available_at, outbox.c.id)
    return tasks, attempts, events, outbox
