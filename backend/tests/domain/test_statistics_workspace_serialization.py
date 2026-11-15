"""The real workspace route must retain R3 fields through response_model."""
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from tests.integration.test_statistics_summary_projection import report_metadata


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


@pytest.mark.parametrize('kind',('word_report','collection_word_report'))
@pytest.mark.parametrize('state',('reader','historical','pending'))
def test_workspace_http_response_preserves_fixed_reader_fields_and_legacy_shape(monkeypatch,kind,state):
    from app.api import tasks
    fixed=report_metadata('saved-report',kind,reader=state!='historical')
    report=dict(filename=fixed['filename'],download_url='/fixed/original-word-download',
        **{key:fixed[key] for key in ('reader_export','reader_report','members') if key in fixed})
    artifacts=dict(figure=None,explanation=None,report=report if state!='pending' else None)
    if state!='historical':artifacts['reader_export']=fixed['reader_export']
    version=dict(setup_revision=1,output_language='zh-CN')
    if kind=='collection_word_report':
        version=dict(kind='report_collection',collection_version_id='collection-version',export_revision=1,
            output_language='zh-CN',workflow_version='collection_word_report_v1')
    payload=dict(task=dict(id='saved-report-task',project_id='project',task_type=kind,status='queued' if state=='pending' else 'succeeded',
        phase='export',display_status='queued' if state=='pending' else 'succeeded',revision=1,current_attempt=0,
        reason_code=None,created_at='2026-11-15T12:00:00+00:00',updated_at='2026-11-15T12:00:00+00:00',input_version=version),
        source=dict(file_id='file',filename='input.csv',analysis_run_id='run' if kind=='word_report' else None,is_current=True),
        wait=None,allowed_actions=[],artifacts=artifacts)
    # Use the registered production router and its actual response_model;
    # substitute only the already-verified service boundary and auth scope.
    monkeypatch.setattr(tasks,'TaskWorkspaceService',lambda owner:SimpleNamespace(get=lambda identifier:payload))
    app=FastAPI();app.include_router(tasks.router)
    app.dependency_overrides[tasks.get_request_task_store]=lambda:SimpleNamespace(user_id='owner')
    with TestClient(app) as client:
        response=client.get('/api/v1/tasks/saved-report-task/workspace')
    assert response.status_code==200,response.text
    value=response.json()['artifacts']
    if state=='historical':
        assert 'reader_export' not in value
        assert value['report']==report=={'filename':fixed['filename'],'download_url':'/fixed/original-word-download'}
    else:
        assert value['reader_export']==fixed['reader_export']
        if state=='pending':assert value['report'] is None
        else:
            assert value['report']==report
            assert value['report']['members']==fixed['members']
            assert value['report']['reader_report']==fixed['reader_report']
