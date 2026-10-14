"""Allow image originals; preserve all OCR history when downgrading."""
from alembic import op

revision = '0020_ocr_parsing'
down_revision = '0019_pdf_parsing'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('files_type_check', 'files', type_='check')
    op.create_check_constraint('files_type_check', 'files', "file_type IN ('xlsx','docx','pdf','png','jpeg')")


def downgrade():
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM files WHERE file_type IN ('png','jpeg')) OR EXISTS (SELECT 1 FROM tasks WHERE workflow_version='ocr_document_v1' OR input_snapshot->>'kind'='ocr_document') OR EXISTS (SELECT 1 FROM file_parse_results WHERE result_json->>'kind'='ocr_document' OR parser_version='rapidocr-3.10.0-ppocrv6-small-v1' OR settings_json ? 'ocr') THEN RAISE EXCEPTION 'OCR history requires preservation before downgrade'; END IF; END $$")
    op.drop_constraint('files_type_check', 'files', type_='check')
    op.create_check_constraint('files_type_check', 'files', "file_type IN ('xlsx','docx','pdf')")
