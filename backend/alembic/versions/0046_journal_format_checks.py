"""Frozen additive author guides, target confirmations and independent checks."""
from alembic import op
revision='0046_journal_format_checks'
down_revision='0045_journal_recommendations'
branch_labels=None
depends_on=None
OLD_TYPES="'boxplot', 'explanation', 'word_report', 'parse_file', 'extract_dataset', 'prepare_dataset', 'review_ocr', 'analysis_plan', 'analysis_recommendation', 'figure_projection', 'figure_workbench', 'figure_explanation', 'collection_word_report', 'statistics_compute', 'literature_search', 'literature_assistance', 'manuscript_draft', 'manuscript_docx', 'pdf_export', 'manuscript_writing', 'layout_docx', 'school_template_parse'" + ", 'journal_recommendation'"
FORMAT_SNAPSHOT_CHECK="task_type<>'journal_format_check' OR ((input_snapshot->>'kind'='journal_format_check' AND input_snapshot->>'workflow_version'='journal_format_check_v1' AND jsonb_typeof(input_snapshot->'target')='object' AND jsonb_typeof(input_snapshot->'manuscript')='object' AND input_snapshot->>'check_version'='1' AND input_snapshot->'real_model_calls'='false'::jsonb AND input_snapshot->'real_network_calls'='false'::jsonb) IS TRUE)"
"""Small owner-scoped append-only guide, target and check history."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

def define_journal_format_tables(metadata):
    def common(prefix):
        return [sa.Column('id',sa.Text,primary_key=True),sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),sa.Column('idempotency_key',sa.Text,nullable=False),sa.Column('request_json',JSONB,nullable=False),sa.Column('request_digest',sa.Text,nullable=False),sa.Column('snapshot_json',JSONB,nullable=False),sa.Column('snapshot_sha256',sa.Text,nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.UniqueConstraint('id','project_id','user_id',name=prefix+'_scope_key'),sa.UniqueConstraint('project_id','user_id','idempotency_key',name=prefix+'_request_key'),sa.ForeignKeyConstraint(['project_id','user_id'],['projects.id','projects.owner_id'],name=prefix+'_owner_fk'),sa.CheckConstraint("idempotency_key ~ '^[!-~]{1,128}$' AND request_digest ~ '^[0-9a-f]{64}$' AND snapshot_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(request_json)='object' AND jsonb_typeof(snapshot_json)='object'",name=prefix+'_json_check')]
    def scoped(column,table,prefix):
        return sa.ForeignKeyConstraint([column,'project_id','user_id'],[table+'.id',table+'.project_id',table+'.user_id'],name=prefix+'_scope_fk')
    guides=sa.Table('journal_guides',metadata,*common('jg'),sa.Column('profile_id',sa.Text,nullable=False),sa.Column('previous_version_id',sa.Text),sa.Column('requirements_version',sa.Text,nullable=False),scoped('profile_id','journal_profiles','jg_profile'),scoped('previous_version_id','journal_guides','jg_previous'),sa.UniqueConstraint('previous_version_id',name='jg_single_successor'),sa.CheckConstraint("requirements_version ~ '^[0-9a-f]{64}$' AND (previous_version_id IS NULL OR previous_version_id<>id)",name='jg_version_check'))
    targets=sa.Table('journal_targets',metadata,*common('jt'),sa.Column('recommendation_id',sa.Text,nullable=False),sa.Column('profile_id',sa.Text,nullable=False),sa.Column('guide_id',sa.Text,nullable=False),scoped('recommendation_id','journal_recommendations','jt_recommendation'),scoped('profile_id','journal_profiles','jt_profile'),scoped('guide_id','journal_guides','jt_guide'))
    checks=sa.Table('journal_format_checks',metadata,*common('jfc'),sa.Column('target_id',sa.Text,nullable=False),sa.Column('guide_id',sa.Text,nullable=False),sa.Column('task_id',sa.Text,nullable=False,unique=True),sa.Column('manuscript_id',sa.Text,nullable=False),sa.Column('manuscript_revision',sa.Integer,nullable=False),sa.Column('manuscript_version_id',sa.Text,nullable=False),sa.Column('result_json',JSONB(none_as_null=True)),sa.Column('result_sha256',sa.Text),scoped('target_id','journal_targets','jfc_target'),scoped('guide_id','journal_guides','jfc_guide'),scoped('task_id','tasks','jfc_task'),scoped('manuscript_id','manuscripts','jfc_manuscript'),sa.ForeignKeyConstraint(['manuscript_id','manuscript_revision'],['manuscript_versions.manuscript_id','manuscript_versions.revision'],name='jfc_revision_fk'),sa.ForeignKeyConstraint(['manuscript_version_id','manuscript_id'],['manuscript_versions.id','manuscript_versions.manuscript_id'],name='jfc_version_fk'),sa.CheckConstraint("(result_json IS NULL AND result_sha256 IS NULL) OR (jsonb_typeof(result_json)='object' AND result_sha256 ~ '^[0-9a-f]{64}$')",name='jfc_result_check'))
    for table in (guides,targets,checks):sa.Index(table.name+'_project_created',table.c.project_id,table.c.created_at.desc(),table.c.id)
    return guides,targets,checks

def tables():
    metadata=sa.MetaData()
    for name,columns in [('projects',('id','owner_id')),('tasks',('id','project_id','user_id')),('journal_profiles',('id','project_id','user_id')),('journal_recommendations',('id','project_id','user_id')),('manuscripts',('id','project_id','user_id')),('manuscript_versions',('id','manuscript_id','revision'))]:
        sa.Table(name,metadata,*(sa.Column(c,sa.Text) for c in columns))
    return define_journal_format_tables(metadata)

def upgrade():
    op.drop_constraint('tasks_type_check','tasks',type_='check')
    op.create_check_constraint('tasks_type_check','tasks',"task_type IN ("+OLD_TYPES+", 'journal_format_check')")
    op.create_check_constraint('tasks_journal_format_snapshot_check','tasks',FORMAT_SNAPSHOT_CHECK)
    for table in tables():table.create(op.get_bind())
    op.add_column('journal_material_refs',sa.Column('guide_id',sa.Text))
    op.create_foreign_key('jmr_guide_scope_fk','journal_material_refs','journal_guides',['guide_id','project_id','user_id'],['id','project_id','user_id'])
    op.drop_constraint('jmr_parent_check','journal_material_refs',type_='check')
    op.create_check_constraint('jmr_parent_check','journal_material_refs','num_nonnulls(profile_id,recommendation_id,guide_id)=1')
    op.execute("""CREATE FUNCTION journal_format_seal() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      IF TG_TABLE_NAME='journal_format_checks' AND TG_OP='UPDATE' AND OLD.result_json IS NULL AND NEW.result_json IS NOT NULL
        AND (to_jsonb(NEW)-ARRAY['result_json','result_sha256'])=(to_jsonb(OLD)-ARRAY['result_json','result_sha256']) THEN RETURN NEW; END IF;
      RAISE EXCEPTION 'Immutable journal format history'; END $$""")
    for name in ('journal_guides','journal_targets','journal_format_checks'):
        op.execute('CREATE TRIGGER '+name+'_seal BEFORE UPDATE OR DELETE ON '+name+' FOR EACH ROW EXECUTE FUNCTION journal_format_seal()')

def downgrade():
    if any(op.get_bind().exec_driver_sql('SELECT EXISTS(SELECT 1 FROM '+t.name+')').scalar_one() for t in tables()):raise RuntimeError('Journal format history exists; refusing destructive downgrade.')
    op.drop_constraint('jmr_parent_check','journal_material_refs',type_='check')
    op.create_check_constraint('jmr_parent_check','journal_material_refs','(profile_id IS NULL)<>(recommendation_id IS NULL)')
    op.drop_constraint('jmr_guide_scope_fk','journal_material_refs',type_='foreignkey')
    op.drop_column('journal_material_refs','guide_id')
    for table in reversed(tables()):table.drop(op.get_bind())
    op.execute('DROP FUNCTION journal_format_seal()')
    op.drop_constraint('tasks_journal_format_snapshot_check','tasks',type_='check')
    op.drop_constraint('tasks_type_check','tasks',type_='check')
    op.create_check_constraint('tasks_type_check','tasks','task_type IN ('+OLD_TYPES+')')
