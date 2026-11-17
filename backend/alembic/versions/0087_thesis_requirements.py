"""Store customer thesis requirements on the existing school profile."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = '0087_thesis_requirements'
down_revision = '0086_sci_project_settings'
branch_labels = depends_on = None


def upgrade():
    op.add_column('thesis_profiles', sa.Column('requirements_json', JSONB(), nullable=True))


def downgrade():
    if op.get_bind().execute(sa.text('SELECT EXISTS (SELECT 1 FROM thesis_profiles WHERE requirements_json IS NOT NULL)')).scalar_one():
        raise RuntimeError('Cannot remove stored thesis requirements.')
    op.drop_column('thesis_profiles', 'requirements_json')
