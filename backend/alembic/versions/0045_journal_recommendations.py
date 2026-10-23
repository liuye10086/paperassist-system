"""Add sealed journal source versions and public recommendation tasks."""
from alembic import op
import sqlalchemy as sa
revision='0045_journal_recommendations'
down_revision='0044_school_changes'
branch_labels=None
depends_on=None
OLD_TYPES="'boxplot', 'explanation', 'word_report', 'parse_file', 'extract_dataset', 'prepare_dataset', 'review_ocr', 'analysis_plan', 'analysis_recommendation', 'figure_projection', 'figure_workbench', 'figure_explanation', 'collection_word_report', 'statistics_compute', 'literature_search', 'literature_assistance', 'manuscript_draft', 'manuscript_docx', 'pdf_export', 'manuscript_writing', 'layout_docx', 'school_template_parse'"

from sqlalchemy.dialects.postgresql import JSONB

def define_journal_tables(metadata):
    def common(name):
        return [sa.Column('id',sa.Text,primary_key=True),sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),
            sa.Column('idempotency_key',sa.Text,nullable=False),sa.Column('request_json',JSONB,nullable=False),sa.Column('request_digest',sa.Text,nullable=False),
            sa.Column('snapshot_json',JSONB,nullable=False),sa.Column('snapshot_sha256',sa.Text,nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
            sa.UniqueConstraint('id','project_id','user_id',name=name+'_scope_key'),sa.UniqueConstraint('project_id','user_id','idempotency_key',name=name+'_request_key'),
            sa.ForeignKeyConstraint(['project_id','user_id'],['projects.id','projects.owner_id'],name=name+'_owner_fk'),
            sa.CheckConstraint("idempotency_key ~ '^[!-~]{1,128}$' AND request_digest ~ '^[0-9a-f]{64}$' AND snapshot_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(request_json)='object' AND jsonb_typeof(snapshot_json)='object'",name=name+'_json_check')]
    profiles=sa.Table('journal_profiles',metadata,*common('jp'),sa.Column('previous_version_id',sa.Text),
        sa.ForeignKeyConstraint(['previous_version_id','project_id','user_id'],['journal_profiles.id','journal_profiles.project_id','journal_profiles.user_id'],name='jp_previous_scope_fk'),
        sa.UniqueConstraint('previous_version_id',name='jp_single_successor'),sa.CheckConstraint('previous_version_id IS NULL OR previous_version_id<>id',name='jp_previous_check'))
    recommendations=sa.Table('journal_recommendations',metadata,*common('jr'),sa.Column('task_id',sa.Text,nullable=False,unique=True),
        sa.Column('manuscript_id',sa.Text),sa.Column('manuscript_revision',sa.Integer),
        sa.Column('result_json',JSONB(none_as_null=True)),sa.Column('result_sha256',sa.Text),
        sa.ForeignKeyConstraint(['task_id','project_id','user_id'],['tasks.id','tasks.project_id','tasks.user_id'],name='jr_task_scope_fk'),
        sa.ForeignKeyConstraint(['manuscript_id','project_id','user_id'],['manuscripts.id','manuscripts.project_id','manuscripts.user_id'],name='jr_manuscript_scope_fk'),
        sa.ForeignKeyConstraint(['manuscript_id','manuscript_revision'],['manuscript_versions.manuscript_id','manuscript_versions.revision'],name='jr_manuscript_revision_fk'),
        sa.CheckConstraint('(manuscript_id IS NULL)=(manuscript_revision IS NULL)',name='jr_manuscript_check'),
        sa.CheckConstraint("(result_json IS NULL AND result_sha256 IS NULL) OR (jsonb_typeof(result_json)='object' AND result_sha256 ~ '^[0-9a-f]{64}$')",name='jr_result_check'))
    references=sa.Table('journal_material_refs',metadata,sa.Column('id',sa.Text,primary_key=True),sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),
        sa.Column('profile_id',sa.Text),sa.Column('recommendation_id',sa.Text),sa.Column('file_id',sa.Text,nullable=False),
        sa.Column('document_version_id',sa.Text,sa.ForeignKey('file_parse_results.id')),sa.Column('ocr_review_version_id',sa.Text,sa.ForeignKey('ocr_review_versions.id')),
        sa.Column('external_evidence_version_id',sa.Text,sa.ForeignKey('external_evidence_versions.id')),
        sa.ForeignKeyConstraint(['profile_id','project_id','user_id'],['journal_profiles.id','journal_profiles.project_id','journal_profiles.user_id'],name='jmr_profile_scope_fk'),
        sa.ForeignKeyConstraint(['recommendation_id','project_id','user_id'],['journal_recommendations.id','journal_recommendations.project_id','journal_recommendations.user_id'],name='jmr_recommendation_scope_fk'),
        sa.ForeignKeyConstraint(['file_id','project_id'],['files.id','files.project_id'],name='jmr_file_scope_fk'),
        sa.CheckConstraint('(profile_id IS NULL)<>(recommendation_id IS NULL)',name='jmr_parent_check'))
    for table in (profiles,recommendations):sa.Index(table.name+'_project_created',table.c.project_id,table.c.created_at.desc(),table.c.id)
    sa.Index('jmr_file',references.c.file_id)
    return profiles,recommendations,references


