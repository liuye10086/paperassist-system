"""Default public transactions remain idempotent; no plot consumer or provider."""
import pytest
from tests.api.test_analysis import client
from tests.integration.test_batch05_figure_store import source
from tests.integration.test_batch05_figure_execution import frozen_policy
from tests.helpers.projection import check_projection, confirm_projection
from app.domain.figure_workbench.contracts import SaveConfiguration, ConfirmProjection, GenerateFigure
from app.domain.figure_workbench.tasks import submit
from app.core.exceptions import StorageError
from app.db.database import database_connection


def test_public_figure_default_transaction_replays_key_and_rejects_valid_changed_configuration(client, monkeypatch):
    store, project, result = source(client)
    args = (project, result['file_id'], result['id'])
    config = {'figure_kind':'line','language':'en','projection':{'x_column':'A','y_column':'C'}}
    saved = store.save(*args, SaveConfiguration(config=config))
    vid = saved['version']['id']
    initial = store.check(*args, vid)
    assert initial['task']['id'] == store.check(*args, vid)['task']['id']
    checked = check_projection(store, *args, vid)
    confirm_projection(store, *args, vid, ConfirmProjection(input_sha256=checked['input_sha256'], approved=True))
    assert store.check(*args, vid)['task'] is None
    monkeypatch.setattr('app.domain.figure_workbench.tasks.policy_for', frozen_policy)
    external = {'confirmed':True,'payload_sha256':store.external_preview(*args, vid)['payload_sha256']}
    request = GenerateFigure(idempotency_key='original-public-same-key',external_processing=external)
    first = submit(store, *args, vid, request)['task']
    replay = submit(store, *args, vid, request)['task']
    assert first['id'] == replay['id'] and replay['status'] == 'queued'
    second = store.save(*args, SaveConfiguration(configuration_id=saved['id'], expected_revision=1,config=config | {'style':{'title':'Another valid fixed title'}}))
    second_id = second['version']['id']
    changed = GenerateFigure(idempotency_key=request.idempotency_key,external_processing={'confirmed':True,'payload_sha256':store.external_preview(*args, second_id)['payload_sha256']})
    with pytest.raises(StorageError) as error:
        submit(store, *args, second_id, changed)
    assert error.value.code == 'task_idempotency_conflict'
    with database_connection() as db:
        assert db.execute("SELECT count(*) AS n FROM tasks WHERE task_type='figure_projection'").fetchone()['n'] == 1
        assert db.execute("SELECT count(*) AS n FROM tasks WHERE task_type='figure_workbench'").fetchone()['n'] == 1
        assert db.execute('SELECT count(*) AS n FROM model_calls WHERE task_id=%s',(first['id'],)).fetchone()['n'] == 0
