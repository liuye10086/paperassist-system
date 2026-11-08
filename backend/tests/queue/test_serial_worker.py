"""Opt-in real RabbitMQ/two-process Word probe; synthetic sources, no paid APIs.

Run explicitly inside the supplied Linux acceptance image/network. This test
starts only its two Celery subprocesses, never Docker, RabbitMQ or a dispatcher
service. PostgreSQL/schema/assets come from the ordinary disposable fixtures.
"""
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from uuid import uuid4
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from app.db.database import database_connection
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_boxplot import cloud  # noqa: F401
from tests.integration.test_explanations import writer  # noqa: F401
from tests.integration.test_reports import report_ready

pytestmark = pytest.mark.skipif(
    os.environ.get('PAPERASSIST_RUN_QUEUE_TESTS') != '1' or sys.platform != 'linux',
    reason='Explicit isolated Linux serial queue acceptance is disabled.',
)


def _events(path):
    if not path.exists():
        return []
    # A concurrent append can leave only the last record temporarily incomplete.
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines(keepends=True)
            if line.endswith('\n')]


def _process_sample(process):
    """Read only this test's parent and its current prefork children."""
    try:
        children = [int(pid) for pid in Path(f'/proc/{process.pid}/task/{process.pid}/children').read_text().split()]
    except (FileNotFoundError, ProcessLookupError):
        children = []
    rows = []
    for pid in [process.pid, *children]:
        try:
            status = Path(f'/proc/{pid}/status').read_text()
        except (FileNotFoundError, ProcessLookupError):
            continue
        rss = re.search(r'^VmRSS:\s+(\d+)\s+kB$', status, re.M)
        rows.append(dict(pid=pid, parent_pid=process.pid,
                         role='parent' if pid == process.pid else 'child',
                         rss_bytes=int(rss.group(1)) * 1024 if rss else None))
    return rows


def _stop_workers(processes):
    for process in processes:
        # Each process group was created by this test with start_new_session.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    for process in processes:
        try:
            process.wait(timeout=12)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)