def tables():
    metadata=sa.MetaData()
    for name,columns in [('projects',('id','owner_id')),('tasks',('id','project_id','user_id')),('files',('id','project_id')),('manuscripts',('id','project_id','user_id')),('manuscript_versions',('manuscript_id','revision')),('file_parse_results',('id',)),('ocr_review_versions',('id',)),('external_evidence_versions',('id',))]:
        sa.Table(name,metadata,*(sa.Column(c,sa.Text) for c in columns))
    return define_journal_tables(metadata)

def upgrade():
    op.drop_constraint('tasks_type_check','tasks',type_='check')
    op.create_check_constraint('tasks_type_check','tasks',"task_type IN ("+OLD_TYPES+", 'journal_recommendation')")
    op.create_check_constraint('tasks_journal_snapshot_check','tasks',"task_type<>'journal_recommendation' OR ((input_snapshot->>'kind'='journal_recommendation' AND input_snapshot->>'workflow_version'='journal_recommendation_v1' AND jsonb_typeof(input_snapshot->'profiles')='array' AND jsonb_typeof(input_snapshot->'research')='object' AND input_snapshot->'real_model_calls'='false'::jsonb AND input_snapshot->'real_network_calls'='false'::jsonb) IS TRUE)")
    for table in tables():table.create(op.get_bind())
    op.execute("""CREATE FUNCTION journal_seal() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      IF TG_TABLE_NAME='journal_recommendations' AND TG_OP='UPDATE' AND OLD.result_json IS NULL AND NEW.result_json IS NOT NULL
        AND (to_jsonb(NEW)-ARRAY['result_json','result_sha256'])=(to_jsonb(OLD)-ARRAY['result_json','result_sha256']) THEN RETURN NEW; END IF;
      RAISE EXCEPTION 'Immutable journal history'; END $$""")
    for table in ('journal_profiles','journal_recommendations','journal_material_refs'):
        op.execute('CREATE TRIGGER '+table+'_seal BEFORE UPDATE OR DELETE ON '+table+' FOR EACH ROW EXECUTE FUNCTION journal_seal()')

def downgrade():
    if any(op.get_bind().exec_driver_sql('SELECT EXISTS(SELECT 1 FROM '+t.name+')').scalar_one() for t in tables()):raise RuntimeError('Journal history exists; refusing destructive downgrade.')
    for table in reversed(tables()):table.drop(op.get_bind())
    op.execute('DROP FUNCTION journal_seal()')
    op.drop_constraint('tasks_journal_snapshot_check','tasks',type_='check')
    op.drop_constraint('tasks_type_check','tasks',type_='check')
    op.create_check_constraint('tasks_type_check','tasks','task_type IN ('+OLD_TYPES+')')
