"""Add project delegation and bind analyst progress to a grant revision."""

from alembic import op
import sqlalchemy as sa

from app.db.schema import metadata


revision = '0078_project_assignments'
down_revision = '0077_customer_workspace'
branch_labels = depends_on = None

TABLES = ('project_assignments', 'project_assignment_events')
PROGRESS = 'customer_requirement_progress'
REVISION_CHECK = 'customer_progress_assignment_revision'


def upgrade():
    for name in TABLES:
        metadata.tables[name].create(op.get_bind())
    op.add_column(PROGRESS, sa.Column('assignment_revision', sa.BigInteger))
    op.create_check_constraint(REVISION_CHECK, PROGRESS, 'assignment_revision > 0')
    op.add_column('files', sa.Column('upload_actor_id', sa.Text, sa.ForeignKey('users.id', name='files_upload_actor_fk')))
    op.add_column('file_upload_batches', sa.Column('upload_actor_id', sa.Text,
                  sa.ForeignKey('users.id', name='file_batches_upload_actor_fk')))
    op.execute('UPDATE file_upload_batches SET upload_actor_id=user_id')
    op.alter_column('file_upload_batches', 'upload_actor_id', nullable=False)
    op.create_unique_constraint('file_batches_actor_request_key', 'file_upload_batches',
                                ['user_id', 'project_id', 'upload_actor_id', 'idempotency_key'])
    op.drop_constraint('file_batches_request_key', 'file_upload_batches', type_='unique')


def downgrade():
    for name in TABLES:
        if op.get_bind().exec_driver_sql(f'SELECT EXISTS (SELECT 1 FROM {name})').scalar_one():
            raise RuntimeError('Project assignment history exists; downgrade would lose information.')
    if op.get_bind().exec_driver_sql(f'SELECT EXISTS (SELECT 1 FROM {PROGRESS} WHERE assignment_revision IS NOT NULL)').scalar_one():
        raise RuntimeError('Delegated progress exists; downgrade would lose information.')
    op.create_unique_constraint('file_batches_request_key', 'file_upload_batches', ['user_id', 'project_id', 'idempotency_key'])
    op.drop_constraint('file_batches_actor_request_key', 'file_upload_batches', type_='unique')
    op.drop_column('file_upload_batches', 'upload_actor_id')
    op.drop_column('files', 'upload_actor_id')
    op.drop_constraint(REVISION_CHECK, PROGRESS, type_='check')
    op.drop_column(PROGRESS, 'assignment_revision')
    for name in reversed(TABLES):
        op.drop_table(name)
