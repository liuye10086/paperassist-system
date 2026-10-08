"""Explicit Linux Worker test; ordinary pytest never starts or contacts a broker."""
import hashlib
import os
from pathlib import Path
import sys
import time

import pytest

from app.core.config import local_config
from app.core.paths import PROJECT_ROOT
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_boxplot import cloud  # noqa: F401
from tests.integration.test_explanations import writer  # noqa: F401
from tests.integration.test_reports import report_ready

sys.path.insert(0, str(PROJECT_ROOT / 'script' / 'dev'))
import worker_stack

pytestmark = pytest.mark.skipif(os.environ.get('PAPERASSIST_RUN_QUEUE_TESTS') != '1',
                               reason='Explicit isolated Linux queue test is disabled.')


def wait_report(client, url, task_id):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        task = client.get('/api/v1/tasks/' + task_id).json()
        assert task['status'] != 'failed', task
        if task['status'] == 'succeeded':
            report = client.get(url).json()['report']
            downloaded = client.get(url + '/' + report['id'] + '/download')
            assert downloaded.status_code == 200
            assert hashlib.sha256(downloaded.content).hexdigest() == report['sha256']
            return task, report
        time.sleep(0.2)
    pytest.fail('The isolated Linux Worker did not finish within 60 seconds.')


@pytest.fixture
def isolated_worker_stack(postgres_schema, tmp_path):
    test_id = postgres_schema.schema.removeprefix('pa_test_')
    stack = worker_stack.prepare(PROJECT_ROOT, local_config(), test_id=test_id, assets=tmp_path / 'data')
    assert stack.project.startswith('pa-test-')
    assert stack.environment['PAPERASSIST_TASK_QUEUE'] == 'paperassist.test.' + test_id
    worker_stack.ensure_docker()
    try:
        worker_stack.compose(stack, ['build', 'worker'], timeout=1200)
        yield stack
    finally:
        worker_stack.owned_containers(stack)
        worker_stack.compose(stack, ['down', '--volumes', '--remove-orphans', '--timeout', '45'], timeout=120)


def test_linux_word_queue_and_broker_restart(client, cloud, writer, isolated_worker_stack, tmp_path):
    stack = isolated_worker_stack
    *_, figure, explanation, url = report_ready(client)
    body = {'expected_revision': figure['setup_revision'], 'figure_id': figure['id'],
            'explanation_id': explanation['id']}
    response = client.post(url, json=body)
    assert response.status_code == 202, response.text
    task_id = response.json()['task']['id']
    assert response.json()['task']['status'] == 'queued'
    # All Docker services were stopped at acceptance; POST has only committed its outbox.
    worker_stack.compose(stack, ['up', '-d', '--wait', '--wait-timeout', '90'], timeout=180)
    first_task, first_report = wait_report(client, url, task_id)
    assert first_task['current_attempt'] == 1
    assert client.post(url, json=body).json()['report']['id'] == first_report['id']
    assert len(list((tmp_path / 'data' / 'reports').glob('*.docx'))) == 1

    worker_stack.compose(stack, ['stop', '--timeout', '45', 'worker', 'rabbitmq'], timeout=100)
    *_, second_figure, second_explanation, second_url = report_ready(client)
    response = client.post(second_url, json={'expected_revision': second_figure['setup_revision'],
                        'figure_id': second_figure['id'], 'explanation_id': second_explanation['id']})
    assert response.status_code == 202
    second_id = response.json()['task']['id']
    assert client.get('/api/v1/tasks/' + second_id).json()['status'] == 'queued'
    worker_stack.compose(stack, ['up', '-d', '--wait', '--wait-timeout', '90'], timeout=180)
    second_task, second_report = wait_report(client, second_url, second_id)
    assert second_task['current_attempt'] == 1
    assert second_report['id'] != first_report['id']
