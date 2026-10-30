"""Atomic review intent + public queues; synthetic isolated schema, no plot worker."""
import pytest
from tests.api.test_analysis import client
from tests.api.test_review_rounds import make_round
from tests.api.test_review_science import queued_analysis
from tests.api.test_review_science_figures import figure_round
from tests.helpers.projection import check_projection, confirm_projection
from app.domain.figure_workbench.contracts import SaveConfiguration, ConfirmProjection
from app.domain.review_rounds.science import ScienceService
from app.db.database import database_connection


def counts():
    with database_connection() as db:
        return {table: db.execute('SELECT count(*) AS n FROM '+table).fetchone()['n']
                for table in ('tasks','task_checkpoints','task_events','task_outbox','model_budgets','review_opinion_task_links')}


@pytest.mark.parametrize('kind', ['projection', 'plot', 'statistics'])
def test_review_queue_and_link_rollback_together_then_fix_full_request(client, monkeypatch, kind):
    if kind == 'statistics':
        _, path, round, _, _, _, body = queued_analysis(client, monkeypatch)
        alternative = body | dict(item_id=round['items'][1]['id'])
        config_alternative = None
    else:
        with monkeypatch.context() as patch:
            patch.setattr('tests.api.test_review_science_figures.make_round',
                lambda instance, text: make_round(instance, '1. Please redraw this figure.\n2. Please redraw the other figure.'))
            store, args, vid, path, body = figure_round(client, monkeypatch)
        round = client.get(path).json()
        alternative = body | dict(item_id=round['items'][1]['id'])
        second = store.save(*args, SaveConfiguration(config={'figure_kind':'line','language':'en','projection':{'x_column':'A','y_column':'C'},'style':{'title':'Another valid config'}}))
        config_alternative = body | dict(figure_config_version_id=second['version']['id'])
        if kind == 'plot':
            from tests.integration.test_batch05_figure_execution import frozen_policy
            monkeypatch.setattr('app.domain.figure_workbench.tasks.policy_for', frozen_policy)
            checked = check_projection(store, *args, vid)
            projection = confirm_projection(store, *args, vid, ConfirmProjection(input_sha256=checked['input_sha256'], approved=True))
            preview = store.external_preview(*args, vid)
            extra = dict(projection_id=projection['id'],projection_input_sha256=checked['input_sha256'],external_processing={'confirmed':True,'payload_sha256':preview['payload_sha256']})
            body |= extra
            alternative |= extra
            config_alternative = None
    baseline = counts()
    original = ScienceService.insert
    for phase in ('before_insert', 'after_insert'):
        with monkeypatch.context() as patch:
            def interrupted(self, db, table, *args, **kwargs):
                if table != 'review_opinion_task_links':
                    return original(self, db, table, *args, **kwargs)
                if phase == 'after_insert':
                    original(self, db, table, *args, **kwargs)
                raise RuntimeError('synthetic interruption '+phase)
            patch.setattr(ScienceService, 'insert', interrupted)
            failed = client.post(path+'/'+kind+'-tasks',json=body,headers={'Idempotency-Key':'atomic-review-intent'})
            assert failed.status_code == 500, failed.text
        assert counts() == baseline, 'Task, queue/outbox, checkpoints, budgets and link must all roll back'
    # Both interrupted attempts never committed. One explicit retry creates the
    # sole final task/link; after success the full body is durable and immutable.
    response = client.post(path+'/'+kind+'-tasks',json=body,headers={'Idempotency-Key':'atomic-review-intent'})
    assert response.status_code == 202, response.text
    linked = response.json()
    assert linked['item_id'] == body['item_id']
    assert counts()['tasks'] == baseline['tasks']+1
    assert counts()['review_opinion_task_links'] == baseline['review_opinion_task_links']+1
    assert client.post(path+'/'+kind+'-tasks',json=body,headers={'Idempotency-Key':'atomic-review-intent'}).json()['id'] == linked['id']
    assert client.post(path+'/'+kind+'-tasks',json=alternative,headers={'Idempotency-Key':'atomic-review-intent'}).status_code == 409
    if config_alternative:
        assert client.post(path+'/projection-tasks',json=config_alternative,headers={'Idempotency-Key':'atomic-review-intent'}).status_code == 409
    assert counts()['tasks'] == baseline['tasks']+1
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls WHERE task_id=%s',(linked['task']['id'],)).fetchone()['n'] == 0
        if kind == 'projection':
            assert db.execute('SELECT idempotency_key FROM tasks WHERE id=%s',(linked['task']['id'],)).fetchone()['idempotency_key'] == body['figure_config_version_id']
