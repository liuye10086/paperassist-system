from tests.api.test_analysis import client
from tests.integration.test_batch05_figure_store import source
from tests.helpers.projection import check_projection
from app.domain.figure_workbench.contracts import SaveConfiguration,ConfirmProjection


def test_projection_lease_expiring_inside_publication_rolls_back_result(client,monkeypatch):
    store,project,result=source(client);args=(project,result['file_id'],result['id'])
    saved=store.save(*args,SaveConfiguration(config={'figure_kind':'line','language':'en','projection':{'x_column':'A','y_column':'C'}}));v=saved['version']['id']
    checked=check_projection(store,*args,v)
    task=store.confirm(*args,v,ConfirmProjection(input_sha256=checked['input_sha256'],approved=True))['task']
    from app.db.database import DatabaseConnection,database_connection
    original=DatabaseConnection.execute
    def expire_after_insert(db,sql,params=None):
        answer=original(db,sql,params)
        if sql.startswith('INSERT INTO figure_projection_results'):
            original(db,"UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s AND status='running'",(task['id'],))
        return answer
    monkeypatch.setattr(DatabaseConnection,'execute',expire_after_insert)
    from app.domain.figure_workbench.projection_execution import run_projection_task
    assert run_projection_task(task['id'],task['revision']) is None
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM figure_projection_results WHERE config_version_id=%s',(v,)).fetchone()['n']==0
        assert db.execute('SELECT status FROM tasks WHERE id=%s',(task['id'],)).fetchone()['status']=='running'
