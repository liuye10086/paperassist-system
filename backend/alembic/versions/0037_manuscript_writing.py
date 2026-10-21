"""Frozen additive manuscript writing request migration."""
from alembic import op
import sqlalchemy as sa
revision='0037_manuscript_writing'
down_revision='0036_pdf_exports'
branch_labels=None
depends_on=None
"""Additive durable writing candidates; publication remains an immutable manuscript."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

def define_manuscript_writing_tables(metadata):
    table=sa.Table('manuscript_writing_requests',metadata,
        sa.Column('task_id',sa.Text,sa.ForeignKey('tasks.id'),primary_key=True),
        sa.Column('project_id',sa.Text,nullable=False),sa.Column('user_id',sa.Text,nullable=False),
        sa.Column('manuscript_id',sa.Text,nullable=False),sa.Column('base_version_id',sa.Text,nullable=False),
        sa.Column('request_json',JSONB,nullable=False),sa.Column('input_snapshot',JSONB,nullable=False),sa.Column('input_digest',sa.Text,nullable=False),
        sa.Column('candidate_json',JSONB(none_as_null=True)),sa.Column('candidate_sha256',sa.Text),
        sa.Column('published_revision',sa.Integer),sa.Column('publish_key',sa.Text),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),
        sa.ForeignKeyConstraint(['manuscript_id','project_id','user_id'],['manuscripts.id','manuscripts.project_id','manuscripts.user_id'],name='mw_root_fk'),
        sa.ForeignKeyConstraint(['base_version_id','manuscript_id'],['manuscript_versions.id','manuscript_versions.manuscript_id'],name='mw_base_fk'),
        sa.CheckConstraint("input_digest ~ '^[0-9a-f]{64}$' AND jsonb_typeof(input_snapshot)='object' AND jsonb_typeof(request_json)='object' AND updated_at>=created_at",name='mw_input_check'),
        sa.CheckConstraint("(candidate_json IS NULL AND candidate_sha256 IS NULL) OR (jsonb_typeof(candidate_json)='object' AND candidate_sha256 ~ '^[0-9a-f]{64}$')",name='mw_candidate_check'),
        sa.CheckConstraint("(published_revision IS NULL AND publish_key IS NULL) OR (published_revision>1 AND publish_key ~ '^[!-~]{1,128}$')",name='mw_publication_check'))
    sa.Index('mw_project_created',table.c.project_id,table.c.created_at.desc(),table.c.task_id)
    return (table,)

OLD_TYPES="'boxplot', 'explanation', 'word_report', 'parse_file', 'extract_dataset', 'prepare_dataset', 'review_ocr', 'analysis_plan', 'analysis_recommendation', 'figure_projection', 'figure_workbench', 'figure_explanation', 'collection_word_report', 'statistics_compute', 'literature_search', 'literature_assistance', 'manuscript_draft', 'manuscript_docx', 'pdf_export'"
def frozen_tables():
    metadata=sa.MetaData()
    for name,columns in (('tasks',('id',)),('manuscripts',('id','project_id','user_id')),('manuscript_versions',('id','manuscript_id'))):
        sa.Table(name,metadata,*(sa.Column(c,sa.Text) for c in columns))
    return define_manuscript_writing_tables(metadata)
def upgrade():
    for table in frozen_tables(): table.create(op.get_bind())
    op.drop_constraint('tasks_type_check','tasks',type_='check')
    op.create_check_constraint('tasks_type_check','tasks',"task_type IN ("+OLD_TYPES+",'manuscript_writing')")
def downgrade():
    bind=op.get_bind()
    if bind.exec_driver_sql('SELECT EXISTS(SELECT 1 FROM manuscript_writing_requests)').scalar_one() or bind.exec_driver_sql("SELECT EXISTS(SELECT 1 FROM tasks WHERE task_type='manuscript_writing')").scalar_one():
        raise RuntimeError('Writing history exists; refusing destructive downgrade.')
    op.drop_constraint('tasks_type_check','tasks',type_='check')
    op.create_check_constraint('tasks_type_check','tasks','task_type IN ('+OLD_TYPES+')')
    for table in reversed(frozen_tables()): table.drop(bind)
