"""Add model usage and cumulative budgets; definitions are frozen in this revision."""
from alembic import op
from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, ForeignKey, Integer,
    Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB


CALL_STATUSES = "'reserved', 'submitting', 'submitted', 'submission_unknown', 'completed', 'failed', 'released'"
USAGE_STATUSES = "'pending', 'estimated'"


revision = '0008_model_usage'
down_revision = '0007_task_execution'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'model_budgets',
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
    op.create_index('model_budgets_owner', 'model_budgets', ['user_id', 'scope_type'])

    op.create_table(
        'model_calls',
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
    )
    op.create_index('model_calls_project_created', 'model_calls', ['project_id', text('created_at DESC'), 'id'])
    op.create_index('model_calls_owner_status', 'model_calls', ['user_id', 'status'])

    op.create_table(
        'usage_events',
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
    op.create_index('usage_events_call_created', 'usage_events', ['call_id', 'created_at'])

    op.create_table(
        'budget_reservations',
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
    op.create_index('budget_reservations_budget_status', 'budget_reservations', ['budget_id', 'status'])


def downgrade():
    op.drop_table('budget_reservations')
    op.drop_table('usage_events')
    op.drop_table('model_calls')
    op.drop_table('model_budgets')
