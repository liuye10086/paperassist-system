from pydantic import ValidationError
import pytest


def test_bulk_delivery_routes_are_mounted():
    from app.main import app

    prefix = '/api/v1/projects/{project_id}/bulk-workflow'
    routes = {(path, method.upper()) for path, operations in app.openapi()['paths'].items()
              for method in operations}
    assert {(prefix, 'GET'), (prefix + '/sensitivity', 'POST'),
            (prefix + '/delivery/preview', 'POST'), (prefix + '/delivery/report.docx', 'POST'),
            (prefix + '/delivery/reproducibility-package', 'POST')} <= routes


def test_download_requires_preview_digest_and_unique_versions():
    from app.domain.bio_insights.bulk_delivery_contracts import BulkDeliveryRequest, BulkDownloadRequest

    body = dict(comparison_version_id='baseline', result_version_ids=['figure'],
                selections=[dict(contrast_id='treated_vs_control', direction='up')])
    assert BulkDeliveryRequest.model_validate(body).selections[0].q_column == 'q_within_contrast'
    with pytest.raises(ValidationError):
        BulkDownloadRequest.model_validate(body)
    with pytest.raises(ValidationError):
        BulkDeliveryRequest.model_validate({**body, 'result_version_ids': ['figure', 'figure']})
    assert BulkDownloadRequest.model_validate({**body, 'facts_digest': 'a' * 64}).facts_digest == 'a' * 64


def test_download_rejects_different_facts_digest_before_rendering():
    from app.api.bulk_workflow import checked_facts
    from app.core.exceptions import StorageError
    from app.domain.bio_insights.bulk_delivery_contracts import BulkDownloadRequest

    selection = BulkDownloadRequest(comparison_version_id='baseline', facts_digest='a' * 64)
    with pytest.raises(StorageError) as error:
        checked_facts(selection, {'facts_digest': 'b' * 64})
    assert error.value.status == 409


def test_filtered_export_keeps_original_fields_and_frozen_directions(tmp_path):
    import zipfile

    from app.adapters.bio_insights_reproduction import ReproductionArchive
    from app.domain.bio_insights.bulk_delivery_archive import add_filtered_tables

    full = tmp_path / 'comparison.tsv'
    header = 'contrast_id\tnumerator\tdenominator\tfeature_id\trow_key\ttested\ttest_status\teffect_value\tq_within_contrast\tstatistic\n'
    up = 'ab\tA\tB\tENSG00000001.4\trow_01\ttrue\tcomputed\t1.450\t0.020\t3.250\n'
    down = 'ab\tA\tB\tENSG00000002\trow_02\ttrue\tcomputed\t-2.10\t0.013\t-3.251\n'
    excluded = 'ab\tA\tB\tENSG00000003\trow_03\tfalse\texcluded\t\t\t\n'
    full.write_text(header + up + down + excluded, encoding='utf-8')
    archive = ReproductionArchive()
    try:
        records = add_filtered_tables(archive, full, 'f' * 64, [
            dict(contrast_id='ab', numerator='A', denominator='B', counts=dict(up=1),
                 selection=dict(contrast_id='ab', direction='up')),
        ])
        handle, _ = archive.finish(dict(kind='test'))
        with zipfile.ZipFile(handle) as packed:
            assert packed.read(records[0]['path']).decode() == header + up
        assert records[0]['rows'] == 1 and records[0]['source_sha256'] == 'f' * 64
    finally:
        archive.close()


def test_historical_environment_requires_exact_locked_code_and_profile(tmp_path, monkeypatch):
    import hashlib
    import json

    from app.domain.bioinformatics.contracts import digest
    from app.domain.bio_insights.bulk_reproduction_environment import ARCHIVE_DIR_ENV, archived_environment

    lock = b'fixed dependencies\n'
    code = b'# fixed engine\n'
    lock_sha256 = hashlib.sha256(lock).hexdigest()
    code_digest = hashlib.sha256(b'engine.py\0' + code + b'\0').hexdigest()
    environment = dict(python='test', packages={}, native_libraries={}, lock_sha256=lock_sha256, limits={})
    identity = dict(engine_version='bio_insights_v1.0.0', code_digest=code_digest,
                    environment_digest=digest(environment), lock_sha256=lock_sha256)
    folder = tmp_path / code_digest / identity['environment_digest']
    (folder / 'app').mkdir(parents=True)
    (folder / 'app/engine.py').write_bytes(code)
    (folder / 'code-files.json').write_text('["engine.py"]', encoding='utf-8')
    (folder / 'requirements-bio-insights.lock.txt').write_bytes(lock)
    (folder / 'reproduce.py').write_bytes(b'# archived verify and recompute program')
    (folder / 'render_worker.py').write_bytes(b'# archived renderer')
    report = {**environment, **identity, 'schema_version': 1, 'status': 'passed', 'profile': 'bulk_model',
              'numeric_threads': 1, 'checks': {'bulk_shared_wald': True}, 'interpreter': '/fixed/python',
              'isolation': dict(network='denied', file='denied', fork='denied', subprocess='denied')}
    (folder / 'runtime-bulk_model.json').write_text(json.dumps(report), encoding='utf-8')
    monkeypatch.setenv(ARCHIVE_DIR_ENV, str(tmp_path))
    assert archived_environment(identity, 'bulk_model').code == (('engine.py', code),)
    assert archived_environment(identity, 'bulk_display') is None
    (folder / 'app/engine.py').write_bytes(b'# changed engine\n')
    assert archived_environment(identity, 'bulk_model') is None


def test_archive_bytes_use_fixed_timestamps():
    from app.adapters.bio_insights_reproduction import ReproductionArchive
    from zipfile import ZipFile

    archive = ReproductionArchive()
    try:
        archive.add_bytes('facts.json', b'{}')
        handle, _ = archive.finish(dict(kind='test'))
        with ZipFile(handle) as packed:
            assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in packed.infolist())
    finally:
        archive.close()
