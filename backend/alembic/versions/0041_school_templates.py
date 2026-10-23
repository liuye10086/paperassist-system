"""Add immutable school template intake without rewriting existing history."""
from alembic import op
revision='0041_school_templates'
down_revision='0040_manuscript_writing_live'
branch_labels=None
depends_on=None
"""Additive owner-scoped school template configuration and sealed source history."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def define_school_template_tables(metadata):
    def scope(prefix):
        return [sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),
            sa.ForeignKeyConstraint(['project_id','user_id'],['projects.id','projects.owner_id'],name=prefix+'_owner_fk')]
    def request(prefix):
        return [sa.Column('idempotency_key',sa.Text,nullable=False),sa.Column('request_json',JSONB,nullable=False),sa.Column('request_digest',sa.Text,nullable=False),
            sa.CheckConstraint("idempotency_key ~ '^[!-~]{1,128}$' AND request_digest ~ '^[0-9a-f]{64}$' AND jsonb_typeof(request_json)='object'",name=prefix+'_request_check')]
    versions=sa.Table('school_template_versions',metadata,sa.Column('id',sa.Text,primary_key=True),*scope('stv'),*request('stv'),
        sa.Column('name',sa.Text,nullable=False),sa.Column('school',sa.Text,nullable=False),sa.Column('version_label',sa.Text,nullable=False),
        sa.Column('task_id',sa.Text,nullable=False,unique=True),sa.Column('sources_sha256',sa.Text,nullable=False),
        sa.Column('analysis_json',JSONB(none_as_null=True)),sa.Column('analysis_sha256',sa.Text),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('id','project_id','user_id',name='stv_scope_key'),
        sa.UniqueConstraint('project_id','user_id','idempotency_key',name='stv_request_key'),
        sa.ForeignKeyConstraint(['task_id','project_id','user_id'],['tasks.id','tasks.project_id','tasks.user_id'],name='stv_task_scope_fk'),
        sa.CheckConstraint("sources_sha256 ~ '^[0-9a-f]{64}$' AND ((analysis_json IS NULL AND analysis_sha256 IS NULL) OR (jsonb_typeof(analysis_json)='object' AND analysis_sha256 ~ '^[0-9a-f]{64}$'))",name='stv_hashes_check'))
    sources=sa.Table('school_template_sources',metadata,sa.Column('id',sa.Text,primary_key=True),*scope('sts'),
        sa.Column('template_version_id',sa.Text,nullable=False),sa.Column('file_id',sa.Text,nullable=False),
        sa.Column('role',sa.Text,nullable=False),sa.Column('source_json',JSONB,nullable=False),sa.Column('sha256',sa.Text,nullable=False),
        sa.Column('document_version_id',sa.Text),
        sa.ForeignKeyConstraint(['template_version_id','project_id','user_id'],['school_template_versions.id','school_template_versions.project_id','school_template_versions.user_id'],name='sts_version_scope_fk'),
        sa.ForeignKeyConstraint(['file_id','project_id'],['files.id','files.project_id'],name='sts_file_scope_fk'),
        sa.ForeignKeyConstraint(['document_version_id','file_id'],['file_parse_results.id','file_parse_results.file_id'],name='sts_document_scope_fk'),
        sa.UniqueConstraint('template_version_id','file_id',name='sts_file_key'),
        sa.CheckConstraint("role IN ('template','supplement','manuscript') AND sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(source_json)='object' AND (role<>'supplement' OR document_version_id IS NOT NULL)",name='sts_source_check'))
    confirmations=sa.Table('school_template_confirmations',metadata,sa.Column('id',sa.Text,primary_key=True),*scope('stc'),*request('stc'),
        sa.Column('template_version_id',sa.Text,nullable=False),sa.Column('analysis_sha256',sa.Text,nullable=False),
        sa.Column('snapshot_json',JSONB,nullable=False),sa.Column('snapshot_sha256',sa.Text,nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.ForeignKeyConstraint(['template_version_id','project_id','user_id'],['school_template_versions.id','school_template_versions.project_id','school_template_versions.user_id'],name='stc_version_scope_fk'),
        sa.UniqueConstraint('id','project_id','user_id',name='stc_scope_key'),sa.UniqueConstraint('template_version_id',name='stc_version_key'),
        sa.UniqueConstraint('template_version_id','idempotency_key',name='stc_request_key'),
        sa.CheckConstraint("analysis_sha256 ~ '^[0-9a-f]{64}$' AND snapshot_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(snapshot_json)='object'",name='stc_hash_check'))
    profiles=sa.Table('thesis_profiles',metadata,*scope('tp'),sa.Column('revision',sa.Integer,nullable=False),
        *(sa.Column(k,sa.Text,nullable=False) for k in ('school','department','major','degree_type','education_level','applicable_version')),
        sa.Column('bound_confirmation_id',sa.Text),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),
        sa.PrimaryKeyConstraint('project_id'),
        sa.ForeignKeyConstraint(['bound_confirmation_id','project_id','user_id'],['school_template_confirmations.id','school_template_confirmations.project_id','school_template_confirmations.user_id'],name='tp_binding_scope_fk'),
        sa.CheckConstraint('revision>=1',name='tp_revision_check'))
    sa.Index('stv_project_created',versions.c.project_id,versions.c.created_at.desc(),versions.c.id)
    return profiles,versions,sources,confirmations

OLD_TYPES="'boxplot', 'explanation', 'word_report', 'parse_file', 'extract_dataset', 'prepare_dataset', 'review_ocr', 'analysis_plan', 'analysis_recommendation', 'figure_projection', 'figure_workbench', 'figure_explanation', 'collection_word_report', 'statistics_compute', 'literature_search', 'literature_assistance', 'manuscript_draft', 'manuscript_docx', 'pdf_export', 'manuscript_writing', 'layout_docx'"

def frozen_tables():
    metadata=sa.MetaData()
    for name,columns in (('projects',('id','owner_id')),('tasks',('id','project_id','user_id')),('files',('id','project_id')),('file_parse_results',('id','file_id'))):
        sa.Table(name,metadata,*(sa.Column(c,sa.Text) for c in columns))
    return define_school_template_tables(metadata)

def upgrade():
    op.create_unique_constraint('files_project_scope_key','files',['id','project_id'])
    op.create_unique_constraint('fpr_file_scope_key','file_parse_results',['id','file_id'])
    op.drop_constraint('tasks_type_check','tasks',type_='check')
    op.create_check_constraint('tasks_type_check','tasks',"task_type IN ("+OLD_TYPES+", 'school_template_parse')")
    profiles,versions,sources,confirmations=frozen_tables()
    for table in (versions,sources,confirmations,profiles): table.create(op.get_bind())
    op.execute("""CREATE FUNCTION school_template_seal() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF TG_TABLE_NAME='school_template_versions' AND TG_OP='UPDATE' AND OLD.analysis_json IS NULL
          AND NEW.analysis_json IS NOT NULL AND (to_jsonb(NEW)-ARRAY['analysis_json','analysis_sha256'])=(to_jsonb(OLD)-ARRAY['analysis_json','analysis_sha256'])
        THEN RETURN NEW; END IF;
        RAISE EXCEPTION 'Immutable school template history';
      END $$""")
    for table in ('school_template_versions','school_template_sources','school_template_confirmations'):
        op.execute('CREATE TRIGGER '+table+'_seal BEFORE UPDATE OR DELETE ON '+table+' FOR EACH ROW EXECUTE FUNCTION school_template_seal()')

def downgrade():
    bind=op.get_bind()
    if any(bind.exec_driver_sql('SELECT EXISTS(SELECT 1 FROM '+t.name+')').scalar_one() for t in frozen_tables()):
        raise RuntimeError('School template history exists; refusing destructive downgrade.')
    profiles,versions,sources,confirmations=frozen_tables()
    for table in (profiles,confirmations,sources,versions): table.drop(bind)
    op.execute('DROP FUNCTION school_template_seal()')
    op.drop_constraint('tasks_type_check','tasks',type_='check')
    op.create_check_constraint('tasks_type_check','tasks','task_type IN ('+OLD_TYPES+')')
    op.drop_constraint('fpr_file_scope_key','file_parse_results',type_='unique')
    op.drop_constraint('files_project_scope_key','files',type_='unique')
