"""Append actual evidence without backfilling or rewriting historical estimates."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0013_cost_reconciliation'
down_revision = '0012_task_errors'
branch_labels = None
depends_on = None

EVIDENCE_CHECK = """(event_type <> 'reconciliation') OR (reconciliation->'request' ?& ARRAY['event_key','expected_revision','component','amount_micro_usd','evidence_kind','evidence_reference','evidence_sha256','provider_object_id','operator']
 AND (reconciliation->'request') - ARRAY['event_key','expected_revision','component','amount_micro_usd','evidence_kind','evidence_reference','evidence_sha256','provider_object_id','operator']='{}'::jsonb
 AND reconciliation->'receipt' ?& ARRAY['call_id','revision','component','actual_micro_usd','reconciliation_status','accounted_before_micro_usd','accounted_after_micro_usd','delta_micro_usd','reserved_after_micro_usd']
 AND reconciliation->'previous_actual_micro_usd' ?& ARRAY['token_micro_usd','tool_micro_usd']
 AND reconciliation->'actual_micro_usd' ?& ARRAY['token_micro_usd','tool_micro_usd']
 AND reconciliation->'request'->>'component' IN ('token','tool')
 AND reconciliation->'request'->>'evidence_kind' IN ('provider_statement','provider_support')
 AND jsonb_typeof(reconciliation->'request'->'amount_micro_usd')='number'
 AND reconciliation->'request'->>'amount_micro_usd' ~ '^[0-9]+$'
 AND jsonb_typeof(reconciliation->'request'->'expected_revision')='number'
 AND reconciliation->'request'->>'expected_revision' ~ '^[0-9]+$'
 AND reconciliation->'request'->>'evidence_sha256' ~ '^[0-9a-f]{64}$'
 AND jsonb_typeof(reconciliation->'request'->'evidence_reference')='string'
 AND length(reconciliation->'request'->>'evidence_reference') >= 1 AND length(reconciliation->'request'->>'evidence_reference') <= 256
 AND jsonb_typeof(reconciliation->'request'->'provider_object_id')='string'
 AND length(reconciliation->'request'->>'provider_object_id') >= 1 AND length(reconciliation->'request'->>'provider_object_id') <= 256
 AND jsonb_typeof(reconciliation->'request'->'operator')='string'
 AND length(reconciliation->'request'->>'operator') >= 1 AND length(reconciliation->'request'->>'operator') <= 128
 AND jsonb_typeof(reconciliation->'revision')='number'
 AND jsonb_typeof(reconciliation->'accounted_before_micro_usd')='number'
 AND jsonb_typeof(reconciliation->'accounted_after_micro_usd')='number'
 AND jsonb_typeof(reconciliation->'delta_micro_usd')='number'
 AND reconciliation->'request'->>'operator'=reconciliation->>'operator'
 AND reconciliation->'request'->>'event_key'=event_key
 AND reconciliation->'receipt'->>'call_id'=call_id
 AND reconciliation->'receipt'->>'revision'=reconciliation->>'revision'
 AND reconciliation->'receipt'->>'component'=reconciliation->'request'->>'component'
 AND reconciliation->'receipt'->>'reconciliation_status' IN ('partial','reconciled'))"""

PAYLOAD_CHECK = """(event_type <> 'reconciliation' AND reconciliation IS NULL) OR
 (event_type = 'reconciliation' AND reconciliation IS NOT NULL
 AND jsonb_typeof(reconciliation)='object'
 AND reconciliation ?& ARRAY['request','operator','revision','previous_actual_micro_usd','actual_micro_usd',
 'accounted_before_micro_usd','accounted_after_micro_usd','delta_micro_usd','receipt']
 AND jsonb_typeof(reconciliation->'request')='object'
 AND jsonb_typeof(reconciliation->'receipt')='object'
 AND jsonb_typeof(reconciliation->'previous_actual_micro_usd')='object'
 AND jsonb_typeof(reconciliation->'actual_micro_usd')='object'
 AND jsonb_typeof(reconciliation->'operator')='string'
 AND (reconciliation->>'revision') ~ '^[1-9][0-9]*$'
 AND (reconciliation->>'accounted_before_micro_usd') ~ '^[0-9]+$'
 AND (reconciliation->>'accounted_after_micro_usd') ~ '^[0-9]+$'
 AND (reconciliation->>'delta_micro_usd') ~ '^-?[0-9]+$')"""


def upgrade():
    for column in ('actual_token_micro_usd', 'actual_tool_micro_usd'):
        op.add_column('model_calls', sa.Column(column, sa.BigInteger))
        op.create_check_constraint('model_calls_' + column + '_check', 'model_calls', column + ' >= 0')
    op.add_column('model_calls', sa.Column('reconciliation_revision', sa.Integer, nullable=False, server_default=sa.text('0')))
    op.create_check_constraint('model_calls_reconciliation_revision_check', 'model_calls', 'reconciliation_revision >= 0')
    op.add_column('usage_events', sa.Column('reconciliation', JSONB(none_as_null=True)))
    op.drop_constraint('usage_events_type_check', 'usage_events', type_='check')
    op.create_check_constraint('usage_events_type_check', 'usage_events', "event_type IN ('observation','release','reconciliation')")
    op.create_check_constraint('usage_events_reconciliation_check', 'usage_events', PAYLOAD_CHECK)
    op.create_check_constraint('usage_events_reconciliation_evidence_check', 'usage_events', '(' + EVIDENCE_CHECK + ') IS TRUE')


def downgrade():
    op.drop_constraint('usage_events_reconciliation_evidence_check', 'usage_events', type_='check')
    op.drop_constraint('usage_events_reconciliation_check', 'usage_events', type_='check')
    op.drop_constraint('usage_events_type_check', 'usage_events', type_='check')
    op.create_check_constraint('usage_events_type_check', 'usage_events', "event_type IN ('observation','release')")
    op.drop_column('usage_events', 'reconciliation')
    op.drop_constraint('model_calls_reconciliation_revision_check', 'model_calls', type_='check')
    op.drop_column('model_calls', 'reconciliation_revision')
    for column in ('actual_tool_micro_usd', 'actual_token_micro_usd'):
        op.drop_constraint('model_calls_' + column + '_check', 'model_calls', type_='check')
        op.drop_column('model_calls', column)
