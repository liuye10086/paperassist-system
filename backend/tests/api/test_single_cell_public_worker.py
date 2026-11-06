"""Opt-in real public matrices through unmodified runtime gates/task handlers.

Run via script/dev/single_cell_runtime.py verify in the retained Linux image.
This exercises application Worker dispatch, not a RabbitMQ delivery benchmark.
Both libraries are from ONE donor; this does not validate group inference.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import time
from uuid import uuid4

from docx import Document
import pytest

from tests.api.test_projects import client, create_project


@pytest.mark.skipif(not os.environ.get('PAPERASSIST_SC_PUBLIC_DATA'), reason='Requires public data and actually probed Linux runtime')
@pytest.mark.parametrize('libraries', [1, 2], ids=['single', 'multiple'])
def test_public_matrix_normal_worker(client, monkeypatch, tmp_path, libraries):
    from app.domain.bioinformatics.single_cell_settings import runtime_identity
    from app.domain.tasks.execution import run_task
    runtime = runtime_identity()
    assert runtime['available'], runtime
    assert runtime['status'] == 'verified_configuration_not_liveness'
    data = Path(os.environ['PAPERASSIST_SC_PUBLIC_DATA'])
    sources = json.loads((data / 'sources.json').read_text())[:libraries]
    destination = Path(os.environ['PAPERASSIST_SC_PUBLIC_EVIDENCE']) / ('single' if libraries == 1 else 'multiple')
    destination.mkdir(parents=True, exist_ok=True)
    staging = tmp_path / 'staging'
    monkeypatch.setenv('PAPERASSIST_BIO_STAGING_DIR', str(staging))
    base = '/api/v1/projects/' + create_project(client, 'Public PBMC matrix verification')['id']
    files, samples = [], []
    for source in sources:
        body = (data / source['filename']).read_bytes()
        assert hashlib.sha256(body).hexdigest() == source['sha256']
        item = str(uuid4())
        response = client.post(base + '/bio-upload-batches', headers={'Idempotency-Key':item},
            json={'items':[dict(client_id=item, filename=source['filename'], size_bytes=len(body))]})
        assert response.status_code == 201, response.text
        upload = client.post(base + f"/bio-upload-batches/{response.json()['id']}/items/{item}",
            files={'file':(source['filename'], body)})
        assert upload.status_code == 202, upload.text
        files.append(upload.json()['file_id'])
        samples.append(dict(sample_id=source['sample'], library_id=source['sample'], donor='10x_pbmc3k_6k_donor',
            batch=source['sample'], group='healthy', file_ids=[files[-1]], species_taxon_id=9606,
            reference_id=source['reference_id'], reference_version=source['reference_version'],
            library_chemistry=source['library_chemistry'], pair_id=None))
    started_at = time.monotonic()
    response = client.post(base + '/bio-imports', headers={'Idempotency-Key':'public-import'}, json=dict(
        workflow_version='bio_import_v4', assay='single_cell', file_ids=files, samples=samples,
        name='Public PBMC matrices', expected_dataset_revision=0, matrix_representation='mtx',
        two_column_feature_type='Gene Expression'))
    assert response.status_code == 202, response.text
    imported, task = response.json(), response.json()['task']
    waiting = run_task(task['id'], task['revision'])
    assert waiting['status'] == 'waiting_confirmation', waiting
    review = client.get(base + '/bio-imports/' + imported['id']).json()
    response = client.post(base + '/bio-imports/' + imported['id'] + '/confirm',
        headers={'Idempotency-Key':'public-confirm'}, json=dict(task_revision=review['task']['revision'],
        checkpoint_id=review['checkpoint_id'], wait_id=review['wait_id'], candidate_sha256=review['candidate']['sha256'],
        expected_dataset_revision=review['expected_dataset_revision']))
    assert response.status_code == 202, response.text
    done = run_task(task['id'], response.json()['revision'])
    assert done['status'] == 'succeeded', done
    source = client.get(base + '/bio-imports/' + imported['id']).json()['result_source']
    import_seconds = time.monotonic() - started_at
    request = dict(name='Public single-cell matrix', raw_source=source, params=dict(
        min_counts=1, min_genes=1, min_spots=1, hvg_count=2000, pca_components=30,
        neighbors=15, resolution=0.5, seed=0))
    integration_tools = os.environ.get('PAPERASSIST_SC_INTEGRATION_TOOLS') == '1'
    request['params'].update(hvg_batch_key='batch' if integration_tools else None,
        technical_covariates=['log1p_total_counts'] if integration_tools else [],
        harmony=dict(enabled=integration_tools,batch_key='batch',theta=2,**{'lambda':1},max_iter=10))
    qc_tools = os.environ.get('PAPERASSIST_SC_QC_TOOLS') == '1'
    if qc_tools:
        request['params'].update(
            library_qc_overrides=[dict(library_id='pbmc3k',min_counts=500,min_genes=200)],
            doublet=dict(enabled=True,exclude_predicted=False,expected_rate=None),
            decontx=dict(enabled=True))
    response = client.post(base + '/single-cell-analysis-runs', headers={'Idempotency-Key':'public-analyze'}, json=request)
    assert response.status_code == 202, response.text
    started = response.json()
    replay = client.post(base + '/single-cell-analysis-runs', headers={'Idempotency-Key':'public-analyze'}, json=request)
    assert replay.json()['id'] == started['id']
    task = started['task']
    compute_at = time.monotonic()
    done = run_task(task['id'], task['revision'])
    assert done['status'] == 'succeeded', done
    compute_seconds = time.monotonic() - compute_at
    identifier = done['result_bio_processed_dataset_version_id']
    response = client.get(base + '/bio-processed-datasets/' + identifier)
    assert response.status_code == 200, response.text
    result = response.json()
    expected_cells = 2700 if libraries == 1 else 8119
    assert result['shape']['raw_observations'] == expected_cells
    assert 0 < result['shape']['retained_observations'] <= expected_cells
    assert result['manifest']['assay'] == 'single_cell'
    assert len(result['manifest']['samples']) == libraries
    assert all(s['species_taxon_id'] == 9606 and s['donor'] == '10x_pbmc3k_6k_donor' for s in result['manifest']['samples'])
    assert result['figures'] and all(m['format'] != 'pdf' for f in result['figures'] for m in f['members'])
    assert any(m['format'] == 'h5ad' for m in result['members'])
    if qc_tools:
        steps = {step['key']:step for step in result['steps']}
        assert steps['scdblfinder']['status'] == 'completed', steps['scdblfinder']
        assert steps['decontx']['status'] == 'completed', steps['decontx']
        assert 'decontx_counts' in result['manifest']['layers']
        assert {'library_qc','library_algorithms','single_cell_tool_versions'} <= {t['key'] for t in result['tables']}
        preview=client.get(base+'/bio-processed-datasets/'+identifier+'/matrix-preview',params={'layer':'decontx_counts'})
        assert preview.status_code == 200, preview.text
    if integration_tools:
        integration=result['manifest']['summary']['single_cell_integration']
        assert integration['technical_covariates']['applied'] is True,integration
        assert integration['harmony']['status']==('not_computable' if libraries==1 else 'completed'),integration
        assert integration['downstream_representation']==('X_pca' if libraries==1 else 'X_pca_harmony')
        kinds={f['config']['kind'] for f in result['figures']}
        assert 'integration_covariates' in kinds
        if libraries==2:assert 'integration_harmony' in kinds
    for figure in result['figures']:
        png = next(m for m in figure['members'] if m['format'] == 'png')
        response = client.get(png['download_url'])
        assert response.status_code == 200 and hashlib.sha256(response.content).hexdigest() == png['sha256']
    response = client.get(base + '/bio-processed-datasets/' + identifier + '/report.docx')
    assert response.status_code == 200, response.text
    document = Document(io.BytesIO(response.content))
    assert len(document.inline_shapes) == len(result['figures'])
    texts = '\n'.join(p.text for p in document.paragraphs) + '\n' + '\n'.join(c.text for t in document.tables for row in t.rows for c in row.cells)
    assert all(value in texts for value in ('pbmc3k', '9606', 'hg19'))
    if qc_tools:
        assert 'scDblFinder' in texts and 'decontX' in texts
    (destination / 'single-cell-report.docx').write_bytes(response.content)
    summary = dict(input_sources=sources, biological_scope='same donor, descriptive analysis; no independent replication',
        runtime_gate='actual probes and normal runtime_identity, no injected capability',
        execution='normal run_task -> default parser/engine -> isolated Linux scientific child',
        queue_delivery='not exercised by this test', qc_tools_requested=qc_tools, integration_tools_requested=integration_tools, runtime=runtime, shape=result['shape'], steps=result['steps'],
        figure_count=len(result['figures']), resources=result['manifest'].get('parent_resources'),
        import_seconds=import_seconds, compute_seconds=compute_seconds)
    (destination / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    (destination / 'processed-manifest.json').write_text(json.dumps(result['manifest'], ensure_ascii=False, indent=2), encoding='utf-8')
