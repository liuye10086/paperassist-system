"""0042 adds a nullable school binding without rewriting SCI history."""
from tests.helpers.historical_migration import historical_workflow, assert_saved_history_blocks
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_manuscripts import setup,body
from tests.api.test_literature_evidence import post
from app.db.database import database_connection


def test_school_binding_column_preserves_sci_snapshot(client):
    path,_,_=setup(client)
    created=post(client,path,body(),'sci-control')
    assert created.status_code==201,created.text
    version=created.json()['versions'][0]
    with database_connection() as db:
        row=db.execute('SELECT snapshot_json,school_confirmation_id FROM manuscript_versions WHERE id=%s',(version['id'],)).fetchone()
        assert row['school_confirmation_id'] is None
        assert row['snapshot_json']==version['snapshot']
    assert 'thesis_context' not in version['snapshot']

def test_school_migration_adds_scope_fk_preserves_old_data_and_guards_downgrade(client):
    import pytest
    from alembic import command
    from sqlalchemy.exc import SQLAlchemyError
    from app.db.database import migration_connection, get_migration_database_config
    from app.domain.tasks.execution import run_task
    from tests.api.test_thesis_manuscripts import bound
    from tests.maintenance.test_literature_evidence_migration import fingerprints
    path,_,_=setup(client)
    created = post(client, path, body(), 'sci-before')
    assert created.status_code == 201, created.text
    sci = created.json()
    with historical_workflow(get_migration_database_config(), '0041_school_templates') as (db, cfg):
        assert db.execute("SELECT 1 FROM manuscript_versions WHERE id=%s", (sci['versions'][0]['id'],)).fetchone()
        before=fingerprints(db,['manuscripts','manuscript_versions','manuscript_sources','school_template_versions'])
        # Compare the pre-existing fields; the sole new nullable column is expected.
        rows=list(db.execute('SELECT id,snapshot_json,snapshot_sha256,request_json,request_digest FROM manuscript_versions'))
        command.upgrade(cfg,'0042_thesis_manuscripts')
        assert list(db.execute('SELECT id,snapshot_json,snapshot_sha256,request_json,request_digest FROM manuscript_versions'))==rows
        assert fingerprints(db,['manuscripts','manuscript_sources','school_template_versions'])=={k:v for k,v in before.items() if k!='manuscript_versions'}
        # Restore the current additive head before exercising application APIs.
        command.upgrade(cfg,'head')
    # The SCI draft was submitted before the school's document parse in the same serial queue.
    task_id = sci['versions'][0]['task_id']
    queued = client.get('/api/v1/tasks/' + task_id)
    assert queued.status_code == 200, queued.text
    task = queued.json()
    assert task['task_type'] == 'manuscript_draft' and task['status'] == 'queued'
    assert run_task(task_id, task['revision'])['status'] == 'succeeded'
    school,_,request=bound(client)
    created = post(client, school+'/manuscripts', request, 'school')
    assert created.status_code == 201, created.text
    school_root = created.json()
    with pytest.raises(SQLAlchemyError) as scope_error:
        with migration_connection(write=True) as db:
            db.execute('UPDATE manuscript_versions SET school_confirmation_id=%s WHERE id=%s',(request['thesis']['confirmation_id'],sci['versions'][0]['id']))
    assert scope_error.value.orig.diag.constraint_name=='mv_school_confirmation_scope_fk'
    assert_saved_history_blocks('0042_thesis_manuscripts', 'School manuscript history exists; refusing destructive downgrade.')
    assert client.get(school+'/manuscripts/'+school_root['id']).status_code==200
