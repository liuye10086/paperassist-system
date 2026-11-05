"""Initial report validation must allow independent task lease renewal."""
from tests.api.test_research_findings import client, selected_cell
import pytest


def test_report_initial_source_validation_allows_heartbeat(client, tmp_path, monkeypatch):
    from app.adapters.research_report_render import render_report
    from app.adapters.task_execution_store import TaskExecutionStore, TaskLease
    from app.domain.research_results.execution import run_research_task
    from app.domain.research_results.reports import ResearchReportService

    base, source = selected_cell(client)
    finding = client.post(base + '/research-findings', json={'title': 'Fixed finding', 'sources': [source]},
                          headers={'Idempotency-Key': 'lease-finding'}).json()
    response = client.post(base + '/research-reports',
                           json={'title': 'Fixed report', 'finding_version_id': finding['id']},
                           headers={'Idempotency-Key': 'lease-report'})
    assert response.status_code == 201, response.text
    report = response.json()
    original = ResearchReportService.require_sources
    checked = []

    def validate(self, db, task, *, progress=None):
        if progress is None:
            assert db.execute('SHOW transaction_read_only').fetchone()['transaction_read_only'] == 'on'
            attempt = db.execute('SELECT * FROM task_attempts WHERE task_id=%s AND attempt_no=%s',
                                 (task['id'], task['current_attempt'])).fetchone()
            lease = TaskLease(task['id'], task['current_attempt'], attempt['lease_owner'])
            repository = TaskExecutionStore(config=db.config, directory=self.assets.directory)
            assert repository.heartbeat(lease)
            checked.append(task['id'])
        return original(self, db, task, progress=progress)

    monkeypatch.setattr(ResearchReportService, 'require_sources', validate)
    done = run_research_task(report['task_id'], report['task']['revision'],
                             task_type='research_report', engine=render_report,
                             staging_directory=tmp_path / 'stage')
    assert done['status'] == 'succeeded', done
    assert checked == [report['task_id']]


@pytest.mark.parametrize('change', ['lease', 'checkpoint'])
def test_report_rechecks_fence_after_initial_source_read(client, tmp_path, monkeypatch, change):
    from app.db.database import database_connection
    from app.domain.bioinformatics.service import append_checkpoint
    from app.domain.research_results.execution import run_research_task, checkpoint_for
    from app.domain.research_results.reports import ResearchReportService
    from app.adapters.task_execution_store import TaskExecutionStore

    base, source = selected_cell(client)
    finding = client.post(base + '/research-findings',
                          json={'title': 'Fixed finding', 'sources': [source]},
                          headers={'Idempotency-Key': 'fence-finding'}).json()
    report = client.post(base + '/research-reports',
                         json={'title': 'Fixed report', 'finding_version_id': finding['id']},
                         headers={'Idempotency-Key': 'fence-report'}).json()
    original = ResearchReportService.require_sources
    observed = []

    def validate(self, db, task, *, progress=None):
        payload = original(self, db, task, progress=progress)
        if progress is None:
            with database_connection(write=True, config=db.config) as writer:
                if change == 'lease':
                    writer.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s", (task['id'],))
                else:
                    cp = checkpoint_for(writer, task)
                    append_checkpoint(writer, dict(task, updated_at=TaskExecutionStore.now(writer)),
                                      'check', 'check', {**cp['state_json'], 'stage': 'changed'}, cp)
            observed.append(change)
        return payload

    rendered = []
    monkeypatch.setattr(ResearchReportService, 'require_sources', validate)
    done = run_research_task(report['task_id'], report['task']['revision'],
                             task_type='research_report', engine=lambda *args: rendered.append(True),
                             staging_directory=tmp_path / 'stage')
    assert done is None if change == 'lease' else done['status'] == 'failed'
    assert observed == [change] and not rendered


def test_delivery_package_initial_source_validation_is_read_only(client, tmp_path, monkeypatch):
    from tests.api.test_delivery_snapshots import setup_delivery
    from app.domain.delivery_packages.service import DeliveryService
    from app.domain.research_results.execution import run_research_task

    _, path, body = setup_delivery(client)
    saved = client.post(path + '/snapshots', json=body,
                        headers={'Idempotency-Key': 'read-only-snapshot'}).json()
    response = client.post(path + '/snapshots/' + saved['id'] + '/package', json={},
                           headers={'Idempotency-Key': 'read-only-package'})
    assert response.status_code == 201, response.text
    task = response.json()['task']
    original = DeliveryService.require_sources
    observed = []

    def validate(self, db, task, *, progress=None):
        if progress is None:
            assert db.execute('SHOW transaction_read_only').fetchone()['transaction_read_only'] == 'on'
            observed.append(task['id'])
        return original(self, db, task, progress=progress)

    monkeypatch.setattr(DeliveryService, 'require_sources', validate)
    done = run_research_task(task['id'], task['revision'], task_type='delivery_package',
                             staging_directory=tmp_path / 'stage')
    assert done['status'] == 'succeeded', done
    assert observed == [task['id']]
