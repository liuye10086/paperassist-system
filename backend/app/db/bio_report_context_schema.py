"""Immutable native selection, immediate file protection and successful prepare receipts."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

TABLE_NAMES = ('bio_report_context_versions', 'bio_report_context_files', 'bio_report_context_requests')


def define_bio_report_context_tables(metadata):
    def text(name):
        return sa.Column(name, sa.Text, nullable=False)

    contexts = sa.Table(TABLE_NAMES[0], metadata,
        *(text(key) for key in ('id', 'project_id', 'user_id', 'content_sha256')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('schema_version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('content_json', JSONB, nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('id', 'project_id', name='brc_project_key'),
        sa.UniqueConstraint('id', 'project_id', 'user_id', name='brc_scope_key'),
        sa.UniqueConstraint('project_id', 'user_id', 'content_sha256', name='brc_content_key'),
        sa.ForeignKeyConstraint(['project_id', 'user_id'], ['projects.id', 'projects.owner_id'], name='brc_owner_fk'),
        sa.CheckConstraint("schema_version=1 AND content_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(content_json)='object' AND octet_length(content_json::text)<=4194304", name='brc_content_check'),
        sa.Index('brc_project_created', 'project_id', 'created_at'),
    )
    files = sa.Table(TABLE_NAMES[1], metadata,
        *(text(key) for key in ('id', 'context_id', 'project_id', 'user_id', 'file_id', 'sha256')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('context_id', 'file_id', name='brc_file_key'),
        sa.ForeignKeyConstraint(['context_id', 'project_id', 'user_id'], ['bio_report_context_versions.id', 'bio_report_context_versions.project_id', 'bio_report_context_versions.user_id'], name='brc_file_context_fk'),
        sa.ForeignKeyConstraint(['file_id', 'project_id'], ['files.id', 'files.project_id'], name='brc_file_scope_fk'),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name='brc_file_sha_check'),
        sa.Index('brc_file_lookup', 'file_id', 'project_id'),
    )
    receipts = sa.Table(TABLE_NAMES[2], metadata,
        *(text(key) for key in ('id', 'context_id', 'project_id', 'user_id', 'request_key', 'request_digest', 'finding_version_id')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'user_id', 'request_key', name='brc_request_key'),
        sa.ForeignKeyConstraint(['context_id', 'project_id', 'user_id'], ['bio_report_context_versions.id', 'bio_report_context_versions.project_id', 'bio_report_context_versions.user_id'], name='brc_request_context_fk'),
        sa.ForeignKeyConstraint(['finding_version_id', 'project_id', 'user_id'], ['research_finding_versions.id', 'research_finding_versions.project_id', 'research_finding_versions.user_id'], name='brc_request_finding_fk'),
        sa.CheckConstraint("request_digest ~ '^[0-9a-f]{64}$' AND request_key ~ '^[!-~]{1,128}$'", name='brc_request_check'),
        sa.Index('brc_request_context', 'context_id'),
    )
    return contexts, files, receipts
