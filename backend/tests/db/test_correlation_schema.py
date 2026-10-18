"""0025 only widens compatible task metadata, retaining older history."""
from app.db.database import database_connection
import pytest

def test_second_batch_schema_has_nullable_verified_failure_evidence(postgres_schema):
    with database_connection() as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()['version_num']=='0029_statistics_execution'
        row=db.execute("SELECT is_nullable,data_type FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='tasks' AND column_name='verification_failure'").fetchone()
        assert row=={'is_nullable':'YES','data_type':'jsonb'}


def test_0025_preserves_existing_values_indexes_and_adds_null_evidence(postgres_migration_config):
    from alembic import command
    from app.db.database import migration_connection,alembic_config
    from tests.db.test_task_schema import seed_owner,task_row,insert_row
    with migration_connection(config=postgres_migration_config) as db:
        config=alembic_config();config.attributes.update(connection=db.raw_connection,database_config=postgres_migration_config)
        command.downgrade(config,'0024_research_plans')
        seed_owner(db);insert_row(db,'tasks',task_row(input_snapshot={'original':['001 mg',None]}))
        tables=[r['table_name'] for r in db.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema() AND table_name<>'alembic_version'")]
        before={name:[dict(r) for r in db.execute('SELECT * FROM '+name)] for name in tables}
        indexes=[dict(r) for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema() ORDER BY indexname')]
        command.upgrade(config,'0025_correlation_planning')
        after={name:[dict(r) for r in db.execute('SELECT * FROM '+name)] for name in tables}
        for row in after['tasks']: assert row.pop('verification_failure') is None
        assert before==after
        assert indexes==[dict(r) for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema() ORDER BY indexname')]


@pytest.mark.parametrize('changes',[
    {'task_type':'analysis_recommendation'}, {'workflow_version':'analysis_plan_v3'},
    {'verification_failure':{'status':'mismatched'}},
])
def test_0025_downgrade_refuses_new_history(postgres_migration_config,changes):
    from alembic import command
    from sqlalchemy.exc import DBAPIError
    from app.db.database import migration_connection,alembic_config
    from tests.db.test_task_schema import seed_owner,task_row,insert_row
    with database_connection(write=True) as db:
        seed_owner(db);insert_row(db,'tasks',task_row(**changes))
    with pytest.raises(DBAPIError):
        with migration_connection(config=postgres_migration_config) as db:
            config=alembic_config();config.attributes.update(connection=db.raw_connection,database_config=postgres_migration_config)
            command.downgrade(config,'0024_research_plans')
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM tasks').fetchone()['n']==1
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()['version_num']=='0029_statistics_execution'


def test_0025_evidence_rejects_non_object_json(postgres_schema):
    from sqlalchemy.exc import IntegrityError
    from tests.db.test_task_schema import seed_owner,task_row,insert_row
    with pytest.raises(IntegrityError):
        with database_connection(write=True) as db:
            seed_owner(db);insert_row(db,'tasks',task_row(verification_failure=['unbounded']))
