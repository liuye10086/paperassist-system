"""D-ratio-no-refit-v1; thresholds frozen before observing this implementation."""
import csv
import hashlib
import json
import importlib.util
import os
from pathlib import Path
import numpy as np
import pytest


@pytest.fixture(autouse=True)
def postgres_schema():yield None


def test_sample_counts_core_exists_separately_from_spatial_poscounts():
    assert importlib.util.find_spec('app.adapters.bio_insights_engine.counts_model') is not None


@pytest.mark.parametrize('shared', [False, True], ids=['legacy','reviewed'])
def test_counts_against_fixed_r_outputs_all_genes_and_samples(shared):
    if importlib.util.find_spec('pydeseq2') is None:pytest.skip('fixed Linux scientific interpreter required; not a passing numerical comparison')
    from app.adapters.bio_insights_engine.counts_model import fit_counts, fit_reviewed_counts
    from app.domain.bio_insights.quantitative_contracts import QuantitativeComparisonConfig
    from app.domain.bio_insights.quantitative_design import validate_quantitative_design
    import pandas as pd
    references=Path(os.environ['B05_REFERENCE_ROOT']) if os.environ.get('B05_REFERENCE_ROOT') else Path(__file__).resolve().parents[3]/'script/.runtime/client-requirements-b05/references'
    root=references/'PyDESeq2/original'
    counts=pd.read_csv(root/'datasets/synthetic/test_counts.csv',index_col=0)
    metadata=pd.read_csv(root/'datasets/synthetic/test_metadata.csv',index_col=0)
    # Source is samples x genes in the upstream fixed file; explicitly bind IDs.
    if len(counts.index)==10:counts=counts.T
    metadata=metadata.loc[counts.index]
    assert counts.shape==(100,10) and set(metadata.condition)=={'A','B'}
    keys=[('fixed_d',s) for s in counts.index]
    by_key={k:dict(processed_version_id=k[0],sample_id=k[1],condition=metadata.loc[k[1],'condition'],biological_unit_id=k[1],pair_id='',donor='',batch='') for k in keys}
    groups=[[i for i,k in enumerate(keys) if by_key[k]['condition']==g] for g in ('B','A')]
    cfg=QuantitativeComparisonConfig(mode='bulk_counts',design='independent',method='deseq2_wald',analysis_layer='raw_counts',
        contrasts=[dict(contrast_id='B_A',name='B/A',groups=[dict(label=g,sample_keys=[dict(processed_version_id=keys[i][0],sample_id=keys[i][1]) for i in indices]) for g,indices in zip(('B','A'),groups)])],
        family_contrast_ids=['B_A'],inference_unit='biological',inference_goal='inference',independence_confirmed=True,
        independence_basis='Synthetic units solely for offline numeric benchmark; no biological donor claim',design_basis='D-ratio-no-refit-v1',
        data_driven_grouping=False,namespace='synthetic_gene',reference_version='4426e4db990db1c511de3b1b9b7a514989663dad')
    matrix=counts.to_numpy(dtype='int64');features=counts.columns.tolist()
    if shared:
        cfg=QuantitativeComparisonConfig.model_validate({**cfg.model_dump(), 'bulk_model':'shared_wald_v1'})
        preview=validate_quantitative_design(cfg,[dict(source_kind='bio_processed_dataset_version',
            metadata=dict(canonical_dataset_id='fixed',observation_level='sample',assay='bulk_rna_counts',
            namespace=cfg.namespace,reference_version=cfg.reference_version,feature_ids=features,
            observations=[{**row,'retained':True} for row in by_key.values()]))])
        assert preview.executable,preview.blocking_reasons
        fitted,model=fit_reviewed_counts(matrix,features,{key:i for i,key in enumerate(keys)},preview.bulk_model,cfg)
        rows=fitted['B_A']
    else:
        rows,model=fit_counts(matrix,features,cfg.contrasts[0],groups,[[keys[i] for i in group] for group in groups],by_key,cfg)
    reference=pd.read_csv(root/'tests/data/single_factor/r_test_res.csv',index_col=0)
    sf=pd.read_csv(root/'tests/data/single_factor/r_test_size_factors.csv',index_col=0)
    for name,expected_sha in [('r_test_res.csv','e22bd2a8b3bcf4e40d23a771ddc944808fcf0e09f6b5a395e8b45c41c325f5de'),('r_test_size_factors.csv','cafc275fba97f8123f288f048fc1ebdf1d6a7a38e68d2a2cb17085abed30d742')]:
        assert hashlib.sha256((root/'tests/data/single_factor'/name).read_bytes()).hexdigest()==expected_sha
    if not shared and os.environ.get('B05_NUMERIC_OUTPUT'):
        dest=Path(os.environ['B05_NUMERIC_OUTPUT']);dest.mkdir(parents=True,exist_ok=False)
        pd.DataFrame(rows,index=counts.columns).to_csv(dest/'actual-results.csv',index_label='feature_id')
        pd.DataFrame(model['size_factors']).to_csv(dest/'actual-size-factors.csv',index=False)
        pd.DataFrame(model['model_counts']).to_csv(dest/'actual-input-counts.csv',index=False)
        pd.DataFrame(model['model_convergence']).to_csv(dest/'actual-convergence.csv',index=False)
        (dest/'actual-model-diagnostics.json').write_text(json.dumps(model['diagnostics'],indent=2),encoding='utf-8')
    assert len(rows)==10 and len(model['size_factors'])==100
    actual_sf={r['sample_id']:r['factor'] for r in model['size_factors']}
    assert set(actual_sf)==set(sf.index)
    for sid,value in sf.iloc[:,0].items():assert np.isfinite(actual_sf[sid]) and actual_sf[sid]>0 and abs(actual_sf[sid]-value)<=1e-6
    actual=pd.DataFrame(rows,index=counts.columns)
    mapping={'baseMean':'base_mean','log2FoldChange':'effect_value','lfcSE':'lfc_se','stat':'statistic','pvalue':'p_value','padj':'original_method_adjustment'}
    assert set(actual.index)==set(reference.index)
    for ref,col in mapping.items():
        expected=reference.loc[actual.index,ref].to_numpy();observed=actual[col].to_numpy(dtype=float)
        assert np.array_equal(np.isnan(expected),np.isnan(observed)) and np.isfinite(observed).all()
        if ref=='baseMean':assert np.all(abs(observed-expected)<=1e-6+1e-6*abs(expected))
        else:assert np.all(abs(observed-expected)/abs(expected)<.02),(ref,(abs(observed-expected)/abs(expected)).tolist())
    assert np.array_equal(np.sign(actual.effect_value),np.sign(reference.loc[actual.index,'log2FoldChange']))
    assert actual.statistic.tolist()==actual.wald_statistic.tolist()
    assert all(r['test_status']=='tested' for r in rows)
    assert model['diagnostics']['rank']==2 and model['diagnostics']['residual_degrees_freedom']==98
    assert model['diagnostics']['fit_type_effective']=='parametric'
    from app.adapters.bio_insights_engine.comparison import adjust_families
    for row in rows:row['contrast_id']='B_A'
    adjust_families(rows,['B_A'])
    for col in ('q_within_contrast','q_global_family'):
        expected=reference.loc[actual.index,'padj'].to_numpy();observed=np.array([r[col] for r in rows])
        assert np.all(abs(observed-expected)/abs(expected)<.02)
