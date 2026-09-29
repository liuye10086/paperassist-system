from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
from threading import Barrier

from PIL import Image
import pytest
from app.database import database_connection, migrate_database

from test_analysis import client, add_file, selection  # noqa: F401
from test_descriptive import configured, run


@pytest.fixture
def cloud(monkeypatch):
    from app import boxplot
    class FakeCloud:
        calls = []
        pending = False
        corrupt = False
        def __init__(self, model=None):
            self.model = model or 'test-model'
        def start(self, payload, task_id, on_container):
            self.calls.append(payload)
            on_container('cntr_test')
            return 'resp_test'
        def fetch(self, job):
            if self.pending:
                return None
            # Explicit synthetic provider response: never a real OpenAI result.
            manifest = json.loads(json.dumps(job['expected']))
            if self.corrupt:
                manifest['overall']['mean'] += 10
            buffer = BytesIO()
            Image.new('RGB', (1600, 1200), 'white').save(buffer, format='PNG')
            return {'png': buffer.getvalue(), 'manifest': manifest,
                    'provenance': {'response_id': 'resp_test', 'container_id': 'cntr_test', 'model': 'test-model',
                                   'code': ['# Synthetic provider test'], 'usage': {'input_tokens': 100, 'output_tokens': 100}}}
    monkeypatch.setattr(boxplot, 'CloudPlot', FakeCloud)
    monkeypatch.setenv('OPENAI_API_KEY', 'test-only-not-a-key')
    monkeypatch.setenv('OPENAI_MODEL', 'test-model')
    return FakeCloud


def prepared(client, rows=None, **changes):
    base, record = configured(client, rows, **changes)
    result = run(client, base)
    return base, record, result, base + '/analysis-runs/' + result['id'] + '/boxplot'


def generate(client, url, revision=1):
    response = client.post(url, json={'expected_revision': revision})
    assert response.status_code in (200, 202), response.text
    response = client.get(url)
    assert response.status_code == 200, response.text
    state = response.json()
    assert state['figure'] is not None, state
    return state['figure']


