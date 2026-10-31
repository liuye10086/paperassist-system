"""Recovery verification must distinguish source values from execution identity."""
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def recovery_module():
    path = Path(__file__).resolve().parents[1] / 'dev/cr_b04_recovery.py'
    spec = importlib.util.spec_from_file_location('cr_b04_recovery', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_result(run, task):
    identity = dict(project_id='synthetic-project', plan_version_id='fixed-plan', run_id=run, task_id=task,
        code_digest='fixed-code', config_sha256='fixed-config', environment_digest='fixed-environment',
        lock_sha256='fixed-lock', engine_version='fixed-engine', source_digest='fixed-source')
    result = dict(id=run+'-result', run_id=run, task_id=task, plan_version_id='fixed-plan',
        kind='result_import', provenance='external_result', inference_scope='external_result', manifest_sha256='fixture-manifest',
        manifest={'identity': identity}, task={'id': task, 'project_id': 'synthetic-project'}, members=[])
    rows = []
    for feature, value in [('g1', '0'), ('g2', '1e-320'), ('g3', 'NA')]:
        rows.append(dict(row_key=feature+'-key', feature_id=feature, original_p_value=value,
            original_q=value, source_cells=json.dumps({'gene': feature, 'p': value, 'q': value}),
            provenance=json.dumps(dict(identity=identity, file_source_id='fixed-file', reference_version='fixed-reference',
                external_result=True, source_row=2, weight=1.0))))
    return result, rows


def encode(result, rows):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter='\t')
    writer.writeheader()
    writer.writerows(rows)
    raw = stream.getvalue().encode('utf-8')
    result['members'] = [dict(key='comparison_results', format='tsv', size_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(), download_url='/'+result['id']+'/table')]
    return raw


def exercise_run(tmp_path, mutate=None, corrupt_download=False):
    module = recovery_module()
    source, source_rows = make_result('original-run', 'original-task')
    result, recovered_rows = make_result('recovery-run', 'recovery-task')
    if mutate:
        mutate(result, recovered_rows)
    original_raw = encode(source, source_rows)
    recovered_raw = encode(result, recovered_rows)
    downloads = {source['members'][0]['download_url']: original_raw,
        result['members'][0]['download_url']: recovered_raw + (b'corrupt' if corrupt_download else b'')}
    run = {'id': 'recovery-run', 'task_id': 'recovery-task'}
    completed = dict(id='recovery-task', status='succeeded', current_attempt=2)
    attempt1 = dict(attempt_no=1, status='failed', error_code='storage_quota_exceeded')
    fake = object.__new__(module.Experiment)
    fake.args = SimpleNamespace(restore_only=False)
    fake.state = {'staging': str(tmp_path/'staging')}
    fake.output = tmp_path
    fake.base = '/projects/synthetic-project'
    fake.record = dict(actions={'retry-task': {'response': {'accepted': True}}},
        attempt1_failure={'id': 'recovery-task'}, attempt1_proof={'attempts': [attempt1]},
        attempt1_staging_files={})
    fake.ledger = SimpleNamespace(save=lambda: None)
    fake.preflight = lambda: (source, {'id': 'fixed-plan'})
    fake.create_run = lambda _: run
    fake.restore = lambda: None
    fake.retry_public = lambda _: None
    fake.wait_terminal = lambda _: completed
    fake.attempts_and_checkpoint = lambda _: {'attempts': [attempt1, {'attempt_no': 2, 'status': 'succeeded'}]}
    fake.verify_protected = lambda: None
    fake.client = SimpleNamespace(get=lambda path: SimpleNamespace(status_code=200, content=downloads[path]))
    def get(path):
        if path.endswith('/workspace'):
            return {'allowed_actions': []}
        if path.endswith('/bio-insight-runs/recovery-run'):
            return dict(run, result_version_id=result['id'])
        if path.endswith('/bio-insight-results/'+result['id']):
            return result
        raise AssertionError('Unexpected test I/O: '+path)
    fake.get = get
    fake.run()
    return fake.record


