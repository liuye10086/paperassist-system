"""Bulk workflow observes real owner-scoped tasks and immutable project attachments."""
import hashlib

import pytest

from tests.api.test_bio_quantitative_lifecycle import processed_fixture
from tests.api.test_projects import client, create_project, upload


def test_workflow_reopens_and_tracks_bulk_run_recovery(client, monkeypatch, tmp_path):
    from app.core.exceptions import StorageError
    from app.domain.bio_insights.execution import run_bio_insight_task
    from app.domain.bio_insights.service import BioInsightsService
    from tests.api.test_bio_insight_reproducibility import fixed_fixture_runtime

    base, processed = processed_fixture(client, monkeypatch, tmp_path, assay='bulk_rna_counts')
    runtime = fixed_fixture_runtime(monkeypatch)
    monkeypatch.setattr(BioInsightsService, '_runtime_for', lambda self, config: runtime)

    def overview():
        response = client.get(base + '/bulk-workflow')
        assert response.status_code == 200, response.text
        return {item['key']: item for item in response.json()['stages']}

    def post(url, value, key):
        response = client.post(base + url, json=value, headers={'Idempotency-Key': key})
        assert response.status_code < 300, response.text
        return response.json()

    initial = overview()
    assert initial['data']['status'] == 'succeeded'
    assert initial['data']['refs']['import_id']
    assert initial['qc']['status'] == 'succeeded'
    assert initial['qc']['refs']['processed_version_id'] == processed
    assert initial['differential']['status'] == 'ready'
    assert initial['functional']['status'] == 'dependency_blocked'

    detail = client.get(base + '/bio-processed-datasets/' + processed).json()
    groups = [dict(label=label, sample_keys=[dict(processed_version_id=processed, sample_id=f'{label}{i}')
                                            for i in range(2)]) for label in ('B', 'A')]
    config = dict(schema_version=2, kind='comparison', mode='bulk_counts', design='independent',
                  method='deseq2_wald', analysis_layer='raw_counts', bulk_model='shared_wald_v1',
                  contrasts=[dict(contrast_id='B_A', name='B/A', groups=groups)], family_contrast_ids=['B_A'],
                  namespace='ensembl', reference_version='fixed', data_driven_grouping=False,
                  design_basis='Synthetic frozen design', independence_confirmed=True,
                  independence_basis='Synthetic independent units', inference_goal='inference', inference_unit='biological')
    body = dict(name='Workflow recovery', kind='comparison', decision='draft', expected_revision=0,
                sources=[dict(source_kind='bio_processed_dataset_version', source_id=processed,
                              sha256=detail['manifest_sha256'], role='processed')], config=config)
    review = post('/bio-insight-plans/preview', body, 'preview')
    draft = post('/bio-insight-plans', body, 'draft')
    assert overview()['differential']['status'] == 'waiting_confirmation'
    plan = post(f"/bio-insight-plans/{draft['plan_id']}/versions", {
        **body, 'decision': 'confirmed', 'expected_revision': 1, 'reviewed_design_sha256': review['reviewed_design_sha256'],
    }, 'confirm-model')
    run = post('/bio-insight-runs', dict(plan_version_id=plan['id'], expected_plan_revision=2,
                                        source_digest=plan['source_digest']), 'recoverable-run')
    recovered = client.get(base + '/bio-insight-requests/recoverable-run?kind=run')
    assert recovered.status_code == 200 and recovered.json()['id'] == run['id']
    assert overview()['differential']['refs']['insight_run_id'] == run['id']
    assert overview()['differential']['status'] == 'queued'

    def controlled_timeout(*args):
        active = overview()['differential']
        assert active['status'] == 'running'
        raise StorageError('bio_insights_timeout', 'controlled fixture timeout', 409)

    task = run_bio_insight_task(run['task_id'], run['task_revision'], task_type='bio_comparison',
                               engine=controlled_timeout, staging_directory=tmp_path / 'insights')
    assert task['error_code'] == 'bio_insights_timeout'
    failed = overview()['differential']
    assert failed['status'] == 'failed'
    assert failed['items'][0]['error_code'] == 'bio_insights_timeout'
    task_url = '/api/v1/tasks/' + run['task_id']
    events = client.get(task_url + '/events')
    assert events.status_code == 200 and any(event['status'] == 'failed' for event in events.json()['items'])
    retry = client.post(task_url + '/retry', json={'expected_revision': task['revision']})
    assert retry.status_code == 202, retry.text
    assert overview()['differential']['status'] == 'queued'
    cancel = client.post(task_url + '/cancel', json={'expected_revision': retry.json()['revision']})
    assert cancel.status_code == 200, cancel.text
    assert overview()['differential']['status'] == 'cancelled'
    assert client.get(base + '/bio-insight-runs').json()['total'] == 1

    qc_refs = initial['qc']['refs']
    recipes_url = f"/bio-analysis-setups/{qc_refs['setup_id']}/recipes"
    fixed_recipe = client.get(base + recipes_url + '/' + qc_refs['recipe_version_id']).json()
    display_params = {**fixed_recipe['params'], 'normalization': 'vst', 'pca_components': 6}
    recipe = dict(recipe_code='tabular_quantitative_v1', name='samples', raw_source=fixed_recipe['raw_source'],
                  expected_revision=fixed_recipe['revision'], params=display_params)
    display_recipe = post(recipes_url, recipe, 'display-recipe')
    after_display = overview()
    assert after_display['qc']['refs']['recipe_version_id'] == display_recipe['id']
    assert after_display['qc']['reusable_processed_refs'] == qc_refs
    assert not after_display['differential']['stale']
    science_recipe = post(recipes_url, {**recipe, 'expected_revision': display_recipe['revision'],
                                      'params': {**display_params, 'exclude_samples': ['B0']}}, 'exclude-sample')
    after_exclusion = overview()
    assert after_exclusion['qc']['refs']['recipe_version_id'] == science_recipe['id']
    assert 'reusable_processed_refs' not in after_exclusion['qc']
    assert after_exclusion['differential']['status'] == 'dependency_blocked'
    assert after_exclusion['differential']['items'][0]['status'] == 'cancelled'
    assert after_exclusion['differential']['items'][0]['stale']
    assert client.get(base + '/bio-processed-datasets/' + processed).status_code == 200


