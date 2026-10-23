"""Additive owner-scoped school template configuration and sealed source history."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def define_school_template_tables(metadata):
    def scope(prefix):
        return [sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),
            sa.ForeignKeyConstraint(['project_id','user_id'],['projects.id','projects.owner_id'],name=prefix+'_owner_fk')]
    def request(prefix):
        return [sa.Column('idempotency_key',sa.Text,nullable=False),sa.Column('request_json',JSONB,nullable=False),sa.Column('request_digest',sa.Text,nullable=False),
            sa.CheckConstraint("idempotency_key ~ '^[!-~]{1,128}$' AND request_digest ~ '^[0-9a-f]{64}$' AND jsonb_typeof(request_json)='object'",name=prefix+'_request_check')]
    versions=sa.Table('school_template_versions',metadata,sa.Column('id',sa.Text,primary_key=True),*scope('stv'),*request('stv'),
        sa.Column('name',sa.Text,nullable=False),sa.Column('school',sa.Text,nullable=False),sa.Column('version_label',sa.Text,nullable=False),
        sa.Column('task_id',sa.Text,nullable=False,unique=True),sa.Column('sources_sha256',sa.Text,nullable=False),
        sa.Column('analysis_json',JSONB(none_as_null=True)),sa.Column('analysis_sha256',sa.Text),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('previous_version_id',sa.Text),
        sa.ForeignKeyConstraint(['previous_version_id','project_id','user_id'],['school_template_versions.id','school_template_versions.project_id','school_template_versions.user_id'],name='stv_previous_scope_fk'),
        sa.CheckConstraint('previous_version_id IS NULL OR previous_version_id<>id',name='stv_previous_check'),
        sa.UniqueConstraint('id','project_id','user_id',name='stv_scope_key'),
        sa.UniqueConstraint('project_id','user_id','idempotency_key',name='stv_request_key'),
        sa.ForeignKeyConstraint(['task_id','project_id','user_id'],['tasks.id','tasks.project_id','tasks.user_id'],name='stv_task_scope_fk'),
        sa.CheckConstraint("sources_sha256 ~ '^[0-9a-f]{64}$' AND ((analysis_json IS NULL AND analysis_sha256 IS NULL) OR (jsonb_typeof(analysis_json)='object' AND analysis_sha256 ~ '^[0-9a-f]{64}$'))",name='stv_hashes_check'))
    sources=sa.Table('school_template_sources',metadata,sa.Column('id',sa.Text,primary_key=True),*scope('sts'),
        sa.Column('template_version_id',sa.Text,nullable=False),sa.Column('file_id',sa.Text,nullable=False),
        sa.Column('role',sa.Text,nullable=False),sa.Column('source_json',JSONB,nullable=False),sa.Column('sha256',sa.Text,nullable=False),
        sa.Column('document_version_id',sa.Text),
        sa.ForeignKeyConstraint(['template_version_id','project_id','user_id'],['school_template_versions.id','school_template_versions.project_id','school_template_versions.user_id'],name='sts_version_scope_fk'),
        sa.ForeignKeyConstraint(['file_id','project_id'],['files.id','files.project_id'],name='sts_file_scope_fk'),
        sa.ForeignKeyConstraint(['document_version_id','file_id'],['file_parse_results.id','file_parse_results.file_id'],name='sts_document_scope_fk'),
        sa.UniqueConstraint('template_version_id','file_id',name='sts_file_key'),
        sa.CheckConstraint("role IN ('template','supplement','manuscript') AND sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(source_json)='object' AND (role<>'supplement' OR document_version_id IS NOT NULL)",name='sts_source_check'))
    confirmations=sa.Table('school_template_confirmations',metadata,sa.Column('id',sa.Text,primary_key=True),*scope('stc'),*request('stc'),
        sa.Column('template_version_id',sa.Text,nullable=False),sa.Column('analysis_sha256',sa.Text,nullable=False),
        sa.Column('snapshot_json',JSONB,nullable=False),sa.Column('snapshot_sha256',sa.Text,nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.ForeignKeyConstraint(['template_version_id','project_id','user_id'],['school_template_versions.id','school_template_versions.project_id','school_template_versions.user_id'],name='stc_version_scope_fk'),
        sa.UniqueConstraint('id','project_id','user_id',name='stc_scope_key'),sa.UniqueConstraint('template_version_id',name='stc_version_key'),
        sa.UniqueConstraint('template_version_id','idempotency_key',name='stc_request_key'),
        sa.CheckConstraint("analysis_sha256 ~ '^[0-9a-f]{64}$' AND snapshot_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(snapshot_json)='object'",name='stc_hash_check'))
    profiles=sa.Table('thesis_profiles',metadata,*scope('tp'),sa.Column('revision',sa.Integer,nullable=False),
        *(sa.Column(k,sa.Text,nullable=False) for k in ('school','department','major','degree_type','education_level','applicable_version')),
        sa.Column('bound_confirmation_id',sa.Text),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),
        sa.PrimaryKeyConstraint('project_id'),
        sa.ForeignKeyConstraint(['bound_confirmation_id','project_id','user_id'],['school_template_confirmations.id','school_template_confirmations.project_id','school_template_confirmations.user_id'],name='tp_binding_scope_fk'),
        sa.CheckConstraint('revision>=1',name='tp_revision_check'))
    sa.Index('stv_project_created',versions.c.project_id,versions.c.created_at.desc(),versions.c.id)
    return profiles,versions,sources,confirmations
