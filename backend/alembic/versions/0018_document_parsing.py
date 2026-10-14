"""Immutable Word parsing versions without new tables."""
from alembic import op
revision = '0018_document_parsing'
down_revision = '0017_dataset_preparation'
branch_labels = None
depends_on = None

def upgrade():
    op.drop_constraint('file_parse_results_version_check', 'file_parse_results', type_='check')
    op.create_check_constraint('file_parse_results_version_check', 'file_parse_results', 'version > 0')
    op.create_check_constraint('files_type_check', 'files', "file_type IN ('xlsx','docx')")

def downgrade():
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM files WHERE file_type='docx') OR EXISTS (SELECT 1 FROM tasks WHERE workflow_version='docx_document_v1') OR EXISTS (SELECT 1 FROM file_parse_results WHERE version<>1) THEN RAISE EXCEPTION 'document history requires preservation before downgrade'; END IF; END $$")
    op.drop_constraint('files_type_check','files',type_='check')
    op.drop_constraint('file_parse_results_version_check','file_parse_results',type_='check')
    op.create_check_constraint('file_parse_results_version_check','file_parse_results','version = 1')
