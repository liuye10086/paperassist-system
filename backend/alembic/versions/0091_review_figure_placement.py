"""Allow a customer to choose a review illustration's section without supplying a caption."""
from alembic import op
import sqlalchemy as sa

revision = '0091_review_figure_placement'
down_revision = '0090_material_submissions'
branch_labels = depends_on = None


def result_check(minimum):
    table = 'paper_material_notes'
    name = 'paper_material_notes_result_check'
    op.drop_constraint(name, table, type_='check')
    op.create_check_constraint(name, table,
                               f'length(result_text) BETWEEN {minimum} AND 20000 AND result_text = btrim(result_text)')


def upgrade():
    result_check(0)


def downgrade():
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM paper_material_notes WHERE result_text='')")).scalar_one():
        raise RuntimeError('Caption-free figure placements exist; downgrade would lose their settings.')
    result_check(1)