def test_actual_recovery_run_accepts_exact_raw_values_with_bound_new_execution_ids(tmp_path):
    result = exercise_run(tmp_path)
    assert result['status'] == 'controlled_recovery_passed'
    assert result['original_table_sha256'] != result['recovered_table_sha256']
    assert result['table_equivalence']['row_count'] == 3
    assert result['table_equivalence']['allowed_identity_fields'] == ['run_id', 'task_id']


@pytest.mark.parametrize('column,value', [('original_q', 'NA'), ('original_p_value', '1'), ('source_cells', '{}')])
def test_semantic_changes_are_rejected_even_with_valid_member_sha(tmp_path, column, value):
    with pytest.raises(AssertionError):
        exercise_run(tmp_path, lambda result, rows: rows[0].update({column: value}))


def test_new_execution_identity_must_match_its_own_published_manifest(tmp_path):
    def change(result, rows):
        value = json.loads(rows[0]['provenance'])
        value['identity']['run_id'] = 'foreign-run'
        rows[0]['provenance'] = json.dumps(value)
    with pytest.raises(AssertionError):
        exercise_run(tmp_path, change)


def test_frozen_environment_change_cannot_be_normalized_away(tmp_path):
    def change(result, rows):
        result['manifest']['identity']['environment_digest'] = 'different-environment'
        for row in rows:
            value = json.loads(row['provenance'])
            value['identity']['environment_digest'] = 'different-environment'
            row['provenance'] = json.dumps(value)
    with pytest.raises(AssertionError):
        exercise_run(tmp_path, change)


def test_source_provenance_change_is_rejected(tmp_path):
    def change(result, rows):
        value = json.loads(rows[0]['provenance'])
        value['reference_version'] = 'different-reference'
        rows[0]['provenance'] = json.dumps(value)
    with pytest.raises(AssertionError):
        exercise_run(tmp_path, change)


def test_result_identity_binding_cannot_disagree_with_manifest(tmp_path):
    with pytest.raises(AssertionError):
        exercise_run(tmp_path, lambda result, rows: result.update(task_id='foreign-task'))


def test_download_is_checked_against_its_own_member_sha(tmp_path):
    with pytest.raises(AssertionError):
        exercise_run(tmp_path, corrupt_download=True)


@pytest.mark.parametrize('field,value', [('external_result', 1), ('source_row', 2.0), ('weight', 1)])
def test_json_provenance_types_are_not_collapsed_by_python_equality(tmp_path, field, value):
    def change(result, rows):
        provenance = json.loads(rows[0]['provenance'])
        provenance[field] = value
        rows[0]['provenance'] = json.dumps(provenance)
    with pytest.raises(AssertionError):
        exercise_run(tmp_path, change)


@pytest.mark.parametrize('nested', [False, True])
def test_duplicate_json_keys_are_rejected_even_when_last_value_matches(tmp_path, nested):
    def change(result, rows):
        if nested:
            rows[0]['provenance'] = rows[0]['provenance'].replace('"identity": {', '"identity": {"run_id": "discarded-foreign-run",', 1)
        else:
            rows[0]['provenance'] = '{"external_result": false,' + rows[0]['provenance'][1:]
    with pytest.raises(AssertionError):
        exercise_run(tmp_path, change)


@pytest.mark.parametrize('location', ['row_identity', 'fixed_identity'])
def test_execution_identity_comparison_is_type_strict(tmp_path, location):
    module = recovery_module()
    source, original_rows = make_result('original-run', 'original-task')
    recovered, recovered_rows = make_result('recovery-run', 'recovery-task')
    for result, rows in ((source, original_rows), (recovered, recovered_rows)):
        result['manifest']['identity']['schema_version'] = 1
        for row in rows:
            value = json.loads(row['provenance'])
            value['identity']['schema_version'] = 1
            row['provenance'] = json.dumps(value)
    value = json.loads(recovered_rows[0]['provenance'])
    value['identity']['schema_version'] = True
    recovered_rows[0]['provenance'] = json.dumps(value)
    if location == 'fixed_identity':
        recovered['manifest']['identity']['schema_version'] = True
        for row in recovered_rows:
            value = json.loads(row['provenance'])
            value['identity']['schema_version'] = True
            row['provenance'] = json.dumps(value)
    with pytest.raises(AssertionError):
        module.verify_recovered_table(source, recovered, encode(source, original_rows), encode(recovered, recovered_rows))
