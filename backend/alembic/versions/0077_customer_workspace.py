"""Add explicitly published customer deliveries and customer feedback."""

from alembic import op
from sqlalchemy import MetaData

from app.db.customer_workspace_schema import define_customer_workspace_tables
from app.db.schema import metadata


revision = '0077_customer_workspace'
down_revision = '0076_account_registration'
branch_labels = depends_on = None

TABLES = ('customer_delivery_publications', 'customer_requirement_progress', 'customer_feedback')


def upgrade():
    schema = MetaData()
    for name in ('users', 'projects', 'delivery_snapshots', 'research_requirement_versions'):
        metadata.tables[name].to_metadata(schema)
    for table in define_customer_workspace_tables(schema):
        table.create(op.get_bind())


def downgrade():
    for name in TABLES:
        if op.get_bind().exec_driver_sql(f'SELECT EXISTS (SELECT 1 FROM {name})').scalar_one():
            raise RuntimeError('Customer workspace history exists; downgrade would lose information.')
    for name in reversed(TABLES):
        op.drop_table(name)
