"""Frozen review revisions and independent document versions."""
from alembic import op
revision='0049_review_revisions'
down_revision='0048_review_rounds'
branch_labels=None
depends_on=None
"""Three scoped immutable review result/artifact entities."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

def define_review_revision_tables(metadata):
    def common(prefix):
        return [sa.Column('id',sa.Text,primary_key=True),sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),sa.Column('idempotency_key',sa.Text,nullable=False),sa.Column('request_json',JSONB,nullable=False),sa.Column('request_digest',sa.Text,nullable=False),sa.Column('snapshot_json',JSONB,nullable=False),sa.Column('snapshot_sha256',sa.Text,nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.UniqueConstraint('id','project_id','user_id',name=prefix+'_scope_key'),sa.UniqueConstraint('project_id','user_id','idempotency_key',name=prefix+'_request_key'),sa.ForeignKeyConstraint(['project_id','user_id'],['projects.id','projects.owner_id'],name=prefix+'_owner_fk'),sa.CheckConstraint("request_digest ~ '^[0-9a-f]{64}$' AND snapshot_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(snapshot_json)='object'",name=prefix+'_json_check')]
    def scope(column,table,prefix):return sa.ForeignKeyConstraint([column,'project_id','user_id'],[table+'.id',table+'.project_id',table+'.user_id'],name=prefix+'_scope_fk')
    def result():return [sa.Column('result_json',JSONB(none_as_null=True)),sa.Column('result_sha256',sa.Text)]
    runs=sa.Table('review_revision_runs',metadata,*common('rrr'),sa.Column('round_id',sa.Text,nullable=False),sa.Column('task_id',sa.Text,nullable=False,unique=True),sa.Column('manuscript_id',sa.Text,nullable=False),sa.Column('manuscript_version_id',sa.Text,nullable=False),sa.Column('output_version_id',sa.Text,unique=True),*result(),scope('round_id','review_rounds','rrr_round'),scope('task_id','tasks','rrr_task'),scope('manuscript_id','manuscripts','rrr_manuscript'),sa.ForeignKeyConstraint(['manuscript_version_id','manuscript_id'],['manuscript_versions.id','manuscript_versions.manuscript_id'],name='rrr_input_fk'),sa.ForeignKeyConstraint(['output_version_id','manuscript_id'],['manuscript_versions.id','manuscript_versions.manuscript_id'],name='rrr_output_fk'),sa.CheckConstraint("(result_json IS NULL AND result_sha256 IS NULL AND output_version_id IS NULL) OR (jsonb_typeof(result_json)='object' AND result_sha256 ~ '^[0-9a-f]{64}$' AND output_version_id IS NOT NULL)",name='rrr_result_check'))
    documents=sa.Table('review_documents',metadata,*common('rd'),sa.Column('round_id',sa.Text,nullable=False),sa.Column('revision_id',sa.Text,nullable=False),sa.Column('kind',sa.Text,nullable=False),sa.Column('version',sa.Integer,nullable=False),sa.Column('language',sa.Text,nullable=False),sa.Column('confirmed_at',sa.DateTime(timezone=True)),sa.Column('confirmation_key',sa.Text),scope('round_id','review_rounds','rd_round'),scope('revision_id','review_revision_runs','rd_revision'),sa.UniqueConstraint('revision_id','kind','version',name='rd_version_key'),sa.CheckConstraint("version>=1 AND kind IN ('comparison','reply') AND language IN ('zh-CN','en') AND ((confirmed_at IS NULL)=(confirmation_key IS NULL))",name='rd_kind_check'))
    exports=sa.Table('review_document_exports',metadata,*common('rde'),sa.Column('document_id',sa.Text,nullable=False),sa.Column('task_id',sa.Text,nullable=False,unique=True),*result(),sa.Column('artifact_json',JSONB(none_as_null=True)),scope('document_id','review_documents','rde_document'),scope('task_id','tasks','rde_task'),sa.CheckConstraint("(result_json IS NULL AND result_sha256 IS NULL AND artifact_json IS NULL) OR (jsonb_typeof(result_json)='object' AND result_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(artifact_json)='object')",name='rde_result_check'))
    return runs,documents,exports

OLD_TYPES="'boxplot', 'explanation', 'word_report', 'parse_file', 'extract_dataset', 'prepare_dataset', 'review_ocr', 'analysis_plan', 'analysis_recommendation', 'figure_projection', 'figure_workbench', 'figure_explanation', 'collection_word_report', 'statistics_compute', 'literature_search', 'literature_assistance', 'manuscript_draft', 'manuscript_docx', 'pdf_export', 'manuscript_writing', 'layout_docx', 'school_template_parse', 'journal_recommendation', 'journal_format_check', 'journal_adaptation', 'review_round_plan'"
def tables():
    metadata=sa.MetaData()
    for name,columns in [('projects',('id','owner_id')),('tasks',('id','project_id','user_id')),('review_rounds',('id','project_id','user_id')),('manuscripts',('id','project_id','user_id')),('manuscript_versions',('id','manuscript_id'))]:
        sa.Table(name,metadata,*(sa.Column(c,sa.Text) for c in columns))
    return define_review_revision_tables(metadata)

def upgrade():
    op.drop_constraint('tasks_type_check','tasks',type_='check')
    op.create_check_constraint('tasks_type_check','tasks',"task_type IN ("+OLD_TYPES+", 'review_revision', 'review_document_export')")
    for kind in ('review_revision','review_document_export'):
        op.create_check_constraint('tasks_'+kind+'_snapshot_check','tasks',"task_type<>'"+kind+"' OR ((workflow_version='"+kind+"_v1' AND input_snapshot->>'kind'='"+kind+"' AND input_snapshot->'real_model_calls'='false'::jsonb AND input_snapshot->'real_network_calls'='false'::jsonb) IS TRUE)")
    for table in tables():table.create(op.get_bind())
    op.add_column('pdf_exports',sa.Column('review_document_export_id',sa.Text))
    op.create_foreign_key('pdf_review_document_scope_fk','pdf_exports','review_document_exports',['review_document_export_id','project_id','user_id'],['id','project_id','user_id'])
    op.drop_constraint('pdf_typed_source_check','pdf_exports',type_='check')
    op.create_check_constraint('pdf_typed_source_check','pdf_exports',"num_nonnulls(report_id,collection_report_id,manuscript_export_id,layout_export_id,review_document_export_id)=1 AND ((source_kind='report' AND report_id IS NOT NULL AND source_id=report_id) OR (source_kind='collection_report' AND collection_report_id IS NOT NULL AND source_id=collection_report_id) OR (source_kind='manuscript_export' AND manuscript_export_id IS NOT NULL AND source_id=manuscript_export_id) OR (source_kind='layout_export' AND layout_export_id IS NOT NULL AND source_id=layout_export_id) OR (source_kind='review_document_export' AND review_document_export_id IS NOT NULL AND source_id=review_document_export_id))")
    op.execute("""CREATE FUNCTION review_revision_seal() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      IF TG_OP='UPDATE' THEN
        IF TG_TABLE_NAME='review_revision_runs' THEN
          IF OLD.result_json IS NULL AND NEW.result_json IS NOT NULL AND (to_jsonb(NEW)-ARRAY['result_json','result_sha256','output_version_id'])=(to_jsonb(OLD)-ARRAY['result_json','result_sha256','output_version_id']) THEN RETURN NEW; END IF;
        ELSIF TG_TABLE_NAME='review_document_exports' THEN
          IF OLD.result_json IS NULL AND NEW.result_json IS NOT NULL AND (to_jsonb(NEW)-ARRAY['result_json','result_sha256','artifact_json'])=(to_jsonb(OLD)-ARRAY['result_json','result_sha256','artifact_json']) THEN RETURN NEW; END IF;
        ELSIF TG_TABLE_NAME='review_documents' THEN
          IF OLD.confirmed_at IS NULL AND NEW.confirmed_at IS NOT NULL AND (to_jsonb(NEW)-ARRAY['confirmed_at','confirmation_key'])=(to_jsonb(OLD)-ARRAY['confirmed_at','confirmation_key']) THEN RETURN NEW; END IF;
        END IF;
      END IF;
      RAISE EXCEPTION 'Immutable review revision history'; END $$""")
    for table in tables():op.execute('CREATE TRIGGER '+table.name+'_seal BEFORE UPDATE OR DELETE ON '+table.name+' FOR EACH ROW EXECUTE FUNCTION review_revision_seal()')

def downgrade():
    if any(op.get_bind().exec_driver_sql('SELECT EXISTS(SELECT 1 FROM '+t.name+')').scalar_one() for t in tables()):raise RuntimeError('Review revision history exists; refusing destructive downgrade.')
    op.drop_constraint('pdf_typed_source_check','pdf_exports',type_='check')
    op.drop_constraint('pdf_review_document_scope_fk','pdf_exports',type_='foreignkey')
    op.drop_column('pdf_exports','review_document_export_id')
    op.create_check_constraint('pdf_typed_source_check','pdf_exports',"num_nonnulls(report_id,collection_report_id,manuscript_export_id,layout_export_id )=1 AND ((source_kind='report' AND report_id IS NOT NULL AND source_id=report_id) OR (source_kind='collection_report' AND collection_report_id IS NOT NULL AND source_id=collection_report_id) OR (source_kind='manuscript_export' AND manuscript_export_id IS NOT NULL AND source_id=manuscript_export_id) OR (source_kind='layout_export' AND layout_export_id IS NOT NULL AND source_id=layout_export_id))")
    for table in reversed(tables()):table.drop(op.get_bind())
    op.execute('DROP FUNCTION review_revision_seal()')
    for kind in ('review_revision','review_document_export'):op.drop_constraint('tasks_'+kind+'_snapshot_check','tasks',type_='check')
    op.drop_constraint('tasks_type_check','tasks',type_='check')
    op.create_check_constraint('tasks_type_check','tasks','task_type IN ('+OLD_TYPES+')')
