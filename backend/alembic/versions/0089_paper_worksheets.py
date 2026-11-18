"""Keep the confirmed Excel sheet selection with each paper material note."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY


revision = '0089_paper_worksheets'
down_revision = '0088_paper_material_notes'
branch_labels = depends_on = None


def upgrade():
    op.add_column('paper_material_notes', sa.Column('worksheet_names', ARRAY(sa.Text)))


def downgrade():
    if op.get_bind().execute(sa.text(
            'SELECT EXISTS (SELECT 1 FROM paper_material_notes WHERE worksheet_names IS NOT NULL)'
    )).scalar_one():
        raise RuntimeError('Cannot remove confirmed manuscript worksheet selections.')
    op.drop_column('paper_material_notes', 'worksheet_names')
