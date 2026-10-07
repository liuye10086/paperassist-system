"""Online migrations require a validated administrative connection."""
from contextlib import nullcontext

from alembic import context
from app.db.database import get_migration_database_config, get_database_config, migration_connection, validate_migration_connection, validate_database_pair, migration_summary, grant_runtime_access
from app.db.schema import metadata

config = context.config


def run_on_connection(connection, database_config):
    # Own and commit a transaction only when the caller supplied a bare
    # connection. Existing caller transactions retain their rollback boundary.
    transaction = nullcontext() if connection.in_transaction() else connection.begin()
    with transaction:
        runtime = get_database_config()
        validate_database_pair(database_config, runtime)
        validate_migration_connection(connection, database_config)
        migration_summary(connection, database_config, target_revision=context.get_revision_argument())
        context.configure(connection=connection, target_metadata=metadata,
            version_table_schema=database_config.schema, include_schemas=True, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
            grant_runtime_access(connection, database_config, runtime)


if context.is_offline_mode():
    raise ValueError("Offline migrations are disabled; use a validated migration connection.")
else:
    connection = config.attributes.get("connection")
    database_config = config.attributes.get("database_config") or get_migration_database_config()
    if connection is not None:
        run_on_connection(connection, database_config)
    else:
        with migration_connection(write=True, config=database_config) as database:
            run_on_connection(database.raw_connection, database_config)
