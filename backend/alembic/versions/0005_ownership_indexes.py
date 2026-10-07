"""Add ownership and resource run indexes without changing persisted values."""
from alembic import op
import sqlalchemy as sa
revision = '0005_ownership_indexes'
down_revision = '0004_language_preferences'
branch_labels = None
depends_on = None

def upgrade():
    op.create_index('projects_owner_updated', 'projects', ['owner_id', sa.text('updated_at DESC'), sa.text('id ASC')])
    for table in ('explanations', 'explanation_jobs', 'reports'):
        op.create_index(table + '_run', table, ['analysis_run_id'])

def downgrade():
    for table in ('reports', 'explanation_jobs', 'explanations'):
        op.drop_index(table + '_run', table_name=table)
    op.drop_index('projects_owner_updated', table_name='projects')
