"""Completed-result reuse with real publication and synthetic scientific inputs."""
from tests.api.test_projects import client


def counts():
    from app.db.database import database_connection
    with database_connection() as db:
        return {table: db.execute('SELECT count(*) AS n FROM ' + table).fetchone()['n']
                for table in ('tasks', 'task_attempts', 'task_outbox', 'bio_insight_runs',
                              'bio_insight_result_versions', 'research_report_versions')}


def test_completed_insight_reuses_published_result_without_new_task(client, monkeypatch, tmp_path):
    from tests.api.test_bio_insight_publication import create_run, synthetic_engine
    from app.domain.bio_insights.execution import run_bio_insight_task
    project, run = create_run(client, monkeypatch)
    done = run_bio_insight_task(run['task_id'], run['task_revision'], task_type='bio_result_import',
                               engine=synthetic_engine, staging_directory=tmp_path / 'stage')
    assert done['status'] == 'succeeded', done
    base = f'/api/v1/projects/{project}'
    old = client.get(base + '/bio-insight-runs/' + run['id']).json()
    before = counts()
    request = dict(plan_version_id=run['plan_version_id'], expected_plan_revision=1,
                   source_digest=run['source_digest'])
    reused = client.post(base + '/bio-insight-runs', json=request,
                         headers={'Idempotency-Key': 'completed-insight-alias'})
    assert reused.status_code == 200, reused.text
    assert reused.json()['id'] == old['id']
    assert reused.json()['result_version_id'] == old['result_version_id']
    assert reused.json()['task']['status'] == 'succeeded'
    lookup = client.get(base + '/bio-insight-requests/completed-insight-alias?kind=run')
    assert lookup.status_code == 200 and lookup.json()['id'] == old['id']
    assert counts() == before


def test_completed_report_reuses_word_bytes_without_new_task(client, tmp_path):
    from tests.api.test_research_findings import selected_cell
    from app.domain.research_results.execution import run_research_task
    from app.adapters.research_report_render import render_report
    base, source = selected_cell(client)
    finding = client.post(base + '/research-findings', json={'title': 'Result', 'sources': [source]},
                          headers={'Idempotency-Key': 'completed-finding'}).json()
    request = dict(title='Word reuse', finding_version_id=finding['id'])
    created = client.post(base + '/research-reports', json=request,
                          headers={'Idempotency-Key': 'completed-report'})
    assert created.status_code == 201, created.text
    report = created.json()
    done = run_research_task(report['task_id'], report['task']['revision'], task_type='research_report',
                            engine=render_report, staging_directory=tmp_path / 'stage')
    assert done['status'] == 'succeeded', done
    old = client.get(base + '/research-reports/' + report['id']).json()
    word = next(member for member in old['members'] if member['role'] == 'docx')
    content = client.get(word['download_url']).content
    before = counts()
    reused = client.post(base + '/research-reports', json=request,
                         headers={'Idempotency-Key': 'completed-report-alias'})
    assert reused.status_code == 200, reused.text
    assert reused.json()['id'] == old['id'] and reused.json()['manifest_sha256'] == old['manifest_sha256']
    assert client.get(word['download_url']).content == content
    lookup = client.get(base + '/research-requests/completed-report-alias?kind=report')
    assert lookup.status_code == 200 and lookup.json()['id'] == old['id']
    assert counts() == before
