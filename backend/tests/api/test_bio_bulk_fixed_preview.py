from hashlib import sha256
import logging

import pytest
from fastapi.testclient import TestClient

from app.adapters.bio_objects import BioAnalysisObjects
from app.core.config import get_data_dir
from app.db.database import database_connection
from app.main import app
from tests.api.test_bio_quantitative_lifecycle import processed_fixture
from tests.api.test_customer_workspace import create_customer_project, sign_in, write_requirements
from tests.api.test_project_assignments import assign


def test_assigned_analyst_previews_b00_bulk_members_read_only(monkeypatch, tmp_path, caplog):
    monkeypatch.delenv('PAPERASSIST_SKILL_WORKFLOWS', raising=False)
    caplog.set_level(logging.INFO, logger='app.core.request_id.skills')
    with TestClient(app) as customer, TestClient(app) as admin, TestClient(app) as analyst, TestClient(app) as outsider:
        sign_in(customer, 'bulk-preview-owner@skills.test', 'customer')
        sign_in(admin, 'bulk-preview-admin@skills.test', 'admin')
        analyst_id = sign_in(analyst, 'bulk-preview-analyst@skills.test', 'analyst')
        sign_in(outsider, 'bulk-preview-outsider@skills.test', 'analyst')
        project = create_customer_project(customer)
        other_project = create_customer_project(customer, key='different-preview-project')
        write_requirements(customer, project, 1, 'confirm')
        for base in (project, other_project):
            granted = assign(admin, base, analyst_id, 0)
            assert granted.status_code == 200, granted.text
        _, version_id = processed_fixture(analyst, monkeypatch, tmp_path, assay='bulk_rna_counts', project_base=project)
        result_path = project + '/bio-processed-datasets/' + version_id
        preview_path = result_path + '/bulk-fixed-preview'
        original = analyst.get(result_path).json()
        assert 'bulk_fixed_preview' not in original
        assert analyst.get(preview_path, params={'panel': 'qc_missing'}).status_code == 404

        monkeypatch.setenv('PAPERASSIST_SKILL_WORKFLOWS', 'bulk_fixed_preview')
        advertised = analyst.get(result_path).json()
        assert advertised.pop('bulk_fixed_preview') is True
        assert advertised == original
        assert customer.get(preview_path, params={'panel': 'qc_missing'}).status_code == 403
        assert outsider.get(preview_path, params={'panel': 'qc_missing'}).status_code == 404
        wrong_project = other_project + '/bio-processed-datasets/' + version_id + '/bulk-fixed-preview'
        assert analyst.get(wrong_project, params={'panel': 'qc_missing'}).status_code == 404
        assert analyst.get(preview_path, params={'panel': 'qc_ecdf'}).status_code == 422

        project_id = original['source']['project_id']
        with database_connection() as db:
            tasks_before = db.execute('SELECT count(*) AS n FROM tasks WHERE project_id=%s', (project_id,)).fetchone()['n']
        members = {member['key']: member for member in original['members']}
        previews = {}
        for panel in ('qc_missing', 'pca_scores', 'pca_variance'):
            response = analyst.get(preview_path, params={'panel': panel})
            assert response.status_code == 200, response.text
            assert response.headers['Cache-Control'] == 'no-store'
            preview = response.json()
            assert (preview['project_id'], preview['processed_version_id']) == (project_id, version_id)
            trace = preview['trace']
            assert (trace['workflow'], trace['workflow_version'], trace['step']) == ('bulk_fixed_preview', '1.0.0', 'qc_pca')
            assert trace['tool'] == {'id': 'bulk_plot_data', 'version': '1.0.0'}
            assert len(trace['manifest_sha256']) == 64
            assert [skill['name'] for skill in trace['skills']] == ['bulk-result-reading']
            assert len(trace['skills'][0]['sha256']) == 64
            plot = previews[panel] = preview['plot']
            assert (plot['source_id'], plot['source_sha256']) == (version_id, original['manifest_sha256'])
            assert plot['source_members'] == {key: members[key]['sha256'] for key in plot['source_members']}
            assert 'object_key' not in response.text
            request_id = response.headers['X-Request-ID']
            event = next(record.getMessage() for record in caplog.records
                         if record.name == 'app.core.request_id.skills' and f'request_id={request_id} ' in record.getMessage())
            assert f'processed_version_id={version_id}' in event and f'panel={panel}' in event
            assert trace['manifest_sha256'] in event and trace['skills'][0]['sha256'] in event
            assert plot['source_sha256'] in event and all(digest in event for digest in plot['source_members'].values())
            assert 'sample_ids' not in event and 'object_key' not in event and 'scores=' not in event

        samples = ['B0', 'B1', 'B2', 'A0', 'A1', 'A2']
        qc, pca, variance = (previews[name] for name in ('qc_missing', 'pca_scores', 'pca_variance'))
        assert qc['axes'] == {'x': 'sample_id', 'y': 'missing_fraction'}
        assert qc['sample_ids'] == samples and qc['missing_fraction'] == [0.0] * 6
        assert pca['axes'] == {'x': 'pc1', 'y': 'pc2'}
        assert pca['sample_ids'] == samples and pca['condition'] == ['B'] * 3 + ['A'] * 3
        assert pca['components'] == variance['components'] == [1, 2]
        assert pca['variance_ratio'] == variance['variance_ratio'] == pytest.approx([0.986929200789437, 0.013070799210562981])
        for scores, frozen in zip(pca['scores'], [
            [1.7749046687798917, -1.2537685747240515],
            [3.820826471125758, -0.35143605359570346],
            [10.090807030371197, 0.9475419241561449],
            [-8.345662735068109, 0.6367645310874898],
            [-6.167525780514407, 0.13107746658264643],
            [-1.1733496546943245, -0.11017929350652853],
        ], strict=True):
            assert scores == pytest.approx(frozen)
        assert set(qc['source_members']) == {'qc_missing_data'}
        assert set(pca['source_members']) == {'pca_data', 'pca_scores', 'pca_variance_ratio'}
        assert set(variance['source_members']) == {'pca_variance_ratio'}
        for key in ('qc_missing_data', 'pca_scores', 'pca_variance_ratio', 'pca_data'):
            downloaded = analyst.get(members[key]['download_url'])
            assert downloaded.status_code == 200, downloaded.text
            assert sha256(downloaded.content).hexdigest() == members[key]['sha256']
        with monkeypatch.context() as unavailable:
            unavailable.setenv('PAPERASSIST_SKILLS_DIR', str(tmp_path / 'missing-skills'))
            blocked = analyst.get(preview_path, params={'panel': 'qc_missing'})
            assert blocked.status_code == 503
            assert blocked.json()['detail']['code'] == 'runtime_skills_unavailable'
            assert analyst.get(members['qc_missing_data']['download_url']).status_code == 200
        with database_connection() as db:
            assert db.execute('SELECT count(*) AS n FROM tasks WHERE project_id=%s', (project_id,)).fetchone()['n'] == tasks_before
            object_key = db.execute('''SELECT o.object_key FROM bio_analysis_artifacts a
                JOIN storage_objects o ON o.id=a.storage_object_id
                WHERE a.processed_dataset_version_id=%s AND a.key='pca_scores' ''', (version_id,)).fetchone()['object_key']

        source = BioAnalysisObjects(get_data_dir()).path(object_key)
        frozen = source.read_bytes()
        source.write_bytes(bytes([frozen[0] ^ 1]) + frozen[1:])
        try:
            changed = analyst.get(preview_path, params={'panel': 'pca_scores'})
            assert changed.status_code == 409
            assert changed.json()['detail']['code'] == 'bio_input_integrity_changed'
            assert analyst.get(preview_path, params={'panel': 'qc_missing'}).status_code == 200
        finally:
            source.write_bytes(frozen)

        revoked = assign(admin, project, None, 1, 'Finish offline preview verification')
        assert revoked.status_code == 200, revoked.text
        assert analyst.get(preview_path, params={'panel': 'qc_missing'}).status_code == 404


