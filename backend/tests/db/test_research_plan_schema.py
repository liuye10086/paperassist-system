"""Research migration only extends CHECKs and preserves real v1 history."""
from tests.helpers.statistics import statistics_post
import pytest
from alembic import command
from sqlalchemy.exc import DBAPIError
from app.db.database import database_connection, verify_runtime_permissions
from tests.api.test_analysis import client
from tests.helpers.analysis_plan import confirmed_sample
from tests.helpers.historical_migration import historical_workflow
from tests.integration.test_research_plan import create_research


def test_research_upgrade_preserves_all_legacy_table_values_and_indexes(client,postgres_migration_config):
    base,_,_,view=confirmed_sample(client)
    assert statistics_post(client, base+'/analysis-runs',json={'expected_revision':1}).status_code==200
    with historical_workflow(postgres_migration_config, '0023_file_lifecycle') as (db, config):
        assert db.execute('SELECT plan_json FROM confirmed_analysis_plans WHERE id=%s', (view['result']['id'],)).fetchone()
        assert db.execute('SELECT count(*) AS n FROM analysis_runs').fetchone()['n'] > 0
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

    assert client.get(base+'/analysis-plans/'+view['result']['id']).json()==view['result']
    with database_connection() as db:
        verify_runtime_permissions(db.raw_connection,db.config)


def test_research_downgrade_refuses_even_unchecked_v2_history(client,postgres_migration_config):
    _,_,task,_=create_research(client)
    with historical_workflow(postgres_migration_config, '0024_research_plans') as (db, config):
        before = db.execute('SELECT * FROM tasks WHERE id=%s', (task['id'],)).fetchone()
        assert before['workflow_version'] == 'analysis_plan_v2'
        with pytest.raises(DBAPIError, match='research plan history requires preservation'):
            with db.raw_connection.begin_nested():
                command.downgrade(config, '0023_file_lifecycle')
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()['version_num'] == '0024_research_plans'
        assert db.execute('SELECT * FROM tasks WHERE id=%s', (task['id'],)).fetchone() == before
    assert client.get('/api/v1/tasks/'+task['id']+'/analysis-plan').status_code==200
