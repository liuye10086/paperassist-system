"""Additive immutable image-language artifacts, scoped to project and owner."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def define_manuscript_figure_language_tables(metadata):
    table=sa.Table('manuscript_figure_language_versions',metadata,
        sa.Column('id',sa.Text,primary_key=True),sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),
        sa.Column('file_id',sa.Text,sa.ForeignKey('files.id'),nullable=False),
        sa.Column('figure_id',sa.Text,sa.ForeignKey('figures.id')),
        sa.Column('document_version_id',sa.Text,sa.ForeignKey('file_parse_results.id')),
        sa.Column('replacement_file_id',sa.Text,sa.ForeignKey('files.id')),
        sa.Column('idempotency_key',sa.Text,nullable=False),sa.Column('request_digest',sa.Text,nullable=False),
        sa.Column('request_json',JSONB,nullable=False),sa.Column('snapshot_json',JSONB,nullable=False),
        sa.Column('snapshot_sha256',sa.Text,nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.ForeignKeyConstraint(['project_id','user_id'],['projects.id','projects.owner_id'],name='mflv_owner_fk'),
        sa.UniqueConstraint('id','project_id','user_id',name='mflv_scope_key'),
        sa.UniqueConstraint('id','file_id',name='mflv_file_key'),
        sa.UniqueConstraint('project_id','user_id','idempotency_key',name='mflv_request_key'),
        sa.CheckConstraint("idempotency_key ~ '^[!-~]{1,128}$' AND request_digest ~ '^[0-9a-f]{64}$' AND snapshot_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(request_json)='object' AND jsonb_typeof(snapshot_json)='object'",name='mflv_json_check'),
        sa.CheckConstraint("num_nonnulls(figure_id,document_version_id)<=1 AND snapshot_json->>'output_language' IN ('en','zh-CN') AND snapshot_json->>'mode' IN ('local_boxplot','uploaded_replacement','no_text_confirmation')",name='mflv_source_check'))
    return (table,)
