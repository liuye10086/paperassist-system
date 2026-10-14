"""Dataset references are audited read-only, without changing historical JSON."""
import json
import pytest
from psycopg.types.json import Jsonb

from app.db.database import database_connection
from app.maintenance.database_audit import audit_database
from tests.api.test_analysis import client  # noqa: F401
from tests.integration.test_dataset_artifact_chain import complete_chain


@pytest.mark.parametrize('table,column', [
    ('analysis_setups', 'setup_json'), ('analysis_runs', 'result_json'),
    ('figures', 'figure_json'), ('explanations', 'explanation_json'),
    ('reports', 'report_json'), ('tasks', 'input_snapshot'),
])
def test_readonly_audit_detects_missing_dataset_reference(client, monkeypatch, table, column):
    chain = complete_chain(client, monkeypatch)
    with database_connection() as db:
        assert audit_database(db)['ok']
    with database_connection(write=True) as db:
        predicate = " WHERE task_type='word_report'" if table == 'tasks' else ''
        row = db.execute('SELECT * FROM ' + table + predicate + ' LIMIT 1').fetchone()
        value = row[column] if table == 'tasks' else json.loads(row[column])
        value['source']['dataset_id'] = 'missing-dataset-reference'
        key = 'file_id' if table == 'analysis_setups' else 'id'
        changed = Jsonb(value) if table == 'tasks' else json.dumps(value)
        db.execute('UPDATE ' + table + ' SET ' + column + '=%s WHERE ' + key + '=%s', (changed, row[key]))
    with database_connection() as db:
        assert db.execute('SHOW transaction_read_only').fetchone()['transaction_read_only'] == 'on'
        audited = audit_database(db)
    assert not audited['ok']
    check = next(item for item in audited['data_checks']
                 if item['table'] == table and item['column'] == 'dataset_source')
    assert check['invalid'] == 1
    assert 'missing-dataset-reference' not in json.dumps(audited)
    # File retention counts already traverse runs/tasks, and must continue to
    # include dataset-based results without inventing separate duplicate rows.
    details = client.get(chain['base'] + '/details')
    assert details.status_code == 200
    refs = details.json()['references']
    assert (refs['analysis_setups'], refs['analysis_runs'], refs['figures'], refs['explanations'], refs['reports']) == (1,1,1,1,1)
    assert refs['structure_versions'] == 1 and refs['dataset_versions'] == 3 and refs['tasks'] == 4

@pytest.mark.parametrize('dataset_ids', [None, 7, 'invalid', {}])
def test_readonly_audit_reports_invalid_manifest_dataset_ids(client, dataset_ids):
    from tests.integration.test_dataset_artifact_chain import new_result
    base, file, result = new_result(client)
    with database_connection(write=True) as db:
        row = db.execute('SELECT manifest_json FROM file_structure_versions WHERE id=%s', (result['source']['structure_id'],)).fetchone()
        manifest = row['manifest_json']
        if isinstance(dataset_ids, str):
            dataset_ids = result['source']['dataset_id']
        elif isinstance(dataset_ids, dict):
            dataset_ids = {result['source']['dataset_id']: True}
        manifest['dataset_ids'] = dataset_ids
        db.execute('UPDATE file_structure_versions SET manifest_json=%s WHERE id=%s', (Jsonb(manifest), result['source']['structure_id']))
    with database_connection() as db:
        assert db.execute('SHOW transaction_read_only').fetchone()['transaction_read_only'] == 'on'
        audited = audit_database(db)
        assert db.execute('SELECT manifest_json FROM file_structure_versions WHERE id=%s', (result['source']['structure_id'],)).fetchone()['manifest_json'] == manifest
    assert not audited['ok']
    checks = [item for item in audited['data_checks'] if item['column'] == 'dataset_source' and item['table'] in ('analysis_setups', 'analysis_runs')]
    assert len(checks) == 2 and all(item['invalid'] == 1 for item in checks)


def prepared_chain(client):
    from tests.integration.test_dataset_preparation import create_preparation, run, review, decide, decision
    base, file, raw, _, task = create_preparation(client)
    run(task)
    accepted = decide(client, task, decision(review(client, task))).json()
    assert run(accepted)['status'] == 'succeeded'
    return base, file, raw, task, review(client, task)['result']


def readonly_sources():
    from app.maintenance.dataset_source_audit import audit_dataset_sources
    with database_connection() as db:
        assert db.execute('SHOW transaction_read_only').fetchone()['transaction_read_only'] == 'on'
        return audit_dataset_sources(db)


