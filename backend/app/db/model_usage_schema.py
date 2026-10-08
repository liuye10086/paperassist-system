"""Persist model observations and cumulative budget admission separately from billing."""
from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer,
    Table, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB


CALL_STATUSES = "'reserved', 'submitting', 'submitted', 'submission_unknown', 'completed', 'failed', 'released'"
USAGE_STATUSES = "'pending', 'estimated'"


def define_model_usage_tables(metadata):
    budgets = Table(
        'model_budgets', metadata,
        Column('id', Text, primary_key=True),
        Column('user_id', Text, ForeignKey('users.id'), nullable=False),
        Column('scope_type', Text, nullable=False),
        Column('scope_key', Text, nullable=False),
        Column('project_id', Text, ForeignKey('projects.id')),
        Column('task_id', Text, ForeignKey('tasks.id')),
        Column('limit_micro_usd', BigInteger, nullable=False),
        Column('revision', Integer, nullable=False),
        Column('created_at', DateTime(timezone=True), nullable=False),
        Column('updated_at', DateTime(timezone=True), nullable=False),
        UniqueConstraint('scope_type', 'scope_key', name='model_budgets_scope_key'),
        CheckConstraint("(scope_type = 'user' AND scope_key = user_id AND project_id IS NULL AND task_id IS NULL) OR "
                        "(scope_type = 'project' AND project_id IS NOT NULL AND scope_key = project_id AND task_id IS NULL) OR "
                        "(scope_type = 'task' AND project_id IS NOT NULL AND task_id IS NOT NULL AND scope_key = task_id)",
                        name='model_budgets_scope_check'),
        CheckConstraint("limit_micro_usd >= 0 AND limit_micro_usd <= '1000000000000'::bigint", name='model_budgets_limit_check'),
        CheckConstraint('revision >= 1', name='model_budgets_revision_check'),
        CheckConstraint('updated_at >= created_at', name='model_budgets_time_check'),
    )
    Index('model_budgets_owner', budgets.c.user_id, budgets.c.scope_type)

    calls = Table(
        'model_calls', metadata,
        Column('id', Text, primary_key=True),
        Column('user_id', Text, ForeignKey('users.id'), nullable=False),
        Column('project_id', Text, ForeignKey('projects.id'), nullable=False),
        Column('task_id', Text, ForeignKey('tasks.id'), nullable=False),
        Column('attempt_no', Integer, nullable=False),
        Column('call_key', Text, nullable=False),
        Column('input_digest', Text, nullable=False),
        Column('provider', Text, nullable=False),
        Column('model', Text, nullable=False),
        Column('policy_snapshot', JSONB, nullable=False),
        Column('price_snapshot', JSONB, nullable=False),
        Column('status', Text, nullable=False),
        Column('provider_status', Text),
        Column('provider_request_id', Text),
        Column('provider_response_id', Text),
        Column('error_code', Text),
        Column('estimated_cost_micro_usd', BigInteger),
        Column('usage_status', Text, nullable=False),
        Column('created_at', DateTime(timezone=True), nullable=False),
        Column('updated_at', DateTime(timezone=True), nullable=False),
        UniqueConstraint('task_id', 'call_key', name='model_calls_task_key'),
        Column('provider_state', JSONB(none_as_null=True)),
        UniqueConstraint('provider', 'provider_response_id', name='model_calls_response_key'),
        CheckConstraint('attempt_no >= 1', name='model_calls_attempt_check'),
        CheckConstraint('length(call_key) >= 1 AND length(call_key) <= 128', name='model_calls_key_check'),
        CheckConstraint("input_digest ~ '^[0-9a-f]{64}$'", name='model_calls_digest_check'),
        CheckConstraint("provider = 'openai'", name='model_calls_provider_check'),
        CheckConstraint('length(model) >= 1 AND length(model) <= 200', name='model_calls_model_check'),
        CheckConstraint("jsonb_typeof(policy_snapshot) = 'object' AND jsonb_typeof(price_snapshot) = 'object'",
                        name='model_calls_snapshot_check'),
        CheckConstraint(f'status IN ({CALL_STATUSES})', name='model_calls_status_check'),
        CheckConstraint(f'usage_status IN ({USAGE_STATUSES})', name='model_calls_usage_check'),
        CheckConstraint('estimated_cost_micro_usd >= 0', name='model_calls_cost_check'),
        CheckConstraint('updated_at >= created_at', name='model_calls_time_check'),
        CheckConstraint("provider_state IS NULL OR jsonb_typeof(provider_state) = 'object'",
                        name='model_calls_provider_state_check'),
    )
    Index('model_calls_project_created', calls.c.project_id, calls.c.created_at.desc(), calls.c.id)
    Index('model_calls_owner_status', calls.c.user_id, calls.c.status)

    usage = Table(
        'usage_events', metadata,
        Column('id', Text, primary_key=True),
        Column('call_id', Text, ForeignKey('model_calls.id'), nullable=False),
        Column('event_key', Text, nullable=False),
        Column('event_digest', Text, nullable=False),
        Column('event_type', Text, nullable=False),
        Column('provider_usage', JSONB(none_as_null=True)),
        Column('price_snapshot', JSONB, nullable=False),
        Column('estimated_cost_micro_usd', BigInteger),
        Column('usage_status', Text, nullable=False),
        Column('reason_code', Text),
        Column('created_at', DateTime(timezone=True), nullable=False),
        UniqueConstraint('call_id', 'event_key', name='usage_events_call_key'),
        CheckConstraint('length(event_key) >= 1 AND length(event_key) <= 128', name='usage_events_key_check'),
        CheckConstraint("event_digest ~ '^[0-9a-f]{64}$'", name='usage_events_digest_check'),
        CheckConstraint("event_type IN ('observation', 'release')", name='usage_events_type_check'),
        CheckConstraint("provider_usage IS NULL OR jsonb_typeof(provider_usage) = 'object'", name='usage_events_usage_object_check'),
        CheckConstraint("jsonb_typeof(price_snapshot) = 'object'", name='usage_events_price_check'),
        CheckConstraint(f'usage_status IN ({USAGE_STATUSES})', name='usage_events_status_check'),
        CheckConstraint('estimated_cost_micro_usd >= 0', name='usage_events_cost_check'),
    )
    Index('usage_events_call_created', usage.c.call_id, usage.c.created_at)

    reservations = Table(
        'budget_reservations', metadata,
        Column('call_id', Text, ForeignKey('model_calls.id'), primary_key=True),
        Column('budget_id', Text, ForeignKey('model_budgets.id'), primary_key=True),
        Column('reserved_micro_usd', BigInteger, nullable=False),
        Column('accounted_micro_usd', BigInteger, nullable=False),
        Column('status', Text, nullable=False),
        Column('updated_at', DateTime(timezone=True), nullable=False),
        CheckConstraint("reserved_micro_usd >= 0 AND reserved_micro_usd <= '1000000000000'::bigint", name='budget_reservations_reserved_check'),
        CheckConstraint('accounted_micro_usd >= 0', name='budget_reservations_accounted_check'),
        CheckConstraint("status IN ('held', 'settled', 'released')", name='budget_reservations_status_check'),
    )
    Index('budget_reservations_budget_status', reservations.c.budget_id, reservations.c.status)
    return budgets, calls, usage, reservations
