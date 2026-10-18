"""Opt-in real Linux statistics queue and OCR cgroup acceptance evidence."""
import json
import os
from pathlib import Path
import sys
import time

import pytest

from app.core.config import local_config
from app.core.paths import PROJECT_ROOT
from app.db.database import database_connection
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_descriptive import configured
from tests.queue.test_file_parse_queue import create_batch, upload_item
from tests.queue.test_documents_queue import version_list, assert_no_model_calls

sys.path.insert(0, str(PROJECT_ROOT / 'script' / 'dev'))
import worker_stack

pytestmark = pytest.mark.skipif(os.environ.get('PAPERASSIST_RUN_QUEUE_TESTS') != '1',
                               reason='Explicit isolated Linux queue test is disabled.')
EVIDENCE = PROJECT_ROOT / 'script/.runtime/stage04-batch10'
EVIDENCE_LABEL = os.environ.get('PAPERASSIST_QUEUE_EVIDENCE_LABEL', 'queue')
assert EVIDENCE_LABEL.replace('-', '').isalnum()


def evidence(value):
    (EVIDENCE / (EVIDENCE_LABEL + '-resources.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


@pytest.fixture
def batch10_stack(postgres_schema, tmp_path):
    test_id = postgres_schema.schema.removeprefix('pa_test_')
    assert postgres_schema.schema != 'pa_test_6c22bd2d48154b7faae0481a02f4cdf6'
    stack = worker_stack.prepare(PROJECT_ROOT, local_config(), test_id=test_id, assets=tmp_path / 'data')
    assert stack.project == 'pa-test-' + test_id
    assert (stack.directory / 'model-api-key').read_text() == ''
    override = tmp_path / 'batch10-worker.json'
    override.write_text(json.dumps({'services': {'worker': {
        'cpuset': '1',
        'command': ['python', '/app/batch10_statistics_bootstrap.py', 'worker'],
        'volumes': [{'type': 'bind', 'source': str(Path(__file__).with_name('batch10_statistics_bootstrap.py').resolve()),
                     'target': '/app/batch10_statistics_bootstrap.py', 'read_only': True}],
    }}}), encoding='utf-8')
    data = {'schema': postgres_schema.schema, 'project': stack.project, 'model_credentials_present': False,
            'observations': [], 'checks': [], 'stopped': False}
    evidence(data)
    worker_stack.ensure_docker()
    try:
        worker_stack.compose(stack, ['build', 'worker'], timeout=1200)
        yield stack, override, data
    finally:
        # User explicitly retains broker volumes. Only our exact owned stack is stopped.
        worker_stack.stop(stack)
        data['containers_after_stop'] = worker_stack.owned_containers(stack)
        data['stopped'] = all(item['status'] != 'running' for item in data['containers_after_stop'])
        data['broker_volumes_retained'] = True
        evidence(data)


def start(stack, override):
    worker_stack.compose(stack, ['--file', str(override), 'up', '-d', '--wait', '--wait-timeout', '90'], timeout=180)


def memory(stack, data, label):
    cid = next(item['id'] for item in worker_stack.owned_containers(stack) if item['service'] == 'worker')
    script = """import json, os
from pathlib import Path
p=Path('/sys/fs/cgroup')
r={name:(p/name).read_text().strip() for name in ('memory.max','memory.current','memory.peak','memory.events')}
r['credential_present']=bool(Path('/run/secrets/model-api-key').read_text().strip())
r['environment']=os.environ['PAPERASSIST_ENV']
r['schema']=os.environ['PAPERASSIST_DB_SCHEMA']
r['allowed_cpus']=sorted(os.sched_getaffinity(0))
print(json.dumps(r))
"""
    snapshot = json.loads(worker_stack.docker(['exec', cid, 'python', '-c', script]))
    snapshot.update(label=label, container_id=cid)
    assert snapshot['memory.max'] == str(2 * 1024**3)
    assert not snapshot['credential_present'] and snapshot['environment'] == 'test'
    assert snapshot['schema'] == data['schema']
    assert snapshot['allowed_cpus'] == [1]
    events = dict(line.split() for line in snapshot['memory.events'].splitlines())
    assert events['oom'] == events['oom_kill'] == '0', snapshot
    data['observations'].append(snapshot)
    evidence(data)


def wait_success(client, task_id, timeout=100):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get('/api/v1/tasks/' + task_id)
        assert response.status_code == 200, response.text
        task = response.json()
        assert task['status'] != 'failed', task
        if task['status'] == 'succeeded':
            return task
        time.sleep(.2)
    pytest.fail('Real Linux queue task did not succeed before deadline: ' + task_id)


def post_statistics(client, base, key):
    response = client.post(base + '/analysis-runs', json={'expected_revision': 1, 'idempotency_key': key})
    assert response.status_code == 202, response.text
    return response.json()


def assert_statistics(client, base, task, data):
    response = client.get(base + '/analysis-runs/' + task['result_analysis_run_id'])
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['overall']['n'] == 3 and result['overall']['mean'] == 2.0
    assert client.get(base + '/analysis-result').json()['execution_verification'] == 'verified'
    receipt = task['execution_receipt']
    assert receipt['status'] == 'succeeded' and receipt['nodes']
    measured = [node for node in receipt['nodes'] if not node['cache_hit']]
    assert measured and all(node['child_peak_rss_bytes'] > 0 and node['child_cpu_seconds'] >= 0 for node in measured)
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM analysis_runs WHERE file_id=%s', (result['file_id'],)).fetchone()['n'] == 1
        assert db.execute("SELECT count(*) AS n FROM task_events WHERE task_id=%s AND event_type='succeeded'", (task['id'],)).fetchone()['n'] == 1
    data['checks'].append({'task_id': task['id'], 'result_id': result['id'], 'attempts': task['current_attempt'],
                           'receipt': receipt})
    evidence(data)


def test_real_statistics_queue_recovery_and_ocr_memory(client, batch10_stack, tmp_path):
    stack, override, data = batch10_stack
    rows = [['value'], [1], [2], [3]]
    base, _ = configured(client, rows, group_column=None)
    first = post_statistics(client, base, 'queue-first')
    assert first['status'] == 'queued'
    assert post_statistics(client, base, 'queue-first')['id'] == first['id']
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM analysis_runs').fetchone()['n'] == 0
        assert db.execute('SELECT count(*) AS n FROM task_outbox WHERE task_id=%s', (first['id'],)).fetchone()['n'] == 1
    start(stack, override)
    first = wait_success(client, first['id'])
    assert first['current_attempt'] == 1
    assert_statistics(client, base, first, data)
    assert post_statistics(client, base, 'queue-first')['id'] == first['id']
    memory(stack, data, 'statistics_before_restart')

    worker_stack.stop(stack)
    second_base, _ = configured(client, rows, group_column=None)
    second = post_statistics(client, second_base, 'queue-after-restart')
    assert second['status'] == 'queued'
    start(stack, override)
    second = wait_success(client, second['id'])
    assert second['current_attempt'] == 1
    assert_statistics(client, second_base, second, data)
    memory(stack, data, 'statistics_after_restart')

    # Hold dispatcher so the precise task can be marked before delivery.
    worker_stack.compose(stack, ['stop', '--timeout', '45', 'dispatcher'], timeout=60)
    third_base, _ = configured(client, [['value'], [-1], [2], [5]], group_column=None)
    third = post_statistics(client, third_base, 'queue-crash')
    (tmp_path / 'data/.batch10-crash-task').write_text(third['id'], encoding='ascii')
    start(stack, override)
    marker = tmp_path / 'data/.batch10-crashed'
    deadline = time.monotonic() + 90
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(.2)
    assert marker.exists(), client.get('/api/v1/tasks/' + third['id']).json()
    assert marker.read_text(encoding='ascii') == third['id']
    with database_connection() as db:
        row = db.execute('SELECT * FROM tasks WHERE id=%s', (third['id'],)).fetchone()
        assert row['status'] == 'running' and row['current_attempt'] == 1
        assert row['result_analysis_run_id'] is None and row['execution_receipt'] is None
        assert db.execute('SELECT count(*) AS n FROM analysis_runs WHERE file_id=%s', (third_base.split('/')[-1],)).fetchone()['n'] == 0
    # Observe the real 60-second lease; no database timestamp modification.
    third = wait_success(client, third['id'], timeout=180)
    assert third['current_attempt'] == 2
    assert_statistics(client, third_base, third, data)
    with database_connection(write=True) as db:
        attempts = db.execute('SELECT status,reason_code FROM task_attempts WHERE task_id=%s ORDER BY attempt_no', (third['id'],)).fetchall()
        assert [row['status'] for row in attempts] == ['failed', 'succeeded']
        db.execute('UPDATE task_outbox SET published_at=NULL,available_at=clock_timestamp() WHERE task_id=%s', (third['id'],))
    time.sleep(5)
    replay = client.get('/api/v1/tasks/' + third['id']).json()
    assert replay['current_attempt'] == 2 and replay['result_analysis_run_id'] == third['result_analysis_run_id']
    memory(stack, data, 'statistics_after_crash_recovery_and_redelivery')

    content = (Path(__file__).parents[1] / 'fixtures/ocr/printed-zh-en.png').read_bytes()
    project_base, batch = create_batch(client, [('synthetic-printed.png', content)])
    uploaded = upload_item(client, project_base, batch, 0, content)
    ocr_task = wait_success(client, uploaded['task']['id'], timeout=240)
    item = version_list(client, project_base + '/files/' + uploaded['file_id'])['items'][0]
    document = client.get(item['download_url']).json()
    assert document['kind'] == 'ocr_document' and document['counts']['text_blocks'] > 0
    data['ocr'] = {'task_id': ocr_task['id'], 'status': ocr_task['status'], 'text_blocks': document['counts']['text_blocks']}
    memory(stack, data, 'same_worker_after_real_ocr')
    assert_no_model_calls()
    data['model_calls'] = 0
    data['budget_reservations'] = 0
    evidence(data)


def test_final_prefork_deadline_smoke(client, batch10_stack):
    """Rebuild current product and execute its signal deadline in actual prefork."""
    stack, override, data = batch10_stack
    base, _ = configured(client, [['value'], [1], [2], [3]], group_column=None)
    queued = post_statistics(client, base, 'final-prefork-deadline')
    assert queued['status'] == 'queued'
    start(stack, override)
    task = wait_success(client, queued['id'])
    assert task['current_attempt'] == 1
    assert_statistics(client, base, task, data)
    assert post_statistics(client, base, 'final-prefork-deadline')['id'] == task['id']
    memory(stack, data, 'final_prefork_numeric_deadline')
    assert_no_model_calls()
    data.update(model_calls=0, budget_reservations=0)
    data['image'] = worker_stack.docker(['image', 'inspect', stack.project + '-worker:local',
        '--format', '{{.Id}} {{.Created}}']).strip()
    evidence(data)