def test_missing_api_configuration_preserves_local_features(client, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', '')
    monkeypatch.setenv('OPENAI_MODEL', '')
    response = client.get('/api/v1/ai/config')
    assert response.status_code == 200
    assert response.json()['configured'] is False
    base, _, result, url = prepared(client)
    assert client.post(url, json={'expected_revision': 1}).status_code == 503
    assert client.get('/api/v1/health').json()['status'] == 'ok'
    assert client.get(base + '/analysis-result').json()['result'] == result


def test_cloud_chart_uses_complete_data_and_correct_box_parameters(client, cloud):
    rows = [['浓度', '处理组', '不应发送的备注']] + [[i, '对照组', '秘密'] for i in range(1, 25)] + [[100, '对照组'], [7, '单条组'], [None, '排除'], [999, None]]
    base, record, result, url = prepared(client, rows)
    assert client.get(url).json()['figure'] is None
    figure = generate(client, url)
    assert figure['analysis_run_id'] == result['id'] and figure['source_sha256'] == record['sha256']
    assert figure['engine']['provider'] == 'openai_code_interpreter'
    assert figure['verification']['status'] == 'matched'
    assert figure['x_label'] == '浓度（mg/L）'
    first, singleton = figure['series']
    assert (first['n'], first['q1'], first['median'], first['q3']) == (25, 7, 13, 19)
    assert (first['whislo'], first['whishi'], first['fliers']) == (1, 24, [100])
    assert singleton['n'] == 1 and singleton['whislo'] == singleton['whishi'] == 7
    assert '排除 2 行' in figure['caption']
    assert '秘密' not in json.dumps(cloud.calls, ensure_ascii=False)
    assert len(cloud.calls[0]['values']) == 26
    image = client.get(url + '/image?download=true')
    assert image.headers['content-type'] == 'image/png' and 'attachment' in image.headers['content-disposition']
    assert hashlib.sha256(image.content).hexdigest() == figure['sha256']
    assert client.get(base + '/analysis-result').json()['result'] == result
    assert generate(client, url) == figure and len(cloud.calls) == 1


def test_pending_resume_without_resubmission_and_keyless_saved_download(client, cloud, monkeypatch):
    _, _, _, url = prepared(client)
    cloud.pending = True
    assert client.post(url, json={'expected_revision': 1}).status_code == 202
    assert client.get(url).json()['job']['status'] == 'running'
    assert client.post(url, json={'expected_revision': 1}).status_code == 202
    cloud.pending = False
    figure = client.get(url).json()['figure']
    monkeypatch.setenv('OPENAI_API_KEY', '')
    assert client.get(url).json()['figure'] == figure
    assert client.get(url + '/image').status_code == 200
    assert len(cloud.calls) == 1


def test_cloud_mismatch_fails_and_only_explicit_retry_submits(client, cloud):
    _, _, _, url = prepared(client)
    cloud.corrupt = True
    client.post(url, json={'expected_revision': 1})
    state = client.get(url).json()
    assert state['figure'] is None and state['job']['status'] == 'failed'
    assert '核对' in state['job']['message']
    client.post(url, json={'expected_revision': 1})
    assert len(cloud.calls) == 1
    cloud.corrupt = False
    client.post(url, json={'expected_revision': 1, 'retry': True})
    assert client.get(url).json()['figure'] is not None and len(cloud.calls) == 2


def test_old_chart_keeps_correct_revision_and_new_chart_is_separate(client, cloud):
    base, _, _, url = prepared(client)
    old = generate(client, url)
    client.put(base + '/analysis-setup', json=selection(expected_revision=1, unit='mmol/L'))
    assert client.get(url).json()['is_current'] is False
    assert client.post(url, json={'expected_revision': 1}).status_code == 409
    second = run(client, base, 2)
    new = generate(client, base + '/analysis-runs/' + second['id'] + '/boxplot', 2)
    assert old['id'] != new['id'] and 'mmol/L' in new['x_label']
    assert client.get(url + '/image').status_code == 200


def test_ownership_strict_requests_and_original_integrity(client, cloud):
    base, record, result, url = prepared(client)
    for body in [{}, {'expected_revision': True}, {'expected_revision': 1, 'values': [9]}]:
        assert client.post(url, json=body).status_code == 422
    other, _ = add_file(client)
    assert client.get(other + '/analysis-runs/' + result['id'] + '/boxplot').status_code == 404
    generate(client, url)
    original = Path(os.environ['PAPERASSIST_DATA_DIR']) / 'files' / (record['id'] + '.xlsx')
    original.write_bytes(b'changed')
    assert client.get(url).status_code == 409
    assert client.get(url + '/image').status_code == 409
    original.unlink()
    assert client.post(url, json={'expected_revision': 1}).status_code == 410


def test_changed_png_and_failed_local_save_are_not_silently_regenerated(client, cloud):
    _, _, _, url = prepared(client)
    figure = generate(client, url)
    path = Path(os.environ['PAPERASSIST_DATA_DIR']) / 'figures' / (figure['id'] + '.png')
    path.write_bytes(b'corrupt')
    assert client.get(url).status_code == 409
    path.unlink()
    assert client.get(url + '/image').status_code == 410
    assert len(cloud.calls) == 1


def test_save_failure_leaves_cloud_job_resumable_without_another_charge(client, cloud, reject_database_write):
    _, _, _, url = prepared(client)
    client.post(url, json={'expected_revision': 1})
    with reject_database_write('figures'):
        assert client.get(url).status_code == 503
    assert client.get(url).json()['figure'] is not None
    assert len(cloud.calls) == 1


def test_concurrent_submits_create_only_one_paid_job(client, cloud, monkeypatch):
    _, _, _, url = prepared(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.post(url, json={'expected_revision': 1}), range(2)))
    assert all(r.status_code == 202 for r in results)
    assert len(cloud.calls) == 1


def test_explicit_migration_preserves_analysis_result(client, cloud):
    base, _, result, url = prepared(client)
    migrate_database()
    generate(client, url)
    assert client.get(base + '/analysis-result').json()['result'] == result


def test_persisted_cloud_chart_restores_in_a_fresh_process(client, cloud):
    _, _, _, url = prepared(client)
    expected = generate(client, url)
    code = 'from fastapi.testclient import TestClient; from app.main import app; import sys,json; print(json.dumps(TestClient(app).get(sys.argv[1]).json()))'
    process = subprocess.run([sys.executable, '-c', code, url], cwd=Path(__file__).resolve().parents[1],
                             capture_output=True, text=True, check=True, timeout=30)
    assert json.loads(process.stdout)['figure'] == expected


def test_configuration_change_while_cloud_running_does_not_attach_old_chart(client, cloud):
    base, _, _, url = prepared(client)
    client.post(url, json={'expected_revision': 1})
    client.put(base + '/analysis-setup', json=selection(expected_revision=1, unit='changed'))
    state = client.get(url).json()
    assert state['figure'] is None and state['job']['status'] == 'failed'
    assert '配置已修改' in state['job']['message']
    assert not list((Path(os.environ['PAPERASSIST_DATA_DIR']) / 'figures').glob('*'))


