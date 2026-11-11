"""Versioned bulk counts core. The existing spatial poscounts model is unchanged."""
import warnings
import numpy as np
import pandas as pd
from app.domain.bioinformatics.settings import BioLimits
from .comparison import _identity


def frozen_parameters(config):
    return dict(size_factors_fit_type=config.size_factor_method,fit_type='parametric',refit_cooks=False,cooks_filter=True,independent_filter=True,alpha=.05,
        lfc_null=0.,alt_hypothesis=None,prior_LFC_var=None,lfc_shrinkage=False,min_mu=.5,min_disp=1e-8,max_disp=10.,min_replicates=7,beta_tol=1e-8,low_memory=False,n_cpus=1,minimum_total_counts=config.minimum_total_counts)


def _check_counts(matrix):
    limits = BioLimits()
    if matrix.size > limits.max_bulk_matrix_cells or len(matrix) > limits.max_bulk_observations:
        raise ValueError('bulk_model_budget')
    if matrix.dtype != np.dtype('int64') or np.any(matrix < 0) or sum(map(int, matrix.ravel())) > np.iinfo(np.int64).max:
        raise ValueError('raw_counts_invalid')


def reviewed_filter(matrix, rules):
    total = matrix.sum(0) >= rules['minimum_total_counts']
    expressed = (matrix >= rules['minimum_sample_counts']).sum(0) >= rules['minimum_expressing_samples']
    return total & expressed, np.where(~total, 'minimum_total_counts', 'minimum_sample_counts')


def _fit(matrix, tested, features, ids, metadata, design, contrasts, config):
    from pydeseq2.dds import DeseqDataSet
    from pydeseq2.ds import DeseqStats
    from pydeseq2.default_inference import DefaultInference

    frame = pd.DataFrame(matrix[:, tested], index=ids, columns=np.asarray(features)[tested])
    if frame.empty or np.any(matrix[:, tested].sum(1) == 0):
        raise ValueError('no_testable_features_or_zero_library')
    if config.size_factor_method == 'ratio' and not (frame.to_numpy() > 0).all(0).any():
        raise ValueError('ratio_no_positive_features')
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate_model_sample')
    inference = DefaultInference(n_cpus=1)
    results = {}
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter('always')
        dds = DeseqDataSet(counts=frame, metadata=metadata, design=design, fit_type='parametric',
            size_factors_fit_type=config.size_factor_method, refit_cooks=False, low_memory=False, n_cpus=1,
            inference=inference, quiet=True, min_mu=.5, min_disp=1e-8, max_disp=10., min_replicates=7, beta_tol=1e-8)
        design_frame = dds.obsm['design_matrix']
        design_array = np.asarray(design_frame, dtype=float)
        rank = int(np.linalg.matrix_rank(design_array))
        if rank != design_array.shape[1] or len(matrix) - rank <= 0:
            raise ValueError('actual_design_rank_invalid')
        dds.deseq2()
        for cid, contrast in contrasts.items():
            stats = DeseqStats(dds, contrast=contrast, alpha=.05, cooks_filter=True,
                independent_filter=True, lfc_null=0., alt_hypothesis=None, prior_LFC_var=None,
                n_cpus=1, inference=inference, quiet=True)
            stats.summary()
            results[cid] = stats.results_df
    factors = np.asarray(dds.obs['size_factors'], dtype=float)
    if factors.shape != (len(matrix),) or not np.isfinite(factors).all() or np.any(factors <= 0):
        raise ValueError('size_factors_invalid')
    messages = [str(item.message) for item in captured]
    diagnostics = dict(rank=rank, residual_degrees_freedom=len(matrix)-rank, parameters=frozen_parameters(config),
        design_columns=list(design_frame.columns), design_matrix=design_array.tolist(), sample_unit_ids=ids,
        warnings=messages, fit_type_requested='parametric',
        fit_type_effective='mean' if any('mean-based' in message for message in messages) else 'parametric')
    return dds, results, factors, diagnostics


def _feature_rows(dds, results, cid, features, tested, exclusion_reasons=None):
    output = []
    convergence = []
    flags = ('_LFC_converged', '_genewise_converged', '_MAP_converged')
    fit_fields = {flag: dds.var[flag] for flag in flags if flag in dds.var}
    cooks = dds.var.get('_pvalue_cooks_outlier')
    for index, feature in enumerate(features):
        tested_feature = bool(tested[index])
        row = dict(effect_name='effect_log2fc', effect_value=None, effect_unit='log2 count fold change',
            effect_reason='not_computable', base_mean=None, lfc_se=None, statistic=None, wald_statistic=None,
            p_value=None, original_method_adjustment=None, tested=tested_feature,
            test_status='not_computable' if tested_feature else 'excluded',
            reason=None if tested_feature else str(exclusion_reasons[index]) if exclusion_reasons is not None else 'minimum_total_counts',
            p_value_underflow=False)
        diagnostic = dict(contrast_id=cid, feature_id=feature, tested=tested_feature, **dict.fromkeys(flags))
        if tested_feature:
            observed = results.loc[feature]
            for field, series in fit_fields.items():
                value = series.at[feature]
                diagnostic[field] = None if pd.isna(value) else bool(value)
            failures = [flag for flag in flags if diagnostic[flag] is False]
            for out, col in [('base_mean','baseMean'),('effect_value','log2FoldChange'),('lfc_se','lfcSE'),
                             ('statistic','stat'),('wald_statistic','stat'),('p_value','pvalue'),('original_method_adjustment','padj')]:
                value = observed[col]
                row[out] = float(value) if np.isfinite(value) else None
            if failures:
                row.update(test_status='not_computable', reason='model_not_converged:'+','.join(failures),
                    effect_value=None, p_value=None, statistic=None, wald_statistic=None, original_method_adjustment=None)
            elif row['p_value'] is None:
                reason = 'cooks_filtered_or_undefined_wald'
                if exclusion_reasons is not None and cooks is not None:
                    reason = 'cooks_filtered' if bool(cooks.at[feature]) else 'undefined_wald'
                row.update(reason=reason)
            else:
                row.update(test_status='tested', effect_reason=None, p_value_underflow=row['p_value']==0)
        if exclusion_reasons is not None:
            row['original_adjustment_reason'] = None if row['original_method_adjustment'] is not None else (
                row['reason'] or 'independent_filtered_or_undefined_adjustment')
        convergence.append(diagnostic)
        output.append(row)
    return output, convergence


