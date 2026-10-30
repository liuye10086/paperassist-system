"""One owner-scoped, write-once school advice artifact family."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

def define_school_suggestion_table(metadata):
    return sa.Table('school_rule_suggestions',metadata,sa.Column('id',sa.Text,primary_key=True),
        *(sa.Column(k,sa.Text,nullable=False) for k in ('project_id','user_id','template_version_id','task_id','idempotency_key','request_digest','input_digest')),
        sa.Column('request_json',JSONB,nullable=False),sa.Column('input_snapshot',JSONB,nullable=False),
        sa.Column('raw_output_json',JSONB(none_as_null=True)),sa.Column('result_json',JSONB(none_as_null=True)),
        sa.Column('artifact_sha256',sa.Text),sa.Column('model_call_id',sa.Text),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.ForeignKeyConstraint(['project_id','user_id'],['projects.id','projects.owner_id'],name='srs_owner_fk'),
        sa.ForeignKeyConstraint(['template_version_id','project_id','user_id'],['school_template_versions.id','school_template_versions.project_id','school_template_versions.user_id'],name='srs_template_scope_fk'),
        sa.ForeignKeyConstraint(['task_id','project_id','user_id'],['tasks.id','tasks.project_id','tasks.user_id'],name='srs_task_scope_fk'),
        sa.ForeignKeyConstraint(['model_call_id','project_id','user_id'],['model_calls.id','model_calls.project_id','model_calls.user_id'],name='srs_call_scope_fk'),
        sa.UniqueConstraint('task_id',name='srs_task_key'),sa.UniqueConstraint('id','project_id','user_id',name='srs_scope_key'),
        sa.UniqueConstraint('template_version_id','idempotency_key',name='srs_request_key'),
        sa.CheckConstraint("request_digest ~ '^[0-9a-f]{64}$' AND input_digest ~ '^[0-9a-f]{64}$' AND jsonb_typeof(request_json)='object' AND jsonb_typeof(input_snapshot)='object'",name='srs_input_check'),
        sa.CheckConstraint("num_nonnulls(result_json,raw_output_json,artifact_sha256,model_call_id) IN (0,4) AND ((result_json IS NULL AND raw_output_json IS NULL AND artifact_sha256 IS NULL AND model_call_id IS NULL) OR (jsonb_typeof(result_json)='object' AND jsonb_typeof(raw_output_json)='object' AND artifact_sha256 ~ '^[0-9a-f]{64}$' AND model_call_id IS NOT NULL))",name='srs_result_check'))
