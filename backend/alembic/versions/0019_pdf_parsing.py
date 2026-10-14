"""Extend immutable document parsing to PDF without new tables."""
from alembic import op

revision = '0019_pdf_parsing'
down_revision = '0018_document_parsing'
branch_labels = None
depends_on = None

def upgrade():
    op.drop_constraint('files_type_check', 'files', type_='check')
    op.create_check_constraint('files_type_check', 'files', "file_type IN ('xlsx','docx','pdf')")

def downgrade():
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM files WHERE file_type='pdf') OR EXISTS (SELECT 1 FROM tasks WHERE workflow_version='pdf_document_v1') OR EXISTS (SELECT 1 FROM file_parse_results WHERE result_json->>'kind'='pdf_document') THEN RAISE EXCEPTION 'PDF history requires preservation before downgrade'; END IF; END $$")
    op.drop_constraint('files_type_check', 'files', type_='check')
    op.create_check_constraint('files_type_check', 'files', "file_type IN ('xlsx','docx')")
