"""Allow TIFF originals and record owner-scoped figure and table details."""
from alembic import op
import sqlalchemy as sa

from app.db.paper_materials_schema import define_paper_material_notes
from app.db.schema import files, projects
from app.db.storage_deletion_schema import install_file_reference_barriers


revision = '0088_paper_material_notes'
down_revision = '0087_thesis_requirements'
branch_labels = depends_on = None

PREVIOUS_TYPES = "file_type IN ('xlsx','docx','pdf','png','jpeg','bio_bundle','bio_component')"
PAPER_TYPES = "file_type IN ('xlsx','docx','pdf','png','jpeg','tiff','bio_bundle','bio_component')"


def upgrade():
    op.drop_constraint('files_type_check', 'files', type_='check')
    op.create_check_constraint('files_type_check', 'files', PAPER_TYPES)
    metadata = sa.MetaData()
    for table in (projects, files):
        table.to_metadata(metadata)
    define_paper_material_notes(metadata, include_worksheet_names=False, allow_empty_result=False).create(op.get_bind())
    install_file_reference_barriers(op.execute, ('paper_material_notes',))


def downgrade():
    db = op.get_bind()
    retained = db.execute(sa.text("""SELECT EXISTS (SELECT 1 FROM paper_material_notes)
        OR EXISTS (SELECT 1 FROM files WHERE file_type='tiff')""")).scalar_one()
    if retained:
        raise RuntimeError('Cannot remove stored TIFF files or paper material notes.')
    op.execute('DROP TRIGGER storage_deletion_guard ON paper_material_notes')
    op.execute('DROP FUNCTION storage_guard_paper_material_notes()')
    op.drop_table('paper_material_notes')
    op.drop_constraint('files_type_check', 'files', type_='check')
    op.create_check_constraint('files_type_check', 'files', PREVIOUS_TYPES)