def forbid_candidate_read(*args, **kwargs):
    raise AssertionError('Relational audit must never read dataset objects')


def test_preparation_source_audit_accepts_real_revise_and_publish_history_without_assets(client, monkeypatch):
    from tests.integration.test_dataset_preparation import create_preparation, run, review, decide, decision
    _, _, _, _, task = create_preparation(client)
    assert all(check['invalid'] == 0 for check in readonly_sources())
    run(task)
    first = review(client, task)
    revised_recipe = first['recipe']
    revised_recipe['fields'][1]['trim_text'] = True
    revised = decide(client, task, decision(first, 'revise', revised_recipe), 'revise').json()
    run(revised)
    accepted = decide(client, task, decision(review(client, task)), 'approve').json()
    assert run(accepted)['status'] == 'succeeded'
    monkeypatch.setattr('app.adapters.prepared_dataset_objects.PreparedDatasetObjects.read', forbid_candidate_read)
    monkeypatch.setattr('app.adapters.dataset_objects.DatasetObjects.read', forbid_candidate_read)
    checks = readonly_sources()
    assert all(check['invalid'] == 0 for check in checks)
    by_table = {check['table']: check for check in checks}
    assert by_table['task_checkpoints']['rows'] == 7
    assert by_table['dataset_preparation_decisions']['rows'] == 2
    assert by_table['prepared_dataset_versions']['rows'] == 1
    assert by_table['tasks']['rows'] == 1


def test_prepared_sources_audit_checks_original_parent_and_prepared_object_identity(client, monkeypatch):
    from tests.api.test_analysis import selection
    base, file, raw, task, prepared = prepared_chain(client)
    # Persist the real equivalent raw result, then bind its JSON to the published
    # prepared source. The audit operates on stored metadata, independent of readers.
    assert client.put(base+'/analysis-setup', json=selection(dataset_id=raw['id'], expected_revision=0)).status_code == 200
    assert client.post(base+'/analysis-runs', json={'expected_revision':1}).status_code == 200
    with database_connection(write=True) as db:
        for table, column in [('analysis_setups', 'setup_json'), ('analysis_runs', 'result_json')]:
            row = db.execute('SELECT * FROM '+table+' WHERE file_id=%s', (file['id'],)).fetchone()
            value = json.loads(row[column])
            value['source'] = prepared['source']
            db.execute('UPDATE '+table+' SET '+column+'=%s WHERE file_id=%s', (json.dumps(value), file['id']))
    monkeypatch.setattr('app.adapters.prepared_dataset_objects.PreparedDatasetObjects.read', forbid_candidate_read)
    assert all(check['invalid'] == 0 for check in readonly_sources())
    with database_connection(write=True) as db:
        row = db.execute('SELECT result_json FROM analysis_runs WHERE file_id=%s', (file['id'],)).fetchone()
        value = json.loads(row['result_json'])
        value['source']['parent_dataset_version'] += 1
        db.execute('UPDATE analysis_runs SET result_json=%s WHERE file_id=%s', (json.dumps(value), file['id']))
    check = next(c for c in readonly_sources() if c['table'] == 'analysis_runs')
    assert check['invalid'] == 1


@pytest.mark.parametrize('table,column', [('task_checkpoints', 'state_json'),
    ('dataset_preparation_decisions', 'request_json'), ('prepared_dataset_versions', 'recipe_json')])
def test_readonly_audit_detects_preparation_relation_drift(client, monkeypatch, table, column):
    base, file, raw, task, prepared = prepared_chain(client)
    with database_connection(write=True) as db:
        row = db.execute('SELECT * FROM '+table+' WHERE task_id=%s ORDER BY created_at DESC LIMIT 1', (task['id'],)).fetchone()
        value = row[column]
        if table == 'prepared_dataset_versions':
            value['fields'][0]['name'] = 'altered field'
        else:
            value['input_version']['source']['dataset_sha256'] = 'f' * 64
        db.execute('UPDATE '+table+' SET '+column+'=%s WHERE id=%s', (Jsonb(value), row['id']))
    monkeypatch.setattr('app.adapters.prepared_dataset_objects.PreparedDatasetObjects.read', forbid_candidate_read)
    checks = readonly_sources()
    assert next(c for c in checks if c['table'] == table)['invalid'] == 1
    assert 'altered field' not in json.dumps(checks) and raw['id'] not in json.dumps(checks)
    with database_connection() as db:
        assert db.execute('SELECT '+column+' FROM '+table+' WHERE id=%s', (row['id'],)).fetchone()[column] == value