def _size_factors(samples, factors, config, *, model_id=None):
    key = {'model_id': model_id} if model_id else {}
    return [dict(key or {'contrast_id': row['contrast_id']}, unit_id=row['unit_id'],
        processed_version_id=row['processed_version_id'], sample_id=row['sample_id'], factor=float(factor),
        method=config.size_factor_method) for row, factor in zip(samples, factors)]


def fit_counts(values, features, contrast, groups, group_keys, by_key, config):
    """Legacy V2 model fitted independently for each contrast."""
    cid = contrast.contrast_id
    ordered = [(key, index, contrast.groups[side].label) for side in (1, 0)
               for key, index in zip(group_keys[side], groups[side])]
    matrix = np.asarray(values[[index for _, index, _ in ordered]])
    _check_counts(matrix)
    tested = matrix.sum(0) >= config.minimum_total_counts
    ids = ['s'+_identity(key)[:24] for key, _, _ in ordered]
    samples = [dict(contrast_id=cid, unit_id=uid, processed_version_id=key[0], sample_id=key[1], condition=label,
                    donor=by_key[key].get(config.pairing_field) or '', batch=by_key[key].get('batch') or '',
                    biological_unit_id=by_key[key].get('biological_unit_id') or by_key[key].get('donor') or '')
               for uid, (key, _, label) in zip(ids, ordered)]
    metadata = pd.DataFrame(samples, index=ids)
    metadata['condition'] = pd.Categorical(metadata['condition'], categories=[contrast.groups[1].label, contrast.groups[0].label])
    formula = '~ donor + condition' if config.design == 'paired' else '~ batch + condition' if config.batch_adjustment else '~ condition'
    dds, results, factors, diagnostics = _fit(matrix, tested, features, ids, metadata, formula,
        {cid: ['condition', contrast.groups[0].label, contrast.groups[1].label]}, config)
    output, convergence = _feature_rows(dds, results[cid], cid, features, tested)
    normalized = matrix / factors[:, None]
    if not np.isfinite(normalized).all():
        raise ValueError('normalized_counts_nonfinite')
    return output, dict(diagnostics=dict(contrast_id=cid, formula=formula, **diagnostics),
        model_sample_metadata=samples, model_convergence=convergence, size_factors=_size_factors(samples, factors, config),
        model_counts=[dict(contrast_id=cid, unit_id=uid, feature_id=feature, counts=int(matrix[i,j]), tested=bool(tested[j]))
                      for i, uid in enumerate(ids) for j, feature in enumerate(features)],
        model_normalized_counts=[dict(contrast_id=cid, unit_id=uid, feature_id=feature, normalized_counts=float(normalized[i,j]))
                                 for i, uid in enumerate(ids) for j, feature in enumerate(features)])


BULK_FIT_ID = 'bulk_model_1'


def fit_reviewed_counts(values, features, index, model, config):
    """Fit the reviewed sample cohort once and evaluate its frozen contrasts."""
    from app.domain.bio_insights.bulk_model_design import contrast_vectors

    keys = [(row['processed_version_id'], row['sample_id']) for row in model['samples']]
    ids = ['s'+_identity(key)[:24] for key in keys]
    matrix = np.asarray(values[[index[key] for key in keys]])
    _check_counts(matrix)
    tested, exclusion_reasons = reviewed_filter(matrix, model['filter'])
    samples = [dict(model_id=BULK_FIT_ID, unit_id=uid, **row) for uid, row in zip(ids, model['samples'])]
    design = pd.DataFrame(model['design_matrix'], index=ids, columns=model['design_columns'], dtype=float)
    vectors = contrast_vectors(model)
    contrasts = {cid: np.asarray(vector, dtype=float) for cid, vector in vectors.items()}
    dds, results, factors, diagnostics = _fit(matrix, tested, features, ids, pd.DataFrame(index=ids), design, contrasts, config)
    fitted = {}
    convergence = []
    for cid, result in results.items():
        fitted[cid], flags = _feature_rows(dds, result, cid, features, tested, exclusion_reasons)
        convergence.extend(flags)
    normalized = matrix / factors[:, None]
    if not np.isfinite(normalized).all():
        raise ValueError('normalized_counts_nonfinite')
    diagnostics.update(model_id=BULK_FIT_ID, method=config.bulk_model, formula=model['formula'],
        terms=model['terms'], condition_reference=model['condition_reference'], contrast_ids=list(contrasts),
        contrast_vectors=vectors, filter=model['filter'],
        eligible_features=len(features), tested_features=int(tested.sum()))
    return fitted, dict(diagnostics=diagnostics, model_sample_metadata=samples, model_convergence=convergence,
        size_factors=_size_factors(samples, factors, config, model_id=BULK_FIT_ID),
        model_counts=matrix, model_normalized_counts=normalized)
