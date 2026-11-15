"""Synthetic PCA/Slingshot outputs through real import, source and task checks.

This fixture is report engineering evidence, not validation of PCA or Slingshot.
"""
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import numpy as np


def published_trajectory(client, monkeypatch, tmp_path, *, cell_count=4, processed_only=False):
    from app.adapters.bio_engine.single_cell import import_counts
    from app.domain.bioinformatics import single_cell_settings
    from app.domain.bioinformatics.execution import run_bio_import_task
    from app.domain.bioinformatics.analysis_execution import run_bio_analysis_task
    from app.domain.bio_insights.service import BioInsightsService
    from tests.api.test_projects import create_project
    from tests.api.test_single_cell_mainline import _bundle
    from tests.api.test_bio_insight_reproducibility import fixed_fixture_runtime
    from tests.api.test_bio_reader_report_insights import execute_plan

    runtime = dict(available=True, blockers=[], engine_version='visium_explore_v1.0.0',
                   code_digest='a'*64, environment_digest='b'*64)
    monkeypatch.setattr(single_cell_settings, 'runtime_identity', lambda: runtime)
    stage = tmp_path / 'trajectory-stage'
    monkeypatch.setenv('PAPERASSIST_BIO_STAGING_DIR', str(stage))
    base = '/api/v1/projects/' + create_project(client)['id']
    archive = _bundle(np.tile(np.array([[3,1],[4,2],[1,3],[2,4]], dtype='int64'), (cell_count//4, 1)))
    if cell_count > 4:
        import tarfile
        buffer = io.BytesIO()
        with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as original, tarfile.open(fileobj=buffer, mode='w:gz') as output:
            for item in original:
                raw = original.extractfile(item).read()
                if item.name == 'barcodes.tsv':
                    raw = ''.join(f'AACCTTGG{i:08d}-1\n' for i in range(cell_count)).encode()
                item.size = len(raw)
                output.addfile(item, io.BytesIO(raw))
        archive = buffer.getvalue()
    item = str(uuid4())
    batch = client.post(base + '/bio-upload-batches', json={'items':[
        dict(client_id=item, filename='synthetic-cells.tar.gz', size_bytes=len(archive))]},
        headers={'Idempotency-Key':'topic-upload'})
    assert batch.status_code == 201, batch.text
    upload = client.post(base + f"/bio-upload-batches/{batch.json()['id']}/items/{item}",
        files={'file':('synthetic-cells.tar.gz', archive)})
    assert upload.status_code == 202, upload.text
    file_id = upload.json()['file_id']
    imported = client.post(base + '/bio-imports', json=dict(workflow_version='bio_import_v4',
        assay='single_cell', file_ids=[file_id], name='Synthetic four-cell matrix',
        expected_dataset_revision=0, matrix_representation='mtx', samples=[dict(
            sample_id='S1', library_id='L1', donor='D1', group='synthetic', file_ids=[file_id])]),
        headers={'Idempotency-Key':'topic-import'})
    assert imported.status_code == 202, imported.text
    imported = imported.json()
    def parser(frozen, output, settings):
        return import_counts(frozen | {'output_directory':str(output), 'settings':settings})
    task = imported['task']
    wait = run_bio_import_task(task['id'], task['revision'], parser=parser, staging_directory=stage)
    assert wait['status'] == 'waiting_confirmation', wait
    detail = client.get(base + '/bio-imports/' + imported['id']).json()
    confirmed = client.post(base + '/bio-imports/' + imported['id'] + '/confirm',
        headers={'Idempotency-Key':'topic-import-confirm'}, json=dict(task_revision=detail['task']['revision'],
        checkpoint_id=detail['checkpoint_id'], wait_id=detail['wait_id'], candidate_sha256=detail['candidate']['sha256'],
        expected_dataset_revision=detail['expected_dataset_revision']))
    assert confirmed.status_code == 202, confirmed.text
    done = run_bio_import_task(task['id'], confirmed.json()['revision'], parser=parser, staging_directory=stage)
    assert done['status'] == 'succeeded', done
    source = client.get(base + '/bio-imports/' + imported['id']).json()['result_source']

    def engine(payload, output, mode):
        raw_members = payload['raw']['members']
        features = json.loads(Path(raw_members['features_index']['path']).read_bytes())
        cells = json.loads(Path(raw_members['barcodes_index']['path']).read_bytes())['barcodes']
        outputs = []
        def leaf(key, content, fmt, role='axis'):
            path = output / (key + '.' + fmt)
            path.write_bytes(content)
            outputs.append(dict(key=key, role=role, format=fmt, path=str(path.resolve()),
                size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest()))
        def array(key, values):
            stream = io.BytesIO()
            np.save(stream, values, allow_pickle=False)
            leaf(key, stream.getvalue(), 'npy')
        leaf('raw_axes', json.dumps(dict(barcodes=cells, **features)).encode(), 'json')
        array('observation_mask', np.ones(len(cells), dtype=bool))
        array('feature_mask', np.ones(2, dtype=bool))
        array('pca', np.tile(np.array([[0.,0.],[.2,.1],[1.,1.],[1.2,1.1]]), (len(cells)//4, 1)))
        text = 'barcode\tkept\tcluster\n' + ''.join(f'{cell}\tTrue\t{i//(len(cells)//2)}\n' for i,cell in enumerate(cells))
        leaf('observations', text.encode(), 'tsv', 'table')
        text = 'feature_id\tfeature_type\tkept\n' + ''.join(f'{g}\tGene Expression\tTrue\n' for g in features['feature_ids'])
        leaf('features', text.encode(), 'tsv', 'table')
        summary = dict(shape=[len(cells),2], raw_observations=len(cells), retained_observations=len(cells), excluded_observations=0,
            raw_features=2, retained_features=2, excluded_features=0, statistical_unit='cell_exploratory')
        steps = [dict(key='raw_qc', status='completed', reason=None, params={})]
        manifest = dict(schema_version=1, engine_version=runtime['engine_version'], identity=payload['identity'],
            raw_source=source, summary=summary, params=payload['config'], steps=steps, tables=[],
            assay='single_cell', observation_level='cell', code_digest=runtime['code_digest'],
            environment_digest=runtime['environment_digest'])
        if payload.get('subset'):
            manifest['subset'] = payload['subset']
            from PIL import Image
            image = io.BytesIO(); Image.new('RGB', (100,100), 'navy').save(image, format='PNG')
            leaf('umap_png', image.getvalue(), 'png', 'figure')
            leaf('umap_data', json.dumps(dict(synthetic_fixture=True,
                coordinates=np.tile([[0.,0.],[.2,.1],[1.,1.],[1.2,1.1]], (len(cells)//4,1)).tolist())).encode(), 'json')
            leaf('umap_manifest', json.dumps(dict(config=dict(kind='umap', panel='scores',
                title='Synthetic cell projection'), dpi=100, width_inches=1, height_inches=1)).encode(), 'json')
        return dict(outputs=outputs, manifest=manifest, summary=summary, steps=steps, checks={}, effective_params=payload['config'])
    started = client.post(base + '/single-cell-analysis-runs', headers={'Idempotency-Key':'topic-parent'},
        json=dict(name='Synthetic PCA parent', raw_source=source, params=dict(min_spots=1)))
    assert started.status_code == 202, started.text
    task = started.json()['task']
    done = run_bio_analysis_task(task['id'], task['revision'], engine=engine, staging_directory=stage)
    assert done['status'] == 'succeeded', done
    processed = done['result_bio_processed_dataset_version_id']
    fixed = client.get(base + '/bio-processed-datasets/' + processed).json()

    if processed_only:
        parent = client.get(base + '/bio-analysis-runs/' + started.json()['id']).json()['result_source']
        return dict(base=base, source=parent, engine=engine, stage=stage)

    insight_runtime = fixed_fixture_runtime(monkeypatch)
    monkeypatch.setattr(BioInsightsService, '_runtime_for', lambda self, config: insight_runtime)
    def slingshot(matrix, cells, clusters, root, seed):
        assert len(cells) == 4 and set(clusters) == {'0','1'} and root == '0'
        return dict(status='completed', lineage_ids=['L1'], pseudotime=np.arange(4.)[:,None],
            weights=np.ones((4,1)), curves=[np.array([[0.,0.],[1.2,1.1]])], versions={},
            logs=['Synthetic trajectory bridge for report engineering only'], parameters={}, lineage_clusters=[['0','1']])
    from app.adapters.single_cell_r import topics
    monkeypatch.setattr(topics, 'get_topics_bridge', lambda: SimpleNamespace(slingshot=slingshot))
    result = execute_plan(client, base, dict(kind='integration', sources=[dict(source_kind='bio_processed_dataset_version',
        source_id=processed, sha256=fixed['manifest_sha256'], role='processed')],
        config=dict(kind='integration', schema_version=2, method='slingshot', processed_source_id=processed,
            root_cluster='0', root_basis='Synthetic coordinate root', n_components=2, output_language='en')),
        'trajectory', tmp_path)
    return base, processed, result
