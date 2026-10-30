"""Native PostgreSQL tables for the unified task persistence contract."""

from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer,
    Table, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB


TASK_TYPES = "'boxplot', 'explanation', 'word_report', 'parse_file', 'extract_dataset', 'prepare_dataset', 'review_ocr', 'analysis_plan', 'analysis_recommendation', 'figure_projection', 'figure_workbench', 'figure_explanation', 'collection_word_report', 'statistics_compute', 'literature_search', 'literature_assistance', 'manuscript_draft', 'manuscript_docx', 'pdf_export', 'manuscript_writing', 'layout_docx', 'school_template_parse', 'school_rule_suggestion', 'journal_recommendation', 'journal_format_check', 'journal_adaptation', 'review_round_plan', 'review_revision', 'review_document_export'"
STATUSES = "'queued', 'running', 'waiting_input', 'waiting_confirmation', 'succeeded', 'failed'"
ATTEMPT_STATUSES = "'running', 'waiting_input', 'waiting_confirmation', 'succeeded', 'failed'"
PHASES = "'parse', 'plan', 'compute', 'search', 'interpret', 'write', 'export', 'verify'"
REASONS = ("'input_required', 'confirmation_required', 'submission_unknown', "
           "'budget_exceeded', 'execution_failed', 'retry_requested', "
           "'input_provided', 'confirmation_received', 'observation_expired'")


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
        Column('result_analysis_run_id', Text, ForeignKey('analysis_runs.id', name='tasks_result_analysis_run_id_fkey')),
        Column('execution_receipt', JSONB(none_as_null=True)),
        CheckConstraint("execution_receipt IS NULL OR ((jsonb_typeof(execution_receipt)='object' AND execution_receipt->'schema_version'='1'::jsonb AND jsonb_typeof(execution_receipt->'nodes')='array' AND execution_receipt->>'status' IN ('succeeded','failed')) IS TRUE)", name='tasks_execution_receipt_check'),
        Column('result_report_id', Text, ForeignKey('reports.id', name='tasks_result_report_id_fkey')),
        Column('error_code', Text),
        Column('result_explanation_id', Text, ForeignKey('explanations.id', name='tasks_result_explanation_id_fkey')),
        Column('result_figure_id', Text, ForeignKey('figures.id', name='tasks_result_figure_id_fkey')),
        Column('figure_candidate', JSONB(none_as_null=True)),
        CheckConstraint("verification_failure IS NULL OR jsonb_typeof(verification_failure)='object'", name='tasks_verification_failure_check'),
        UniqueConstraint('id','project_id','user_id', name='tasks_scope_key'),
        UniqueConstraint('user_id', 'project_id', 'task_type', 'idempotency_key', name='tasks_idempotency_key'),
        CheckConstraint(f'task_type IN ({TASK_TYPES})', name='tasks_type_check'),
        CheckConstraint("task_type<>'journal_recommendation' OR ((input_snapshot->>'kind'='journal_recommendation' AND input_snapshot->>'workflow_version'='journal_recommendation_v1' AND jsonb_typeof(input_snapshot->'profiles')='array' AND jsonb_typeof(input_snapshot->'research')='object' AND input_snapshot->'real_model_calls'='false'::jsonb AND input_snapshot->'real_network_calls'='false'::jsonb) IS TRUE)",name='tasks_journal_snapshot_check'),
        CheckConstraint("task_type<>'journal_format_check' OR ((input_snapshot->>'kind'='journal_format_check' AND input_snapshot->>'workflow_version'='journal_format_check_v1' AND jsonb_typeof(input_snapshot->'target')='object' AND jsonb_typeof(input_snapshot->'manuscript')='object' AND input_snapshot->>'check_version'='1' AND input_snapshot->'real_model_calls'='false'::jsonb AND input_snapshot->'real_network_calls'='false'::jsonb) IS TRUE)",name='tasks_journal_format_snapshot_check'),
        CheckConstraint("task_type<>'journal_adaptation' OR ((input_snapshot->>'kind'='journal_adaptation' AND input_snapshot->>'workflow_version'='journal_adaptation_v1' AND jsonb_typeof(input_snapshot->'manuscript')='object' AND jsonb_typeof(input_snapshot->'selected_action_ids')='array' AND input_snapshot->'real_model_calls'='false'::jsonb AND input_snapshot->'real_network_calls'='false'::jsonb) IS TRUE)",name='tasks_journal_adaptation_snapshot_check'),
        CheckConstraint("task_type<>'review_round_plan' OR ((workflow_version='review_round_plan_v1' AND input_snapshot->>'kind'='review_round_plan' AND input_snapshot->>'workflow_version'='review_round_plan_v1' AND jsonb_typeof(input_snapshot->'manuscript')='object' AND jsonb_typeof(input_snapshot->'sources')='array' AND input_snapshot->'real_model_calls'='false'::jsonb AND input_snapshot->'real_network_calls'='false'::jsonb) IS TRUE)",name='tasks_review_round_snapshot_check'),
        CheckConstraint("task_type<>'review_revision' OR ((workflow_version='review_revision_v1' AND input_snapshot->>'kind'='review_revision' AND input_snapshot->'real_model_calls'='false'::jsonb AND input_snapshot->'real_network_calls'='false'::jsonb) IS TRUE)",name='tasks_review_revision_snapshot_check'),
        CheckConstraint("task_type<>'review_document_export' OR ((workflow_version='review_document_export_v1' AND input_snapshot->>'kind'='review_document_export' AND input_snapshot->'real_model_calls'='false'::jsonb AND input_snapshot->'real_network_calls'='false'::jsonb) IS TRUE)",name='tasks_review_document_export_snapshot_check'),
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
    Index('tasks_result_analysis_run', tasks.c.result_analysis_run_id)
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
