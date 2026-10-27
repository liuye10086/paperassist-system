"""Append-only admin account audit and safe operational events."""
from alembic import op
import sqlalchemy as sa
from app.db.admin_operations_schema import define_admin_operations_tables

revision='0051_admin_operations'
down_revision='0050_review_round_returns'
branch_labels=None
depends_on=None


def tables():
    metadata=sa.MetaData()
    sa.Table('users',metadata,sa.Column('id',sa.Text))
    sa.Table('tasks',metadata,sa.Column('id',sa.Text))
    return define_admin_operations_tables(metadata)


def upgrade():
    op.add_column('users',sa.Column('admin_revision',sa.Integer,nullable=False,server_default=sa.text('1')))
    op.create_check_constraint('users_admin_revision_check','users','admin_revision>=1')
    for table in tables(): table.create(op.get_bind())
    op.execute('INSERT INTO operational_collection(id,started_at) VALUES(1,clock_timestamp())')
    op.execute("""CREATE FUNCTION admin_operations_seal() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Immutable operational history'; END $$""")
    for table in tables():
        op.execute('CREATE TRIGGER '+table.name+'_seal BEFORE UPDATE OR DELETE ON '+table.name+
                   ' FOR EACH ROW EXECUTE FUNCTION admin_operations_seal()')


def downgrade():
    if any(op.get_bind().exec_driver_sql('SELECT EXISTS(SELECT 1 FROM '+name+')').scalar_one()
           for name in ('admin_audit_events','operational_request_events')):
        raise RuntimeError('Operational history exists; refusing destructive downgrade.')
    for table in reversed(tables()): table.drop(op.get_bind())
    op.execute('DROP FUNCTION admin_operations_seal()')
    op.drop_constraint('users_admin_revision_check','users',type_='check')
    op.drop_column('users','admin_revision')
