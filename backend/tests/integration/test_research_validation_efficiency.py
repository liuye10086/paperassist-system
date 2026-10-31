"""Report validation stays fresh while avoiding duplicate work inside one phase."""
from copy import deepcopy

import pytest

from tests.api.test_research_findings import client, selected_cell


def report_service(project):
    from app.adapters.storage import ProjectStore
    from app.core.config import get_data_dir
    from app.db.database import database_connection
    from app.domain.research_results.reports import ResearchReportService
    with database_connection() as db:
        owner = db.execute('SELECT owner_id FROM projects WHERE id=%s', (project,)).fetchone()['owner_id']
    return ResearchReportService(ProjectStore(get_data_dir(), owner_id=owner))


def test_freeze_validates_finding_binding_once_and_revalidates_next_phase(client, monkeypatch):
    from app.domain.research_results.contracts import ResearchReportRequest
    from app.domain.research_results.sources import ResearchSourceReader
    base, source = selected_cell(client)
    response = client.post(base + '/research-findings', json=dict(title='Exact values', sources=[source]),
                           headers={'Idempotency-Key': 'once-finding'})
    assert response.status_code == 201, response.text
    finding = response.json()
    project = base.rsplit('/', 1)[-1]
    service = report_service(project)
    request = ResearchReportRequest(title='Fresh report', finding_version_id=finding['id'])
    calls = []
    original = ResearchSourceReader._original

    def counted(self, db, project, selected):
        calls.append((db, selected.source_id))
        return original(self, db, project, selected)

    monkeypatch.setattr(ResearchSourceReader, '_original', counted)
    with service.store.connection() as db:
        first, bindings, payload = service.freeze(db, project, request)
        assert first['finding']['content'] == finding['content']
        assert bindings[0].content == finding['content']
        saved = deepcopy(first)
        first['finding']['content']['title'] = 'caller mutation'
        assert bindings[0].content == finding['content']
        second, _, _ = service.freeze(db, project, request)
        assert second == saved
        assert payload['table_raws'] == []
    # One complete binding validation per freeze, never a cache across freezes.
    assert len(calls) == 2, {'full_source_reads_for_two_freezes': len(calls)}


def test_b04_freeze_avoids_duplicate_finding_pass_and_keeps_full_table(client, monkeypatch, tmp_path):
    from tests.api.test_bio_insight_research_bridge import published
    from app.domain.bio_insights.service import BioInsightsService
    from app.domain.research_results.contracts import ResearchReportRequest
    project, result, member = published(client, monkeypatch, tmp_path)
    base = '/api/v1/projects/' + project
    sources = [dict(source_kind='bio_insight_result_version', source_id=result['id']),
               dict(source_kind='bio_insight_result_member', source_id=member['id'],
                    locator=dict(kind='row', table=member['key'], row_key={'row_key': 'g1'}, column='p_value'))]
    response = client.post(base + '/research-findings', json=dict(title='Exact B04 values', sources=sources),
                           headers={'Idempotency-Key': 'once-b04-finding'})
    assert response.status_code == 201, response.text
    finding = response.json()
    service = report_service(project)
    request = ResearchReportRequest(title='Complete B04 table', finding_version_id=finding['id'])
    calls = []
    original = BioInsightsService._require_sources_in_phase

    def counted(self, db, task, **kwargs):
        if task['id'] == result['task_id']:
            calls.append(db)
        return original(self, db, task, **kwargs)

    monkeypatch.setattr(BioInsightsService, '_require_sources_in_phase', counted)
    with service.store.connection() as db:
        content, _, payload = service.freeze(db, project, request)
    assert content['finding']['content'] == finding['content']
    table = next(t for t in payload['tables'] if t['key'] == 'comparison_results')
    raw = payload['table_raws'][payload['tables'].index(table)]
    assert table['expected_rows'] == 2
    assert b'g1\tg1\t0\t' in raw and b'g2\tg2\t\t0.2' in raw
    # Two independently checked source selections and one full-table validation.
    # This narrow change deliberately introduces no result/DAG cache.
    assert len(calls) == 3, {'full_b04_validations_in_one_freeze': len(calls)}


