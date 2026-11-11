"""Reconcile published Bulk tables with the independent R DESeq2 export."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


KEYS = ['contrast_id', 'feature_id']
LABELS = ['numerator', 'denominator']
P_FIELD = 'p_value'
Q_WITHIN = 'q_within_contrast'
Q_FAMILY = 'q_global_family'
EFFECT = 'effect_value'
REFERENCE_OUTPUTS = ('comparison_results.tsv', 'size_factors.tsv', 'design_matrix.tsv',
                     'model_sample_metadata.tsv', 'session-info.txt')


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def table(path, numeric=()):
    rows = pd.read_csv(path, sep='\t', dtype=str, keep_default_na=False)
    for field in numeric:
        rows[field] = pd.to_numeric(rows[field].replace({'': np.nan, 'NA': np.nan}), errors='raise')
    return rows


def bh(values, family_size=None):
    result = np.full(len(values), np.nan)
    finite = np.flatnonzero(np.isfinite(values))
    ordered = finite[np.argsort(values[finite], kind='stable')]
    ranks = np.arange(1, len(ordered) + 1)
    adjusted = values[ordered] * (len(ordered) if family_size is None else family_size) / ranks
    result[ordered] = np.minimum(1, np.minimum.accumulate(adjusted[::-1])[::-1])
    return result


def bh_columns(rows, *, predeclared):
    def adjusted(group):
        family_size = int(group['tested'].str.upper().eq('TRUE').sum()) if predeclared else None
        return bh(group[P_FIELD].to_numpy(), family_size)

    within = pd.Series(np.nan, index=rows.index)
    for _, group in rows.groupby('contrast_id'):
        within.loc[group.index] = adjusted(group)
    return {Q_WITHIN: within, Q_FAMILY: adjusted(rows)}


def audit_bh(rows, *, predeclared):
    def matches(observed, expected):
        return bool(np.allclose(observed, expected, atol=1e-13, rtol=1e-11, equal_nan=True))

    adjusted = bh_columns(rows, predeclared=predeclared)
    return dict(within=matches(rows[Q_WITHIN], adjusted[Q_WITHIN]),
                family=matches(rows[Q_FAMILY], adjusted[Q_FAMILY]))


def audit_reference_provenance(reference, spec_path, spec):
    inputs = {'spec': sha256(spec_path)}
    for key in ('counts', 'metadata'):
        inputs[key] = sha256(spec_path.parent / spec[key])
        assert inputs[key] == spec[key + '_sha256'], f'Frozen {key} checksum differs'
    diagnostics = json.loads((reference / 'diagnostics.json').read_text(encoding='utf-8'))
    assert diagnostics.get('input_sha256') == inputs, 'R input checksums differ from frozen inputs'
    outputs = {name: sha256(reference / name) for name in REFERENCE_OUTPUTS}
    assert diagnostics.get('output_sha256') == outputs, 'R output checksums differ from the run receipt'
    return diagnostics


def audit_design(platform, reference, expected_model, protocol):
    actual = table(platform / 'size_factors.tsv', ['factor'])
    expected = table(reference / 'size_factors.tsv', ['factor'])
    joined = actual.merge(expected, on='sample_id', suffixes=('_platform', '_r'), validate='one_to_one')
    assert len(joined) == len(actual) == len(expected), 'Size-factor sample axis differs'
    size_error = (joined['factor_platform'] - joined['factor_r']).abs()
    actual_models = json.loads((platform / 'model_diagnostics.json').read_text(encoding='utf-8'))
    if isinstance(actual_models, list):
        (actual_model,) = actual_models
    else:
        actual_model = actual_models
    unit_to_sample = dict(zip(actual['unit_id'], actual['sample_id'], strict=True))
    sample_order = [unit_to_sample[unit] for unit in actual_model['sample_unit_ids']]
    platform_matrix = pd.DataFrame(actual_model['design_matrix'], index=sample_order)
    r_matrix = table(reference / 'design_matrix.tsv').set_index('sample_id').astype(float)
    assert set(platform_matrix.index) == set(r_matrix.index), 'Design sample axis differs'
    return dict(size_factor_max_abs=float(size_error.max()),
                size_factors_within_limit=bool(size_error.le(protocol['size_factor_absolute_limit']).all()),
                design_equal=np.array_equal(platform_matrix.loc[r_matrix.index].to_numpy(), r_matrix.to_numpy()),
                rank_equal=actual_model['rank'] == expected_model['rank'],
                residual_df_equal=actual_model['residual_degrees_freedom'] == expected_model['residual_df'],
                rank=actual_model['rank'], residual_df=actual_model['residual_degrees_freedom'],
                platform_formula=actual_model['formula'], r_formula=expected_model['design'],
                platform_fit_type=actual_model['fit_type_effective'], r_fit_type=expected_model['fit_type']), joined


def audit_counts(platform, spec_path, spec, factors):
    feature_column = spec.get('feature_column', 'feature_id')
    source = pd.read_csv(spec_path.parent / spec['counts'], sep=spec['separator'],
                         dtype={feature_column: str}, keep_default_na=False).set_index(feature_column, verify_integrity=True)
    published = table(platform / 'model_counts.tsv').set_index('feature_id', verify_integrity=True)
    units = dict(zip(factors['sample_id'], factors['unit_id'], strict=True))
    samples = spec['samples']
    assert set(units) == set(samples) and set(published.index) == set(source.index), 'Model counts axes differ'
    assert set(published.columns) == {'model_id', *units.values()}, 'Model counts unit axis differs'
    actual = published.loc[source.index, [units[sample] for sample in samples]].to_numpy(dtype=np.int64)
    expected = source[samples].to_numpy(dtype=np.int64)
    assert np.array_equal(actual, expected), 'Published model counts differ from frozen integer input'
    return (dict(features=actual.shape[0], samples=actual.shape[1], exact_integer_cells=actual.size,
                 published_counts_sha256=sha256(platform / 'model_counts.tsv')), set(source.index))


def compare_values(rows, field, limits):
    left = rows[field + '_platform'].to_numpy()
    right = rows[field + '_r'].to_numpy()
    shared = np.isfinite(left) & np.isfinite(right)
    left_finite, right_finite = np.isfinite(left), np.isfinite(right)
    error = np.abs(left[shared] - right[shared])
    beyond = np.zeros(len(rows), dtype=bool)
    beyond[shared] = error > limits['atol'] + limits['rtol'] * np.abs(right[shared])
    rows[field + '_abs_diff'] = np.abs(left - right)
    rows[field + '_beyond_limit'] = beyond
    report = dict(both_finite=int(shared.sum()), platform_only_finite=int((left_finite & ~right_finite).sum()),
                  r_only_finite=int((~left_finite & right_finite).sum()), beyond_limit=int(beyond.sum()),
                  median_abs_diff=float(np.median(error)) if error.size else None,
                  p95_abs_diff=float(np.quantile(error, 0.95)) if error.size else None,
                  max_abs_diff=float(error.max()) if error.size else None)
    if field in (P_FIELD, Q_WITHIN, Q_FAMILY, 'original_method_adjustment'):
        positive = shared & (left > 0) & (right > 0)
        report.update(platform_zero=int((left == 0).sum()), r_zero=int((right == 0).sum()),
                      max_log10_gap=float(np.max(np.abs(np.log10(left[positive]) - np.log10(right[positive]))))
                      if positive.any() else None)
    return report


def compare_contrast(rows, protocol):
    platform, r = rows[EFFECT + '_platform'], rows[EFFECT + '_r']
    signed = platform.notna() & r.notna() & (np.sign(platform) != np.sign(r))
    above_floor = platform.abs().gt(protocol['absolute_direction_floor']) & r.abs().gt(protocol['absolute_direction_floor'])
    platform_selected = platform.abs().ge(protocol['effect_selection_threshold']) & rows[Q_WITHIN + '_platform'].le(protocol['alpha'])
    r_selected = r.abs().ge(protocol['effect_selection_threshold']) & rows[Q_WITHIN + '_r'].le(protocol['alpha'])
    r_cook = rows['p_without_cooks'].notna() & rows[P_FIELD + '_r'].isna()
    return dict(rows=len(rows), retained=int(rows['tested_r'].eq('TRUE').sum()),
                platform_status=rows['test_status'].value_counts().to_dict(),
                platform_unavailable_reasons=rows.loc[rows['test_status'] != 'tested', 'reason'].value_counts().to_dict(),
                r_beta_nonconverged=int(rows['beta_converged'].eq('FALSE').sum()), r_cook_filtered=int(r_cook.sum()),
                finite_sign_mismatches=int(signed.sum()), sign_mismatches_above_floor=int((signed & above_floor).sum()),
                platform_selected=int(platform_selected.sum()), r_selected=int(r_selected.sum()),
                shared_selected=int((platform_selected & r_selected).sum()),
                metrics={field: compare_values(rows, field, bounds) for field, bounds in protocol['limits'].items()})


def reciprocal(rows):
    directions = {}
    for name, subset in rows.groupby('contrast_id'):
        directions[tuple(subset[LABELS].iloc[0])] = (name, subset.set_index('feature_id'))
    results = []
    for direction, (name, forward) in directions.items():
        reverse = directions.get(direction[::-1])
        if reverse is None or name >= reverse[0]:
            continue
        backward = reverse[1].loc[forward.index]
        errors = {}
        for field in (EFFECT, 'wald_statistic', P_FIELD, Q_WITHIN, Q_FAMILY, 'original_method_adjustment'):
            sign = -1 if field in (EFFECT, 'wald_statistic') else 1
            errors[field] = bool(np.allclose(forward[field], sign * backward[field], atol=1e-10, rtol=1e-10, equal_nan=True))
        results.append(dict(forward=name, reverse=reverse[0], **errors))
    return results


def reconcile(platform, reference, spec_path, protocol_path, output):
    protocol = json.loads(protocol_path.read_text(encoding='utf-8'))
    spec = json.loads(spec_path.read_text(encoding='utf-8-sig'))
    assert sha256(protocol_path) == spec['protocol_sha256'], 'Protocol changed after the input was frozen'
    reference_model = audit_reference_provenance(reference, spec_path, spec)
    actual = table(platform / 'comparison_results.tsv', protocol['limits'])
    expected = table(reference / 'comparison_results.tsv', [*protocol['limits'], 'p_without_cooks', 'dispersion'])
    audit = dict(platform=audit_bh(actual, predeclared=True), r_finite_p=audit_bh(expected, predeclared=False))
    r_reciprocal = reciprocal(expected)
    for column, adjusted in bh_columns(expected, predeclared=True).items():
        expected[column + '_r_finite_p'] = expected[column]
        expected[column] = adjusted
    rows = actual.merge(expected, on=KEYS, how='outer', suffixes=('_platform', '_r'), validate='one_to_one', indicator=True)
    assert rows['_merge'].eq('both').all(), 'Comparison/feature axis differs'
    planned = {item['id']: (item['numerator'], item['denominator']) for item in spec['contrasts']}
    assert set(rows['contrast_id']) == set(planned)
    design, factors = audit_design(platform, reference, reference_model, protocol)
    model_counts, frozen_features = audit_counts(platform, spec_path, spec, factors)
    for key, group in rows.groupby('contrast_id'):
        assert len(group) == len(frozen_features) and set(group['feature_id']) == frozen_features, (
            f'Comparison {key} does not cover the frozen feature axis'
        )
        for label, frozen in zip(LABELS, planned[key], strict=True):
            assert group[label + '_platform'].eq(frozen).all() and group[label + '_r'].eq(frozen).all(), (key, label)
    assert rows['tested_platform'].str.upper().eq(rows['tested_r']).all(), 'Pre-filtered feature membership differs'
    excluded = rows['tested_r'].eq('FALSE')
    assert rows.loc[excluded, 'reason'].eq(rows.loc[excluded, 'exclusion_reason']).all(), 'Pre-filter reason differs'
    by_contrast = {}
    for key, group in rows.groupby('contrast_id'):
        by_contrast[key] = compare_contrast(group.copy(), protocol)
    for field, bounds in protocol['limits'].items():
        compare_values(rows, field, bounds)
    summary = dict(design=design, model_counts=model_counts, by_contrast=by_contrast, bh=audit,
                   compared_bh_family='predeclared tests, missing attempted p values count as one',
                   reciprocal=dict(platform=reciprocal(actual), r=r_reciprocal),
                   platform_sha256=sha256(platform / 'comparison_results.tsv'), reference_sha256=sha256(reference / 'comparison_results.tsv'),
                   reference_diagnostics_sha256=sha256(reference / 'diagnostics.json'),
                   spec_sha256=sha256(spec_path), protocol_sha256=sha256(protocol_path))
    output.mkdir(parents=True, exist_ok=False)
    (output / 'summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    columns = KEYS + [name for name in rows.columns if name != '_merge' and name not in KEYS]
    rows[columns].to_csv(output / 'full-differences.tsv.gz', sep='\t', index=False, na_rep='NA',
                         compression={'method': 'gzip', 'mtime': 0, 'compresslevel': 4})
    factors.to_csv(output / 'size-factor-differences.tsv', sep='\t', index=False)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('platform', 'reference', 'spec', 'output'):
        parser.add_argument(name, type=Path)
    parser.add_argument('--protocol', type=Path, default=Path(__file__).with_name('bulk_b08_reference_protocol.json'))
    args = parser.parse_args()
    report = reconcile(args.platform, args.reference, args.spec, args.protocol, args.output)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
