"""Add explicit saved figure adoptions; preserve all sealed revision payloads."""
from alembic import op
import sqlalchemy as sa
from app.db.review_figure_schema import define_review_figure_tables

revision='0054_review_figure_adoptions'
down_revision='0053_storage_governance'
branch_labels=None
depends_on=None


def tables():
    metadata=sa.MetaData()
    for name,columns in [('projects',('id','owner_id')),('review_rounds',('id','project_id','user_id')),
        ('review_opinion_task_links',('id','project_id','user_id')),('tasks',('id','project_id','user_id')),
        ('files',('id','project_id')),('analysis_runs',('id',)),('figures',('id',)),
        ('manuscripts',('id','project_id','user_id')),('manuscript_versions',('id','manuscript_id'))]:
        sa.Table(name,metadata,*(sa.Column(c,sa.Text) for c in columns))
    return define_review_figure_tables(metadata)


def upgrade():
    for table in tables():table.create(op.get_bind())
    op.execute('CREATE TRIGGER review_figure_adoptions_seal BEFORE UPDATE OR DELETE ON review_figure_adoptions FOR EACH ROW EXECUTE FUNCTION review_continuation_seal()')
    # Reuse the existing project/file deletion barrier, with this table's own
    # project_id/file_id fields; the historical 0053 table list stays unchanged.
    op.execute('CREATE TRIGGER storage_deletion_guard BEFORE INSERT OR UPDATE ON review_figure_adoptions FOR EACH ROW EXECUTE FUNCTION storage_guard_review_analysis_adoptions()')


def downgrade():
    if op.get_bind().exec_driver_sql('SELECT EXISTS(SELECT 1 FROM review_figure_adoptions)').scalar_one():
        raise RuntimeError('Figure adoption history exists; refusing destructive downgrade.')
    for table in reversed(tables()):table.drop(op.get_bind())
