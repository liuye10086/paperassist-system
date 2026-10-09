"""External confirmation is local and bound to the exact accepted source."""
import copy

from app.db.database import database_connection
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_boxplot import cloud, prepared, generate  # noqa: F401
import pytest


@pytest.fixture
def policy(tmp_path, monkeypatch, cloud):
    from tests.api.test_plot_tasks import execution_policy
    import json
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(execution_policy()), encoding="utf-8")
    monkeypatch.setenv("PAPERASSIST_PLOT_POLICY_FILE", str(path))
    return execution_policy()


def persistence_counts():
    with database_connection() as db:
        return {table: db.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]
                for table in ("tasks", "task_outbox", "task_events", "model_calls", "model_budgets", "budget_reservations")}


def confirmation(client, url):
    response = client.get(url + '/disclosure')
    assert response.status_code == 200, response.text
    value = response.json()
    return {'version': 1, 'confirmed': True, 'source_digest': value['source_digest'],
            'labels': {item['key']: item['value'] for item in value['labels']}}


def test_new_plot_requires_confirmation_without_side_effects(client, cloud, policy):
    _, _, _, url = prepared(client)
    before = persistence_counts()
    response = client.post(url, json={'expected_revision': 1})
    assert response.status_code == 422, response.text
    assert response.json()['detail']['code'] == 'task_input_invalid'
    assert persistence_counts() == before
    assert cloud.calls == []


def test_disclosure_is_read_only_and_confirmation_is_frozen(client, cloud, policy):
    _, _, _, url = prepared(client)
    before = persistence_counts()
    external = confirmation(client, url)
    assert persistence_counts() == before
    external['labels']['numeric_name'] = '本次数值'
    body = {'expected_revision': 1, 'external_processing': external}
    headers = {'Idempotency-Key': 'external-plot'}
    accepted = client.post(url, json=body, headers=headers)
    assert accepted.status_code == 202, accepted.text
    assert client.post(url, json=body, headers=headers).json()['task']['id'] == accepted.json()['task']['id']
    with database_connection() as db:
        frozen = db.execute('SELECT input_snapshot FROM tasks').fetchone()['input_snapshot']['external_processing']
        assert frozen['labels'] == external['labels']
        assert frozen['confirmed_by'] and frozen['confirmed_at']
        assert frozen['source_digest'] == external['source_digest']
    changed = copy.deepcopy(body)
    changed['external_processing']['labels']['numeric_name'] = '另一个名称'
    assert client.post(url, json=changed, headers=headers).status_code == 409
    assert cloud.calls == []


def test_changed_source_or_invalid_labels_reject_without_writes(client, cloud, policy):
    _, _, _, url = prepared(client)
    external = confirmation(client, url)
    before = persistence_counts()
    stale = {**external, 'source_digest': '0' * 64}
    response = client.post(url, json={'expected_revision': 1, 'external_processing': stale})
    assert response.status_code == 409
    for change in ({'extra': 'x'}, {'numeric_name': ''}, {'numeric_name': 'bad\nlabel'}, {'unit': 'x' * 161}):
        invalid = copy.deepcopy(external)
        invalid['labels'].update(change)
        assert client.post(url, json={'expected_revision': 1, 'external_processing': invalid}).status_code == 422
    assert persistence_counts() == before


def test_saved_legacy_figure_requires_no_confirmation(client, cloud):
    _, _, _, url = prepared(client)
    figure = generate(client, url)
    before = persistence_counts()
    assert client.get(url + '/disclosure').json()['has_saved_result'] is True
    response = client.post(url, json={'expected_revision': 1})
    assert response.status_code == 200 and response.json()['figure'] == figure
    assert persistence_counts() == before


def test_new_explanation_requires_confirmation_and_preview_reads_no_configuration(client, cloud, monkeypatch):
    from tests.integration.test_explanations import ready
    from app.domain import explanation_policy
    *_, figure, url = ready(client)
    monkeypatch.setattr(explanation_policy, 'get_execution_policy', lambda *args: pytest.fail('preview must not read policy'))
    before = persistence_counts()
    preview = client.get(url + '/disclosure')
    assert preview.status_code == 200, preview.text
    assert 'figure_title' in {item['key'] for item in preview.json()['labels']}
    rejected = client.post(url, json={'expected_revision': 1, 'figure_id': figure['id']})
    assert rejected.status_code == 422, rejected.text
    assert persistence_counts() == before


def test_creation_transaction_rechecks_confirmation_source(client, cloud, policy, monkeypatch):
    import json
    from app.domain.tasks.service import TaskService
    _, _, result, url = prepared(client)
    external = confirmation(client, url)
    original = TaskService.create
    def changed_source(service, *args, **kwargs):
        with database_connection(write=True) as db:
            changed = {**result, 'numeric_name': 'changed since preview'}
            db.execute('UPDATE analysis_runs SET result_json=%s WHERE id=%s',
                       (json.dumps(changed, ensure_ascii=False), result['id']))
        return original(service, *args, **kwargs)
    monkeypatch.setattr(TaskService, 'create', changed_source)
    before = persistence_counts()
    response = client.post(url, json={'expected_revision': 1, 'external_processing': external})
    assert response.status_code == 409, response.text
    assert response.json()['detail']['code'] == 'task_source_conflict'
    assert persistence_counts() == before
