"""Finite configuration revisions, evidence, atomic pointer and immutable bindings."""
from alembic import op
import sqlalchemy as sa
from app.db.admin_configuration_schema import define_admin_configuration_tables, IMMUTABLE_TABLES

revision='0052_admin_configurations'
down_revision='0051_admin_operations'
branch_labels=None
depends_on=None


def tables():
    metadata=sa.MetaData()
    sa.Table('users',metadata,sa.Column('id',sa.Text))
    sa.Table('tasks',metadata,sa.Column('id',sa.Text))
    return define_admin_configuration_tables(metadata)


def upgrade():
    for table in tables():table.create(op.get_bind())
    op.execute('INSERT INTO admin_configuration_pointer(id,revision) VALUES(1,0)')
    op.execute("""CREATE FUNCTION admin_configuration_seal() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Immutable configuration history'; END $$""")
    for name in IMMUTABLE_TABLES:
        op.execute('CREATE TRIGGER '+name+'_seal BEFORE UPDATE OR DELETE ON '+name+
                   ' FOR EACH ROW EXECUTE FUNCTION admin_configuration_seal()')


def downgrade():
    if any(op.get_bind().exec_driver_sql('SELECT EXISTS(SELECT 1 FROM '+name+')').scalar_one() for name in IMMUTABLE_TABLES):
        raise RuntimeError('Configuration history exists; refusing destructive downgrade.')
    for table in reversed(tables()):table.drop(op.get_bind())
    op.execute('DROP FUNCTION admin_configuration_seal()')
