"""One sealed input and adoption record, reusing public manuscript versions."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def define_school_change_table(metadata):
    return sa.Table('manuscript_school_changes',metadata,
        sa.Column('id',sa.Text,primary_key=True),sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),
        sa.Column('manuscript_id',sa.Text,nullable=False),sa.Column('base_version_id',sa.Text,nullable=False),
        sa.Column('kind',sa.Text,nullable=False),sa.Column('target_confirmation_id',sa.Text),sa.Column('file_id',sa.Text),sa.Column('document_version_id',sa.Text),sa.Column('base_export_id',sa.Text),
        sa.Column('idempotency_key',sa.Text,nullable=False),sa.Column('request_json',JSONB,nullable=False),sa.Column('request_digest',sa.Text,nullable=False),
        sa.Column('input_json',JSONB,nullable=False),sa.Column('input_sha256',sa.Text,nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('adopted_revision',sa.Integer),sa.Column('adopt_key',sa.Text),sa.Column('adopt_json',JSONB(none_as_null=True)),sa.Column('adopt_sha256',sa.Text),
        sa.Column('candidate_json',JSONB(none_as_null=True)),sa.Column('candidate_sha256',sa.Text),
        sa.ForeignKeyConstraint(['manuscript_id','project_id','user_id'],['manuscripts.id','manuscripts.project_id','manuscripts.user_id'],name='msc_root_scope_fk'),
        sa.ForeignKeyConstraint(['base_version_id','manuscript_id'],['manuscript_versions.id','manuscript_versions.manuscript_id'],name='msc_base_scope_fk'),
        sa.ForeignKeyConstraint(['target_confirmation_id','project_id','user_id'],['school_template_confirmations.id','school_template_confirmations.project_id','school_template_confirmations.user_id'],name='msc_confirmation_scope_fk'),
        sa.ForeignKeyConstraint(['file_id','project_id'],['files.id','files.project_id'],name='msc_file_scope_fk'),
        sa.ForeignKeyConstraint(['document_version_id','file_id'],['file_parse_results.id','file_parse_results.file_id'],name='msc_document_scope_fk'),
        sa.ForeignKeyConstraint(['base_export_id'],['manuscript_exports.id'],name='msc_export_fk'),
        sa.ForeignKeyConstraint(['manuscript_id','adopted_revision'],['manuscript_versions.manuscript_id','manuscript_versions.revision'],name='msc_adopted_fk'),
        sa.UniqueConstraint('manuscript_id','idempotency_key',name='msc_request_key'),
        sa.CheckConstraint("idempotency_key ~ '^[!-~]{1,128}$' AND request_digest ~ '^[0-9a-f]{64}$' AND input_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(input_json)='object' AND jsonb_typeof(request_json)='object'",name='msc_input_check'),
        sa.CheckConstraint("(kind='template_migration' AND target_confirmation_id IS NOT NULL AND file_id IS NULL AND document_version_id IS NULL AND base_export_id IS NULL) OR (kind='docx_return' AND target_confirmation_id IS NULL AND file_id IS NOT NULL AND document_version_id IS NOT NULL)",name='msc_kind_check'),
        sa.CheckConstraint("(adopted_revision IS NULL AND adopt_key IS NULL AND adopt_json IS NULL AND adopt_sha256 IS NULL AND candidate_json IS NULL AND candidate_sha256 IS NULL) OR (adopted_revision>1 AND adopt_key IS NOT NULL AND adopt_json IS NOT NULL AND adopt_sha256 ~ '^[0-9a-f]{64}$' AND candidate_json IS NOT NULL AND candidate_sha256 ~ '^[0-9a-f]{64}$')",name='msc_adoption_check'))
