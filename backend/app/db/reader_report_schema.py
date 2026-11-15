"""Owner-scoped report narratives and replay receipts."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


TASK_SNAPSHOT_CHECK = """task_type<>'reader_report_narrative' OR (
    workflow_version='reader_report_narrative_v1'
    AND input_snapshot->>'kind'=task_type
    AND input_snapshot->>'workflow_version'=workflow_version
    AND input_snapshot->'schema_version'='1'::jsonb
    AND input_snapshot->>'project_id'=project_id
    AND input_snapshot->>'binding_sha256' ~ '^[0-9a-f]{64}$'
    AND length(input_snapshot->>'narrative_id')>0
    AND input_snapshot->'request'->'confirmed_external_processing'='true'::jsonb
) IS TRUE"""


def define_reader_report_tables(metadata):
    narratives = sa.Table(
        'reader_report_narratives', metadata,
        sa.Column('id', sa.Text, primary_key=True),
        *(sa.Column(key, sa.Text, nullable=False) for key in (
            'project_id', 'user_id', 'task_id', 'request_digest', 'input_digest',
            'binding_sha256', 'bundle_sha256',
        )),
        sa.Column('request_json', JSONB, nullable=False),
        sa.Column('input_snapshot', JSONB, nullable=False),
        sa.Column('raw_output_json', JSONB(none_as_null=True)),
        sa.Column('result_json', JSONB(none_as_null=True)),
        sa.Column('artifact_sha256', sa.Text),
        sa.Column('model_call_id', sa.Text),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['project_id', 'user_id'], ['projects.id', 'projects.owner_id'], name='rrn_owner_fk'),
        sa.ForeignKeyConstraint(['task_id', 'project_id', 'user_id'], ['tasks.id', 'tasks.project_id', 'tasks.user_id'],
                                name='rrn_task_scope_fk'),
        sa.ForeignKeyConstraint(['model_call_id', 'project_id', 'user_id'],
                                ['model_calls.id', 'model_calls.project_id', 'model_calls.user_id'],
                                name='rrn_call_scope_fk'),
        sa.UniqueConstraint('id', 'project_id', 'user_id', name='rrn_scope_key'),
        sa.UniqueConstraint('task_id', name='rrn_task_key'),
        sa.CheckConstraint("""request_digest ~ '^[0-9a-f]{64}$' AND input_digest ~ '^[0-9a-f]{64}$'
            AND binding_sha256 ~ '^[0-9a-f]{64}$' AND bundle_sha256 ~ '^[0-9a-f]{64}$'
            AND jsonb_typeof(request_json)='object' AND jsonb_typeof(input_snapshot)='object'""", name='rrn_input_check'),
        sa.CheckConstraint("""num_nonnulls(result_json,raw_output_json,artifact_sha256,model_call_id)=0 OR
            (num_nonnulls(result_json,raw_output_json,artifact_sha256,model_call_id)=4
             AND jsonb_typeof(result_json)='object' AND jsonb_typeof(raw_output_json)='object'
             AND artifact_sha256 ~ '^[0-9a-f]{64}$')""", name='rrn_result_check'),
        sa.Index('rrn_reuse_idx', 'project_id', 'user_id', 'binding_sha256', 'bundle_sha256', 'created_at'),
    )
    receipts = sa.Table(
        'reader_report_narrative_requests', metadata,
        *(sa.Column(key, sa.Text, nullable=False) for key in (
            'project_id', 'user_id', 'idempotency_key', 'narrative_id', 'request_digest',
        )),
        sa.PrimaryKeyConstraint('project_id', 'user_id', 'idempotency_key', name='rrn_requests_pk'),
        sa.ForeignKeyConstraint(['narrative_id', 'project_id', 'user_id'],
                                ['reader_report_narratives.id', 'reader_report_narratives.project_id', 'reader_report_narratives.user_id'],
                                name='rrn_request_scope_fk'),
        sa.CheckConstraint("request_digest ~ '^[0-9a-f]{64}$' AND length(idempotency_key) BETWEEN 1 AND 128",
                           name='rrn_request_digest_check'),
    )
    return narratives, receipts