def test_two_real_workers_serialize_word_backlog_and_recycle_children(
        client, cloud, writer, postgres_schema, tmp_path, monkeypatch):
    from app.domain.tasks.contracts import TaskCreateRequest
    from app.domain.tasks.service import TaskService
    from app.workers.celery_app import create_app
    from app.workers.dispatcher import dispatch_once
    from tests.helpers.tasks import task_owner

    assert postgres_schema.environment == 'test'
    assert re.fullmatch(r'pa_test_[0-9a-f]{32}', postgres_schema.schema)
    assert os.environ.get('PAPERASSIST_BROKER_URL'), 'An existing acceptance RabbitMQ is required'
    token = postgres_schema.schema.removeprefix('pa_test_')
    queues = [f'paperassist.test.serial.{token}.{suffix}' for suffix in ('a', 'b')]
    data = tmp_path / 'data'
    monkeypatch.setenv('PAPERASSIST_EXECUTION_LOCK_FILE', str(data / '.worker-execution.lock'))
    monkeypatch.setenv('PAPERASSIST_QUEUE_TEST_ALLOWED', '1')

    # Prepare all frozen sources before queuing any Word task: otherwise source
    # fixture statistics would correctly wait behind the first queued report.
    sources = [report_ready(client) for _ in range(3)]
    owner = task_owner(client)
    tasks = []
    for index, (base, file, result, figure, explanation, url) in enumerate(sources):
        task, _ = TaskService(owner).create(base.split('/')[4], TaskCreateRequest(
            task_type='word_report', file_id=file['id'], analysis_run_id=result['id'],
            expected_revision=result['setup_revision'], figure_id=figure['id'],
            explanation_id=explanation['id']), idempotency_key=f'serial-word-{index}')
        tasks.append(task)
    ids = [task['id'] for task in tasks]
    model_fixture_calls = (len(cloud.calls), len(writer.calls))
    # The fake source fixtures use a marker key. Neither real Worker receives it.
    monkeypatch.setenv('OPENAI_API_KEY', '')
    monkeypatch.setenv('OPENAI_API_KEY_FILE', '')
    apps = []
    for queue in queues:
        monkeypatch.setenv('PAPERASSIST_TASK_QUEUE', queue)
        apps.append(create_app())

    events_path = tmp_path / 'serial-worker-events.jsonl'
    processes, logs, routed = [], [], []
    record = dict(scope='real RabbitMQ + PostgreSQL + two Celery workers + local Word',
                  scientific_validation=False, source_provider='synthetic cloud/writer fixtures',
                  real_model_calls=0, pdf_generation=False, schema=postgres_schema.schema,
                  queues=queues, samples=[], status='incomplete')
    deadline = time.monotonic() + 150

    def sample():
        assert time.monotonic() < deadline, 'Serial queue probe exceeded 150 seconds'
        assert all(process.poll() is None for process in processes), 'An owned Worker exited early'
        with database_connection() as db:
            running = db.execute("SELECT count(*) AS n FROM tasks WHERE status='running'").fetchone()['n']
        record['samples'].append(dict(monotonic_ns=time.monotonic_ns(), running_tasks=running,
                                      processes=[row for process in processes for row in _process_sample(process)]))
        assert running <= 1, 'Two tasks were running in the same isolated schema'
        return _events(events_path)

    def wait_for(predicate):
        while True:
            observed = sample()
            if predicate(observed):
                return observed
            time.sleep(.1)

    def publish(message, *, index=None):
        chosen = len(routed) % 2 if index is None else index
        app = apps[chosen]
        app.send_task('paperassist.word_report',
                      args=[message['task_id'], message['task_revision']],
                      task_id=message['id'], queue=queues[chosen], serializer='json',
                      delivery_mode=2, retry=False, ignore_result=True, confirm_timeout=5)
        if index is None:
            routed.append(dict(task_id=message['task_id'], queue=queues[chosen]))

    try:
        for index, queue in enumerate(queues):
            environment = dict(os.environ)
            # Worker uses this exact fixture schema/assets and runtime role only.
            for key in list(environment):
                if 'MIGRATION_DATABASE_URL' in key:
                    environment.pop(key)
            environment.update(PAPERASSIST_TASK_QUEUE=queue,
                               PAPERASSIST_TEST_DATABASE_URL=postgres_schema.url.render_as_string(hide_password=False),
                               PAPERASSIST_TEST_DATABASE_URL_FILE='',
                               PAPERASSIST_DATABASE_URL_FILE='',
                               PAPERASSIST_DATA_DIR=str(data),
                               SERIAL_PROBE_EVENTS=str(events_path),
                               SERIAL_PROBE_WORKER=f'serial-{token}-{index}@localhost')
            log = (tmp_path / f'serial-worker-{index}.log').open('wb')
            logs.append(log)
            processes.append(subprocess.Popen(
                [sys.executable, str(Path(__file__).with_name('_serial_worker_bootstrap.py'))],
                env=environment, stdout=log, stderr=subprocess.STDOUT, start_new_session=True))
        wait_for(lambda events: len({event['worker'] for event in events if event['kind'] == 'ready'}) == 2)
        assert dispatch_once(publish=publish, config=postgres_schema, limit=1) == 1
        wait_for(lambda events: any(event['kind'] == 'word_build_start' for event in events))
        backlog_id = str(uuid4())
        publish(dict(id=backlog_id, task_id=tasks[2]['id'], task_revision=tasks[2]['revision']), index=1)
        wait_for(lambda events: any(event.get('message_id') == backlog_id and
                                    event['kind'] == 'delivery_start' for event in events))

        while True:
            sample()
            with database_connection() as db:
                rows = db.execute('SELECT id,status,result_report_id FROM tasks WHERE id=ANY(%s)', (ids,)).fetchall()
            assert all(row['status'] not in ('failed', 'cancelled') for row in rows), [dict(row) for row in rows]
            if len(rows) == 3 and all(row['status'] == 'succeeded' for row in rows):
                break
            dispatch_once(publish=publish, config=postgres_schema, limit=1)
            time.sleep(.1)
        assert [route['task_id'] for route in routed] == ids
        assert [route['queue'] for route in routed] == [queues[0], queues[1], queues[0]]

        with database_connection() as db:
            attempts = db.execute('''SELECT task_id,status,started_at,finished_at FROM task_attempts
                WHERE task_id=ANY(%s) ORDER BY started_at''', (ids,)).fetchall()
            report_count = db.execute('SELECT count(*) AS n FROM reports').fetchone()['n']
        assert len(attempts) == 3 and [attempt['task_id'] for attempt in attempts] == ids
        assert all(attempt['status'] == 'succeeded' and attempt['finished_at'] is not None for attempt in attempts)
        assert all(left['finished_at'] <= right['started_at'] for left, right in zip(attempts, attempts[1:]))
        assert report_count == 3

        reports = []
        for task, source in zip(tasks, sources):
            current = client.get('/api/v1/tasks/' + task['id']).json()
            report_id = current['result_report_id']
            response = client.get(source[-1] + '/' + report_id + '/download')
            assert response.status_code == 200
            with ZipFile(BytesIO(response.content)) as archive:
                root = ET.fromstring(archive.read('word/document.xml'))
                text = ''.join(root.itertext())
                assert all(section['text'] in text for section in source[4]['sections'])
                assert any(name.startswith('word/media/') for name in archive.namelist())
            reports.append(dict(task_id=task['id'], report_id=report_id,
                                sha256=hashlib.sha256(response.content).hexdigest()))

        # Wait for successful handlers to return before testing broker redelivery.
        wait_for(lambda events: all(any(event['kind'] == 'delivery_finished' and
                                        event.get('task_id') == task_id for event in events) for task_id in ids))
        duplicate_id = str(uuid4())
        publish(dict(id=duplicate_id, task_id=tasks[0]['id'], task_revision=tasks[0]['revision']), index=1)
        events = wait_for(lambda events: any(event['kind'] == 'delivery_finished' and
                                             event.get('message_id') == duplicate_id for event in events))
        with database_connection() as db:
            assert db.execute('SELECT count(*) AS n FROM task_attempts WHERE task_id=ANY(%s)', (ids,)).fetchone()['n'] == 3
            assert db.execute('SELECT count(*) AS n FROM reports').fetchone()['n'] == report_count
        assert (len(cloud.calls), len(writer.calls)) == model_fixture_calls
        builds = [event for event in events if event['kind'] == 'word_build_start']
        assert len(builds) == 3 and len({event['pid'] for event in builds}) == 3
        first_build_finished = next(event for event in events if event['kind'] == 'word_build_finished')
        backlog_started = next(event for event in events if event.get('message_id') == backlog_id and
                               event['kind'] == 'delivery_start')
        backlog_finished = next(event for event in events if event.get('message_id') == backlog_id and
                                event['kind'] == 'delivery_finished')
        # The second Worker received a legitimate old backlog message while
        # Worker A was building Word, but returned only after the shared slot
        # released. DB head checks alone would return this message immediately.
        assert builds[0]['monotonic_ns'] <= backlog_started['monotonic_ns'] < first_build_finished['monotonic_ns']
        assert backlog_finished['monotonic_ns'] >= first_build_finished['monotonic_ns']
        worker_a_builds = [event for event in builds if event['worker'].endswith('-0@localhost')]
        assert len(worker_a_builds) == 2 and worker_a_builds[0]['pid'] != worker_a_builds[1]['pid']
        assert any(row['running_tasks'] == 1 for row in record['samples'])
        record.update(status='passed', reports=reports, attempts=[dict(row) for row in attempts],
                      routed=routed, events=events, distinct_word_child_pids=sorted({event['pid'] for event in builds}),
                      recycle_observed=True,
                      peak_sampled_rss_bytes=max(sum(process['rss_bytes'] or 0 for process in sample['processes'])
                                                 for sample in record['samples']))
    finally:
        _stop_workers(processes)
        for log in logs:
            log.close()
        cleanup_errors = []
        for app, queue in zip(apps, queues):
            try:
                with app.connection_for_write() as connection:
                    channel = connection.channel()
                    try:
                        app.amqp.queues[queue].bind(channel).delete(if_unused=False, if_empty=False)
                        app.amqp.queues[queue].exchange.bind(channel).delete(if_unused=False)
                    finally:
                        channel.close()
            except Exception as exc:
                cleanup_errors.append(type(exc).__name__)
            app.close()
        record.update(events=_events(events_path), cleanup_errors=cleanup_errors,
                      owned_worker_returncodes=[process.returncode for process in processes])
        output = os.environ.get('PAPERASSIST_QUEUE_PROBE_OUTPUT')
        if output:
            destination = Path(output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
        assert not cleanup_errors, 'Failed to remove this probe\'s unique queues/exchanges'
