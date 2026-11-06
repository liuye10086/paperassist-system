"""Regression for imports performed after Linux scientific isolation starts."""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

import anndata as ad
import numpy as np
import pytest
from scipy import sparse


@pytest.mark.skipif(sys.platform != 'linux', reason='The production science sandbox requires Linux')
def test_single_cell_qc_metadata_and_resources_in_real_worker(tmp_path):
    from app.adapters.bio_engine.single_cell import import_counts
    source = tmp_path / 'input.h5ad'
    ad.AnnData(sparse.csr_matrix(np.random.default_rng(0).poisson(3, (12, 8)))).write_h5ad(source)
    config = dict(workflow_version='bio_import_v4', assay='single_cell', file_ids=['fixture'],
        name='Sandbox regression', expected_dataset_revision=0, matrix_representation='h5ad',
        h5ad=dict(matrix='X', obs_index='_index', var_index='_index'),
        samples=[dict(sample_id='s1', library_id='l1', species_taxon_id=9606, file_ids=['fixture'])])
    result = import_counts(dict(single_cell_config=config, files=[dict(id='fixture', filename=source.name,
        path=str(source), size_bytes=source.stat().st_size, sha256=hashlib.sha256(source.read_bytes()).hexdigest())],
        output_directory=str(tmp_path / 'import')))
    output = tmp_path / 'qc'; output.mkdir()
    payload = dict(mode='qc', raw=dict(manifest=result['manifest'], members={m['key']:m for m in result['outputs']}),
        config=dict(min_spots=1), output_directory=str(output))
    body = json.dumps(payload).encode()
    worker = Path(__file__).resolve().parents[2] / 'app/adapters/bio_engine/worker.py'
    completed = subprocess.run([sys.executable, '-I', '-B', str(worker), str(os.getpid())],
        input=struct.pack('!I', len(body)) + body, env={}, capture_output=True, timeout=180)
    assert completed.returncode == 0, completed.stderr.decode()
    assert completed.stdout.startswith(b'READY\n'), completed.stderr.decode()
    answer = json.loads(completed.stdout.split(b'\n', 1)[1])
    assert 'error' not in answer, completed.stderr.decode()
    manifest = answer['result']['manifest']
    assert manifest['resources']['rss_limit_bytes']==2*1024**3
    assert manifest['resources']['address_space_limit_bytes']==3*1024**3
    assert manifest['samples'][0]['species_taxon_id'] == 9606
    assert manifest['resource_estimate']['matrix']['observations'] == 12
    assert manifest['resource_estimate']['estimate_only'] is True
