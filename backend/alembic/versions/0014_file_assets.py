"""Append file metadata without rewriting historical assets or provenance."""
from alembic import op
import sqlalchemy as sa

revision = '0014_file_assets'
down_revision = '0013_cost_reconciliation'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('files', sa.Column('uploader_id', sa.Text))
    op.create_foreign_key('files_uploader_id_fkey', 'files', 'users', ['uploader_id'], ['id'])
    op.add_column('files', sa.Column('storage_backend', sa.Text, nullable=False, server_default='local'))
    op.add_column('files', sa.Column('object_key', sa.Text))
    op.add_column('files', sa.Column('metadata_revision', sa.Integer, nullable=False, server_default='1'))
    op.create_check_constraint('files_storage_backend_check', 'files', "storage_backend = 'local'")
    op.create_check_constraint('files_metadata_revision_check', 'files', 'metadata_revision >= 1')
    op.execute("UPDATE files SET object_key='files/' || id || '.xlsx'")
    op.create_index('files_project_uploaded_id', 'files', ['project_id', sa.text('uploaded_at DESC'), 'id'])
    op.create_table('file_purposes',
        sa.Column('file_id', sa.Text, sa.ForeignKey('files.id'), primary_key=True),
        sa.Column('purpose', sa.Text, primary_key=True),
        sa.Column('assigned_by', sa.Text, sa.ForeignKey('users.id')),
        sa.Column('assigned_at', sa.Text, nullable=False),
        sa.CheckConstraint("purpose IN ('raw_data','figure','methods','school_template','paper','revision_material')", name='file_purposes_purpose_check'))


def downgrade():
    op.drop_table('file_purposes')
    op.drop_index('files_project_uploaded_id', table_name='files')
    op.drop_constraint('files_metadata_revision_check', 'files', type_='check')
    op.drop_constraint('files_storage_backend_check', 'files', type_='check')
    op.drop_constraint('files_uploader_id_fkey', 'files', type_='foreignkey')
    for name in ('metadata_revision', 'object_key', 'storage_backend', 'uploader_id'):
        op.drop_column('files', name)
