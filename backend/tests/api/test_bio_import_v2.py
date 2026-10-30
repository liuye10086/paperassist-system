"""Versioned import creation preserves v1 and freezes the qualified runtime."""
from tests.api.test_projects import client
from tests.integration.test_bio_import_publication import create_import
import pytest


@pytest.mark.parametrize('request_key', ['bio-import-v2-fixture', 'v'*128])
def test_explicit_v2_import_is_idempotent_and_keeps_legacy_input_unchanged(client, monkeypatch, request_key):
    from app.domain.bioinformatics import analysis_settings
    monkeypatch.setattr(analysis_settings, 'runtime_identity', lambda: dict(available=True, blockers=[],
        engine_version='visium_explore_v1.0.0', environment_digest='a'*64, code_digest='b'*64))
    base, legacy, file_id, _ = create_import(client)
    assert legacy['task']['input_version']['workflow_version'] == 'bio_import_v1'
    request = dict(file_ids=[file_id], assay='visium', name='explicit matrix', expected_dataset_revision=0,
                   matrix_representation='mtx', compare_alternate=False)
    headers = {'Idempotency-Key': request_key}
    created = client.post(base + '/bio-imports', json=request, headers=headers)
    assert created.status_code == 202, created.text
    value = created.json()
    version = value['task']['input_version']
    assert version['workflow_version'] == 'bio_import_v2'
    assert version['parser_version'] == 'geo_visium_import_v2'
    assert version['matrix_representation'] == 'mtx'
    assert version['environment_digest'] == 'a'*64
    assert client.post(base + '/bio-imports', json=request, headers=headers).json() == value
    changed = client.post(base + '/bio-imports', json={**request, 'compare_alternate': True}, headers=headers)
    assert changed.status_code == 409


def test_explicit_v2_retry_preserves_its_frozen_input_version(client, monkeypatch, tmp_path):
    from app.domain.bioinformatics import analysis_settings
    from app.domain.bioinformatics.execution import run_bio_import_task
    from app.core.exceptions import StorageError
    monkeypatch.setattr(analysis_settings, 'runtime_identity', lambda: dict(available=True, blockers=[],
        engine_version='visium_explore_v1.0.0', environment_digest='a'*64, code_digest='b'*64))
    base, _, file_id, _ = create_import(client)
    created = client.post(base+'/bio-imports', headers={'Idempotency-Key':'v2-retry-fixture'}, json=dict(
        file_ids=[file_id], assay='visium', name='frozen v2 retry', expected_dataset_revision=0,
        matrix_representation='mtx', compare_alternate=False))
    assert created.status_code == 202, created.text
    task = created.json()['task']
    def unavailable(*args):
        raise StorageError('bio_environment_unavailable', 'Test runtime unavailable', 409)
    failed = run_bio_import_task(task['id'], task['revision'], parser=unavailable,
        staging_directory=tmp_path/'retained-science-staging')
    assert failed['status']=='failed' and failed['error_code']=='bio_environment_unavailable'
    retried = client.post('/api/v1/tasks/'+task['id']+'/retry', json={'expected_revision':failed['revision']})
    assert retried.status_code == 202, retried.text
    assert retried.json()['id'] == task['id']
    assert retried.json()['input_version'] == task['input_version']
