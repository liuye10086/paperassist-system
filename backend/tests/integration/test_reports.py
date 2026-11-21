from app.core.paths import BACKEND_ROOT, PROJECT_ROOT
from tests.helpers.auth import session_subprocess_env
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile
from xml.etree import ElementTree as ET

import pytest
from app.db.database import database_connection, ensure_schema_current, migrate_database

from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_boxplot import cloud, prepared, generate  # noqa: F401
from tests.integration.test_explanations import writer, ready, submit, seed_legacy, recover  # noqa: F401


def report_ready(client):
    base, file, result, figure, url = ready(client)
    # Existing report tests consume a historical saved explanation, not a new
    # unified task. New explanations are covered by explicit worker tests.
    seed_legacy(client, url, figure)
    recover()
    explanation = client.get(url).json()['explanation']
    return base, file, result, figure, explanation, url.replace('/explanation', '/report')


def export(client, url, figure, explanation, *, key=None, **changes):
    response = client.post(url, json={'expected_revision': figure['setup_revision'], 'figure_id': figure['id'],
                                     'explanation_id': explanation['id'], **changes},
                           headers={'Idempotency-Key': key} if key else {})
    if response.status_code != 202:
        return response
    # Business tests explicitly execute the queued task in the isolated schema;
    # HTTP acceptance and actual broker behavior have separate tests.
    from app.domain.tasks.execution import run_word_task
    task = response.json()['task']
    run_word_task(task['id'], task['revision'])
    return client.get(url)


def frozen_historical_report(client, url, figure, explanation):
    from app.adapters.task_store import TaskStore
    from app.domain.tasks.contracts import TaskCreateRequest
    from app.domain.tasks.execution import run_word_task
    from tests.helpers.tasks import historical_word_task, task_owner

    project = url.split('/')[4]
    request = TaskCreateRequest(task_type='word_report', file_id=figure['file_id'],
        analysis_run_id=figure['analysis_run_id'], expected_revision=figure['setup_revision'],
        figure_id=figure['id'], explanation_id=explanation['id'])
    task = historical_word_task(TaskStore(task_owner(client)), project, request, 'historical-word')
    done = run_word_task(task['id'], task['revision'])
    assert done['status'] == 'succeeded'
    report = client.get(url).json()['historical_report']
    assert report['id'] == done['result_report_id'] and 'reader_export' not in report
    return report


def stored_report_path(report, *, collection=False):
    from app.core.config import get_data_dir
    from app.domain.storage_governance.historical import report_reference

    with database_connection() as db:
        table = 'collection_reports' if collection else 'reports'
        row = db.execute(f'SELECT * FROM {table} WHERE id=%s', (report['id'],)).fetchone()
        ref = report_reference(db, row, collection=collection)
    path = get_data_dir() / ref['object_key']
    assert hashlib.sha256(path.read_bytes()).hexdigest() == report['sha256'] == ref['sha256']
    return path


def test_report_requires_complete_current_sources(client, cloud):
    _, _, _, url = prepared(client)
    url = url.replace('/boxplot', '/report')
    state = client.get(url)
    assert state.status_code == 200
    assert not state.json()['ready'] and state.json()['issues'] and state.json()['report'] is None
    assert client.post(url, json={'expected_revision': 1, 'figure_id': 'missing', 'explanation_id': 'missing'}).status_code == 409


