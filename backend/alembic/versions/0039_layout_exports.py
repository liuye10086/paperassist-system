from alembic import op
revision="0039_layout_exports"
down_revision="0038_manuscript_review"
branch_labels=None
depends_on=None
"""Additive PDF objects with actual typed source references and scoped parent lineage."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

def define_layout_export_tables(metadata):
    table=sa.Table('layout_exports',metadata,
        sa.Column('id',sa.Text,primary_key=True),sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),
        sa.Column('source_kind',sa.Text,nullable=False),sa.Column('source_id',sa.Text,nullable=False),
        sa.Column('report_id',sa.Text,sa.ForeignKey('reports.id')),sa.Column('collection_report_id',sa.Text,sa.ForeignKey('collection_reports.id')),
        sa.Column('manuscript_export_id',sa.Text,sa.ForeignKey('manuscript_exports.id')),
        sa.Column('task_id',sa.Text,sa.ForeignKey('tasks.id'),nullable=False,unique=True),
        sa.Column('parent_export_id',sa.Text),sa.Column('request_key',sa.Text,nullable=False),sa.Column('request_digest',sa.Text,nullable=False),
        sa.Column('input_json',JSONB,nullable=False),sa.Column('input_sha256',sa.Text,nullable=False),
        sa.Column('layout_version',sa.Text,nullable=False),sa.Column('source_sha256',sa.Text,nullable=False),sa.Column('renderer_identity',JSONB,nullable=False),
        sa.Column('metadata_json',JSONB(none_as_null=True)),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.ForeignKeyConstraint(['project_id','user_id'],['projects.id','projects.owner_id'],name='layout_owner_fk'),
        sa.UniqueConstraint('id','project_id','user_id',name='layout_scope_key'),
        sa.ForeignKeyConstraint(['parent_export_id','project_id','user_id'],['layout_exports.id','layout_exports.project_id','layout_exports.user_id'],name='layout_parent_fk'),
        sa.UniqueConstraint('project_id','user_id','request_key',name='layout_request_key'),
        sa.CheckConstraint("request_key ~ '^[!-~]{1,128}$' AND request_digest ~ '^[0-9a-f]{64}$' AND input_sha256 ~ '^[0-9a-f]{64}$' AND source_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(input_json)='object' AND jsonb_typeof(renderer_identity)='object'",name='layout_hash_check'),
        sa.CheckConstraint("(layout_version='document_layout_v1' AND input_json ?& ARRAY['project_id','source_kind','source_id','source_sha256','source','renderer_identity','workflow_version','layout','layout_version','output_language'] AND input_json->>'project_id'=project_id AND input_json->>'source_kind'=source_kind AND input_json->>'source_id'=source_id AND input_json->>'source_sha256'=source_sha256 AND input_json->>'layout_version'=layout_version AND input_json->>'workflow_version'='layout_docx_v1' AND jsonb_typeof(input_json->'layout')='object' AND input_json->'layout'->>'source_sha256'=source_sha256 AND input_json->'renderer_identity'=renderer_identity AND input_json->>'output_language' IN ('zh-CN','en') AND (metadata_json IS NULL OR (jsonb_typeof(metadata_json)='object' AND metadata_json ?& ARRAY['filename','object_name','sha256','size_bytes','source_sha256','input_sha256','renderer_manifest'] AND metadata_json->>'source_sha256'=source_sha256 AND metadata_json->>'input_sha256'=input_sha256 AND metadata_json->'renderer_manifest'=renderer_identity AND metadata_json->>'sha256' ~ '^[0-9a-f]{64}$' AND (metadata_json->>'size_bytes')::bigint>0))) IS TRUE",name='layout_snapshot_check'),
        sa.CheckConstraint("num_nonnulls(report_id,collection_report_id,manuscript_export_id)=1 AND ((source_kind='report' AND report_id IS NOT NULL AND source_id=report_id) OR (source_kind='collection_report' AND collection_report_id IS NOT NULL AND source_id=collection_report_id) OR (source_kind='manuscript_export' AND manuscript_export_id IS NOT NULL AND source_id=manuscript_export_id))",name='layout_typed_source_check'))
    sa.Index('layout_project_created',table.c.project_id,table.c.created_at.desc(),table.c.id)
    return (table,)

OLD_TYPES="'boxplot', 'explanation', 'word_report', 'parse_file', 'extract_dataset', 'prepare_dataset', 'review_ocr', 'analysis_plan', 'analysis_recommendation', 'figure_projection', 'figure_workbench', 'figure_explanation', 'collection_word_report', 'statistics_compute', 'literature_search', 'literature_assistance', 'manuscript_draft', 'manuscript_docx', 'pdf_export', 'manuscript_writing'"
OLD_PDF_CHECK="num_nonnulls(report_id,collection_report_id,manuscript_export_id)=1 AND ((source_kind='report' AND report_id IS NOT NULL AND source_id=report_id) OR (source_kind='collection_report' AND collection_report_id IS NOT NULL AND source_id=collection_report_id) OR (source_kind='manuscript_export' AND manuscript_export_id IS NOT NULL AND source_id=manuscript_export_id))"
NEW_PDF_CHECK="num_nonnulls(report_id,collection_report_id,manuscript_export_id,layout_export_id)=1 AND ((source_kind='report' AND report_id IS NOT NULL AND source_id=report_id) OR (source_kind='collection_report' AND collection_report_id IS NOT NULL AND source_id=collection_report_id) OR (source_kind='manuscript_export' AND manuscript_export_id IS NOT NULL AND source_id=manuscript_export_id) OR (source_kind='layout_export' AND layout_export_id IS NOT NULL AND source_id=layout_export_id))"
def frozen_tables():
    metadata=sa.MetaData()
    for name,columns in (('projects',('id','owner_id')),('users',('id',)),('tasks',('id',)),('reports',('id',)),('collection_reports',('id',)),('manuscript_exports',('id',))):
        sa.Table(name,metadata,*(sa.Column(c,sa.Text) for c in columns))
    return define_layout_export_tables(metadata)
def upgrade():
    for table in frozen_tables(): table.create(op.get_bind())
    op.add_column('pdf_exports',sa.Column('layout_export_id',sa.Text,nullable=True))
    op.create_foreign_key('pdf_exports_layout_export_id_fkey','pdf_exports','layout_exports',['layout_export_id'],['id'])
    op.drop_constraint('pdf_typed_source_check','pdf_exports',type_='check')
    op.create_check_constraint('pdf_typed_source_check','pdf_exports',NEW_PDF_CHECK)
    op.drop_constraint('tasks_type_check','tasks',type_='check')
    op.create_check_constraint('tasks_type_check','tasks','task_type IN ('+OLD_TYPES+", 'layout_docx')")
def downgrade():
    bind=op.get_bind()
    if bind.exec_driver_sql("SELECT EXISTS(SELECT 1 FROM layout_exports) OR EXISTS(SELECT 1 FROM tasks WHERE task_type='layout_docx') OR EXISTS(SELECT 1 FROM pdf_exports WHERE layout_export_id IS NOT NULL)").scalar_one():
        raise RuntimeError('Layout history exists; refusing destructive downgrade.')
    op.drop_constraint('tasks_type_check','tasks',type_='check')
    op.create_check_constraint('tasks_type_check','tasks','task_type IN ('+OLD_TYPES+')')
    op.drop_constraint('pdf_typed_source_check','pdf_exports',type_='check')
    op.create_check_constraint('pdf_typed_source_check','pdf_exports',OLD_PDF_CHECK)
    op.drop_constraint('pdf_exports_layout_export_id_fkey','pdf_exports',type_='foreignkey')
    op.drop_column('pdf_exports','layout_export_id')
    for table in reversed(frozen_tables()): table.drop(bind)
