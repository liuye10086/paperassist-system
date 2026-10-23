"""Nullable scoped school confirmation on immutable manuscript versions."""
from alembic import op
import sqlalchemy as sa
revision='0042_thesis_manuscripts'
down_revision='0041_school_templates'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('manuscript_versions',sa.Column('school_confirmation_id',sa.Text,nullable=True))
    op.create_foreign_key('mv_school_confirmation_scope_fk','manuscript_versions','school_template_confirmations',['school_confirmation_id','project_id','user_id'],['id','project_id','user_id'])


def downgrade():
    if op.get_bind().exec_driver_sql('SELECT EXISTS(SELECT 1 FROM manuscript_versions WHERE school_confirmation_id IS NOT NULL)').scalar_one():
        raise RuntimeError('School manuscript history exists; refusing destructive downgrade.')
    op.drop_constraint('mv_school_confirmation_scope_fk','manuscript_versions',type_='foreignkey')
    op.drop_column('manuscript_versions','school_confirmation_id')