def test_export_reuses_saved_content_and_png_without_api(client, cloud, writer, monkeypatch):
    _, file, result, figure, explanation, url = report_ready(client)
    monkeypatch.setenv('OPENAI_API_KEY', '')
    calls = (len(cloud.calls), len(writer.calls))
    response = export(client, url, figure, explanation)
    assert response.status_code == 200, response.text
    report = response.json()['report']
    assert report['filename'].startswith('描述统计分析报告 - ')
    assert report['source_sha256'] == file['sha256']
    assert report['figure_sha256'] == figure['sha256'] and report['explanation_id'] == explanation['id']
    downloaded = client.get(url + '/' + report['id'] + '/download')
    assert downloaded.status_code == 200
    assert downloaded.headers['content-type'] == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    assert 'attachment' in downloaded.headers['content-disposition']
    from urllib.parse import unquote
    assert '描述统计分析报告 - ' in unquote(downloaded.headers['content-disposition'])
    assert hashlib.sha256(downloaded.content).hexdigest() == report['sha256']
    with ZipFile(BytesIO(downloaded.content)) as archive:
        root = ET.fromstring(archive.read('word/document.xml'))
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        paragraphs = [''.join(p.itertext()) for p in root.findall('.//w:p', ns)]
        text = '\n'.join(paragraphs)
        record = report['reader_report']
        assert record['origin'] == 'saved_explanation_reuse'
        assert record['sources'][0]['explanation_id'] == explanation['id']
        assert len(record['narrative']) == 7
        for prose in record['narrative'].values():
            for line in prose.splitlines():
                if line:
                    assert line in text
        for internal in (file['sha256'], figure['sha256'], result['id'], explanation['id'], report['id'], '引用键：', '配置版本'):
            assert internal not in text
    from app.adapters.storage import get_project_store
    from tests.helpers.research_report import assert_word_figure_pixels
    assert_word_figure_pixels(downloaded.content, get_project_store().figure_png(figure))
    package = next(member for member in report['members'] if member['role'] == 'zip')
    with ZipFile(BytesIO(client.get(package['download_url']).content)) as archive:
        assert archive.read('analysis.docx') == downloaded.content
        assert hashlib.sha256(archive.read('figures/figure_01/selected_png.png')).hexdigest() == figure['sha256']
    repeat = export(client, url, figure, explanation)
    assert repeat.status_code == 200 and repeat.json()['report'] == report
    assert client.get(url).json()['report'] == report
    assert client.get(url + '/' + report['id'] + '/download').content == downloaded.content
    assert calls == (len(cloud.calls), len(writer.calls))


def test_rejects_wrong_ids_revision_and_unknown_fields(client, cloud, writer):
    *_, figure, explanation, url = report_ready(client)
    for changes in ({'figure_id': 'wrong'}, {'explanation_id': 'wrong'}, {'expected_revision': 2}):
        assert export(client, url, figure, explanation, **changes).status_code == 409
    assert export(client, url, figure, explanation, extra=True).status_code == 422


def test_old_report_download_survives_config_change_and_new_export(client, cloud, writer):
    base, _, result, figure, explanation, url = report_ready(client)
    old = export(client, url, figure, explanation).json()['report']
    assert old['filename'].startswith('描述统计分析报告 - ')
    download = url + '/' + old['id'] + '/download'
    content = client.get(download).content
    client.put(base + '/analysis-setup', json={**result['selection'], 'expected_revision': 1, 'unit': 'new'})
    state = client.get(url).json()
    assert not state['is_current'] and not state['ready'] and state['report'] == old
    replay = export(client, url, figure, explanation)
    assert replay.status_code == 200 and replay.json()['report']['id'] == old['id']
    assert export(client, url, figure, explanation, key='new-key-for-old-analysis').status_code == 409
    assert client.get(download).content == content
    from tests.api.test_descriptive import run
    current = run(client, base, revision=2)
    current_url = base + '/analysis-runs/' + current['id']
    new_figure = generate(client, current_url + '/boxplot', revision=2)
    submit(client, current_url + '/explanation', new_figure)
    new_explanation = client.get(current_url + '/explanation').json()['explanation']
    new = export(client, current_url + '/report', new_figure, new_explanation)
    assert new.status_code == 200 and new.json()['report']['id'] != old['id']
    assert client.get(download).content == content


