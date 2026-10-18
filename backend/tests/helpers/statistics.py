"""Existing business regressions use the actual queued free-statistics consumer."""


def statistics_post(client, url, **kwargs):
    response = client.post(url, **kwargs)
    if response.status_code != 202:
        return response
    task = response.json()
    assert task['task_type'] == 'statistics_compute', task
    if task['status'] == 'queued':
        from app.domain.statistics_execution.execution import run_statistics_task
        task = run_statistics_task(task['id'], task['revision'])
    assert task is not None and task['status'] == 'succeeded', task
    assert task['result_analysis_run_id']
    result = client.get(url.rstrip('/') + '/' + task['result_analysis_run_id'])
    # Negative historical-binding tests intentionally receive 409 from this read.
    return result
