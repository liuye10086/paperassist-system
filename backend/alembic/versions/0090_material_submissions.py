"""Record customer material submissions and the progress state they produce."""
from alembic import op
import sqlalchemy as sa

from app.db.customer_workspace_schema import PROGRESS_STATUSES, SUBMITTED_STATUSES, define_material_submission_tables, status_check
from app.db.schema import metadata
from app.db.storage_deletion_schema import install_file_reference_barriers


revision = '0090_material_submissions'
down_revision = '0089_paper_worksheets'
branch_labels = depends_on = None

PROGRESS, STATUS = 'customer_requirement_progress', 'customer_progress_status'
TABLES = ('customer_material_submissions', 'customer_material_submission_files')


def upgrade():
    op.drop_constraint(STATUS, PROGRESS, type_='check')
    op.create_check_constraint(STATUS, PROGRESS, status_check(SUBMITTED_STATUSES))
    schema = sa.MetaData()
    for name in ('users', 'projects', 'files', 'research_requirement_versions'):
        metadata.tables[name].to_metadata(schema)
    for table in define_material_submission_tables(schema):
        table.create(op.get_bind())
    install_file_reference_barriers(op.execute, TABLES)


def downgrade():
    if op.get_bind().execute(sa.text(f"""SELECT EXISTS (SELECT 1 FROM {PROGRESS} WHERE status='materials_submitted')
            OR EXISTS (SELECT 1 FROM customer_material_submissions)""")).scalar_one():
        raise RuntimeError('Customer material submissions exist; downgrade would lose information.')
    for name in reversed(TABLES):
        op.execute(f'DROP TRIGGER storage_deletion_guard ON {name}')
        op.execute(f'DROP FUNCTION storage_guard_{name}()')
        op.drop_table(name)
    op.drop_constraint(STATUS, PROGRESS, type_='check')
    op.create_check_constraint(STATUS, PROGRESS, status_check(PROGRESS_STATUSES))
