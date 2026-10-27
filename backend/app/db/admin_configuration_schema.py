"""Immutable configuration evidence and one CAS pointer."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


IMMUTABLE_TABLES = ('admin_configuration_versions','admin_configuration_validations',
                    'admin_configuration_events','admin_configuration_bindings','admin_usage_summaries')


def define_admin_configuration_tables(metadata):
    versions=sa.Table('admin_configuration_versions',metadata,
        sa.Column('id',sa.Text,primary_key=True),
        sa.Column('parent_id',sa.Text,sa.ForeignKey('admin_configuration_versions.id')),
        sa.Column('sha256',sa.Text,nullable=False),
        sa.Column('bundle',JSONB,nullable=False),sa.Column('sources',JSONB,nullable=False),
        sa.Column('created_by',sa.Text,sa.ForeignKey('users.id'),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.text('clock_timestamp()')),
        sa.UniqueConstraint('id','sha256',name='admin_configuration_version_sha'),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'",name='admin_configuration_sha'))
    validations=sa.Table('admin_configuration_validations',metadata,
        sa.Column('id',sa.Text,primary_key=True),sa.Column('version_id',sa.Text,nullable=False),
        sa.Column('sha256',sa.Text,nullable=False),sa.Column('validator_version',sa.Text,nullable=False),
        sa.Column('capability_version',sa.Text,nullable=False),sa.Column('status',sa.Text,nullable=False),
        sa.Column('result',JSONB,nullable=False),sa.Column('created_by',sa.Text,sa.ForeignKey('users.id'),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.text('clock_timestamp()')),
        sa.ForeignKeyConstraint(['version_id','sha256'],['admin_configuration_versions.id','admin_configuration_versions.sha256']),
        sa.CheckConstraint("status IN ('passed','failed')",name='admin_configuration_validation_status'))
    pointer=sa.Table('admin_configuration_pointer',metadata,
        sa.Column('id',sa.Integer,primary_key=True),sa.Column('revision',sa.Integer,nullable=False),
        sa.Column('version_id',sa.Text,sa.ForeignKey('admin_configuration_versions.id')),
        sa.CheckConstraint('id=1 AND revision>=0',name='admin_configuration_pointer_singleton'))
    events=sa.Table('admin_configuration_events',metadata,
        sa.Column('id',sa.Text,primary_key=True),sa.Column('actor_user_id',sa.Text,sa.ForeignKey('users.id'),nullable=False),
        sa.Column('operation',sa.Text,nullable=False),sa.Column('reason',sa.Text,nullable=False),
        sa.Column('request_key',sa.Text,nullable=False),sa.Column('request_sha256',sa.Text,nullable=False),
        sa.Column('before_version_id',sa.Text,sa.ForeignKey('admin_configuration_versions.id')),
        sa.Column('after_version_id',sa.Text,sa.ForeignKey('admin_configuration_versions.id'),nullable=False),
        sa.Column('validation_id',sa.Text,sa.ForeignKey('admin_configuration_validations.id'),nullable=False),
        sa.Column('revision',sa.Integer,nullable=False),sa.Column('response',JSONB,nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.text('clock_timestamp()')),
        sa.UniqueConstraint('actor_user_id','request_key',name='admin_configuration_request_key'),
        sa.UniqueConstraint('revision',name='admin_configuration_event_revision'),
        sa.CheckConstraint("operation IN ('activate','rollback') AND length(reason) BETWEEN 5 AND 500",name='admin_configuration_event_values'))
    bindings=sa.Table('admin_configuration_bindings',metadata,
        sa.Column('kind',sa.Text,primary_key=True),sa.Column('object_id',sa.Text,primary_key=True),
        sa.Column('version_id',sa.Text,sa.ForeignKey('admin_configuration_versions.id'),nullable=False),
        sa.Column('task_id',sa.Text,sa.ForeignKey('tasks.id')),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.text('clock_timestamp()')),
        sa.CheckConstraint("kind IN ('task','writing_bundle','review_round','school_confirmation','journal_confirmation')",name='admin_configuration_binding_kind'),
        sa.CheckConstraint("(kind='task' AND task_id=object_id AND task_id IS NOT NULL) OR (kind<>'task' AND task_id IS NULL)",name='admin_configuration_binding_task'))
    sa.Index('admin_configuration_validation_lookup',validations.c.version_id,validations.c.created_at.desc())
    sa.Index('admin_configuration_binding_version',bindings.c.version_id)
    summaries=sa.Table('admin_usage_summaries',metadata,
        sa.Column('id',sa.Text,primary_key=True),
        sa.Column('actor_user_id',sa.Text,sa.ForeignKey('users.id'),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.text('clock_timestamp()')),
        sa.Column('asof',sa.DateTime(timezone=True),nullable=False),
        sa.Column('filters',JSONB,nullable=False),sa.Column('source_revision',sa.Text,nullable=False),
        sa.Column('result',JSONB,nullable=False),sa.Column('source_manifest',JSONB,nullable=False),
        sa.Column('sha256',sa.Text,nullable=False),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'",name='admin_usage_summary_sha'))
    return versions,validations,pointer,events,bindings,summaries
