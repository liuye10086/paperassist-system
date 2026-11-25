"""Store a scoped writing stream and read-only editorial replies."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0094_sci_revision_chat'
down_revision = '0093_paper_figure_cancel'
branch_labels = depends_on = None


def upgrade():
    op.add_column('manuscript_writing_requests', sa.Column('draft_chat_json', JSONB(), nullable=True))


def downgrade():
    if op.get_bind().execute(sa.text(
        'SELECT EXISTS (SELECT 1 FROM manuscript_writing_requests WHERE draft_chat_json IS NOT NULL)'
    )).scalar_one():
        raise RuntimeError('Saved draft chat replies exist.')
    op.drop_column('manuscript_writing_requests', 'draft_chat_json')
