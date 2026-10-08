"""Existing synthetic business sources for the new task foundation tests."""
from tests.api.test_boxplot import prepared


def boxplot_task_input(client):
    from app.domain.tasks.contracts import TaskCreateRequest

    base, file, result, _ = prepared(client)
    return base.split('/')[4], TaskCreateRequest(
        task_type='boxplot', file_id=file['id'], analysis_run_id=result['id'],
        expected_revision=result['setup_revision']), base, result


def task_owner(client):
    return client.get('/api/v1/auth/me').json()['user']['id']