@pytest.mark.parametrize('failure_at_end', [None, 'expired', 'owner_changed'])
def test_checked_coalesces_lease_sql_and_always_fences_at_exit(client, monkeypatch, tmp_path, failure_at_end):
    from app.adapters.task_execution_store import TaskExecutionStore, LeaseLost
    from app.domain.research_results import execution
    base, source = selected_cell(client)
    finding = client.post(base + '/research-findings', json=dict(title='Lease facts', sources=[source]),
                          headers={'Idempotency-Key': 'coalesced-finding'}).json()
    response = client.post(base + '/research-reports', json=dict(title='Lease report', finding_version_id=finding['id']),
                           headers={'Idempotency-Key': 'coalesced-report'})
    assert response.status_code == 201, response.text
    report = response.json()
    repository = TaskExecutionStore()
    lease = repository.claim(report['task_id'], report['task']['revision'], task_type='research_report')
    clock = [0.0]
    monkeypatch.setattr(execution, 'monotonic', lambda: clock[0], raising=False)

    class Sources:
        def require_sources(self, db, task, *, progress):
            for _ in range(128):
                progress()
            clock[0] = .999
            progress()
            clock[0] = 1.0
            progress()
            clock[0] = 1.2
            progress()
            if failure_at_end == 'expired':
                db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s", (task['id'],))
            elif failure_at_end == 'owner_changed':
                db.execute("UPDATE task_attempts SET lease_owner='other-worker' WHERE task_id=%s", (task['id'],))
            return {'verified': True}

    monkeypatch.setattr(execution, 'service_for', lambda task, repository: Sources())
    with repository.connection(write=True) as db:
        original = db.execute
        renewals = []

        def observed(sql, parameters=()):
            if sql.startswith('UPDATE task_attempts a SET heartbeat_at=clock_timestamp()'):
                renewals.append(clock[0])
            return original(sql, parameters)

        monkeypatch.setattr(db, 'execute', observed)
        runner = execution.ResearchExecution(repository, tmp_path / 'stage')
        if failure_at_end:
            with pytest.raises(LeaseLost):
                runner.checked(db, lease)
        else:
            _, _, _, payload, progress = runner.checked(db, lease)
            assert payload == {'verified': True}
            row = db.execute('SELECT heartbeat_at,lease_expires_at FROM task_attempts WHERE task_id=%s AND attempt_no=%s',
                             (lease.task_id, lease.attempt_no)).fetchone()
            assert progress.renewed == dict(row)
        assert renewals == [0.0, 1.0, 1.2], {'lease_renewal_times': renewals}


@pytest.mark.parametrize('new_connection', [False, True])
def test_freeze_rechecks_same_size_source_byte_mutation_in_same_or_new_db(client, new_connection):
    from pathlib import Path
    from app.core.config import get_data_dir
    from app.core.exceptions import StorageError
    from app.domain.research_results.contracts import ResearchReportRequest
    base, source = selected_cell(client)
    response = client.post(base + '/research-findings', json=dict(title='Mutable input', sources=[source]),
                           headers={'Idempotency-Key': 'mutation-finding'})
    assert response.status_code == 201, response.text
    project = base.rsplit('/', 1)[-1]
    service = report_service(project)
    request = ResearchReportRequest(title='Fresh source bytes', finding_version_id=response.json()['id'])

    def corrupt(db):
        row = db.execute('SELECT object_key FROM files WHERE id=%s', (source['source_id'],)).fetchone()
        path = Path(get_data_dir()) / row['object_key']
        raw = path.read_bytes()
        path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        assert path.stat().st_size == len(raw)

    with service.store.connection() as db:
        service.freeze(db, project, request)
        corrupt(db)
        if not new_connection:
            with pytest.raises(StorageError) as rejected:
                service.freeze(db, project, request)
            assert rejected.value.status == 409
    if new_connection:
        with service.store.connection() as db:
            with pytest.raises(StorageError) as rejected:
                service.freeze(db, project, request)
            assert rejected.value.status == 409


def test_publication_final_fence_is_not_coalesced_after_member_writes(client, monkeypatch, tmp_path):
    from app.adapters.research_report_render import render_report
    from app.domain.research_results.execution import run_research_report_task
    from app.domain.research_results.reports import ResearchReportService
    from app.db.database import database_connection
    base, source = selected_cell(client)
    finding = client.post(base + '/research-findings', json=dict(title='Publication facts', sources=[source]),
                          headers={'Idempotency-Key': 'final-fence-finding'}).json()
    response = client.post(base + '/research-reports', json=dict(title='Final fence', finding_version_id=finding['id']),
                           headers={'Idempotency-Key': 'final-fence-report'})
    assert response.status_code == 201, response.text
    report = response.json()
    original = ResearchReportService.publish
    final_calls = []

    def expire_before_finish(self, db, task, checkpoint, moment, prepared, *, progress):
        calls = []

        def checked():
            calls.append(True)
            if len(calls) == len(prepared['members']) + 1:
                final_calls.append(True)
                db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s", (task['id'],))
            progress()

        return original(self, db, task, checkpoint, moment, prepared, progress=checked)

    monkeypatch.setattr(ResearchReportService, 'publish', expire_before_finish)
    result = run_research_report_task(report['task_id'], report['task']['revision'], engine=render_report,
                                     staging_directory=tmp_path / 'report-stage')
    assert result is None and final_calls == [True]
    with database_connection() as db:
        assert db.execute('SELECT manifest_object_id FROM research_report_versions WHERE id=%s',
                          (report['id'],)).fetchone()['manifest_object_id'] is None
        assert db.execute('SELECT count(*) AS n FROM research_report_members WHERE report_version_id=%s',
                          (report['id'],)).fetchone()['n'] == 0
