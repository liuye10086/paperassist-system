"""Opt-in real HTTP loss and real broker delivery/replay crash boundaries."""
import hashlib
import json
import os
from pathlib import Path

import httpx2
import pytest

from app.db.database import database_connection
from app.domain.tasks.execution import run_word_task
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_boxplot import cloud  # noqa: F401
from tests.integration.test_explanations import writer  # noqa: F401
from tests.integration.test_reports import report_ready
from tests.queue.delivery_crash_support import (
    crashing_api, dispatcher_exit_code, evidence, queue_stats, wait_until,
)
from tests.queue.test_real_worker import isolated_worker_stack, wait_report, worker_stack  # noqa: F401

pytestmark = pytest.mark.skipif(os.environ.get('PAPERASSIST_RUN_QUEUE_TESTS') != '1',
                               reason='Explicit isolated HTTP/broker crash test is disabled.')


def report_request(client):
    *_, figure, explanation, url = report_ready(client)
    return url, {'expected_revision': figure['setup_revision'], 'figure_id': figure['id'],
                 'explanation_id': explanation['id']}


def ledger(task_id):
    with database_connection() as db:
        return {
            'task': dict(db.execute('SELECT * FROM tasks WHERE id=%s', (task_id,)).fetchone()),
            'events': [dict(row) for row in db.execute('SELECT * FROM task_events WHERE task_id=%s ORDER BY seq', (task_id,))],
            'outbox': [dict(row) for row in db.execute('SELECT * FROM task_outbox WHERE task_id=%s', (task_id,))],
            'attempts': [dict(row) for row in db.execute('SELECT * FROM task_attempts WHERE task_id=%s', (task_id,))],
        }


