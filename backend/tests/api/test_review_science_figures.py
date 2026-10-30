"""Synthetic isolation only: public queues and local projection, no plot worker calls."""
from copy import deepcopy
import pytest
from tests.api.test_analysis import client
from tests.api.test_review_rounds import make_round
from tests.api.test_review_science import upload_in_project
from tests.integration.test_batch05_figure_store import source
from app.domain.figure_workbench.contracts import SaveConfiguration, ConfirmProjection
from tests.helpers.projection import check_projection, confirm_projection
from app.db.database import database_connection
from app.domain.external_processing import digest


def figure_round(client, monkeypatch):
    store, project, result = source(client)
    with monkeypatch.context() as patch:
        patch.setattr('tests.api.test_descriptive.add_file', lambda instance, rows: upload_in_project(instance, project, rows))
        url, round, _, _ = make_round(client, '1. Please redraw this figure.')
    args = (project, result['file_id'], result['id'])
    saved = store.save(*args, SaveConfiguration(config={'figure_kind':'line','language':'en','projection':{'x_column':'A','y_column':'C'}}))
    vid = saved['version']['id']
    path = url + '/rounds/' + round['id']
    body = dict(plan_revision=round['revision'], item_id=round['items'][0]['id'], file_id=result['file_id'], analysis_run_id=result['id'], figure_config_version_id=vid)
    return store, args, vid, path, body


def test_real_projection_and_plot_request_digests_link_and_reject_tampering(client, monkeypatch):
    from tests.integration.test_batch05_figure_execution import frozen_policy
    from app.domain.figure_workbench.tasks import submit
    from app.domain.figure_workbench.contracts import GenerateFigure
    from psycopg.types.json import Jsonb
    store, args, vid, path, body = figure_round(client, monkeypatch)
    check = check_projection(store, *args, vid)
    task = check['task']
    with database_connection() as db:
        raw = db.execute('SELECT * FROM tasks WHERE id=%s', (task['id'],)).fetchone()
        assert digest(raw['input_snapshot']) != raw['input_digest']
    link_body = dict(plan_revision=body['plan_revision'], item_id=body['item_id'], task_id=task['id'], purpose='projection')
    linked = client.post(path+'/task-links', json=link_body, headers={'Idempotency-Key':'projection-link'})
    assert linked.status_code == 201, linked.text
    assert linked.json()['input_snapshot']['task_snapshot_sha256'] == digest(raw['input_snapshot'])
    confirm_projection(store, *args, vid, ConfirmProjection(input_sha256=check['input_sha256'], approved=True))
    assert client.get(path+'/science').status_code == 200
    monkeypatch.setattr('app.domain.figure_workbench.tasks.policy_for', frozen_policy)
    preview = store.external_preview(*args, vid)
    plot = submit(store, *args, vid, GenerateFigure(idempotency_key='plot-existing', external_processing={'confirmed':True,'payload_sha256':preview['payload_sha256']}))['task']
    result = client.post(path+'/task-links', json=link_body | dict(task_id=plot['id'], purpose='plot'), headers={'Idempotency-Key':'plot-link'})
    assert result.status_code == 201, result.text
    assert client.post(path+'/task-links', json=link_body | dict(task_id=plot['id']), headers={'Idempotency-Key':'wrong-purpose'}).status_code == 422
    # Exercise an old link shape in memory, leaving immutable stored history intact.
    from app.domain.review_rounds.science import ScienceService
    with database_connection() as db:
        row = dict(db.execute('SELECT * FROM review_opinion_task_links WHERE id=%s',(linked.json()['id'],)).fetchone())
        old = deepcopy(row['snapshot_json']); old.pop('task_snapshot_sha256')
        row.update(snapshot_json=old, snapshot_sha256=digest(old))
        assert ScienceService(store.assets).link_view(db, row)['task']['id'] == task['id']
    assert client.get(path+'/science').status_code == 200
    with database_connection(write=True) as db:
        raw = db.execute('SELECT * FROM tasks WHERE id=%s',(plot['id'],)).fetchone()
        changed = deepcopy(raw['input_snapshot']); changed['boxplot_policy']['task_limit_micro_usd'] += 1
        db.execute('UPDATE tasks SET input_snapshot=%s WHERE id=%s',(Jsonb(changed),plot['id']))
    assert client.get(path+'/science').status_code == 409


def test_projection_bridge_reuses_queue_after_link_failure_and_confirmed_task(client, monkeypatch):
    from app.domain.review_rounds.science import ScienceService
    store, args, vid, path, body = figure_round(client, monkeypatch)
    with monkeypatch.context() as patch:
        def interrupted(*args, **kwargs):
            raise RuntimeError('synthetic queue-to-link interruption')
        patch.setattr(ScienceService, 'create_link', interrupted)
        interrupted_response = client.post(path+'/projection-tasks', json=body, headers={'Idempotency-Key':'recover-projection'})
        assert interrupted_response.status_code == 500, interrupted_response.text
    response = client.post(path+'/projection-tasks', json=body, headers={'Idempotency-Key':'recover-projection'})
    assert response.status_code == 202, response.text
    link = response.json()
    assert link['input_snapshot']['creation_kind'] == 'projection'
    assert link['input_snapshot']['creation_request'] == body
    assert 'statistics_request' not in link['input_snapshot']
    assert link['task']['status'] == 'queued' and link['result']['result_figure_id'] is None
    assert client.post(path+'/projection-tasks', json=body, headers={'Idempotency-Key':'recover-projection'}).json()['id'] == link['id']
    assert client.post(path+'/projection-tasks', json=body | dict(analysis_run_id='foreign'), headers={'Idempotency-Key':'recover-projection'}).status_code == 409
    check = check_projection(store, *args, vid)
    confirm_projection(store, *args, vid, ConfirmProjection(input_sha256=check['input_sha256'], approved=True))
    confirmed = client.post(path+'/projection-tasks', json=body, headers={'Idempotency-Key':'confirmed-again'})
    assert confirmed.status_code == 202, confirmed.text
    assert confirmed.json()['task']['id'] == link['task']['id']
    assert confirmed.json()['item_id'] == body['item_id']
    assert confirmed.json()['input_snapshot']['creation_request']['figure_config_version_id'] == vid
    with database_connection() as db:
        assert db.execute("SELECT count(*) AS n FROM tasks WHERE task_type='figure_projection' AND idempotency_key=%s",(vid,)).fetchone()['n'] == 1


