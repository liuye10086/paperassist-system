"""Observe historical assets; enforce only newly created scopes."""
from alembic import op
import sqlalchemy as sa
from app.db.storage_governance_schema import define_storage_governance_tables
from app.db.storage_deletion_schema import define_storage_deletion_tables, install_barriers, remove_barriers

revision='0053_storage_governance'
down_revision='0052_admin_configurations'
branch_labels=None
depends_on=None


def tables():
    metadata=sa.MetaData()
    for name in ('users','projects','files'):sa.Table(name,metadata,sa.Column('id',sa.Text))
    return (*define_storage_governance_tables(metadata),*define_storage_deletion_tables(metadata))


def upgrade():
    for table in tables():table.create(op.get_bind())
    op.execute("INSERT INTO storage_policies(scope_type,scope_id,mode,limit_bytes) SELECT 'user',id,'observe_only',5368709120 FROM users")
    op.execute("INSERT INTO storage_policies(scope_type,scope_id,mode,limit_bytes) SELECT 'project',id,'observe_only',1073741824 FROM projects")
    op.execute('CREATE TRIGGER storage_policy_events_seal BEFORE UPDATE OR DELETE ON storage_policy_events FOR EACH ROW EXECUTE FUNCTION admin_configuration_seal()')
    install_barriers(op.execute)


def downgrade():
    if any(op.get_bind().exec_driver_sql('SELECT EXISTS(SELECT 1 FROM '+name+')').scalar_one()
           for name in ('storage_objects','storage_references','storage_reservations','storage_policy_events','storage_disposable_fixtures','storage_deletion_operations')):
        raise RuntimeError('Storage evidence exists; refusing destructive downgrade.')
    remove_barriers(op.execute)
    for table in reversed(tables()):table.drop(op.get_bind())
