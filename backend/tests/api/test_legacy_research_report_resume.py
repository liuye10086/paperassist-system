"""Fixed report tasks accepted by 3932384 can finish after upgrading the worker."""

from io import BytesIO
import json
from pathlib import Path
import sys
from zipfile import ZipFile

import pytest

from tests.api.test_research_findings import client, selected_cell
from tests.integration.test_research_validation_efficiency import report_service


LEGACY_LF = '95be3a1cab17f7cacc22761ec38212caf772c32e93a0ad715d2ceaa20a9fcfa2'
LEGACY_CRLF = '9b2e8022d84d8532925b898af0f6e1f4f26eaa10df55b4c1c03a29f8952b3091'
pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='The real render subprocess requires Linux')


def queue_legacy_report(client, code_digest):
    from app.adapters.research_report_render import renderer_identity
    from app.adapters.research_results_store import base, identity, insert, now
    from app.domain.bioinformatics.contracts import digest
    from app.domain.bioinformatics.service import append_checkpoint
    from app.domain.research_results.contracts import ResearchReportRequest
    from app.domain.research_results.sources import ResearchSourceReader
    from app.domain.research_results.task_contracts import input_version

    endpoint, source = selected_cell(client)
    finding = client.post(endpoint + '/research-findings', json={'title': 'Fixed observations', 'sources': [source]},
                          headers={'Idempotency-Key': 'legacy-report-finding'})
    assert finding.status_code == 201, finding.text
    finding = finding.json()
    project = endpoint.rsplit('/', 1)[-1]
    service = report_service(project)
    request = ResearchReportRequest(title='Frozen external report', finding_version_id=finding['id'], language='en')
    body = request.model_dump(mode='json', exclude={'reader_narrative_id'})
    # Write the 3932384 shape independently of the upgraded service's freeze().
    content = dict(schema_version=1, method_presentation_version='bio_insight_readable_v1', title=request.title,
                   language=request.language, finding=finding, figures=[], tables=[], real_model_calls=0)
    key = 'before-reader-reports'
    report_id = identity(project, 'report', key)
    task_id = identity(project, 'report-task', key)
    moment = now()
    with service.store.connection(write=True) as db:
        binding = ResearchSourceReader(service.assets).read_source(project, dict(
            source_kind='research_finding_version', source_id=finding['id'], sha256=finding['sha256']), db=db)
        snapshot = dict(schema_version=1, kind='research_report', workflow_version='research_report_v1',
                        project_id=project, report_version_id=report_id,
                        renderer_identity={**renderer_identity(), 'code_digest': code_digest},
                        request=body, output_policy='no_generated_pdf_v1', content_sha256=digest(content),
                        source_file_ids=[source['source_id']], output_language='en',
                        real_model_calls=False, real_network_calls=False)
        task = dict(id=task_id, project_id=project, user_id=service.store.user_id, task_type='research_report',
                    idempotency_key='research_report:' + task_id, input_digest=digest(snapshot), input_snapshot=snapshot,
                    workflow_version='research_report_v1', status='queued', phase='export', revision=1, current_attempt=0,
                    reason_code=None, created_at=moment, updated_at=moment)
        service.store.insert_task(db, task, validated_file_ids=snapshot['source_file_ids'])
        insert(db, 'research_report_versions', {**base(report_id, project, service.store.user_id),
            'root_id': report_id, 'revision': 1, 'parent_id': None, 'finding_version_id': request.finding_version_id,
            'task_id': task_id, 'language': request.language, 'content_json': content, 'content_sha256': digest(content),
            'manifest_object_id': None, 'manifest_sha256': None, 'request_key': key, 'request_digest': digest(body)})
        service.bind(db, project, 'report', report_id, binding)
        append_checkpoint(db, task, 'check', 'check', dict(input_version=input_version(task), stage='report'))
        service.store.append_event(db, task, 'created')
        service.store.enqueue(db, task)
    return endpoint + '/research-reports/' + report_id, task, content


