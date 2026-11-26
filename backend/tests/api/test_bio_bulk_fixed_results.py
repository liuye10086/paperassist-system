"""The regular result endpoints expose the fixed B00 QC and PCA content."""

from hashlib import sha256

import pytest
from fastapi.testclient import TestClient

from app.adapters.bio_objects import BioAnalysisObjects
from app.core.config import get_data_dir
from app.db.database import database_connection
from app.main import app
from tests.api.test_bio_quantitative_lifecycle import processed_fixture
from tests.api.test_customer_workspace import create_customer_project, sign_in, write_requirements
from tests.api.test_project_assignments import assign


def test_assigned_analyst_reads_fixed_bulk_tables_and_original_members(monkeypatch, tmp_path):
    monkeypatch.setenv('PAPERASSIST_SKILL_WORKFLOWS', 'bulk_fixed_preview')
    with TestClient(app) as customer, TestClient(app) as admin, TestClient(app) as analyst, TestClient(app) as outsider:
        sign_in(customer, 'bulk-results-owner@skills.test', 'customer')
        sign_in(admin, 'bulk-results-admin@skills.test', 'admin')
        analyst_id = sign_in(analyst, 'bulk-results-analyst@skills.test', 'analyst')
        sign_in(outsider, 'bulk-results-outsider@skills.test', 'analyst')
        project = create_customer_project(customer)
        other = create_customer_project(customer, key='different-results-project')
        write_requirements(customer, project, 1, 'confirm')
        for base in (project, other):
            assert assign(admin, base, analyst_id, 0).status_code == 200
        _, version_id = processed_fixture(analyst, monkeypatch, tmp_path, assay='bulk_rna_counts', project_base=project)
        path = f'{project}/bio-processed-datasets/{version_id}'
        response = analyst.get(path)
        assert response.status_code == 200, response.text
        result = response.json()
        assert 'bulk_fixed_preview' not in result
        assert analyst.get(path + '/bulk-fixed-preview', params={'panel': 'qc_missing'}).status_code == 404
        assert outsider.get(path + '/tables/sample_qc').status_code == 404
        assert analyst.get(f'{other}/bio-processed-datasets/{version_id}/tables/pca_scores').status_code == 404

        project_id = result['source']['project_id']
        with database_connection() as db:
            before = db.execute('SELECT count(*) AS n FROM tasks WHERE project_id=%s', (project_id,)).fetchone()['n']
        members = {member['key']: member for member in result['members']}
        original = {}
        for key in ('qc_missing_data', 'pca_scores', 'pca_variance_ratio', 'pca_data'):
            original[key] = download = analyst.get(members[key]['download_url'])
            assert download.status_code == 200, download.text
            assert sha256(download.content).hexdigest() == members[key]['sha256']

        qc, pca, variance = (analyst.get(path + '/tables/' + key).json()['items']
                             for key in ('sample_qc', 'pca_scores', 'pca_variance_ratio'))
        samples = ['B0', 'B1', 'B2', 'A0', 'A1', 'A2']
        assert [row['sample_id'] for row in qc] == [row['sample_id'] for row in pca] == samples
        assert [row['condition'] for row in qc] == ['B'] * 3 + ['A'] * 3
        assert original['qc_missing_data'].json()['missing_fraction'] == [0.0] * 6
        assert original['pca_data'].json()['sample_ids'] == samples
        assert [float(row['variance_ratio']) for row in variance] == pytest.approx([0.986929200789437, 0.013070799210562981])
        for row, frozen in zip(pca, [
            [1.7749046687798917, -1.2537685747240515],
            [3.820826471125758, -0.35143605359570346],
            [10.090807030371197, 0.9475419241561449],
            [-8.345662735068109, 0.6367645310874898],
            [-6.167525780514407, 0.13107746658264643],
            [-1.1733496546943245, -0.11017929350652853],
        ], strict=True):
            assert [float(row['pc1']), float(row['pc2'])] == pytest.approx(frozen)

        with database_connection() as db:
            assert db.execute('SELECT count(*) AS n FROM tasks WHERE project_id=%s', (project_id,)).fetchone()['n'] == before
            assert db.execute('SELECT count(*) AS n FROM model_calls WHERE project_id=%s', (project_id,)).fetchone()['n'] == 0
            object_key = db.execute('''SELECT o.object_key FROM bio_analysis_artifacts a
                JOIN storage_objects o ON o.id=a.storage_object_id
                WHERE a.processed_dataset_version_id=%s AND a.key='pca_scores' ''', (version_id,)).fetchone()['object_key']
        source = BioAnalysisObjects(get_data_dir()).path(object_key)
        frozen = source.read_bytes()
        source.write_bytes(bytes([frozen[0] ^ 1]) + frozen[1:])
        try:
            changed = analyst.get(path + '/tables/pca_scores')
            assert changed.status_code == 409
            assert changed.json()['detail']['code'] == 'bio_source_conflict'
            assert analyst.get(path + '/tables/sample_qc').status_code == 200
        finally:
            source.write_bytes(frozen)

        assert assign(admin, project, None, 1, 'Finish offline results verification').status_code == 200
        assert analyst.get(path + '/tables/pca_scores').status_code == 404
        assert analyst.get(members['pca_scores']['download_url']).status_code == 404


def test_regular_bulk_result_keeps_noncomputable_pca_empty(monkeypatch, tmp_path):
    with TestClient(app) as customer, TestClient(app) as admin, TestClient(app) as analyst:
        sign_in(customer, 'bulk-empty-owner@skills.test', 'customer')
        sign_in(admin, 'bulk-empty-admin@skills.test', 'admin')
        analyst_id = sign_in(analyst, 'bulk-empty-analyst@skills.test', 'analyst')
        project = create_customer_project(customer)
        write_requirements(customer, project, 1, 'confirm')
        assert assign(admin, project, analyst_id, 0).status_code == 200
        _, version_id = processed_fixture(analyst, monkeypatch, tmp_path, assay='bulk_rna_counts', project_base=project,
                                          recipe_params={'exclude_features': ['f2']})
        path = f'{project}/bio-processed-datasets/{version_id}'
        result = analyst.get(path).json()
        tables = {table['key']: table for table in result['tables']}
        for key in ('pca_scores', 'pca_variance_ratio'):
            assert tables[key]['status'] == 'not_computable'
            assert tables[key]['reason'] == 'insufficient_complete_nonconstant_features_or_samples'
            assert analyst.get(path + '/tables/' + key).json()['items'] == []