def test_interrupted_submission_is_uncertain_and_never_reposts_automatically(client, cloud, monkeypatch):
    from app.openai_plot import PlotError
    _, _, _, url = prepared(client)
    def interrupted(*args):
        raise PlotError('openai_connection', '提交状态不确定，重试可能收费。', 503, uncertain=True)
    monkeypatch.setattr(cloud, 'start', interrupted)
    assert client.post(url, json={'expected_revision': 1}).json()['job']['status'] == 'uncertain'
    assert client.get(url).json()['job']['status'] == 'uncertain'
    assert client.post(url, json={'expected_revision': 1}).json()['job']['status'] == 'uncertain'


def test_stale_submitting_job_is_exposed_for_explicit_recovery(client, cloud):
    _, _, _, url = prepared(client)
    client.post(url, json={'expected_revision': 1})
    with database_connection(write=True) as db:
        row = db.execute('SELECT id, job_json FROM figure_jobs').fetchone()
        job = {**json.loads(row['job_json']), 'status': 'submitting', 'response_id': None, 'created_at': '2020-01-01T00:00:00+00:00'}
        db.execute('UPDATE figure_jobs SET job_json = %s WHERE id = %s', (json.dumps(job), row['id']))
    state = client.get(url).json()
    assert state['job']['status'] == 'uncertain' and state['figure'] is None
    assert len(cloud.calls) == 1


@pytest.mark.parametrize('values', [[4], [2, 2, 2], [-5, -1, 0, 4, 30], [-1e308, 1e308], [1e308, 1e308], [1e-300, 2e-300]])
def test_reference_box_parameters_remain_finite_for_supported_numbers(client, cloud, values):
    _, _, result, url = prepared(client, [['值']] + [[v] for v in values], group_column=None, unit='')
    figure = generate(client, url)
    series = figure['series'][0]
    assert series['label'] == '总体' and series['n'] == len(values)
    assert series['median'] == result['overall']['median']
    assert min(values) <= series['whislo'] <= series['whishi'] <= max(values)
    json.dumps(figure, allow_nan=False)


def test_backend_downloads_without_browser_get_and_resumes_existing_job(client, cloud):
    from app import boxplot
    from app.storage import get_project_store
    _, _, result, url = prepared(client)
    client.post(url, json={'expected_revision': 1})
    cloud.pending = True
    boxplot.poll_pending_figures()
    assert get_project_store().figure_job(result['id'], boxplot.RENDERER)['status'] == 'running'
    cloud.pending = False
    boxplot.poll_pending_figures()
    job = get_project_store().figure_job(result['id'], boxplot.RENDERER)
    assert job['status'] == 'completed'
    assert len(list((Path(os.environ['PAPERASSIST_DATA_DIR']) / 'figures').glob('*.png'))) == 1
    assert len(cloud.calls) == 1


def test_startup_worker_resumes_pending_job_without_new_cloud_submission(client, cloud, monkeypatch):
    import time
    from fastapi.testclient import TestClient
    from app.main import app
    from app.storage import get_project_store
    from app.boxplot import RENDERER
    _, _, result, url = prepared(client)
    client.post(url, json={'expected_revision': 1})
    monkeypatch.setenv('PAPERASSIST_PLOT_WORKER_ENABLED', '1')
    with TestClient(app):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if get_project_store().figure_job(result['id'], RENDERER)['status'] == 'completed':
                break
            time.sleep(0.05)
        assert get_project_store().figure_job(result['id'], RENDERER)['status'] == 'completed'
    assert len(cloud.calls) == 1


def test_worker_reaches_later_jobs_even_when_earliest_ten_remain_pending(client, cloud, monkeypatch):
    from app import boxplot
    from app.storage import get_project_store
    last_result = None
    for _ in range(11):
        _, _, last_result, url = prepared(client)
        client.post(url, json={'expected_revision': 1})
    original = cloud.fetch
    def last_only(self, job):
        return original(self, job) if job['analysis_run_id'] == last_result['id'] else None
    monkeypatch.setattr(cloud, 'fetch', last_only)
    boxplot.poll_pending_figures()
    assert get_project_store().figure_job(last_result['id'], boxplot.RENDERER)['status'] == 'completed'
    assert len(cloud.calls) == 11
