import json

import pytest

from app.domain.bioinformatics.settings import BioLimits
from app.domain.bioinformatics import tabular_settings
from app.domain.bio_insights import settings as insight_settings


def test_single_cell_upload_limit_allows_128_mib_inputs():
    assert BioLimits().max_upload_bytes == 128 * 1024 * 1024
    assert BioLimits(max_upload_bytes=128 * 1024 * 1024).max_upload_bytes == 128 * 1024 * 1024


def test_bulk_capacity_is_centralized_for_the_60k_by_50_target():
    limits = BioLimits()
    assert limits.max_tabular_file_bytes == 128 * 1024 * 1024
    assert limits.max_tabular_expanded_bytes == 256 * 1024 * 1024
    assert limits.max_bulk_matrix_cells >= 60_000 * 50
    assert limits.max_bulk_observations >= 50


@pytest.fixture
def tabular_receipt():
    return {
        'schema_version': 1,
        'status': 'passed',
        'profile': 'tabular',
        'platform': 'linux',
        'interpreter': insight_settings.INTERPRETER,
        'numeric_threads': 1,
        'limits': insight_settings.BioInsightsLimits().model_dump(),
        'bulk_limits': BioLimits().model_dump(),
        'isolation': {key: 'denied' for key in ('network', 'file', 'fork', 'subprocess')},
        'peak_rss_kib': 300000,
        'checks': dict(tabular_import=True, tabular_qc=True, tabular_compute=True),
        'runtime_identity': dict(available=True, blockers=[], engine_version=tabular_settings.ENGINE_VERSION,
            code_digest=tabular_settings.engine_code_digest(), lock_sha256=insight_settings.engine_lock_digest(),
            environment_digest='a' * 64),
    }


def test_scoped_tabular_gate_admits_current_identity_without_general_probe(tmp_path, monkeypatch, tabular_receipt):
    report = tmp_path / 'tabular.json'
    report.write_text(json.dumps(tabular_receipt), encoding='utf-8')
    monkeypatch.setenv('PAPERASSIST_BIO_TABULAR_RUNTIME_MANIFEST', str(report))
    monkeypatch.delenv(insight_settings.RUNTIME_MANIFEST_ENV, raising=False)
    assert tabular_settings.runtime_identity() == tabular_receipt['runtime_identity']


@pytest.mark.parametrize('section,key,value', [
    ('runtime_identity', 'code_digest', '0' * 64),
    ('runtime_identity', 'lock_sha256', '0' * 64),
    ('runtime_identity', 'environment_digest', 'wrong'),
    ('checks', 'tabular_qc', False),
    ('isolation', 'network', 'allowed'),
    (None, 'peak_rss_kib', 2 * 1024**2),
])
def test_explicit_tabular_gate_fails_closed(tmp_path, monkeypatch, tabular_receipt, section, key, value):
    current = tabular_receipt['runtime_identity'].copy()
    legacy = tmp_path / 'general.json'
    legacy.write_text(json.dumps(dict(tabular_code_digest=current['code_digest'],
        checks=dict(tabular_import=True, tabular_compute=True))), encoding='utf-8')
    monkeypatch.setenv(insight_settings.RUNTIME_MANIFEST_ENV, str(legacy))
    monkeypatch.setattr(insight_settings, 'runtime_identity', lambda: current)
    if section:
        tabular_receipt[section][key] = value
    else:
        tabular_receipt[key] = value
    report = tmp_path / 'tabular.json'
    report.write_text(json.dumps(tabular_receipt), encoding='utf-8')
    monkeypatch.setenv('PAPERASSIST_BIO_TABULAR_RUNTIME_MANIFEST', str(report))
    assert not tabular_settings.runtime_identity()['available']


def test_tabular_gate_still_accepts_current_legacy_receipt(tmp_path, monkeypatch, tabular_receipt):
    identity = tabular_receipt['runtime_identity']
    legacy = tmp_path / 'general.json'
    legacy.write_text(json.dumps(dict(tabular_code_digest=identity['code_digest'],
        checks=dict(tabular_import=True, tabular_compute=True))), encoding='utf-8')
    monkeypatch.setenv(insight_settings.RUNTIME_MANIFEST_ENV, str(legacy))
    monkeypatch.delenv('PAPERASSIST_BIO_TABULAR_RUNTIME_MANIFEST', raising=False)
    monkeypatch.setattr(insight_settings, 'runtime_identity', lambda: identity)
    assert tabular_settings.runtime_identity() == identity
