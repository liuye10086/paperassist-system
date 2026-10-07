from app.core.paths import BACKEND_ROOT, PROJECT_ROOT
from tests.helpers.auth import session_subprocess_env
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from threading import Barrier
from io import BytesIO
from zipfile import ZipFile

import pytest
from app.db.database import database_connection, migrate_database

from tests.api.test_analysis import add_file, client, selection


def configured(client, rows=None, **changes):
    base, record = add_file(client, rows)
    response = client.put(base + '/analysis-setup', json=selection(expected_revision=0, **changes))
    assert response.status_code == 200, response.text
    return base, record


def run(client, base, revision=1):
    response = client.post(base + '/analysis-runs', json={'expected_revision': revision})
    assert response.status_code == 200, response.text
    return response.json()


def test_real_statistics_use_complete_records_and_preserve_provenance(client):
    base, record = configured(client, [['值', '组'], [4, 'A'], [1, 'A'], [3, 'B'], [2, 'B'], [None, 'B'], [99, None]])
    result = run(client, base)
    assert result['overall'] == {'n': 4, 'mean': 2.5, 'std': pytest.approx(math.sqrt(5 / 3)),
        'min': 1, 'q1': 1.75, 'median': 2.5, 'q3': 3.25, 'max': 4, 'iqr': 1.5, 'warnings': []}
    assert [g['label'] for g in result['groups']] == ['A', 'B']
    assert result['groups'][0]['statistics']['std'] == pytest.approx(math.sqrt(4.5))
    assert result['groups'][1]['statistics']['mean'] == 2.5
    assert result['check']['excluded_count'] == 2
    assert result['source_sha256'] == record['sha256']
    assert result['selection'] == selection()
    assert (result['numeric_name'], result['group_name']) == ('值', '组')
    assert result['setup_revision'] == 1
    assert result['engine']['id'] == 'descriptive_statistics_v1'
    assert result['engine']['std_ddof'] == 1
    assert result['engine']['quantile_method'] == 'linear_inclusive'
    assert result['engine']['python_version'] and result['engine']['openpyxl_version']
    assert result['started_at'] <= result['completed_at']
    assert client.get(base + '/analysis-result').json() == {'current_revision': 1, 'is_current': True, 'result': result}


def test_uses_rows_beyond_preview_without_grouping(client):
    base, _ = configured(client, [['值', '组']] + [[i, None] for i in range(25)] + [[100, 'A']], group_column=None)
    result = run(client, base)
    assert result['overall']['n'] == 26
    assert result['overall']['mean'] == pytest.approx(400 / 26)
    assert result['overall']['median'] == 12.5
    assert result['overall']['max'] == 100
    assert result['groups'] == [] and result['group_name'] is None


@pytest.mark.parametrize('values, expected', [
    ([7], {'n': 1, 'mean': 7, 'std': None, 'q1': 7, 'median': 7, 'q3': 7, 'iqr': 0}),
    ([5, 5, 5], {'n': 3, 'mean': 5, 'std': 0, 'q1': 5, 'median': 5, 'q3': 5, 'iqr': 0}),
    ([-2.5, 0, 2.5], {'n': 3, 'mean': 0, 'std': 2.5, 'q1': -1.25, 'median': 0, 'q3': 1.25, 'iqr': 2.5}),
    ([1e308, 1e308], {'n': 2, 'mean': 1e308, 'std': 0, 'q1': 1e308, 'median': 1e308, 'q3': 1e308, 'iqr': 0}),
])
def test_boundary_statistics(client, values, expected):
    base, _ = configured(client, [['值']] + [[v] for v in values], group_column=None)
    stats = run(client, base)['overall']
    for key, value in expected.items():
        assert stats[key] == value
    assert bool(stats['warnings']) == (len(values) == 1)


def test_overflow_metrics_are_null_with_explanation_not_infinity(client):
    base, _ = configured(client, [['值']] + [[v] for v in [-1.7e308, -1.7e308, 1.7e308, 1.7e308]], group_column=None)
    result = run(client, base)
    assert result['overall']['mean'] == 0
    assert result['overall']['median'] == 0
    assert result['overall']['std'] is None and result['overall']['iqr'] is None
    assert len(result['overall']['warnings']) == 2
    json.dumps(result, allow_nan=False)


def test_integer_precision_loss_is_rejected_with_no_saved_result(client):
    base, _ = add_file(client, [['值'], [1], [2]])
    # Supply exact OOXML integers; openpyxl's writer would round these first.
    content = client.get(base + '/download').content
    output = BytesIO()
    with ZipFile(BytesIO(content)) as source, ZipFile(output, 'w') as target:
        for name in source.namelist():
            data = source.read(name)
            if name == 'xl/worksheets/sheet1.xml':
                data = data.replace(b'<v>1</v>', b'<v>9007199254740992</v>').replace(b'<v>2</v>', b'<v>9007199254740993</v>')
            target.writestr(name, data)
    record = client.post(base.rsplit('/', 1)[0], files={'file': ('large.xlsx', output.getvalue())}).json()['file']
    base = base.rsplit('/', 1)[0] + '/' + record['id']
    assert client.put(base + '/analysis-setup', json=selection(expected_revision=0, group_column=None)).status_code == 200
    response = client.post(base + '/analysis-runs', json={'expected_revision': 1})
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'numeric_precision'
    assert response.json()['detail']['params'] == {'column': 'A', 'row': 2}
    assert '整数' in response.json()['detail']['message']
    assert client.get(base + '/analysis-result').json()['result'] is None