def test_concurrent_export_saves_one_file(client, cloud, writer, tmp_path):
    *_, figure, explanation, url = report_ready(client)
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: client.post(url, json={'expected_revision': 1,
            'figure_id': figure['id'], 'explanation_id': explanation['id']}), range(4)))
    assert all(item.status_code == 202 for item in responses)
    assert len({item.json()['task']['id'] for item in responses}) == 1
    from app.domain.tasks.execution import run_word_task
    task = responses[0].json()['task']
    run_word_task(task['id'], task['revision'])
    assert client.get(url).json()['report'] is not None
    assert run_word_task(task['id'], task['revision']) is None
    report = client.get(url).json()['report']
    path = stored_report_path(report)
    assert path.read_bytes() == client.get(url + '/' + report['id'] + '/download').content
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM reports').fetchone()['n'] == 1
        assert db.execute("SELECT count(*) AS n FROM research_report_members WHERE role='docx'").fetchone()['n'] == 1


def test_configuration_change_during_build_does_not_save(client, cloud, writer, monkeypatch, tmp_path):
    from app.domain.tasks import execution
    from tests.integration.test_task_execution import queued

    task, base, result, _ = queued(client, historical=True)
    original = execution.build_report

    def changed(*args):
        content = original(*args)
        updated = client.put(base + '/analysis-setup', json={**result['selection'], 'expected_revision': 1, 'unit': 'changed'})
        assert updated.status_code == 200, updated.text
        return content

    monkeypatch.setattr(execution, 'build_report', changed)
    finished = execution.run_word_task(task['id'], task['revision'])
    assert finished['status'] == 'failed' and finished['error_code'] == 'task_source_conflict'
    assert not list((tmp_path / 'data' / 'reports').rglob('*.docx'))
    with database_connection() as db:
        assert db.execute('SELECT 1 FROM reports').fetchone() is None


@pytest.mark.parametrize('damage', ['missing', 'changed'])
def test_report_download_detects_damage(client, cloud, writer, tmp_path, damage):
    *_, figure, explanation, url = report_ready(client)
    report = frozen_historical_report(client, url, figure, explanation)
    path = stored_report_path(report)
    if damage == 'missing':
        path.unlink()
    else:
        path.write_bytes(b'bad')
    status = 410 if damage == 'missing' else 409
    assert client.get(url + '/' + report['id'] + '/download').status_code == status
    assert export(client, url, figure, explanation).status_code == status


def test_foreign_run_and_project_cannot_download_report(client, cloud, writer):
    _, _, result, figure, explanation, url = report_ready(client)
    report = export(client, url, figure, explanation).json()['report']
    base2, _, result2, _, _, url2 = report_ready(client)
    assert client.get(url2 + '/' + report['id'] + '/download').status_code == 404
    assert client.get(base2 + '/analysis-runs/' + result['id'] + '/report/' + report['id'] + '/download').status_code == 404


def test_export_survives_fresh_process_after_explicit_migration(client, cloud, writer, tmp_path):
    *_, figure, explanation, url = report_ready(client)
    report = export(client, url, figure, explanation).json()['report']
    migrate_database()
    script = """from fastapi.testclient import TestClient
from app.main import app
import hashlib, sys
with TestClient(app, cookies={"paperassist_session": __import__("os").environ["PAPERASSIST_TEST_SESSION_COOKIE"]}) as c:
 r=c.get(sys.argv[1]); print(r.status_code, hashlib.sha256(r.content).hexdigest())
"""
    process = subprocess.run([sys.executable, '-c', script, url + '/' + report['id'] + '/download'],
                             cwd=BACKEND_ROOT, env=session_subprocess_env(client), capture_output=True, text=True, check=True)
    assert process.stdout.strip() == '200 ' + report['sha256']
    with database_connection() as db:
        ensure_schema_current(db)


def test_changed_explanation_evidence_is_rejected(client, cloud, writer, tmp_path):
    *_, figure, explanation, url = report_ready(client)
    explanation['sections'][0]['evidence'][0]['value'] = 'forged'
    with database_connection(write=True) as db:
        db.execute('UPDATE explanations SET explanation_json=%s WHERE id=%s', (json.dumps(explanation), explanation['id']))
    assert export(client, url, figure, explanation).status_code == 409


