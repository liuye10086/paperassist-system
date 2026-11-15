"""Reusable native report fixtures: real lifecycle, synthetic numeric estimator only."""
from types import SimpleNamespace


def published_bulk(client, monkeypatch, tmp_path):
    import numpy as np
    import pandas as pd
    from app.adapters.bio_insights_engine import counts_model
    from app.adapters.bio_insights_engine.pipeline import run as pipeline
    from app.domain.bio_insights.execution import run_bio_insight_task
    from app.domain.bio_insights.service import BioInsightsService
    from tests.api.test_bio_quantitative_lifecycle import processed_fixture
    from tests.api.test_bio_insight_reproducibility import fixed_fixture_runtime

    base, processed = processed_fixture(client, monkeypatch, tmp_path, assay='bulk_rna_counts')
    runtime = fixed_fixture_runtime(monkeypatch)
    monkeypatch.setattr(BioInsightsService, '_runtime_for', lambda self, config: runtime)
    def estimator(matrix, tested, features, ids, metadata, design, contrasts, config):
        from scipy.special import ndtr
        selected = np.asarray(features)[tested]
        # Only the fitted coefficient is synthetic. Normalization, base means
        # and the Wald relationship must satisfy the real output validator.
        fit = matrix[:, tested].astype(float)
        if config.size_factor_method == 'ratio':
            logs = np.log(fit[:, (fit > 0).all(0)])
            factors = np.exp(np.median(logs - logs.mean(0), axis=1))
        else:
            logs = np.zeros_like(fit)
            np.log(fit, out=logs, where=fit > 0)
            means = logs.mean(0)
            factors = np.array([np.exp(np.median(np.log(row[(means > 0) & (row > 0)])
                - means[(means > 0) & (row > 0)])) for row in fit])
            factors /= np.exp(np.log(factors).mean())
        means = (fit / factors[:, None]).mean(0)
        probability = float(2 * ndtr(-4.))
        rows = pd.DataFrame(dict(baseMean=means, log2FoldChange=[2.] * len(selected),
            lfcSE=[.5] * len(selected), stat=[4.] * len(selected),
            pvalue=[probability] * len(selected), padj=[probability] * len(selected)), index=selected)
        design_array = np.asarray(design, dtype=float)
        return SimpleNamespace(var=pd.DataFrame(index=selected)), {key: rows.copy() for key in contrasts}, factors, dict(
            rank=int(np.linalg.matrix_rank(design_array)), residual_degrees_freedom=len(ids)-design_array.shape[1],
            parameters=counts_model.frozen_parameters(config), design_columns=list(design.columns), design_matrix=design_array.tolist(),
            sample_unit_ids=ids, warnings=['Synthetic estimator for engineering verification only'], fit_type_requested='parametric', fit_type_effective='parametric')
    monkeypatch.setattr(counts_model, '_fit', estimator)
    source = client.get(base + '/bio-processed-datasets/' + processed).json()
    config = dict(schema_version=2, kind='comparison', mode='bulk_counts', design='independent', method='deseq2_wald',
        analysis_layer='raw_counts', bulk_model='shared_wald_v1', contrasts=[dict(contrast_id='B_A', name='B/A',
            groups=[dict(label=label, sample_keys=[dict(processed_version_id=processed, sample_id=f'{label}{i}') for i in range(3)]) for label in ('B', 'A')])],
        family_contrast_ids=['B_A'], namespace='ensembl', reference_version='fixed', data_driven_grouping=False,
        design_basis='Synthetic frozen design', independence_confirmed=True, independence_basis='Synthetic units',
        inference_goal='inference', inference_unit='biological')
    body = dict(name='Synthetic report comparison', kind='comparison', decision='draft', expected_revision=0,
        sources=[dict(source_kind='bio_processed_dataset_version', source_id=processed, sha256=source['manifest_sha256'], role='processed')], config=config)
    preview = client.post(base + '/bio-insight-plans/preview', json=body)
    assert preview.status_code == 200, preview.text
    confirmed = client.post(base + '/bio-insight-plans', json=body | {'decision': 'confirmed', 'reviewed_design_sha256': preview.json()['reviewed_design_sha256']},
                            headers={'Idempotency-Key': 'bulk-plan'})
    assert confirmed.status_code == 201, confirmed.text
    plan = confirmed.json()
    run = client.post(base + '/bio-insight-runs', json=dict(plan_version_id=plan['id'], expected_plan_revision=1, source_digest=plan['source_digest']),
                      headers={'Idempotency-Key': 'bulk-run'})
    assert run.status_code == 202, run.text
    result = run.json()
    done = run_bio_insight_task(result['task_id'], result['task_revision'], task_type='bio_comparison',
        engine=lambda payload, out: pipeline(payload | {'output_directory': str(out)}), staging_directory=tmp_path / 'bulk-stage')
    assert done['status'] == 'succeeded', done
    result = client.get(base + '/bio-insight-results/' + done['result_bio_insight_result_version_id'])
    assert result.status_code == 200, result.text
    return base, processed, result.json()