def test_iqr_is_computed_before_rounding_quartiles(client):
    from app.domain.descriptive import summarize
    # Both are representable floats; rounded quartiles must not distort their IQR.
    stats = summarize([1e16, 1e16 + 2])
    assert stats['iqr'] == 1
    assert stats['std'] == pytest.approx(math.sqrt(2))


def test_boolean_group_labels_and_singleton_warning(client):
    base, _ = configured(client, [['值', '组'], [0, False], [2, True], [4, True]])
    result = run(client, base)
    assert [g['label'] for g in result['groups']] == ['FALSE', 'TRUE']
    assert result['groups'][0]['statistics']['std'] is None
    assert result['groups'][0]['statistics']['warnings']


def test_requires_saved_configuration_and_strict_revision(client):
    base, _ = add_file(client)
    assert client.get(base + '/analysis-result').json() == {'current_revision': None, 'is_current': False, 'result': None}
    assert client.post(base + '/analysis-runs', json={'expected_revision': 1}).status_code == 409
    for payload in [{}, {'expected_revision': 0}, {'expected_revision': True}, {'expected_revision': 1, 'values': [999]}]:
        assert client.post(base + '/analysis-runs', json=payload).status_code == 422


def test_idempotent_retry_and_changed_configuration_keeps_old_result(client):
    base, _ = configured(client)
    first = run(client, base)
    assert run(client, base) == first
    client.put(base + '/analysis-setup', json=selection(expected_revision=1, group_column=None, unit='new'))
    assert client.get(base + '/analysis-result').json() == {'current_revision': 2, 'is_current': False, 'result': first}
    assert client.post(base + '/analysis-runs', json={'expected_revision': 1}).status_code == 409
    second = run(client, base, 2)
    assert second['id'] != first['id'] and second['overall']['n'] == 4
    assert second['selection']['unit'] == 'new'
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS count FROM analysis_runs').fetchone()['count'] == 2


def test_result_restored_in_independent_process(client):
    base, _ = configured(client)
    expected = run(client, base)
    code = 'from fastapi.testclient import TestClient; from app.main import app; import sys; print(TestClient(app, cookies={"paperassist_session": __import__("os").environ["PAPERASSIST_TEST_SESSION_COOKIE"]}).get(sys.argv[1]).text)'
    completed = subprocess.run([sys.executable, '-c', code, base + '/analysis-result'],
        cwd=BACKEND_ROOT, env=session_subprocess_env(client), capture_output=True, text=True, check=True, timeout=30)
    assert json.loads(completed.stdout)['result'] == expected


def test_ownership_and_original_integrity_guard_results(client):
    base, record = configured(client)
    run(client, base)
    other, _ = add_file(client)
    wrong = other.rsplit('/', 1)[0] + '/' + record['id']
    assert client.get(wrong + '/analysis-result').status_code == 404
    assert client.post(wrong + '/analysis-runs', json={'expected_revision': 1}).status_code == 404
    path = Path(os.environ['PAPERASSIST_DATA_DIR']) / 'files' / (record['id'] + '.xlsx')
    path.write_bytes(b'changed')
    assert client.get(base + '/analysis-result').status_code == 409
    assert client.post(base + '/analysis-runs', json={'expected_revision': 1}).status_code == 409
    path.unlink()
    assert client.get(base + '/analysis-result').status_code == 410


def test_explicit_migration_preserves_configuration_and_file(client):
    base, _ = configured(client)
    before = client.get(base + '/analysis-setup').json()
    migrate_database()
    run(client, base)
    assert client.get(base + '/analysis-setup').json() == before
    assert client.get(base + '/preview').status_code == 200


def test_execution_rechecks_current_parse_limits(client, monkeypatch):
    base, _ = configured(client)
    monkeypatch.setenv('EXCEL_MAX_ROWS', '3')
    response = client.post(base + '/analysis-runs', json={'expected_revision': 1})
    assert response.status_code == 422
    assert client.get(base + '/analysis-result').json()['result'] is None


def test_configuration_changed_during_calculation_is_not_saved(client, monkeypatch):
    from app.domain import descriptive
    base, _ = configured(client, group_column=None)
    original = descriptive.summarize

    def racing(values):
        client.put(base + '/analysis-setup', json=selection(expected_revision=1, group_column=None, unit='changed'))
        return original(values)

    monkeypatch.setattr(descriptive, 'summarize', racing)
    assert client.post(base + '/analysis-runs', json={'expected_revision': 1}).status_code == 409
    assert client.get(base + '/analysis-result').json()['result'] is None


def test_parallel_runs_return_one_persisted_result(client, monkeypatch):
    from app.domain import descriptive
    base, _ = configured(client, group_column=None)
    barrier = Barrier(2)
    original = descriptive.summarize

    def synchronized(values):
        barrier.wait(timeout=10)
        return original(values)

    monkeypatch.setattr(descriptive, 'summarize', synchronized)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(client, base), range(2)))
    assert results[0] == results[1]
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS count FROM analysis_runs').fetchone()['count'] == 1


def test_failed_save_preserves_previous_result(client, reject_database_write):
    base, _ = configured(client)
    previous = run(client, base)
    client.put(base + '/analysis-setup', json=selection(expected_revision=1, unit='changed'))
    with reject_database_write('analysis_runs'):
        response = client.post(base + '/analysis-runs', json={'expected_revision': 2})
    assert response.status_code == 503
    assert client.get(base + '/analysis-result').json()['result'] == previous
