"""Original report routes publish the shared detailed suite under their real task."""
from io import BytesIO
from zipfile import ZipFile
import pytest

from app.db.database import database_connection
from tests.integration.test_reports import client, cloud, writer, report_ready  # noqa: F401
from tests.api.test_statistics_reader_reports import call_count, seed_ordered_collection


def retain_artifacts(name, report, members):
    """Optional local engineering evidence; never changes application publication."""
    import json
    import os
    from pathlib import Path
    target=os.environ.get('PAPERASSIST_R3_TEST_ARTIFACTS')
    if not target:return
    root=Path(target)/name;root.mkdir(parents=True,exist_ok=True)
    for role,response in members.items():
        (root/('analysis.'+role)).write_bytes(response.content)
    (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')


def assert_account_deletion_with_missing_docx(client, project, report):
    from fastapi.testclient import TestClient
    from app.auth.service import create_user
    from app.core.config import get_data_dir
    from app.main import app
    from tests.api.test_account_deletion import delete
    from tests.api.test_admin_operations import PASSWORD, login

    version = report['reader_export']['report_version_id']
    with database_connection() as db:
        members = db.execute('''SELECT m.role,o.id,o.object_key FROM research_report_members m
            JOIN storage_objects o ON o.id=m.storage_object_id WHERE m.report_version_id=%s''', (version,)).fetchall()
    word, = [member for member in members if member['role'] == 'docx']
    root = get_data_dir()
    assert all((root / member['object_key']).is_file() for member in members)
    docx = root / word['object_key']
    docx.unlink()

    account = client.get('/api/v1/auth/me').json()['user']
    actor = create_user('legacy-erasure-admin@paperassist.local', PASSWORD, 'admin')
    with TestClient(app) as admin:
        login(admin, actor)
        scan = admin.post('/api/v1/admin/storage/scan')
        assert scan.status_code == 200, scan.text
        with database_connection() as db:
            assert db.execute('SELECT state FROM storage_objects WHERE id=%s', (word['id'],)).fetchone()['state'] == 'missing'
        download = next(member['download_url'] for member in report['members'] if member['role'] == 'docx')
        assert client.get(download).status_code == 409

        # The old inventory state is not authority to remove replacement bytes.
        replacement = b'unattributed replacement bytes'
        docx.write_bytes(replacement)
        blocked = delete(admin, account)
        assert blocked.status_code == 409 and blocked.json()['detail']['code'] == 'account_delete_blocked'
        assert docx.read_bytes() == replacement
        assert client.get('/api/v1/auth/me').status_code == 200
        docx.unlink()

        response = delete(admin, account)
        assert response.status_code == 200, response.text
        assert response.json() == {'id': account['id'], 'deleted': True}
    assert all(not (root / member['object_key']).exists() for member in members)
    with database_connection() as db:
        assert not db.execute('SELECT id FROM users WHERE id=%s', (account['id'],)).fetchone()
        assert not db.execute('SELECT id FROM storage_objects WHERE id=ANY(%s)', ([member['id'] for member in members],)).fetchall()
        for table in ('statistics_legacy_report_exports', 'statistics_legacy_export_requests', 'research_report_members'):
            assert not db.execute('SELECT 1 FROM ' + table + ' WHERE project_id=%s', (project,)).fetchone()


def test_original_word_route_publishes_atomic_governed_members(client, cloud, writer, tmp_path, monkeypatch):
    from app.domain.tasks.execution import run_word_task
    monkeypatch.setenv('PAPERASSIST_RESEARCH_STAGING_DIR', str(tmp_path/'research-staging'))
    _, _, result, figure, explanation, url = report_ready(client)
    before = call_count()
    response = client.post(url, json=dict(expected_revision=result['setup_revision'], figure_id=figure['id'], explanation_id=explanation['id']))
    assert response.status_code == 202, response.text
    task = response.json()['task']
    for key in ('parallel-key-one','parallel-key-two'):
        replay=client.post(url,json=dict(expected_revision=result['setup_revision'],figure_id=figure['id'],explanation_id=explanation['id']),headers={'Idempotency-Key':key})
        assert replay.status_code==202 and replay.json()['task']['id']==task['id']
    with database_connection() as db:
        saved = db.execute('SELECT * FROM tasks WHERE id=%s', (task['id'],)).fetchone()
        assert saved['input_snapshot'].get('reader_export', {}).get('policy') == 'statistics_reader_export_v1'
        assert saved['task_type'] == 'word_report'
    from app.domain.statistics_reader_reports.legacy_exports import StatisticsLegacyReportService
    original=StatisticsLegacyReportService.publish_members
    def interrupted(self,db,task,identifier,prepared,*,progress):
        original(self,db,task,identifier,prepared,progress=progress)
        raise OSError('Synthetic interruption after member inserts')
    monkeypatch.setattr(StatisticsLegacyReportService,'publish_members',interrupted)
    failed=run_word_task(task['id'],task['revision'])
    assert failed['status']=='failed' and failed['error_code']=='storage_unavailable',failed
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM reports').fetchone()['n']==0
        assert db.execute('SELECT count(*) AS n FROM research_report_members').fetchone()['n']==0
        assert db.execute('SELECT manifest_object_id FROM research_report_versions WHERE task_id=%s',(task['id'],)).fetchone()['manifest_object_id'] is None
        checkpoint=db.execute('SELECT state_json FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(task['id'],)).fetchone()['state_json']
        prepared_shas=[member['sha256'] for member in checkpoint['prepared']['members']]
    monkeypatch.setattr(StatisticsLegacyReportService,'publish_members',original)
    retried=client.post('/api/v1/tasks/'+task['id']+'/retry',json={'expected_revision':failed['revision']})
    assert retried.status_code==202,retried.text
    def no_second_render(*args):raise AssertionError('Prepared recovery must not render again')
    done = run_word_task(task['id'], retried.json()['revision'], engine=no_second_render)
    assert done['status'] == 'succeeded', done
    report = client.get(url).json()['report']
    assert report['reader_export']['task_id'] == task['id']
    assert report['reader_report']['origin'] == 'saved_explanation_reuse'
    members = {member['role']: client.get(member['download_url']) for member in report['members']}
    assert set(members) == {'docx', 'xlsx', 'zip'}
    assert all(member.status_code == 200 for member in members.values())
    assert client.get(url+'/'+report['id']+'/download').content == members['docx'].content
    retain_artifacts('single',report,members)
    with ZipFile(BytesIO(members['zip'].content)) as package:
        assert package.read('analysis.docx') == members['docx'].content
        assert package.read('results.xlsx') == members['xlsx'].content
    with database_connection() as db:
        saved = db.execute('SELECT * FROM tasks WHERE id=%s', (task['id'],)).fetchone()
        assert saved['result_report_id'] == report['id']
        assert saved['result_research_report_version_id'] is None
        assert db.execute('SELECT count(*) AS n FROM statistics_legacy_report_exports WHERE task_id=%s', (task['id'],)).fetchone()['n'] == 1
        saved_shas=db.execute('SELECT sha256 FROM research_report_members WHERE report_version_id=%s',(report['reader_export']['report_version_id'],)).fetchall()
        assert sorted(prepared_shas)==sorted(row['sha256'] for row in saved_shas)
    from app.adapters.storage import get_project_store
    from app.domain.manuscripts.service import ManuscriptService
    from app.domain.manuscripts.analysis_selection import report_source
    from app.domain.report_collections.service import scoped_store
    assets=scoped_store(saved['user_id'])
    source=report_source(ManuscriptService(assets),saved['project_id'],saved['input_snapshot']['file']['id'],report['id'])
    assert source['report_id']==report['id'] and source['text_total_characters']>0
    from app.maintenance.research_results_audit import validate_research_task_source
    from app.domain.storage_governance.historical import report_reference
    with database_connection() as db:
        assert validate_research_task_source(db,saved)['id']==report['reader_export']['report_version_id']
        row=db.execute('SELECT * FROM reports WHERE id=%s',(report['id'],)).fetchone()
        assert report_reference(db,row)['object_key'].startswith('research-results/')
        assert db.execute('SELECT count(*) AS n FROM statistics_legacy_export_requests WHERE task_id=%s',(task['id'],)).fetchone()['n']==3
    from app.domain.file_lifecycle.service import FileLifecycleService
    assessment=FileLifecycleService(assets).assessment(saved['project_id'],saved['input_snapshot']['file']['id'])
    assert {'code':'integrity_unknown'} not in assessment['reasons']
    from app.db.database import migration_connection
    for sql,args in [('UPDATE statistics_legacy_report_exports SET context_id=%s WHERE task_id=%s',('wrong',task['id'])),
                     ('DELETE FROM statistics_legacy_report_exports WHERE task_id=%s',(task['id'],))]:
        with pytest.raises(Exception,match='immutable'):
            with migration_connection(write=True) as db:db.execute(sql,args)
    from tests.integration.test_account_deletion_migration import migrate
    with pytest.raises(RuntimeError,match='Saved statistics exports exist'):
        migrate('0084_statistics_report_context',down=True)
    assert call_count() == before
    repeat = client.post(url, json=dict(expected_revision=result['setup_revision'], figure_id=figure['id'], explanation_id=explanation['id']))
    assert repeat.status_code == 200 and repeat.json()['report'] == report
    from tests.integration.test_project_ownership import account_client
    stranger,_=account_client('legacy-stranger@paperassist.local',role='analyst')
    try:
        assert stranger.get(url+'/'+report['id']+'/download').status_code==404
        assert all(stranger.get(member['download_url']).status_code==404 for member in report['members'])
    finally:
        stranger.close()
    assert_account_deletion_with_missing_docx(client, saved['project_id'], report)


def test_original_collection_export_uses_same_suite(client, monkeypatch, tmp_path):
    from app.domain.report_collections.execution import run_collection_word_task
    monkeypatch.setenv('PAPERASSIST_RESEARCH_STAGING_DIR', str(tmp_path/'research-staging'))
    seeded = seed_ordered_collection(client, monkeypatch)
    repository, state, project = seeded['repository'], seeded['state'], seeded['project_id']
    version = state['versions'][0]
    request = repository.export(project, state['id'], version['id'], 'reader-explicit')
    before = call_count()
    done = run_collection_word_task(request['task_id'], 1)
    assert done['status'] == 'succeeded', done
    report = repository.get(project, state['id'])['versions'][0]['requests'][0]['report']
    assert report['reader_export']['task_type'] == 'collection_word_report'
    assert {member['role'] for member in report['members']} == {'docx', 'xlsx', 'zip'}
    metadata, raw = repository.download(project, state['id'], report['id'])
    assert raw == client.get(next(m['download_url'] for m in report['members'] if m['role']=='docx')).content
    assert metadata == report and call_count() == before
    retain_artifacts('ordered-collection',report,{m['role']:client.get(m['download_url']) for m in report['members']})
    # An accepted waiting row from before the installation keeps its renderer.
    from uuid import uuid4
    from psycopg.types.json import Jsonb
    from app.domain.report_collections.contracts import RENDERER as old_renderer
    from app.adapters.report_store import digest
    old_id=str(uuid4())
    with repository.store.connection(write=True) as db:
        fixed=db.execute('SELECT * FROM report_collection_versions WHERE id=%s',(version['id'],)).fetchone()
        db.execute('''INSERT INTO report_build_requests(id,version_id,export_revision,renderer_version,request_key,request_digest,
            status,dependencies_json,created_at,updated_at) VALUES(%s,%s,2,%s,'old-waiting',%s,'waiting',%s,now(),now())''',
            (old_id,version['id'],old_renderer,digest(dict(version_id=version['id'],sha256=fixed['sha256'],request_key='old-waiting')),Jsonb([])))
        repository.advance_in_transaction(db,project,old_id)
        old=repository.request_view(db,old_id)
        task=db.execute('SELECT * FROM tasks WHERE id=%s',(old['task_id'],)).fetchone()
        assert 'reader_export' not in task['input_snapshot']
    done=run_collection_word_task(old['task_id'],1)
    assert done['status']=='succeeded',done
    old=repository.export(project,state['id'],version['id'],'old-waiting')
    assert old['renderer_version']==old_renderer and 'reader_export' not in old['report']
    assert repository.download(project,state['id'],old['report']['id'])[1]
    assert repository.export(project,state['id'],version['id'],'reader-explicit')['report']==report
    from app.domain.report_collections.contracts import CollectionRequest
    automatic=repository.new_version(project,state['id'],CollectionRequest(title='Ordered statistics',language='en',
        items=seeded['items'],automatic=True,expected_revision=1),'new-automatic')
    build=automatic['versions'][0]['requests'][0]
    assert build['status']=='queued' and build['output_policy']=='statistics_reader_export_v1'
    with repository.store.connection() as db:
        fixed=db.execute('SELECT request_key FROM report_build_requests WHERE id=%s',(build['id'],)).fetchone()
        assert fixed['request_key']=='automatic:r3'
    done=run_collection_word_task(build['task_id'],1)
    assert done['status']=='succeeded',done
    assert call_count()==before
    assert_account_deletion_with_missing_docx(client, project, report)


def test_old_queued_failed_task_and_request_key_keep_original_policy(client, cloud, writer, monkeypatch, tmp_path):
    from datetime import datetime, timezone
    from uuid import uuid4
    from app.adapters.storage import get_project_store
    from app.adapters.task_store import TaskStore, workflow_version
    from app.domain.tasks.contracts import TaskCreateRequest
    from app.domain.external_processing import request_digest
    from app.domain.tasks.execution import run_word_task
    from app.domain.report_tasks import retry_word_task
    from app.domain.statistics_reader_reports.render import execute_statistics_report as render_report
    from app.domain.tasks import execution
    _, _, result, figure, explanation, url = report_ready(client)
    project=url.split('/')[4]
    from app.domain.report_collections.service import scoped_store
    assets=scoped_store(client.get('/api/v1/auth/me').json()['user']['id']);store=TaskStore(assets.owner_id,assets.db_config)
    request=TaskCreateRequest(task_type='word_report',file_id=result['file_id'],analysis_run_id=result['id'],
        expected_revision=result['setup_revision'],figure_id=figure['id'],explanation_id=explanation['id'])
    with store.connection(write=True) as db:
        snapshot=store.source_snapshot(db,store.require_project(db,project),request)
        moment=datetime.now(timezone.utc)
        task=dict(id=str(uuid4()),project_id=project,user_id=store.user_id,task_type='word_report',
            idempotency_key='old-accepted-key',input_digest=request_digest(request),input_snapshot=snapshot,
            workflow_version=workflow_version('word_report',snapshot),status='queued',phase='export',revision=1,
            current_attempt=0,reason_code=None,created_at=moment,updated_at=moment)
        store.insert_task(db,task);store.append_event(db,task,'created');store.enqueue(db,task)
    original=execution.build_report
    def failed_render(*args):raise OSError('Synthetic old renderer interruption')
    monkeypatch.setattr(execution,'build_report',failed_render)
    failed=run_word_task(task['id'],1)
    assert failed['status']=='failed'
    queued=retry_word_task(store,task['id'],failed['revision'])
    monkeypatch.setattr(execution,'build_report',original)
    done=run_word_task(task['id'],queued['revision'])
    assert done['status']=='succeeded',done
    state=client.get(url).json()
    assert state['report'] is None and state['historical_report']['id']==done['result_report_id']
    historic=client.get(url+'/'+done['result_report_id']+'/download').content
    body=dict(expected_revision=result['setup_revision'],figure_id=figure['id'],explanation_id=explanation['id'])
    replay=client.post(url,json=body,headers={'Idempotency-Key':'old-accepted-key'})
    assert replay.status_code==200 and replay.json()['task']['id']==task['id']
    fresh=client.post(url,json=body,headers={'Idempotency-Key':'explicit-detailed-key'})
    assert fresh.status_code==202 and fresh.json()['task']['id']!=task['id']
    new=fresh.json()['task']
    assert run_word_task(new['id'],new['revision'],engine=render_report,staging_directory=tmp_path/'new')['status']=='succeeded'
    assert client.get(url+'/'+done['result_report_id']+'/download').content==historic
    with database_connection() as db:
        old=db.execute('SELECT * FROM tasks WHERE id=%s',(task['id'],)).fetchone()
        assert old['input_snapshot']==snapshot and 'reader_export' not in old['input_snapshot']


@pytest.mark.parametrize('failure', ('quota','lease','source'))
def test_rejected_publication_never_exposes_partial_suite(client, cloud, writer, monkeypatch, tmp_path, failure):
    from app.domain.statistics_reader_reports.render import execute_statistics_report as render_report
    from app.domain.tasks.execution import run_word_task
    from app.domain.research_results import execution
    from app.domain.statistics_reader_reports.legacy_exports import StatisticsLegacyReportService
    from app.adapters.storage import get_project_store
    from app.core.exceptions import StorageError
    _, _, result, figure, explanation, url=report_ready(client)
    response=client.post(url,json=dict(expected_revision=result['setup_revision'],figure_id=figure['id'],explanation_id=explanation['id']))
    assert response.status_code==202,response.text
    task=response.json()['task'];changed=None
    if failure=='quota':
        def refused(*args,**kwargs):raise StorageError('storage_quota_exceeded','Synthetic quota refusal',409)
        monkeypatch.setattr(execution,'admit_bio_manifest',refused)
    elif failure=='lease':
        original=StatisticsLegacyReportService.publish
        def expired(self,db,task,checkpoint,moment,prepared,*,progress):
            calls=[]
            def checked():
                calls.append(1)
                if len(calls)==len(prepared['members'])+1:
                    db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s",(task['id'],))
                progress()
            return original(self,db,task,checkpoint,moment,prepared,progress=checked)
        monkeypatch.setattr(StatisticsLegacyReportService,'publish',expired)
    else:
        path=get_project_store().directory/'figures'/(figure['id']+'.png')
        changed=(path,path.read_bytes());path.write_bytes(changed[1]+b'changed')
    try:
        done=run_word_task(task['id'],task['revision'],engine=render_report,staging_directory=tmp_path/'rejected')
        assert done is None if failure=='lease' else done['status']=='failed'
        if failure=='quota':assert done['error_code']=='storage_quota_exceeded'
        if failure=='quota':
            replay=client.post(url,json=dict(expected_revision=result['setup_revision'],figure_id=figure['id'],explanation_id=explanation['id']),
                headers={'Idempotency-Key':'another-key-after-failure'})
            assert replay.status_code==202 and replay.json()['task']['id']==task['id'],replay.text
        with database_connection() as db:
            assert db.execute('SELECT count(*) AS n FROM research_report_members').fetchone()['n']==0
            assert db.execute('SELECT count(*) AS n FROM reports').fetchone()['n']==0
            assert db.execute('SELECT manifest_object_id FROM research_report_versions WHERE task_id=%s',(task['id'],)).fetchone()['manifest_object_id'] is None
    finally:
        if changed:changed[0].write_bytes(changed[1])