def test_plot_bridge_requires_consent_policy_and_recovers_same_public_queue(client, monkeypatch):
    from tests.integration.test_batch05_figure_execution import frozen_policy
    from app.domain.review_rounds.science import ScienceService
    from app.core.exceptions import StorageError
    store, args, vid, path, body = figure_round(client, monkeypatch)
    check = check_projection(store, *args, vid)
    projection = confirm_projection(store, *args, vid, ConfirmProjection(input_sha256=check['input_sha256'], approved=True))
    preview = store.external_preview(*args, vid)
    body |= dict(projection_id=projection['id'], projection_input_sha256=check['input_sha256'], external_processing={'confirmed':True,'payload_sha256':preview['payload_sha256']})
    assert client.get(path+'/science').json()['task_links'] == []
    for bad in ({}, {'confirmed':False,'payload_sha256':preview['payload_sha256']}):
        assert client.post(path+'/plot-tasks', json=body | dict(external_processing=bad), headers={'Idempotency-Key':'no-consent'}).status_code in (409,422)
    def absent(*args, **kwargs):
        raise StorageError('plot_not_configured','synthetic policy absent',503)
    monkeypatch.setattr('app.domain.figure_workbench.tasks.policy_for', absent)
    assert client.post(path+'/plot-tasks', json=body, headers={'Idempotency-Key':'no-policy'}).status_code == 503
    with database_connection() as db:
        assert db.execute("SELECT count(*) AS n FROM tasks WHERE task_type='figure_workbench'").fetchone()['n'] == 0
    monkeypatch.setattr('app.domain.figure_workbench.tasks.policy_for', frozen_policy)
    with monkeypatch.context() as patch:
        patch.setattr(ScienceService, 'create_link', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('synthetic queue-to-link interruption')))
        interrupted_response = client.post(path+'/plot-tasks', json=body, headers={'Idempotency-Key':'plot-recover'})
        assert interrupted_response.status_code == 500, interrupted_response.text
    response = client.post(path+'/plot-tasks', json=body, headers={'Idempotency-Key':'plot-recover'})
    assert response.status_code == 202, response.text
    link = response.json()
    assert link['task']['status'] == 'queued'
    assert link['input_snapshot']['creation_kind'] == 'plot'
    assert client.post(path+'/plot-tasks', json=body, headers={'Idempotency-Key':'plot-recover'}).json()['id'] == link['id']
    assert client.post(path+'/plot-tasks', json=body | dict(projection_input_sha256='0'*64), headers={'Idempotency-Key':'plot-recover'}).status_code == 409
    with database_connection() as db:
        assert db.execute("SELECT count(*) AS n FROM tasks WHERE task_type='figure_workbench'").fetchone()['n'] == 1
        assert db.execute('SELECT count(*) AS n FROM model_calls WHERE task_id=%s',(link['task']['id'],)).fetchone()['n'] == 0
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET status='failed',error_code='plot_files_missing' WHERE id=%s",(link['task']['id'],))
    monkeypatch.setattr('app.domain.figure_workbench.tasks._call', lambda db, task: {'status':'submission_unknown','provider_response_id':None})
    assert client.post(path+'/plot-tasks', json=body, headers={'Idempotency-Key':'must-not-requeue-unknown'}).status_code == 409
    assert client.post(path+'/plot-tasks', json=body, headers={'Idempotency-Key':'plot-recover'}).json()['task']['id'] == link['task']['id']
    assert client.post(path+'/plot-tasks', json=body | dict(figure_config_version_id='foreign'), headers={'Idempotency-Key':'foreign-config'}).status_code == 404
    with database_connection() as db:
        assert db.execute("SELECT count(*) AS n FROM tasks WHERE task_type='figure_workbench'").fetchone()['n'] == 1
        assert db.execute('SELECT count(*) AS n FROM model_calls WHERE task_id=%s',(link['task']['id'],)).fetchone()['n'] == 0



def test_existing_boxplot_request_digest_remains_linkable(client, monkeypatch):
    from tests.integration.test_boxplot_execution import queued
    task, _, base, _ = queued(client, configured=False)
    project = base.split('/')[4]
    with monkeypatch.context() as patch:
        patch.setattr('tests.api.test_descriptive.add_file', lambda instance, rows: upload_in_project(instance, project, rows))
        url, round, _, _ = make_round(client)
    path = url + '/rounds/' + round['id']
    with database_connection() as db:
        raw = db.execute('SELECT * FROM tasks WHERE id=%s',(task['id'],)).fetchone()
        assert raw['input_digest'] != digest(raw['input_snapshot'])
    body = dict(plan_revision=round['revision'], item_id=round['items'][0]['id'], task_id=task['id'], purpose='plot')
    linked = client.post(path+'/task-links', json=body, headers={'Idempotency-Key':'old-boxplot-link'})
    assert linked.status_code == 201, linked.text
