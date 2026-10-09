"""Persisted state projections through authenticated API reads, with no execution."""
from app.db.database import database_connection
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_boxplot import cloud  # noqa: F401
from tests.integration.test_explanations import writer  # noqa: F401
from tests.browser.task_browser_seed import matrix, project
from tests.browser.task_browser_support import business_fingerprints


def test_persistent_task_state_matrix_preserves_business_records(client, cloud, writer):
    owner = client.get('/api/v1/auth/me').json()['user']['id']
    selected = project(client, 'API十状态及阶段别名 · 合成只读展示')
    rows = matrix(client, owner, selected['id'])
    before = business_fingerprints()
    with database_connection() as db:
        project_before = dict(db.execute('SELECT * FROM projects WHERE id=%s', (selected['id'],)).fetchone())
    assert len(rows) == 13 and len({row['filename'] for row in rows}) == 13
    for row in rows:
        endpoint = '/api/v1/tasks/' + row['task_id']
        task_response, workspace_response = client.get(endpoint), client.get(endpoint + '/workspace')
        assert task_response.status_code == workspace_response.status_code == 200
        task, workspace = task_response.json(), workspace_response.json()
        assert workspace['task'] == task
        assert {key: task[key] for key in ('status', 'phase', 'display_status')} == {
            key: row[key] for key in ('status', 'phase', 'display_status')}
        assert task['input_version'] == {'setup_revision': 1, 'output_language': 'zh-CN'}
        assert workspace['source']['filename'] == row['filename']
        assert workspace['source']['is_current'] is True
        assert workspace['allowed_actions'] == row['allowed_actions']
        if row['wait_kind']:
            assert workspace['wait']['kind'] == row['wait_kind']
            assert workspace['wait']['status'] == 'open'
            assert workspace['wait']['task_revision'] == task['revision']
            assert workspace['wait']['input_version'] == task['input_version']
        else:
            assert workspace['wait'] is None
    page = client.get(f'/api/v1/projects/{selected["id"]}/tasks?page_size=50')
    assert page.status_code == 200
    unified = {item['task']['id']: item for item in page.json()['items'] if item['task']['origin'] == 'unified'}
    assert set(unified) == {row['task_id'] for row in rows}
    for row in rows:
        assert unified[row['task_id']]['source']['filename'] == row['filename']
        for key in ('status', 'phase', 'display_status'):
            assert unified[row['task_id']]['task'][key] == row[key]
    assert business_fingerprints() == before
    with database_connection() as db:
        assert dict(db.execute('SELECT * FROM projects WHERE id=%s', (selected['id'],)).fetchone()) == project_before
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0
    assert cloud.calls == writer.calls == []
