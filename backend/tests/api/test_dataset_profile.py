"""Persisted version profiles use isolated PostgreSQL and temporary assets."""
from tests.api.test_analysis import client, add_file  # noqa: F401
from tests.api.test_dataset_analysis import version, forbid_original
from app.db.database import database_connection
from app.core.config import get_data_dir
import pytest


def snapshots():
    with database_connection() as db:
        tables = ['files', 'tasks', 'task_attempts', 'task_checkpoints', 'dataset_versions',
                  'file_structure_versions', 'prepared_dataset_versions', 'analysis_setups', 'analysis_runs']
        rows = {table: sorted([dict(r) for r in db.execute('SELECT * FROM ' + table).fetchall()], key=repr) for table in tables}
    assets = {str(p.relative_to(get_data_dir())): p.read_bytes() for p in get_data_dir().rglob('*') if p.is_file()}
    return rows, assets


def test_saved_raw_profile_is_readonly_paginated_and_bound_to_selected_version(client, monkeypatch):
    base, _ = add_file(client, [['Value', 'Label']] + [[n, 'NA' if n % 2 else None] for n in range(1, 49)])
    raw = version(client, base)
    newer = version(client, base, 1)
    before = snapshots()
    monkeypatch.setattr('app.adapters.storage.ProjectStore.original', forbid_original)
    monkeypatch.setattr('openpyxl.load_workbook', forbid_original)
    url = base + '/dataset-versions/' + raw['id'] + '/profile'
    response = client.get(url)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['source']['dataset_id'] == raw['id'] and newer['id'] != raw['id']
    assert result['record_count'] == 48 and result['rules_version'] == 'excel_profile_v1'
    assert result['data_range'] == 'A2:B49'
    page = client.get(url + '/issues', params=dict(kind='missing', column=2, page=2)).json()
    assert page['total'] == 24 and page['page_size'] == 20
    assert [i['coordinate'] for i in page['items']] == ['B43', 'B45', 'B47', 'B49']
    rows = client.get(base + '/dataset-versions/' + raw['id'] + '/rows', params=dict(start_row=41)).json()
    assert rows['rows'][2]['row'] == page['items'][0]['row']
    assert snapshots() == before


def test_slash_date_issues_reject_impossible_dates_and_times_without_conversion(client):
    base, _ = add_file(client, [['Time'], ['99/99/2026'], ['01/02/2026 25:00:00'],
                               ['01/02/2026'], ['13/02/2026'], ['02/13/2026']])
    raw = version(client, base)
    before = snapshots()
    url = base + '/dataset-versions/' + raw['id'] + '/profile'
    response = client.get(url)
    assert response.status_code == 200, response.text
    field = response.json()['fields'][0]
    assert field['time_candidates'] == dict(valid_count=0, invalid_count=2, ambiguous_count=3)
    assert field['type_counts'] == {'text': 5} and field['temporal'] == []
    invalid = client.get(url + '/issues?kind=time_invalid&column=1').json()
    assert [item['coordinate'] for item in invalid['items']] == ['A2', 'A3']
    assert [item['value'] for item in invalid['items']] == ['99/99/2026', '01/02/2026 25:00:00']
    ambiguous = client.get(url + '/issues?kind=time_ambiguous&column=1').json()
    assert [item['coordinate'] for item in ambiguous['items']] == ['A4', 'A5', 'A6']
    assert snapshots() == before


@pytest.mark.parametrize('query', ['kind=missing', 'kind=duplicate&column=1', 'kind=unknown&column=1',
    'kind=missing&column=3', 'kind=missing&column=1&page_size=21', 'kind=missing&column=1&page=1.0'])
def test_issue_query_contract_rejects_invalid_combinations(client, query):
    base, _ = add_file(client)
    raw = version(client, base)
    assert client.get(base + '/dataset-versions/' + raw['id'] + '/profile/issues?' + query).status_code == 422


def test_other_file_and_account_cannot_read_profile_or_issues(client):
    from app.auth.service import create_user
    base, _ = add_file(client)
    raw = version(client, base)
    other, _ = add_file(client)
    suffix = '/dataset-versions/' + raw['id'] + '/profile'
    assert client.get(other + suffix).status_code == 404
    create_user('other-profile@paperassist.local', 'isolated-other-password-2026')
    login = client.post('/api/v1/auth/login', json=dict(email='other-profile@paperassist.local', password='isolated-other-password-2026'))
    client.headers['X-CSRF-Token'] = login.json()['csrf_token']
    assert client.get(base + suffix).status_code == 404
    assert client.get(base + suffix + '/issues?kind=missing&column=1').status_code == 404


def test_prepared_profile_uses_effective_missing_rules_and_real_coordinates(client, monkeypatch):
    from tests.integration.test_dataset_preparation import run, review, decide, decision
    base, _ = add_file(client, [['A', 'B', 'Value', 'Label']] + [[None, None, r, 'NA'] for r in range(2, 41)])
    raw = version(client, base)
    defaults = client.get(base + '/dataset-versions/' + raw['id'] + '/preparation-defaults').json()['recipe']
    defaults.update(data_range='C5:D40', fields=[f for f in defaults['fields'] if f['column'] >= 3])
    defaults['fields'][1].update(missing_markers=['NA'])
    task = client.post(base + '/dataset-preparations', json=dict(dataset_id=raw['id'], recipe=defaults), headers={'Idempotency-Key': 'prepared'}).json()
    run(task)
    accepted = decide(client, task, decision(review(client, task))).json()
    assert run(accepted)['status'] == 'succeeded'
    prepared = review(client, task)['result']
    before = snapshots()
    monkeypatch.setattr('app.adapters.storage.ProjectStore.original', forbid_original)
    url = base + '/dataset-versions/' + prepared['id'] + '/profile'
    response = client.get(url)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['source']['kind'] == 'prepared_dataset_version'
    assert result['data_range'] == 'C5:D40' and result['record_count'] == 36
    assert result['fields'][1]['missing_count'] == 36
    page = client.get(url + '/issues?kind=missing&column=4&page=2').json()
    assert page['items'][0]['coordinate'] == 'D25'
    assert snapshots() == before
