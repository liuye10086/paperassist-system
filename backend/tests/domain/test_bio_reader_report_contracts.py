"""Native report choices are explicit; they never resolve a latest figure."""
import importlib.util

import pytest
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def contract():
    assert importlib.util.find_spec('app.domain.bio_reader_reports') is not None, 'Native report context contract is missing'
    from app.domain.bio_reader_reports import BioReportPrepareRequest
    return BioReportPrepareRequest


def test_explicit_order_and_empty_original_selection():
    request = contract()
    body = dict(title='Saved analysis', language='en', selection=dict(kind='processed',
                processed_version_id='processed', annotation_version_id=None, figure_version_ids=[]))
    assert request.model_validate(body).selection.figure_version_ids == []
    body['selection']['figure_version_ids'] = ['second', 'first']
    assert request.model_validate(body).selection.figure_version_ids == ['second', 'first']
    for invalid in (['same', 'same'], list(map(str, range(51)))):
        with pytest.raises(ValidationError):
            request.model_validate(body | {'selection': body['selection'] | {'figure_version_ids': invalid}})
    with pytest.raises(ValidationError):
        request.model_validate(body | {'selection': {'kind': 'processed', 'processed_version_id': 'processed'}})


def test_strict_language_and_bulk_preview_identity():
    request = contract()
    delivery = dict(comparison_version_id='comparison', facts_digest='a'*64, language='zh')
    body = dict(title='报告', language='zh-CN', selection=dict(kind='bulk', delivery=delivery))
    assert request.model_validate(body).selection.delivery.facts_digest == 'a'*64
    with pytest.raises(ValidationError):
        request.model_validate(body | {'language': 'en'})
    with pytest.raises(ValidationError):
        request.model_validate(body | {'extra': 'forbidden'})


def test_csv_table_descriptor_parses_exact_values_and_legacy_tsv_stays_unchanged():
    from app.adapters.reader_report_presentation import report_table
    table = dict(key='results', columns=['gene', 'value'], expected_rows=2, source={})
    parsed, _ = report_table(table | {'format': 'csv'}, b'\xef\xbb\xbfgene,value\nA,0\nB,NA\n')
    assert list(parsed['rows']) == [['A', '0'], ['B', 'NA']]
    parsed, _ = report_table(table, b'gene\tvalue\nA\t0\nB\tNA\n')
    assert list(parsed['rows']) == [['A', '0'], ['B', 'NA']]


def test_csv_package_keeps_csv_extension_and_offline_rebuild(tmp_path):
    import hashlib
    import subprocess
    import sys
    from zipfile import ZipFile
    from app.adapters.research_report_render import render_report, stage_report_payload
    from tests.domain.test_research_reports import sample
    raw = b'gene,value\n"a,b",0\nB,NA\n'
    table = dict(key='csv_results', format='csv', columns=['gene', 'value'], expected_rows=2,
                 source={}, sha256=hashlib.sha256(raw).hexdigest())
    snapshot = sample() | {'tables': [table]}
    staged, output = tmp_path / 'stage', tmp_path / 'out'
    staged.mkdir(); output.mkdir()
    result = render_report(stage_report_payload(dict(snapshot=snapshot, tables=[table], table_raws=[raw], figures=[], package_files=[]), staged), output)
    archive = next(item for item in result['outputs'] if item['format'] == 'zip')
    with ZipFile(archive['path']) as zipped:
        assert zipped.read('tables/table_000.csv') == raw
        assert 'tables/table_000.tsv' not in zipped.namelist()
        zipped.extractall(tmp_path / 'offline')
    run = subprocess.run([sys.executable, str(tmp_path / 'offline' / 'rebuild_report.py')], cwd=tmp_path / 'offline', capture_output=True, timeout=60)
    assert run.returncode == 0, run.stderr


def test_large_annotation_is_referenced_once_and_oversized_context_is_rejected():
    from app.domain.bio_reader_reports.materials import annotation_identity, checked_context_size
    from app.core.exceptions import StorageError
    view = dict(id='v1', set_id='set1', labels=[dict(id='T', cell_ids=['cell'] * 100000)],
                assignments=[dict(barcode='cell', label_id='T', status='assigned')] * 100000)
    fixed = annotation_identity(view, dict(geometry_sha256='a'*64, assignments_sha256='b'*64,
        geometry_object_id='geometry', assignments_object_id='assignments'))
    assert len(str(fixed)) < 1000 and 'view' not in fixed
    with pytest.raises(StorageError) as error:
        checked_context_size({'large': 'x' * 4194304})
    assert error.value.status == 422


def test_native_figure_titles_name_saved_scientific_views():
    from app.domain.bio_reader_reports.materials import scientific_title
    assert scientific_title('qc_missing_png', 'en') == 'Missing fraction by sample'
    assert scientific_title('topic_slingshot', 'en') == 'Single-cell trajectory'
    assert scientific_title('volcano', 'zh-CN') == '差异效应与显著性火山图'


def test_bulk_shortcut_invalid_native_selection_is_a_domain_validation_error():
    from app.domain.bio_reader_reports.bulk import resolve_bulk
    from app.core.exceptions import StorageError
    with pytest.raises(StorageError) as error:
        resolve_bulk(None, dict(comparison_version_id='same', result_version_ids=['same'], language='en'))
    assert error.value.status == 422
