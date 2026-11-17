"""Store optional SCI settings on the existing intake root."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = '0086_sci_project_settings'
down_revision = '0085_statistics_legacy_exports'
branch_labels = depends_on = None


def upgrade():
    op.add_column('research_intakes', sa.Column('sci_settings_json', JSONB(), nullable=True))


def downgrade():
    if op.get_bind().execute(sa.text('SELECT EXISTS (SELECT 1 FROM research_intakes WHERE sci_settings_json IS NOT NULL)')).scalar_one():
        raise RuntimeError('Cannot remove stored SCI project settings.')
    op.drop_column('research_intakes', 'sci_settings_json')
