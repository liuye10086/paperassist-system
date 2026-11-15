"""The bridge keeps genuine legacy identities and frozen output policies."""
import importlib.util
import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def test_explicit_legacy_export_policy_is_available():
    assert importlib.util.find_spec('app.domain.statistics_reader_reports.legacy_exports') is not None


def test_unmarked_old_tasks_are_not_reader_exports():
    from app.domain.statistics_reader_reports.legacy_exports import is_reader_export
    for kind in ('word_report', 'collection_word_report', 'research_report'):
        assert not is_reader_export(dict(task_type=kind, input_snapshot={}))


def test_marker_cannot_change_original_task_identity():
    from app.domain.statistics_reader_reports.legacy_exports import is_reader_export, POLICY
    assert is_reader_export(dict(task_type='word_report', input_snapshot={'reader_export': {'policy': POLICY}}))
    assert not is_reader_export(dict(task_type='research_report', input_snapshot={'reader_export': {'policy': POLICY}}))


def test_governance_uses_trusted_member_object_not_a_second_word_path():
    from app.domain.storage_governance.historical import report_reference
    record = dict(id='report',report_json=dict(id='report',reader_export={'policy':'statistics_reader_export_v1'},
        sha256='a'*64,size_bytes=12))
    class DB:
        def execute(self, sql, args):
            self.args=args
            return self
        def fetchone(self):
            return dict(object_key='research-results/version/content.bin',sha256='a'*64,size_bytes=12)
    assert report_reference(DB(),record,collection=False)['object_key']=='research-results/version/content.bin'


def fixed_word_task():
    from app.domain.statistics_reader_reports.legacy_exports import POLICY, RENDERER, OUTPUT_POLICY, ADAPTER_VERSION
    from app.domain.bioinformatics.contracts import digest
    from app.domain.tasks.contracts import TaskCreateRequest
    from app.domain.external_processing import request_digest
    request=TaskCreateRequest(task_type='word_report',file_id='file',analysis_run_id='run',expected_revision=1,
        figure_id='figure',explanation_id='explanation')
    snapshot=dict(file={'id':'file'},result={'id':'run','setup_revision':1},figure={'id':'figure'},
        explanation={'id':'explanation'},project={'id':'project'},output_language='en',versions={'report':RENDERER})
    snapshot['reader_export']=dict(policy=POLICY,adapter_version=ADAPTER_VERSION,output_policy=OUTPUT_POLICY,
        context_id='context',report_version_id='version',content_sha256='a'*64,source_snapshot_sha256=digest(snapshot))
    return dict(id='task',task_type='word_report',workflow_version='word_report_v1',project_id='project',
        input_digest=request_digest(request),input_snapshot=snapshot,status='succeeded',result_report_id='word')


def test_bridge_identity_keeps_request_digest_and_separately_binds_snapshot():
    from app.domain.statistics_reader_reports.legacy_exports import input_identity
    from app.domain.bioinformatics.contracts import digest
    from app.core.exceptions import StorageError
    task=fixed_word_task();version=input_identity(task)
    assert version['source_sha256']==task['input_digest']
    assert version['snapshot_sha256']==digest(task['input_snapshot'])!=task['input_digest']
    task['input_snapshot']['result']['id']='changed'
    with pytest.raises(StorageError):input_identity(task)


def test_succeeded_bridge_requires_its_compatibility_report_identity():
    from app.domain.statistics_reader_reports.legacy_exports import StatisticsLegacyReportService
    from app.core.exceptions import StorageError
    task=fixed_word_task();marker=task['input_snapshot']['reader_export']
    service=object.__new__(StatisticsLegacyReportService)
    service.require=lambda *args:dict(marker,report_id=None,collection_report_id=None)
    with pytest.raises(StorageError):service.association(None,task)
