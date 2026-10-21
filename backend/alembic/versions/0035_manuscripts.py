"""Frozen additive SCI fact draft and local DOCX migration."""
from alembic import op
revision='0035_manuscripts'
down_revision='0034_literature_pmc'
branch_labels=None
depends_on=None
"""Additive manuscript roots, immutable snapshots, typed source and citation FKs."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

def define_manuscript_tables(metadata):
    def scope(name):
        return [sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),
            sa.ForeignKeyConstraint(['project_id','user_id'],['projects.id','projects.owner_id'],name=name+'_owner_fk')]
    def request(name):
        return [sa.Column('idempotency_key',sa.Text,nullable=False),sa.Column('request_json',JSONB,nullable=False),
            sa.Column('request_digest',sa.Text,nullable=False),
            sa.CheckConstraint("idempotency_key ~ '^[!-~]{1,128}$' AND request_digest ~ '^[0-9a-f]{64}$' AND jsonb_typeof(request_json)='object'",name=name+'_request_check')]
    roots=sa.Table('manuscripts',metadata,sa.Column('id',sa.Text,primary_key=True),*scope('manuscripts'),*request('manuscripts'),
        sa.Column('current_revision',sa.Integer,nullable=False),sa.Column('title',sa.Text,nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('id','project_id','user_id',name='manuscripts_scope_key'),
        sa.UniqueConstraint('project_id','user_id','idempotency_key',name='manuscripts_request_key'),
        sa.CheckConstraint('current_revision>=1 AND updated_at>=created_at',name='manuscripts_revision_check'))
    versions=sa.Table('manuscript_versions',metadata,sa.Column('id',sa.Text,primary_key=True),*scope('mv'),*request('mv'),
        sa.Column('manuscript_id',sa.Text,nullable=False),sa.Column('revision',sa.Integer,nullable=False),
        sa.Column('parent_version_id',sa.Text),sa.Column('task_id',sa.Text,sa.ForeignKey('tasks.id'),nullable=False,unique=True),
        sa.Column('snapshot_json',JSONB,nullable=False),sa.Column('snapshot_sha256',sa.Text,nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.ForeignKeyConstraint(['manuscript_id','project_id','user_id'],['manuscripts.id','manuscripts.project_id','manuscripts.user_id'],name='mv_root_fk'),
        sa.UniqueConstraint('id','manuscript_id',name='mv_parent_scope_key'),
        sa.ForeignKeyConstraint(['parent_version_id','manuscript_id'],['manuscript_versions.id','manuscript_versions.manuscript_id'],name='mv_parent_fk'),
        sa.UniqueConstraint('manuscript_id','revision',name='mv_revision_key'),
        sa.UniqueConstraint('manuscript_id','idempotency_key',name='mv_request_key'),
        sa.CheckConstraint("revision>=1 AND ((revision=1 AND parent_version_id IS NULL) OR (revision>1 AND parent_version_id IS NOT NULL)) AND jsonb_typeof(snapshot_json)='object' AND snapshot_sha256 ~ '^[0-9a-f]{64}$'",name='mv_snapshot_check'))
    sources=sa.Table('manuscript_sources',metadata,sa.Column('id',sa.Text,primary_key=True),
        sa.Column('version_id',sa.Text,sa.ForeignKey('manuscript_versions.id'),nullable=False),
        sa.Column('file_id',sa.Text,sa.ForeignKey('files.id'),nullable=False),
        sa.Column('kind',sa.Text,nullable=False),sa.Column('source_id',sa.Text,nullable=False),sa.Column('role',sa.Text,nullable=False),
        sa.Column('document_version_id',sa.Text,sa.ForeignKey('file_parse_results.id')),
        sa.Column('ocr_review_version_id',sa.Text,sa.ForeignKey('ocr_review_versions.id')),
        sa.Column('external_evidence_version_id',sa.Text,sa.ForeignKey('external_evidence_versions.id')),
        sa.Column('analysis_run_id',sa.Text,sa.ForeignKey('analysis_runs.id')),
        sa.Column('figure_id',sa.Text,sa.ForeignKey('figures.id')),
        sa.Column('source_json',JSONB,nullable=False),sa.Column('sha256',sa.Text,nullable=False),
        sa.UniqueConstraint('version_id','source_id',name='ms_source_key'),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(source_json)='object' AND role IN ('methods','user_results','literature','image_observation','computed_results') AND ((kind='analysis_run')=(role='computed_results'))",name='ms_role_check'),
        sa.CheckConstraint("(kind='original' AND source_id=file_id AND num_nonnulls(document_version_id,ocr_review_version_id,external_evidence_version_id,analysis_run_id,figure_id)=0) OR (kind='document_version' AND source_id=document_version_id AND num_nonnulls(document_version_id,ocr_review_version_id,external_evidence_version_id,analysis_run_id,figure_id)=1) OR (kind='ocr_review_version' AND source_id=ocr_review_version_id AND num_nonnulls(document_version_id,ocr_review_version_id,external_evidence_version_id,analysis_run_id,figure_id)=1) OR (kind='external_evidence_version' AND source_id=external_evidence_version_id AND num_nonnulls(document_version_id,ocr_review_version_id,external_evidence_version_id,analysis_run_id,figure_id)=1) OR (kind='analysis_run' AND source_id=analysis_run_id AND num_nonnulls(document_version_id,ocr_review_version_id,external_evidence_version_id,analysis_run_id,figure_id)=1) OR (kind='figure' AND source_id=figure_id AND num_nonnulls(document_version_id,ocr_review_version_id,external_evidence_version_id,analysis_run_id,figure_id)=1)",name='ms_typed_source_check'))
    citations=sa.Table('manuscript_citations',metadata,sa.Column('id',sa.Text,primary_key=True),
        sa.Column('version_id',sa.Text,sa.ForeignKey('manuscript_versions.id'),nullable=False),
        sa.Column('citation_version_id',sa.Text,sa.ForeignKey('literature_citation_versions.id'),nullable=False),
        sa.Column('paragraph_id',sa.Text,nullable=False),sa.Column('claim_id',sa.Text,sa.ForeignKey('literature_claims.id'),nullable=False),
        sa.Column('claim_revision',sa.Integer,nullable=False),
        sa.Column('review_id',sa.Text,sa.ForeignKey('literature_claim_reviews.id'),nullable=False),
        sa.Column('metadata_version_id',sa.Text,sa.ForeignKey('literature_citation_metadata_versions.id'),nullable=False),
        sa.Column('project_reference_id',sa.Text,sa.ForeignKey('project_references.id'),nullable=False),
        sa.Column('binding_json',JSONB,nullable=False))
    exports=sa.Table('manuscript_exports',metadata,sa.Column('id',sa.Text,primary_key=True),
        sa.Column('version_id',sa.Text,sa.ForeignKey('manuscript_versions.id'),nullable=False),
        sa.Column('task_id',sa.Text,sa.ForeignKey('tasks.id'),nullable=False,unique=True),sa.Column('idempotency_key',sa.Text,nullable=False),
        sa.Column('metadata_json',JSONB(none_as_null=True)),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('version_id','idempotency_key',name='me_request_key'))
    for table in (roots,versions): sa.Index(table.name+'_project_created',table.c.project_id,table.c.created_at.desc(),table.c.id)
    return roots,versions,sources,citations,exports

OLD_TYPES="'boxplot', 'explanation', 'word_report', 'parse_file', 'extract_dataset', 'prepare_dataset', 'review_ocr', 'analysis_plan', 'analysis_recommendation', 'figure_projection', 'figure_workbench', 'figure_explanation', 'collection_word_report', 'statistics_compute', 'literature_search', 'literature_assistance'"
NAMES=('manuscripts','manuscript_versions','manuscript_sources','manuscript_citations','manuscript_exports')
def frozen_tables():
    metadata=sa.MetaData()
    for name,columns in (('projects',('id','owner_id')),('tasks',('id',)),('files',('id',)),('file_parse_results',('id',)),('ocr_review_versions',('id',)),('external_evidence_versions',('id',)),('analysis_runs',('id',)),('figures',('id',)),('literature_citation_versions',('id',)),('literature_claims',('id',)),('literature_claim_reviews',('id',)),('literature_citation_metadata_versions',('id',)),('project_references',('id',))):
        sa.Table(name,metadata,*(sa.Column(column,sa.Text) for column in columns))
    return define_manuscript_tables(metadata)
def upgrade():
    for table in frozen_tables(): table.create(op.get_bind())
    op.drop_constraint('tasks_type_check','tasks',type_='check')
    op.create_check_constraint('tasks_type_check','tasks',"task_type IN ("+OLD_TYPES+",'manuscript_draft','manuscript_docx')")
def downgrade():
    bind=op.get_bind()
    if any(bind.exec_driver_sql('SELECT EXISTS(SELECT 1 FROM '+name+')').scalar_one() for name in NAMES) or bind.exec_driver_sql("SELECT EXISTS(SELECT 1 FROM tasks WHERE task_type IN ('manuscript_draft','manuscript_docx'))").scalar_one():
        raise RuntimeError('Manuscript history exists; refusing destructive downgrade.')
    op.drop_constraint('tasks_type_check','tasks',type_='check')
    op.create_check_constraint('tasks_type_check','tasks','task_type IN ('+OLD_TYPES+')')
    for table in reversed(frozen_tables()): table.drop(bind)
