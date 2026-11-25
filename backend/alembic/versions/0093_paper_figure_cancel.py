"""Release paper figure assemblies without changing frozen figure versions."""
from alembic import op
import sqlalchemy as sa


revision = '0093_paper_figure_cancel'
down_revision = '0092_school_draft_edits'
branch_labels = depends_on = None


def upgrade():
    op.create_table('paper_figure_cancellations',
        sa.Column('root_id', sa.Text, primary_key=True),
        sa.Column('project_id', sa.Text, nullable=False),
        sa.Column('user_id', sa.Text, nullable=False),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['root_id', 'project_id', 'user_id'],
                                ['research_figure_versions.id', 'research_figure_versions.project_id', 'research_figure_versions.user_id'],
                                name='paper_figure_cancellation_scope'))


def downgrade():
    if op.get_bind().execute(sa.text('''SELECT EXISTS (
        SELECT 1 FROM paper_figure_cancellations
    )''')).scalar_one():
        raise RuntimeError('Cancelled figure assemblies exist.')
    op.drop_table('paper_figure_cancellations')
