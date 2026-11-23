"""Store editorial corrections on the exact generated draft."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0092_school_draft_edits'
down_revision = '0091_review_figure_placement'
branch_labels = depends_on = None


def upgrade():
    op.add_column('manuscript_writing_requests', sa.Column('school_draft_edits_json', JSONB(), nullable=True))


def downgrade():
    if op.get_bind().execute(sa.text(
        'SELECT EXISTS (SELECT 1 FROM manuscript_writing_requests WHERE school_draft_edits_json IS NOT NULL)'
    )).scalar_one():
        raise RuntimeError('Saved school draft edits exist.')
    op.drop_column('manuscript_writing_requests', 'school_draft_edits_json')
