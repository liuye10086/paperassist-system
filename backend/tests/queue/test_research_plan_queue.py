"""Opt-in Linux v2 research-input waits, durable review and unique publication."""
from tests.helpers.legacy_plans import seed_legacy_plan
from tests.helpers.statistics import statistics_post
import os
import time

import pytest

from app.db.database import database_connection
from tests.api.test_analysis import client, selection  # noqa: F401
from tests.helpers.analysis_plan import prepared_sample, review_plan, plan_decision, decide_plan
from tests.queue.test_analysis_plan_queue import bootstrap
from tests.queue.test_dataset_queue import wait_task
from tests.queue.test_real_worker import isolated_worker_stack, worker_stack  # noqa: F401


pytestmark = pytest.mark.skipif(os.environ.get('PAPERASSIST_RUN_QUEUE_TESTS') != '1',
    reason='Explicit isolated Linux research-plan drill is disabled.')


def research_request(*, complete=False, question='比较合成处理组的体重分布，仅做描述统计。'):
    return dict(question=question, output_language='zh-CN',
        population='合成测量记录' if complete else '',
        study_design='合成横断面演练' if complete else '',
        observation_unit='每行一条合成观察' if complete else '',
        observation_structure='independent' if complete else 'unknown',
        relationship_description='', output_requirements='总体与分组描述统计')


def create_research_plan(client, base, prepared, key):
    body = dict(dataset_id=prepared['id'], expected_setup_revision=0,
        selection=selection(numeric_column='D', group_column='C', unit='mg'),
        research_request=research_request())
    response = seed_legacy_plan(client, base + '/analysis-plans', json=body, headers={'Idempotency-Key': key})
    assert response.status_code == 202, response.text
    return response.json(), body


def wait_review_status(client, task, status, timeout=115):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        view = review_plan(client, task)
        assert view['task']['status'] != 'failed', view
        if view['task']['status'] == status:
            return view
        time.sleep(.2)
    pytest.fail('Research-plan worker did not reach its durable ' + status + ' wait.')


def revise_request(view, research):
    return dict(operation='revise', expected_task_revision=view['task']['revision'],
        input_version=view['input_version'], checkpoint_id=view['checkpoint_id'],
        wait_id=view['wait_id'], plan_revision=view['plan_revision'],
        resolutions={}, research_request=research)


def assert_released_input_wait(task_id, view):
    assert view['input_version']['workflow_version'] == 'analysis_plan_v2'
    assert view['check']['research_missing'] == [
        'population', 'study_design', 'observation_unit', 'observation_structure']
    with database_connection() as db:
        attempt = db.execute('SELECT * FROM task_attempts WHERE task_id=%s ORDER BY attempt_no DESC LIMIT 1',
            (task_id,)).fetchone()
        assert attempt['finished_at'] and attempt['lease_owner'] is None
        wait = db.execute('SELECT * FROM task_waits WHERE id=%s', (view['wait_id'],)).fetchone()
        assert wait['kind'] == 'analysis_plan_input' and wait['status'] == 'open'
        checkpoint = db.execute('SELECT * FROM task_checkpoints WHERE id=%s', (view['checkpoint_id'],)).fetchone()
        assert checkpoint['node'] == 'await_input'


def test_research_input_wait_releases_worker_and_restart_requires_fresh_approval(
        client, isolated_worker_stack, tmp_path):
    stack = isolated_worker_stack
    base, _, prepared = prepared_sample(client)
    first, body = create_research_plan(client, base, prepared, 'research-restart')
    override = bootstrap(stack, tmp_path)
    incomplete = wait_review_status(client, first, 'waiting_input')
    assert_released_input_wait(first['id'], incomplete)
    assert client.get('/api/v1/tasks/' + first['id'] + '/workspace').json()['allowed_actions'] == ['revise']
    replay = seed_legacy_plan(client, base + '/analysis-plans', json=body, headers={'Idempotency-Key': 'research-restart'})
    assert replay.status_code == 200 and replay.json()['id'] == first['id']

    # Concurrency is one: a second human-input wait proves the first released it.
    second, _ = create_research_plan(client, base, prepared, 'research-second')
    assert_released_input_wait(second['id'], wait_review_status(client, second, 'waiting_input'))
    worker_stack.compose(stack, ['stop', '--timeout', '45', 'worker'], timeout=100)
    assert review_plan(client, first) == incomplete

    supplement = revise_request(incomplete, research_request(complete=True))
    accepted = decide_plan(client, first, supplement, 'research-supplement')
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()['status'] == 'queued' and accepted.json()['reason_code'] == 'input_provided'
    replay = decide_plan(client, first, supplement, 'research-supplement')
    assert replay.status_code == 200 and replay.json() == accepted.json()
    worker_stack.compose(stack, ['--file', str(override), 'up', '-d', '--wait', '--wait-timeout', '90'], timeout=180)
    confirmation = wait_review_status(client, first, 'waiting_confirmation')
    assert confirmation['plan_revision'] == 2 and confirmation['wait_id'] != incomplete['wait_id']
    assert confirmation['check']['research_missing'] == [] and confirmation['result'] is None
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM confirmed_analysis_plans').fetchone()['n'] == 0
        assert db.execute('SELECT count(*) AS n FROM analysis_setups').fetchone()['n'] == 0

    # Editing a confirmation creates another wait; its predecessor cannot approve.
    revised = decide_plan(client, first, revise_request(confirmation,
        research_request(complete=True, question='汇总合成处理组体重，并明确缺失排除。')), 'research-revise-confirmation')
    assert revised.status_code == 202, revised.text
    current = wait_review_status(client, first, 'waiting_confirmation')
    assert current['plan_revision'] == 3 and current['wait_id'] != confirmation['wait_id']
    assert decide_plan(client, first, plan_decision(confirmation), 'research-stale-approval').status_code == 409
    approval = plan_decision(current)
    approved = decide_plan(client, first, approval, 'research-approve')
    assert approved.status_code == 202, approved.text
    assert wait_task(client, first['id'], timeout=115)['status'] == 'succeeded'
    replay = decide_plan(client, first, approval, 'research-approve')
    assert replay.status_code == 200 and replay.json() == approved.json()
    published = review_plan(client, first)['result']
    result = statistics_post(client, base + '/analysis-runs', json={'expected_revision': 1})
    assert result.status_code == 200, result.text
    result = result.json()
    assert result['schema_version'] == published['schema_version'] == 2
    assert result['overall']['n'] == 4 and result['overall']['mean'] == 5.5
    assert result['analysis_plan']['plan_id'] == published['id']
    assert result['analysis_context']['plan'] == published
    assert result['analysis_context']['method']['observation_basis'] == 'rows'
    assert statistics_post(client, base + '/analysis-runs', json={'expected_revision': 1}).json() == result
    assert not (tmp_path / 'data' / '.unexpected-plan-network').exists()
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM confirmed_analysis_plans WHERE task_id=%s',
            (first['id'],)).fetchone()['n'] == 1
        assert db.execute('SELECT revision FROM analysis_setups').fetchone()['revision'] == 1
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0
        assert db.execute('SELECT count(*) AS n FROM budget_reservations').fetchone()['n'] == 0