def test_write_failure_leaves_no_report_and_can_retry(client, cloud, writer, monkeypatch, tmp_path):
    *_, figure, explanation, url = report_ready(client)
    from app.domain.statistics_reader_reports.legacy_exports import StatisticsLegacyReportService

    def fail(*args, **kwargs):
        raise OSError('disk unavailable while publishing report members')

    with monkeypatch.context() as patch:
        patch.setattr(StatisticsLegacyReportService, 'publish_members', fail)
        failed = export(client, url, figure, explanation).json()['task']
        assert failed['status'] == 'failed' and failed['error_code'] == 'storage_unavailable'
    with database_connection() as db:
        assert db.execute('SELECT 1 FROM reports').fetchone() is None
        assert db.execute('SELECT 1 FROM research_report_members').fetchone() is None
    retried = client.post('/api/v1/tasks/' + failed['id'] + '/retry', json={'expected_revision': failed['revision']})
    assert retried.status_code == 202
    from app.domain.tasks.execution import run_word_task
    task = retried.json()
    run_word_task(task['id'], task['revision'])
    assert client.get(url).json()['report'] is not None


def test_cached_report_survives_revision_race(client, cloud, writer, monkeypatch):
    from app.domain import reports
    base, _, result, figure, explanation, url = report_ready(client)
    report = export(client, url, figure, explanation).json()['report']
    download = url + '/' + report['id'] + '/download'
    content = client.get(download).content
    context = reports.context
    def changed(*args, **kwargs):
        value = context(*args, **kwargs)
        update = client.put(base + '/analysis-setup', json={**result['selection'], 'expected_revision': 1, 'unit': 'changed'})
        assert update.status_code == 200, update.text
        return value

    with monkeypatch.context() as patch:
        patch.setattr(reports, 'context', changed)
        replay = export(client, url, figure, explanation)
    assert replay.status_code == 200 and replay.json()['report']['id'] == report['id']
    assert export(client, url, figure, explanation, key='new-after-race').status_code == 409
    assert client.get(download).content == content


@pytest.mark.parametrize('source', ['files', 'figures'])
def test_source_damage_blocks_new_export_but_existing_download_is_independent(client, cloud, writer, tmp_path, source):
    _, file, _, figure, explanation, url = report_ready(client)
    historical = frozen_historical_report(client, url, figure, explanation)
    current = export(client, url, figure, explanation).json()['report']
    filename = file['id'] + '.xlsx' if source == 'files' else figure['id'] + '.png'
    (tmp_path / 'data' / source / filename).write_bytes(b'damaged')
    assert export(client, url, figure, explanation, key='new-after-damage').status_code == 409
    assert client.get(url + '/' + current['id'] + '/download').status_code == 409
    downloaded = client.get(url + '/' + historical['id'] + '/download')
    assert downloaded.status_code == 200
    assert hashlib.sha256(downloaded.content).hexdigest() == historical['sha256']


def test_docx_handles_long_labels_controls_and_extreme_values(client, cloud, writer):
    from app.domain import reports
    from app.adapters.report_store import ReportStore
    from app.adapters.storage import get_project_store
    base, _, _, figure, explanation, url = report_ready(client)
    parts = base.split('/')
    snapshot, _ = reports.context(get_project_store(), parts[4], parts[6], figure['analysis_run_id'])
    snapshot['project']['name'] = '中文很长的项目标题' * 30 + '\x01<&'
    snapshot['result']['groups'][0]['label'] = '中文长分组' * 30
    snapshot['result']['overall'].update(mean=1.7976931348623157e308, std=None)
    content = reports.build_report(snapshot, ReportStore.metadata(snapshot), get_project_store().figure_png(figure))
    with ZipFile(BytesIO(content)) as archive:
        root = ET.fromstring(archive.read('word/document.xml'))
        text = ''.join(root.itertext())
        assert '�<&' in text and '1.79769e+308' in text and '无法计算' in text
