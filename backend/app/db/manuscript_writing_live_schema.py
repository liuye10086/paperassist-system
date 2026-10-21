"""Scoped immutable consent material and transactional submission admissions."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

def define_manuscript_writing_live_tables(metadata):
    bundles=sa.Table('manuscript_writing_bundles',metadata,
        sa.Column('id',sa.Text,primary_key=True),sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),
        sa.Column('manuscript_id',sa.Text,nullable=False),sa.Column('base_version_id',sa.Text,nullable=False),
        sa.Column('request_key',sa.Text,nullable=False),sa.Column('request_digest',sa.Text,nullable=False),
        sa.Column('bundle_sha256',sa.Text,nullable=False),sa.Column('bundle_json',JSONB,nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('id','project_id','user_id',name='mwl_bundle_scope'),
        sa.UniqueConstraint('project_id','user_id','request_key',name='mwl_preview_key'),
        sa.ForeignKeyConstraint(['manuscript_id','project_id','user_id'],['manuscripts.id','manuscripts.project_id','manuscripts.user_id'],name='mwl_bundle_owner'),
        sa.ForeignKeyConstraint(['base_version_id','manuscript_id'],['manuscript_versions.id','manuscript_versions.manuscript_id'],name='mwl_bundle_base'),
        sa.CheckConstraint("bundle_sha256 ~ '^[0-9a-f]{64}$' AND request_digest ~ '^[0-9a-f]{64}$' AND jsonb_typeof(bundle_json)='object'",name='mwl_bundle_check'))
    authorizations=sa.Table('manuscript_writing_authorizations',metadata,
        sa.Column('id',sa.Text,primary_key=True),sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),
        sa.Column('request_key',sa.Text,nullable=False),sa.Column('request_digest',sa.Text,nullable=False),
        sa.Column('manifest_json',JSONB,nullable=False),sa.Column('manifest_sha256',sa.Text,nullable=False),
        sa.Column('status',sa.Text,nullable=False),sa.Column('revision',sa.Integer,nullable=False),
        sa.Column('max_posts',sa.Integer,nullable=False),sa.Column('cap_micro_usd',sa.BigInteger,nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('closed_at',sa.DateTime(timezone=True)),
        sa.UniqueConstraint('id','project_id','user_id',name='mwl_auth_scope'),
        sa.UniqueConstraint('project_id','user_id','request_key',name='mwl_auth_key'),
        sa.ForeignKeyConstraint(['project_id','user_id'],['projects.id','projects.owner_id'],name='mwl_auth_owner'),
        sa.CheckConstraint("status IN ('active','closed','revoked') AND revision>=1 AND max_posts>=1 AND max_posts<=6 AND cap_micro_usd>=0 AND cap_micro_usd<=12000000 AND manifest_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(manifest_json)='object'",name='mwl_auth_check'))
    tasks=sa.Table('manuscript_writing_authorized_tasks',metadata,
        sa.Column('authorization_id',sa.Text,primary_key=True),sa.Column('logical_task_id',sa.Text,primary_key=True),
        sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),
        sa.Column('bundles_json',JSONB,nullable=False),sa.Column('cap_micro_usd',sa.BigInteger,nullable=False),
        sa.UniqueConstraint('authorization_id','logical_task_id','project_id','user_id',name='mwl_task_scope'),
        sa.ForeignKeyConstraint(['authorization_id','project_id','user_id'],['manuscript_writing_authorizations.id','manuscript_writing_authorizations.project_id','manuscript_writing_authorizations.user_id'],name='mwl_task_auth'),
        sa.CheckConstraint("cap_micro_usd>=0 AND cap_micro_usd<=3000000 AND jsonb_typeof(bundles_json)='array'",name='mwl_task_check'))
    admissions=sa.Table('manuscript_writing_call_admissions',metadata,
        sa.Column('model_call_id',sa.Text,primary_key=True),
        sa.Column('bundle_id',sa.Text,nullable=False),sa.Column('authorization_id',sa.Text,nullable=False),sa.Column('logical_task_id',sa.Text,nullable=False),
        sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),
        sa.Column('reserved_micro_usd',sa.BigInteger,nullable=False),sa.Column('status',sa.Text,nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('submission_started_at',sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(['model_call_id','project_id','user_id'],['model_calls.id','model_calls.project_id','model_calls.user_id'],name='mwl_admission_call'),
        sa.ForeignKeyConstraint(['bundle_id','project_id','user_id'],['manuscript_writing_bundles.id','manuscript_writing_bundles.project_id','manuscript_writing_bundles.user_id'],name='mwl_admission_bundle'),
        sa.ForeignKeyConstraint(['authorization_id','logical_task_id','project_id','user_id'],['manuscript_writing_authorized_tasks.authorization_id','manuscript_writing_authorized_tasks.logical_task_id','manuscript_writing_authorized_tasks.project_id','manuscript_writing_authorized_tasks.user_id'],name='mwl_admission_auth'),
        sa.CheckConstraint("reserved_micro_usd>=0 AND status IN ('reserved','submission_started','released') AND ((status='submission_started')=(submission_started_at IS NOT NULL))",name='mwl_admission_check'))
    return bundles,authorizations,tasks,admissions
