"""0057 migration retains old request events and refuses evidence loss."""
from datetime import datetime,timezone
from uuid import uuid4

import pytest
from alembic import command

from app.db.database import alembic_config,migration_connection


def test_0057_keeps_legacy_rows_unknown_and_preserves_append_only_history(postgres_migration_config):
    settings=alembic_config()
    settings.attributes['database_config']=postgres_migration_config
    with migration_connection(write=True) as db:
        settings.attributes['connection']=db.raw_connection
        command.downgrade(settings,'0056_school_rule_suggestions')
        db.execute('''INSERT INTO operational_request_events(request_id,route_template,method,status,elapsed_ms,created_at)
            VALUES(%s,'/api/v1/tasks/{task_id}/resume','POST',202,3,%s)''',(uuid4().hex,datetime.now(timezone.utc)))
        before=dict(db.execute('SELECT * FROM operational_request_events').fetchone())
        command.upgrade(settings,'head')
        after=dict(db.execute('SELECT * FROM operational_request_events').fetchone())
        assert after.pop('task_operation') is None
        assert after==before
    with pytest.raises(Exception,match='Immutable operational history'):
        with migration_connection(write=True) as db:
            db.execute("UPDATE operational_request_events SET task_operation='retry'")
    with pytest.raises(Exception,match='operational_task_operation_values'):
        with migration_connection(write=True) as db:
            db.execute('''INSERT INTO operational_request_events(request_id,method,status,elapsed_ms,created_at,task_operation)
                VALUES(%s,'POST',200,0,%s,'PRIVATE-INVALID')''',(uuid4().hex,datetime.now(timezone.utc)))
    with migration_connection(write=True) as db:
        db.execute('''INSERT INTO operational_request_events(request_id,route_template,method,status,elapsed_ms,created_at,task_operation)
            VALUES(%s,'/api/v1/tasks/{task_id}/resume','POST',202,0,%s,'retry')''',(uuid4().hex,datetime.now(timezone.utc)))
    with pytest.raises(RuntimeError,match='refusing destructive downgrade'):
        with migration_connection(write=True) as db:
            settings.attributes['connection']=db.raw_connection
            command.downgrade(settings,'0056_school_rule_suggestions')
