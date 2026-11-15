"""Serialize account erasure with session refresh and recover pending deletions."""

from pathlib import Path

from alembic import op

from app.db.database import get_database_config


revision = '0081_account_deletion_sessions'
down_revision = '0080_account_deletion'
branch_labels = depends_on = None


def install(path):
    connection = op.get_bind()
    config = get_database_config()
    quote = connection.dialect.identifier_preparer.quote_identifier
    schema = quote(config.schema)
    role = quote(config.url.username)
    sql = path.read_text(encoding='utf-8').replace('CREATE FUNCTION ', 'CREATE OR REPLACE FUNCTION ', 1)
    connection.exec_driver_sql(sql.replace('__APP_SCHEMA__', schema), execution_options={'no_parameters': True})
    signature = f'{schema}.erase_account_records(text, text, integer, jsonb)'
    connection.exec_driver_sql(f'REVOKE ALL ON FUNCTION {signature} FROM PUBLIC')
    connection.exec_driver_sql(f'GRANT EXECUTE ON FUNCTION {signature} TO {role}')


def upgrade():
    install(Path(__file__).with_suffix('.sql'))


def downgrade():
    install(Path(__file__).with_name('0080_account_deletion.sql'))
