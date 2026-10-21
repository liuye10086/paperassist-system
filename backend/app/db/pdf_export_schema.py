"""Additive PDF objects with actual typed source references and scoped parent lineage."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

def define_pdf_export_tables(metadata):
    table=sa.Table('pdf_exports',metadata,
        sa.Column('id',sa.Text,primary_key=True),sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),
        sa.Column('source_kind',sa.Text,nullable=False),sa.Column('source_id',sa.Text,nullable=False),
        sa.Column('report_id',sa.Text,sa.ForeignKey('reports.id')),sa.Column('collection_report_id',sa.Text,sa.ForeignKey('collection_reports.id')),
        sa.Column('manuscript_export_id',sa.Text,sa.ForeignKey('manuscript_exports.id')),
        sa.Column('layout_export_id',sa.Text,sa.ForeignKey('layout_exports.id')),
        sa.Column('task_id',sa.Text,sa.ForeignKey('tasks.id'),nullable=False,unique=True),
        sa.Column('parent_export_id',sa.Text),sa.Column('request_key',sa.Text,nullable=False),sa.Column('request_digest',sa.Text,nullable=False),
        sa.Column('input_json',JSONB,nullable=False),sa.Column('input_sha256',sa.Text,nullable=False),
        sa.Column('source_sha256',sa.Text,nullable=False),sa.Column('renderer_identity',JSONB,nullable=False),
        sa.Column('metadata_json',JSONB(none_as_null=True)),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.ForeignKeyConstraint(['project_id','user_id'],['projects.id','projects.owner_id'],name='pdf_owner_fk'),
        sa.UniqueConstraint('id','project_id','user_id',name='pdf_scope_key'),
        sa.ForeignKeyConstraint(['parent_export_id','project_id','user_id'],['pdf_exports.id','pdf_exports.project_id','pdf_exports.user_id'],name='pdf_parent_fk'),
        sa.UniqueConstraint('project_id','user_id','request_key',name='pdf_request_key'),
        sa.CheckConstraint("request_key ~ '^[!-~]{1,128}$' AND request_digest ~ '^[0-9a-f]{64}$' AND input_sha256 ~ '^[0-9a-f]{64}$' AND source_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(input_json)='object' AND jsonb_typeof(renderer_identity)='object'",name='pdf_hash_check'),
        sa.CheckConstraint("num_nonnulls(report_id,collection_report_id,manuscript_export_id,layout_export_id)=1 AND ((source_kind='report' AND report_id IS NOT NULL AND source_id=report_id) OR (source_kind='collection_report' AND collection_report_id IS NOT NULL AND source_id=collection_report_id) OR (source_kind='manuscript_export' AND manuscript_export_id IS NOT NULL AND source_id=manuscript_export_id) OR (source_kind='layout_export' AND layout_export_id IS NOT NULL AND source_id=layout_export_id))",name='pdf_typed_source_check'))
    sa.Index('pdf_project_created',table.c.project_id,table.c.created_at.desc(),table.c.id)
    return (table,)