@pytest.mark.parametrize('phase,code_digest', [
    pytest.param('queued', LEGACY_LF, id='queued-lf'),
    pytest.param('failed', LEGACY_CRLF, id='explicit-retry-crlf'),
    pytest.param('publish', LEGACY_LF, id='prepared-publication'),
])
def test_legacy_report_resumes_with_original_renderer(client, tmp_path, monkeypatch, phase, code_digest):
    from app.adapters.task_execution_store import LeaseLost, TaskExecutionStore
    from app.core.config import get_data_dir
    from app.db.database import database_connection
    from app.domain.research_results.execution import ResearchExecution, run_research_report_task

    endpoint, task, content = queue_legacy_report(client, code_digest)
    task_id, revision = task['id'], task['revision']
    task_endpoint = '/api/v1/tasks/' + task_id
    staging = tmp_path / 'stage'
    repository = TaskExecutionStore()
    if phase == 'failed':
        lease = repository.claim(task_id, revision, task_type='research_report')
        # The previous worker already rejected the incompatible current digest.
        repository.fail(lease, 'research_source_conflict')
        workspace = client.get(task_endpoint + '/workspace').json()
        assert workspace['allowed_actions'] == ['retry'], workspace
        retry_body = {'operation': 'retry', 'wait_id': None, 'expected_task_revision': workspace['task']['revision'],
                      'input_version': workspace['task']['input_version']}
        retry_headers = {'Idempotency-Key': 'retry-original-report'}
        with database_connection() as db:
            key = db.execute('SELECT object_key FROM files WHERE id=%s',
                             (task['input_snapshot']['source_file_ids'][0],)).fetchone()['object_key']
        original = Path(get_data_dir()) / key
        raw = original.read_bytes()
        try:
            original.write_bytes(raw + b'changed-source')
            assert client.get(task_endpoint + '/workspace').json()['allowed_actions'] == []
            assert client.post(task_endpoint + '/resume', json=retry_body, headers=retry_headers).status_code == 409
        finally:
            original.write_bytes(raw)
        retry = client.post(task_endpoint + '/resume', json=retry_body, headers=retry_headers)
        assert retry.status_code == 202, retry.text
        revision = retry.json()['revision']
    engine = None
    if phase == 'publish':
        def lose_lease(*args):
            raise LeaseLost()

        with monkeypatch.context() as patch:
            patch.setattr(ResearchExecution, 'publish', lose_lease)
            assert run_research_report_task(task_id, revision, staging_directory=staging) is None
        with database_connection(write=True) as db:
            prepared = db.execute('SELECT next_node, state_json FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',
                                  (task_id,)).fetchone()
            assert prepared['next_node'] == 'publish'
            db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s", (task_id,))
        assert repository.recover_expired() == 1
        revision = client.get(task_endpoint).json()['revision']

        def engine(*args):
            pytest.fail('Publication must use the original prepared bytes')

    done = run_research_report_task(task_id, revision, engine=engine, staging_directory=staging)
    assert done['status'] == 'succeeded', done
    published = client.get(endpoint).json()
    assert published['content'] == content
    assert published['manifest']['renderer_identity'] == task['input_snapshot']['renderer_identity']
    assert {member['role'] for member in published['members']} == {'docx', 'xlsx', 'methods', 'manifest', 'zip'}
    if phase == 'publish':
        assert published['manifest'] == prepared['state_json']['prepared']['manifest']
    package = next(member for member in published['members'] if member['role'] == 'zip')
    with ZipFile(BytesIO(client.get(package['download_url']).content)) as bundle:
        assert json.loads(bundle.read('report_snapshot.json')) == content
    with database_connection() as db:
        saved = db.execute('SELECT input_digest, input_snapshot FROM tasks WHERE id=%s', (task_id,)).fetchone()
    assert saved == {field: task[field] for field in saved}