def test_fixed_preview_keeps_noncomputable_pca_empty(monkeypatch, tmp_path):
    monkeypatch.setenv('PAPERASSIST_SKILL_WORKFLOWS', 'bulk_fixed_preview')
    with TestClient(app) as customer, TestClient(app) as admin, TestClient(app) as analyst:
        sign_in(customer, 'bulk-empty-owner@skills.test', 'customer')
        sign_in(admin, 'bulk-empty-admin@skills.test', 'admin')
        analyst_id = sign_in(analyst, 'bulk-empty-analyst@skills.test', 'analyst')
        project = create_customer_project(customer)
        write_requirements(customer, project, 1, 'confirm')
        assert assign(admin, project, analyst_id, 0).status_code == 200
        _, version_id = processed_fixture(
            analyst, monkeypatch, tmp_path, assay='bulk_rna_counts', project_base=project,
            recipe_params={'exclude_features': ['f2']},
        )
        result_path = project + '/bio-processed-datasets/' + version_id
        assert analyst.get(result_path).json()['bulk_fixed_preview'] is True
        for panel in ('pca_scores', 'pca_variance'):
            response = analyst.get(result_path + '/bulk-fixed-preview', params={'panel': panel})
            assert response.status_code == 200, response.text
            plot = response.json()['plot']
            assert plot['empty_reason'] == 'insufficient_complete_nonconstant_features_or_samples'
            assert plot['displayed_count'] == 0
            assert plot['components'] == plot['variance_ratio'] == []
            if panel == 'pca_scores':
                assert plot['sample_ids'] == plot['scores'] == []
                assert set(plot['source_members']) == {'pca_scores', 'pca_variance_ratio'}
