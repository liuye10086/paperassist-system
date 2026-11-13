"""Allow scoped account erasure without widening runtime table permissions."""

from pathlib import Path

from alembic import op

from app.db.database import get_database_config
from app.db.schema import account_deletions


revision = '0080_account_deletion'
down_revision = '0079_delivery_artifact_sources'
branch_labels = depends_on = None


def upgrade():
    connection = op.get_bind()
    config = get_database_config()
    quote = connection.dialect.identifier_preparer.quote_identifier
    schema = quote(config.schema)
    role = quote(config.url.username)
    account_deletions.create(connection)
    sql = Path(__file__).with_suffix('.sql').read_text(encoding='utf-8')
    connection.exec_driver_sql(sql.replace('__APP_SCHEMA__', schema), execution_options={'no_parameters': True})
    signature = f'{schema}.erase_account_records(text, text, integer, jsonb)'
    connection.exec_driver_sql(f'REVOKE ALL ON FUNCTION {signature} FROM PUBLIC')
    connection.exec_driver_sql(f'GRANT EXECUTE ON FUNCTION {signature} TO {role}')


def downgrade():
    connection = op.get_bind()
    if connection.exec_driver_sql('SELECT EXISTS (SELECT 1 FROM account_deletions)').scalar_one():
        raise RuntimeError('Finish pending account deletions before downgrading.')
    op.execute('DROP FUNCTION erase_account_records(text, text, integer, jsonb)')
    account_deletions.drop(connection)
