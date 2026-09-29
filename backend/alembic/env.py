"""Alembic reads the same validated configuration as the application."""

from alembic import context

from app.database import database_connection, get_database_config
from app.db_schema import metadata


config = context.config


def run_on_connection(connection, database_config):
    context.configure(
        connection=connection,
        target_metadata=metadata,
        version_table_schema=database_config.schema,
        include_schemas=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise ValueError("Offline migrations are disabled; use a validated PaperAssist PostgreSQL connection.")
else:
    connection = config.attributes.get("connection")
    database_config = config.attributes.get("database_config") or get_database_config()
    if connection is not None:
        run_on_connection(connection, database_config)
    else:
        with database_connection(write=True, config=database_config) as database:
            run_on_connection(database.raw_connection, database_config)
