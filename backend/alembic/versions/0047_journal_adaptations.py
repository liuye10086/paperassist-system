"""Frozen additive journal adaptation and human submission history."""
from alembic import op
revision='0047_journal_adaptations'
down_revision='0046_journal_format_checks'
branch_labels=None
depends_on=None
"""Scoped adaptation records and append-only user events."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

def define_journal_adaptation_tables(metadata):
    def common(prefix):
        return [sa.Column('id',sa.Text,primary_key=True),sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),sa.Column('idempotency_key',sa.Text,nullable=False),sa.Column('request_json',JSONB,nullable=False),sa.Column('request_digest',sa.Text,nullable=False),sa.Column('snapshot_json',JSONB,nullable=False),sa.Column('snapshot_sha256',sa.Text,nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.UniqueConstraint('id','project_id','user_id',name=prefix+'_scope_key'),sa.UniqueConstraint('project_id','user_id','idempotency_key',name=prefix+'_request_key'),sa.ForeignKeyConstraint(['project_id','user_id'],['projects.id','projects.owner_id'],name=prefix+'_owner_fk'),sa.CheckConstraint("idempotency_key ~ '^[!-~]{1,128}$' AND request_digest ~ '^[0-9a-f]{64}$' AND snapshot_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(request_json)='object' AND jsonb_typeof(snapshot_json)='object'",name=prefix+'_json_check')]
    def scope(column,table,prefix):
        return sa.ForeignKeyConstraint([column,'project_id','user_id'],[table+'.id',table+'.project_id',table+'.user_id'],name=prefix+'_scope_fk')
    adaptations=sa.Table('journal_adaptations',metadata,*common('ja'),sa.Column('target_id',sa.Text,nullable=False),sa.Column('check_id',sa.Text,nullable=False),sa.Column('task_id',sa.Text,nullable=False,unique=True),sa.Column('manuscript_id',sa.Text,nullable=False),sa.Column('manuscript_version_id',sa.Text,nullable=False),sa.Column('output_version_id',sa.Text,unique=True),sa.Column('result_json',JSONB(none_as_null=True)),sa.Column('result_sha256',sa.Text),scope('target_id','journal_targets','ja_target'),scope('check_id','journal_format_checks','ja_check'),scope('task_id','tasks','ja_task'),scope('manuscript_id','manuscripts','ja_manuscript'),sa.ForeignKeyConstraint(['manuscript_version_id','manuscript_id'],['manuscript_versions.id','manuscript_versions.manuscript_id'],name='ja_input_fk'),sa.ForeignKeyConstraint(['output_version_id','manuscript_id'],['manuscript_versions.id','manuscript_versions.manuscript_id'],name='ja_output_fk'),sa.CheckConstraint("(result_json IS NULL AND result_sha256 IS NULL AND output_version_id IS NULL) OR (jsonb_typeof(result_json)='object' AND result_sha256 ~ '^[0-9a-f]{64}$' AND output_version_id IS NOT NULL)",name='ja_result_check'))
    events=sa.Table('journal_submission_events',metadata,*common('jse'),sa.Column('target_id',sa.Text,nullable=False),sa.Column('corrects_event_id',sa.Text,unique=True),sa.Column('manuscript_id',sa.Text),sa.Column('manuscript_version_id',sa.Text),sa.Column('export_id',sa.Text,sa.ForeignKey('manuscript_exports.id')),scope('target_id','journal_targets','jse_target'),scope('corrects_event_id','journal_submission_events','jse_corrects'),scope('manuscript_id','manuscripts','jse_manuscript'),sa.ForeignKeyConstraint(['manuscript_version_id','manuscript_id'],['manuscript_versions.id','manuscript_versions.manuscript_id'],name='jse_version_fk'),sa.CheckConstraint('corrects_event_id IS NULL OR corrects_event_id<>id',name='jse_not_self'))
    for table in (adaptations,events):sa.Index(table.name+'_project_created',table.c.project_id,table.c.created_at.desc(),table.c.id)
    return adaptations,events

def tables():
    metadata=sa.MetaData()
    for name,columns in [('projects',('id','owner_id')),('tasks',('id','project_id','user_id')),('journal_targets',('id','project_id','user_id')),('journal_format_checks',('id','project_id','user_id')),('manuscripts',('id','project_id','user_id')),('manuscript_versions',('id','manuscript_id')),('manuscript_exports',('id',))]:
        sa.Table(name,metadata,*(sa.Column(c,sa.Text) for c in columns))
    return define_journal_adaptation_tables(metadata)
OLD_TYPES="'boxplot', 'explanation', 'word_report', 'parse_file', 'extract_dataset', 'prepare_dataset', 'review_ocr', 'analysis_plan', 'analysis_recommendation', 'figure_projection', 'figure_workbench', 'figure_explanation', 'collection_word_report', 'statistics_compute', 'literature_search', 'literature_assistance', 'manuscript_draft', 'manuscript_docx', 'pdf_export', 'manuscript_writing', 'layout_docx', 'school_template_parse', 'journal_recommendation', 'journal_format_check'"
def upgrade():
    op.drop_constraint('tasks_type_check','tasks',type_='check')
    op.create_check_constraint('tasks_type_check','tasks',"task_type IN ("+OLD_TYPES+", 'journal_adaptation')")
    op.create_check_constraint('tasks_journal_adaptation_snapshot_check','tasks',"task_type<>'journal_adaptation' OR ((input_snapshot->>'kind'='journal_adaptation' AND input_snapshot->>'workflow_version'='journal_adaptation_v1' AND jsonb_typeof(input_snapshot->'manuscript')='object' AND jsonb_typeof(input_snapshot->'selected_action_ids')='array' AND input_snapshot->'real_model_calls'='false'::jsonb AND input_snapshot->'real_network_calls'='false'::jsonb) IS TRUE)")
    for table in tables():table.create(op.get_bind())
    op.execute("""CREATE FUNCTION journal_adaptation_seal() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      IF TG_TABLE_NAME='journal_adaptations' AND TG_OP='UPDATE' AND OLD.result_json IS NULL AND NEW.result_json IS NOT NULL
        AND (to_jsonb(NEW)-ARRAY['result_json','result_sha256','output_version_id'])=(to_jsonb(OLD)-ARRAY['result_json','result_sha256','output_version_id']) THEN RETURN NEW; END IF;
      RAISE EXCEPTION 'Immutable journal adaptation history'; END $$""")
    for name in ('journal_adaptations','journal_submission_events'):
        op.execute('CREATE TRIGGER '+name+'_seal BEFORE UPDATE OR DELETE ON '+name+' FOR EACH ROW EXECUTE FUNCTION journal_adaptation_seal()')
def downgrade():
    if any(op.get_bind().exec_driver_sql('SELECT EXISTS(SELECT 1 FROM '+t.name+')').scalar_one() for t in tables()):raise RuntimeError('Journal adaptation history exists; refusing destructive downgrade.')
    for table in reversed(tables()):table.drop(op.get_bind())
    op.execute('DROP FUNCTION journal_adaptation_seal()')
    op.drop_constraint('tasks_journal_adaptation_snapshot_check','tasks',type_='check')
    op.drop_constraint('tasks_type_check','tasks',type_='check')
    op.create_check_constraint('tasks_type_check','tasks','task_type IN ('+OLD_TYPES+')')
