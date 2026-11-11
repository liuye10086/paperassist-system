"""Negative acceptance cases for the Bulk raw-count workflow."""

import hashlib
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from tests.domain.test_bio_b04_model_design import bulk_config, contrast, sources
from tests.numeric.test_bio_tabular_assays import payload


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


@pytest.fixture
def bulk_import(tmp_path):
    request = payload(tmp_path, counts=True)
    request['config']['scale']['input_origin'] = 'bulk_rna'
    directory = tmp_path / 'raw'
    directory.mkdir()
    request['output_directory'] = str(directory)
    return request


def replace_original(request, file_id, text):
    member = next(file for file in request['files'] if file['id'] == file_id)
    data = text.encode('utf-8')
    Path(member['path']).write_bytes(data)
    member.update(size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


@pytest.mark.parametrize(('field', 'value', 'reason'), [
    ('kind', 'tpm', 'counts_scale_mismatch'),
    ('kind', 'fpkm', 'counts_scale_mismatch'),
    ('kind', 'log2', 'counts_scale_mismatch'),
    ('kind', 'normalized', 'counts_scale_mismatch'),
    ('input_origin', 'single_cell_expression', 'bulk_input_origin_invalid'),
    ('input_origin', 'tpm', 'bulk_input_origin_invalid'),
    ('input_origin', 'fpkm', 'bulk_input_origin_invalid'),
    ('input_origin', 'log', 'bulk_input_origin_invalid'),
    ('input_origin', 'vst', 'bulk_input_origin_invalid'),
    ('input_origin', 'unknown', 'bulk_input_origin_invalid'),
])
def test_bulk_import_rejects_ineligible_scale_and_declared_origin(bulk_import, field, value, reason):
    from app.adapters.bio_engine.tabular_assays import import_tabular

    bulk_import['config']['scale'][field] = value
    with pytest.raises(ValidationError, match=reason):
        import_tabular(bulk_import)
    assert not list(Path(bulk_import['output_directory']).iterdir())


@pytest.mark.parametrize(('value', 'reason'), [
    ('', 'counts_missing'), ('NA', 'counts_missing'), ('-1', 'counts_invalid'),
    ('1.5', 'counts_invalid'), ('NaN', 'matrix_nonfinite'), ('Infinity', 'matrix_nonfinite'),
])
def test_bulk_import_pinpoints_invalid_counts(bulk_import, value, reason):
    from app.adapters.bio_engine.tabular_assays import import_tabular

    replace_original(bulk_import, 'm', f'feature_id,s1,s2,s3\na,1,{value},4\n')
    with pytest.raises(ValueError, match=rf'^{reason}:file=m\.csv:row=2:column=s2:sample_id=s2:feature_id=a$'):
        import_tabular(bulk_import)
    assert not list(Path(bulk_import['output_directory']).iterdir())


@pytest.mark.parametrize(('file_id', 'text', 'reason'), [
    ('s', 'sample_id,condition,biological_unit_id\ns1,A,u1\ns2,A,u2\ns4,B,u4\n',
     r'^sample_axis_mismatch:file=s\.csv:missing=s3:extra=s4$'),
    ('m', 'feature_id,s1,s2,s3\na,1,2,4\na,2,4,8\n',
     r'^duplicate_feature_id:file=m\.csv:row=3:feature_id=a$'),
])
def test_bulk_import_reports_conflicting_axes(bulk_import, file_id, text, reason):
    from app.adapters.bio_engine.tabular_assays import import_tabular

    replace_original(bulk_import, file_id, text)
    with pytest.raises(ValueError, match=reason):
        import_tabular(bulk_import)
    assert not list(Path(bulk_import['output_directory']).iterdir())


def test_bulk_qc_locates_zero_library_and_compute_cannot_keep_it(bulk_import, tmp_path):
    from app.adapters.bio_engine.tabular_assays import _rows, import_tabular, run_tabular

    replace_original(bulk_import, 'm', 'feature_id,s1,s2,s3\na,1,0,4\nb,2,0,8\nc,3,0,12\n')
    result = import_tabular(bulk_import)
    raw = {'manifest': result['manifest'], 'members': {member['key']: member for member in result['outputs']}}
    qc_directory = tmp_path / 'qc'
    qc_directory.mkdir()
    common = dict(raw=raw, config={}, identity=bulk_import['identity'])
    qc = run_tabular({**common, 'mode': 'qc', 'output_directory': str(qc_directory)})
    member = next(item for item in qc['outputs'] if item['key'] == qc['summary']['sample_qc_table'])
    metrics = {row['sample_id']: row for row in _rows(member)}
    assert {sample: float(row['total_counts']) for sample, row in metrics.items()} == {'s1': 6., 's2': 0., 's3': 24.}
    assert int(metrics['s2']['detected_features']) == 0
    assert float(metrics['s2']['zero_fraction']) == 1.
    assert qc['summary']['retained_observations'] == 3

    compute_directory = tmp_path / 'compute'
    compute_directory.mkdir()
    with pytest.raises(ValueError, match='^empty_count_library$'):
        run_tabular({**common, 'mode': 'compute', 'output_directory': str(compute_directory)})


@pytest.mark.parametrize(('problem', 'rank', 'residual'), [
    ('collinear_covariates', 3, 1), ('zero_residual_df', 4, 0),
])
def test_bulk_model_blocks_non_estimable_design(problem, rank, residual):
    from app.domain.bio_insights.quantitative_design import validate_quantitative_design

    source = sources('AB', 2)
    rows = source[0]['metadata']['observations']
    if problem == 'collinear_covariates':
        for row in rows:
            row['related_age'] = str(2 * int(row['age']) + 7)
        options = {'covariates': [
            dict(field=field, kind='continuous', name=field) for field in ('age', 'related_age')
        ]}
    else:
        for row, batch in zip(rows, ('X', 'Y', 'X', 'Z'), strict=True):
            row['batch'] = batch
        options = {'batch_adjustment': True}

    preview = validate_quantitative_design(bulk_config([contrast('B_A', 'B', 'A')], **options), source)
    assert not preview.executable
    assert {reason.code for reason in preview.blocking_reasons} == {'rank_deficient_design'}
    assert len(preview.bulk_model['design_columns']) == 4
    assert preview.bulk_model['rank'] == rank
    assert preview.bulk_model['residual_degrees_freedom'] == residual


def test_bulk_model_blocks_incomplete_pairs_without_removing_samples():
    from app.domain.bio_insights.quantitative_design import validate_quantitative_design

    source = sources('AB', 3, paired=True)
    source[0]['metadata']['observations'][-1]['pair_id'] = 'unmatched'
    preview = validate_quantitative_design(
        bulk_config([contrast('B_A', 'B', 'A', 3)], design='paired'), source,
    )
    assert not preview.executable
    assert {reason.code for reason in preview.blocking_reasons} == {'incomplete_or_duplicate_pairs'}
    assert preview.actual_units[0]['complete_pairs'] == 2
    assert preview.actual_units[0]['group_sizes'] == {'B': 3, 'A': 3}
    assert not preview.exclusions


def test_bulk_fit_blocks_a_library_emptied_by_the_frozen_filter(monkeypatch):
    pytest.importorskip('pydeseq2')
    from pydeseq2.dds import DeseqDataSet
    from app.adapters.bio_insights_engine.counts_model import fit_reviewed_counts
    from app.domain.bio_insights.quantitative_contracts import QuantitativeComparisonConfig
    from app.domain.bio_insights.quantitative_design import validate_quantitative_design

    config = QuantitativeComparisonConfig.model_validate(
        bulk_config([contrast('B_A', 'B', 'A')], minimum_total_counts=10, minimum_sample_counts=1),
    )
    source = sources('AB', 2)
    features = ['low', 'g1', 'g2']
    source[0]['metadata']['feature_ids'] = features
    preview = validate_quantitative_design(config, source)
    assert preview.executable

    index = {('p', sample): i for i, sample in enumerate(('A0', 'A1', 'B0', 'B1'))}
    counts = np.array([[1, 0, 0], [0, 20, 10], [0, 10, 20], [0, 12, 11]], dtype='int64')
    assert np.all(counts.sum(axis=1) > 0)

    def unexpected_fit(self):
        pytest.fail('A sample with zero counts after filtering reached DESeq2 fitting')

    monkeypatch.setattr(DeseqDataSet, 'deseq2', unexpected_fit)
    with pytest.raises(ValueError, match='^no_testable_features_or_zero_library$'):
        fit_reviewed_counts(counts, features, index, preview.bulk_model, config)
