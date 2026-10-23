"""Seal new school export intent without rewriting existing export history."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision='0043_school_exports'
down_revision='0042_thesis_manuscripts'
branch_labels=None
depends_on=None
CHECK="(school_input_json IS NULL AND school_input_sha256 IS NULL) OR (school_input_json IS NOT NULL AND school_input_sha256 IS NOT NULL AND jsonb_typeof(school_input_json)='object' AND school_input_sha256 ~ '^[0-9a-f]{64}$')"

def upgrade():
    op.add_column('manuscript_exports',sa.Column('school_input_json',JSONB,nullable=True))
    op.add_column('manuscript_exports',sa.Column('school_input_sha256',sa.Text,nullable=True))
    op.create_check_constraint('me_school_input_check','manuscript_exports',CHECK)

def downgrade():
    if op.get_bind().exec_driver_sql('SELECT EXISTS(SELECT 1 FROM manuscript_exports WHERE school_input_json IS NOT NULL)').scalar_one():
        raise RuntimeError('School export history exists; refusing destructive downgrade.')
    op.drop_constraint('me_school_input_check','manuscript_exports',type_='check')
    op.drop_column('manuscript_exports','school_input_sha256')
    op.drop_column('manuscript_exports','school_input_json')
