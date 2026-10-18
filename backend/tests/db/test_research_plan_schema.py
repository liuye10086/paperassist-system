"""Research migration only extends CHECKs and preserves real v1 history."""
from tests.helpers.statistics import statistics_post
import pytest
from alembic import command
from sqlalchemy.exc import DBAPIError
from app.db.database import migration_connection, database_connection, alembic_config, verify_runtime_permissions
from tests.api.test_analysis import client
from tests.helpers.analysis_plan import confirmed_sample
from tests.integration.test_research_plan import create_research


def configure(db, config):
    alembic=alembic_config()
    alembic.attributes.update(connection=db.raw_connection,database_config=config)
    return alembic


def test_research_upgrade_preserves_all_legacy_table_values_and_indexes(client,postgres_migration_config):
    base,_,_,view=confirmed_sample(client)
    assert statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).status_code==200
    with migration_connection(config=postgres_migration_config) as db:
        config=configure(db,postgres_migration_config)
        command.downgrade(config,'0023_file_lifecycle')
        tables=[r['table_name'] for r in db.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema() AND table_name<>'alembic_version' ORDER BY table_name")]
        before={name:[dict(r) for r in db.execute('SELECT * FROM '+name)] for name in tables}
        indexes=[dict(r) for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema() ORDER BY indexname')]
        command.upgrade(config,'0024_research_plans')
        assert before=={name:[dict(r) for r in db.execute('SELECT * FROM '+name)] for name in tables}
        assert indexes==[dict(r) for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema() ORDER BY indexname')]
        assert db.execute("SELECT count(*) AS n FROM pg_constraint WHERE connamespace=current_schema()::regnamespace AND NOT convalidated").fetchone()['n']==0
        checks={r['conname']:r['definition'] for r in db.execute("SELECT conname,pg_get_constraintdef(oid) AS definition FROM pg_constraint WHERE connamespace=current_schema()::regnamespace")}
        assert 'analysis_plan_input' in checks['task_waits_kind_check']
        assert 'await_input' in checks['task_checkpoints_node_check']
        assert 'await_input' in checks['task_checkpoints_next_check']
        # This test isolates 0024's CHECK-only upgrade; return to current head for API reads.
        command.upgrade(config,'head')
    assert client.get(base+'/analysis-plans/'+view['result']['id']).json()==view['result']
    with database_connection() as db:
        verify_runtime_permissions(db.raw_connection,db.config)


def test_research_downgrade_refuses_even_unchecked_v2_history(client,postgres_migration_config):
    _,_,task,_=create_research(client)
    with pytest.raises(DBAPIError):
        with migration_connection(config=postgres_migration_config) as db:
            command.downgrade(configure(db,postgres_migration_config),'0023_file_lifecycle')
    assert client.get('/api/v1/tasks/'+task['id']+'/analysis-plan').status_code==200