def test_experimental_material_verifies_bytes_and_project_scope(client):
    from app.adapters.storage import ProjectStore
    from app.core.config import get_data_dir
    from app.core.exceptions import StorageError
    from app.db.database import database_connection
    from app.domain.bio_insights.bulk_workflow import BulkWorkflowService
    from tests.api.test_excel import workbook_bytes

    project, other = create_project(client), create_project(client)
    content = workbook_bytes()
    response = upload(client, project['id'], content, 'experiment.xlsx')
    assert response.status_code == 201, response.text
    identifier = response.json()['file']['id']
    with database_connection() as db:
        owner = db.execute('SELECT owner_id FROM projects WHERE id=%s', (project['id'],)).fetchone()['owner_id']
    service = BulkWorkflowService(ProjectStore(get_data_dir(), owner_id=owner))
    requests = [dict(kind='experimental_material', source_id=identifier, note='Original experiment record')]
    item, = service.evidence(project['id'], requests)
    assert item['verification_status'] == 'attachment_integrity_verified'
    assert item['classification'] == 'user_declared_experimental_material'
    assert item['sha256'] == hashlib.sha256(content).hexdigest()
    with pytest.raises(StorageError) as error:
        service.evidence(other['id'], requests)
    assert error.value.status == 404
    foreign_owner = BulkWorkflowService(ProjectStore(get_data_dir(), owner_id='unrelated-owner'))
    with pytest.raises(StorageError) as error:
        foreign_owner.overview(project['id'])
    assert error.value.status == 404