def source_snapshot(assets):
    with database_connection() as db:
        rows = {table: [dict(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY id')]
                for table in ('files', 'analysis_runs', 'figures', 'explanations')}
    rows['asset_sha256'] = {str(path.relative_to(assets)): hashlib.sha256(path.read_bytes()).hexdigest()
                            for directory in ('files', 'figures')
                            for path in (assets / directory).rglob('*') if path.is_file()}
    return rows


def assert_single_report(client, url, task_id, assets):
    task = client.get('/api/v1/tasks/' + task_id).json()
    assert task['status'] == 'succeeded' and task['current_attempt'] == 1
    report = client.get(url).json()['report']
    response = client.get(url + '/' + report['id'] + '/download')
    assert response.status_code == 200
    digest = hashlib.sha256(response.content).hexdigest()
    assert digest == report['sha256']
    saved = ledger(task_id)
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM tasks WHERE idempotency_key=%s',
                          (saved['task']['idempotency_key'],)).fetchone()['n'] == 1
        reports = db.execute('SELECT id FROM reports').fetchall()
        assert [row['id'] for row in reports] == [report['id']]
    assert len(saved['attempts']) == 1 and saved['attempts'][0]['status'] == 'succeeded'
    assert [row['event_type'] for row in saved['events']] == ['created', 'started', 'succeeded']
    assert len(list((assets / 'reports').glob('*.docx'))) == 1
    snapshot = saved['task']['input_snapshot']
    assert report['source_sha256'] == snapshot['file']['sha256']
    assert report['figure_sha256'] == snapshot['figure']['sha256']
    assert report['explanation_id'] == snapshot['explanation']['id']
    return report, digest


def test_http_process_death_after_commit_replays_one_task(client, cloud, writer, tmp_path, postgres_schema):
    url, body = report_request(client)
    sources = source_snapshot(tmp_path / 'data')
    request_key = 'http-after-commit-' + postgres_schema.schema[8:]
    with crashing_api(request_key) as (process, transport):
        with pytest.raises(httpx2.TransportError) as disconnected:
            transport.post(url, json=body, headers={
                **dict(client.headers), 'Idempotency-Key': request_key,
                'Cookie': 'paperassist_session=' + client.cookies.get('paperassist_session')})
        # A timeout would not prove the process dropped its HTTP response.
        assert not isinstance(disconnected.value, httpx2.TimeoutException)
        assert process.wait(timeout=15) == 74
        marker = json.loads((tmp_path / 'data' / '.test-api-crashed.json').read_text(encoding='utf-8'))
        assert marker['checkpoint'] == 'after_task_commit_before_http_response' and marker['created'] is True
        task_id = marker['task_id']
        committed = ledger(task_id)
        assert committed['task']['status'] == 'queued' and committed['task']['current_attempt'] == 0
        assert [event['event_type'] for event in committed['events']] == ['created']
        assert len(committed['outbox']) == 1 and committed['outbox'][0]['published_at'] is None
        assert not committed['attempts']
        replay = client.post(url, json=body, headers={'Idempotency-Key': request_key})
        assert replay.status_code == 202 and replay.json()['task']['id'] == task_id
        assert ledger(task_id) == committed
        evidence('api_committed_response_lost', schema=postgres_schema.schema, task_id=task_id,
                 exit_code=process.returncode, disconnect=type(disconnected.value).__name__,
                 task_count=1, created_count=1, outbox_count=1, replay_same_task=True)
    run_word_task(task_id, marker['revision'])
    report, digest = assert_single_report(client, url, task_id, tmp_path / 'data')
    repeated = client.post(url, json=body, headers={'Idempotency-Key': request_key})
    assert repeated.status_code == 200 and repeated.json()['report']['id'] == report['id']
    assert hashlib.sha256(client.get(url + '/' + report['id'] + '/download').content).hexdigest() == digest
    assert source_snapshot(tmp_path / 'data') == sources
    evidence('api_recovery_single_artifact', task_id=task_id, attempt_count=1,
             report_count=1, docx_count=1, sha256=digest, sources_unchanged=True)


def test_dispatcher_process_death_after_confirm_replays_real_messages(client, cloud, writer,
        isolated_worker_stack, tmp_path):
    stack = isolated_worker_stack
    assert not worker_stack.owned_containers(stack)
    url, body = report_request(client)
    sources = source_snapshot(tmp_path / 'data')
    accepted = client.post(url, json=body, headers={'Idempotency-Key': 'broker-after-confirm'})
    assert accepted.status_code == 202, accepted.text
    task_id = accepted.json()['task']['id']
    bootstrap = Path(__file__).with_name('dispatcher_crash_bootstrap.py').resolve()
    support = Path(__file__).with_name('delivery_crash_support.py').resolve()
    override = tmp_path / 'crash-dispatcher.json'
    override.write_text(json.dumps({'services': {'dispatcher': {
        'command': ['python', '/app/dispatcher_crash_bootstrap.py', 'dispatch'],
        'environment': {'PAPERASSIST_RUN_QUEUE_TESTS': '1'},
        'volumes': [{'type': 'bind', 'source': str(source), 'target': '/app/' + source.name, 'read_only': True}
                    for source in (bootstrap, support)],
    }}}), encoding='utf-8')
    worker_stack.compose(stack, ['up', '-d', '--wait', '--wait-timeout', '90', 'rabbitmq'], timeout=180)
    worker_stack.owned_containers(stack)
    worker_stack.compose(stack, ['--file', str(override), 'up', '-d', '--no-deps', 'dispatcher'], timeout=90)
    exit_code = wait_until(lambda: dispatcher_exit_code(stack, worker_stack), lambda value: value is not None,
                           seconds=45, description='crashed isolated dispatcher')
    assert exit_code == 75
    marker = json.loads((tmp_path / 'data' / '.test-dispatcher-crashed.json').read_text(encoding='utf-8'))
    assert marker['checkpoint'] == 'after_broker_confirm_before_outbox_mark' and marker['task_id'] == task_id
    first = wait_until(lambda: queue_stats(stack, worker_stack),
                       lambda value: value == {'ready': 1, 'unacked': 0, 'consumers': 0},
                       description='one confirmed RabbitMQ message without consumers')
    saved = ledger(task_id)
    assert saved['task']['status'] == 'queued' and saved['task']['current_attempt'] == 0
    assert len(saved['outbox']) == 1 and saved['outbox'][0]['id'] == marker['id']
    assert saved['outbox'][0]['published_at'] is None and saved['outbox'][0]['publish_attempts'] == 1
    assert not saved['attempts']
    assert {item['service'] for item in worker_stack.owned_containers(stack)} == {'rabbitmq', 'dispatcher'}
    evidence('broker_confirm_process_lost', project=stack.project, task_id=task_id,
             queue=stack.environment['PAPERASSIST_TASK_QUEUE'], exit_code=exit_code,
             stats=first, published=False)
    worker_stack.compose(stack, ['up', '-d', '--force-recreate', '--wait', '--wait-timeout', '90', 'dispatcher'], timeout=180)
    duplicated = wait_until(lambda: queue_stats(stack, worker_stack),
                            lambda value: value == {'ready': 2, 'unacked': 0, 'consumers': 0},
                            description='real outbox message replay before worker start')
    saved = ledger(task_id)
    assert saved['outbox'][0]['published_at'] is not None and saved['outbox'][0]['publish_attempts'] == 2
    assert not saved['attempts']
    evidence('broker_outbox_replayed', project=stack.project, task_id=task_id, stats=duplicated, published=True)
    worker_stack.compose(stack, ['up', '-d', '--wait', '--wait-timeout', '90', 'worker'], timeout=180)
    wait_report(client, url, task_id)
    empty = wait_until(lambda: queue_stats(stack, worker_stack),
                       lambda value: value is not None and value['ready'] == value['unacked'] == 0,
                       description='both real messages acknowledged')
    report, digest = assert_single_report(client, url, task_id, tmp_path / 'data')
    repeated = client.post(url, json=body, headers={'Idempotency-Key': 'broker-after-confirm'})
    assert repeated.status_code == 200 and repeated.json()['report']['id'] == report['id']
    assert hashlib.sha256(client.get(url + '/' + report['id'] + '/download').content).hexdigest() == digest
    assert source_snapshot(tmp_path / 'data') == sources
    evidence('broker_single_artifact', project=stack.project, task_id=task_id, stats=empty,
             attempt_count=1, report_count=1, docx_count=1, sha256=digest, sources_unchanged=True)
    # The imported fixture also checks ownership and tears down on every failure.
    worker_stack.owned_containers(stack)
    worker_stack.compose(stack, ['down', '--volumes', '--remove-orphans', '--timeout', '45'], timeout=120)
    assert not worker_stack.owned_containers(stack)
    evidence('broker_stack_cleanup', project=stack.project, owned_container_count=0)
