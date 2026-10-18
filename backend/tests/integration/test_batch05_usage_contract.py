"""New paid task types retain the public usage/receipt contract."""
from tests.api.test_analysis import client
from tests.integration.test_batch05_figure_execution import complete_figure_bundle


def test_project_and_task_usage_include_figure_and_explanation_calls(client, monkeypatch):
    _, project, _, _ = complete_figure_bundle(client, monkeypatch)
    response = client.get(f'/api/v1/projects/{project}/model-usage')
    assert response.status_code == 200, response.text
    usage = response.json()
    assert {call['task_type'] for call in usage['items']} == {'figure_workbench', 'figure_explanation'}
    assert usage['total'] == 2
    from app.db.database import database_connection
    with database_connection() as db:
        task_ids = [row['task_id'] for row in db.execute('SELECT task_id FROM model_calls WHERE project_id=%s', (project,))]
    for task_id in task_ids:
        detail = client.get(f'/api/v1/tasks/{task_id}/model-usage')
        assert detail.status_code == 200, detail.text
        assert detail.json()['total'] == 1
        assert set(detail.json()['items'][0]) == {'id','task_type','model','status','provider_status','usage_status','estimated_cost_micro_usd','created_at','updated_at','reconciliation'}
