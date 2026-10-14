"""Retain immutable deletion decisions and reparse impact assessments."""
from alembic import op
import sqlalchemy as sa
from app.db.file_lifecycle_schema import SCOPE_FUNCTION_BODY, define_file_lifecycle_tables

revision = '0023_file_lifecycle'
down_revision = '0022_analysis_plans'
branch_labels = None
depends_on = None


def upgrade():
    metadata = sa.MetaData()
    for name in ('files', 'projects', 'users', 'tasks'):
        sa.Table(name, metadata, sa.Column('id', sa.Text, primary_key=True))
    for table in define_file_lifecycle_tables(metadata):
        table.create(op.get_bind())
    # A trigger supplies the cross-table identity constraint without adding
    # redundant unique indexes or changing any historical business row.
    op.execute('CREATE FUNCTION enforce_file_lifecycle_scope() RETURNS trigger LANGUAGE plpgsql AS $$ '
               + SCOPE_FUNCTION_BODY + ' $$')
    for name in ('file_deletion_requests', 'file_reparse_assessments'):
        op.execute(f'CREATE TRIGGER {name}_scope BEFORE INSERT OR UPDATE OR DELETE ON {name} FOR EACH ROW EXECUTE FUNCTION enforce_file_lifecycle_scope()')
    op.create_index('file_upload_batches_owner_created', 'file_upload_batches', ['project_id', 'user_id', sa.text('created_at DESC'), 'id'])


def downgrade():
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM file_deletion_requests)
      OR EXISTS (SELECT 1 FROM file_reparse_assessments)
      THEN RAISE EXCEPTION 'lifecycle history requires preservation before downgrade'; END IF; END $$""")
    op.drop_index('file_upload_batches_owner_created', table_name='file_upload_batches')
    op.drop_table('file_reparse_assessments')
    op.drop_table('file_deletion_requests')
    op.execute('DROP FUNCTION enforce_file_lifecycle_scope()')
