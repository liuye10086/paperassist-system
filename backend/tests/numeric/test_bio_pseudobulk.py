import copy
import numpy as np
import pandas as pd
import pytest
from app.adapters.bio_engine.manifest import Writer
from bio_insights_fixtures import source, config, payload, rows
from test_bio_comparison import execute


def donor_fixture(tmp_path, paired=False):
    rng = np.random.default_rng(82)
    count = 12 if not paired else 12
    matrix = rng.negative_binomial(10,.35,size=(count,80)).astype('int64') + 1
    matrix[6:,:8] *= 4; matrix[:,79] = 0
    donors = [f'd{i//2}' for i in range(12)] if not paired else [f'd{i//2%3}' for i in range(12)]
    conditions = ['A']*6+['B']*6
    s = source(tmp_path,matrix,donors=donors,conditions=conditions)
    cfg=config(12,mode='donor_paired' if paired else 'donor_unpaired')
    return matrix,s,cfg


@pytest.mark.parametrize('paired',[False,True])
def test_raw_gene_pseudobulk_matches_direct_pydeseq2(tmp_path,paired):
    from pydeseq2.dds import DeseqDataSet
    from pydeseq2.ds import DeseqStats
    from pydeseq2.default_inference import DefaultInference
    matrix,s,cfg=donor_fixture(tmp_path,paired)
    result,w=execute(tmp_path,payload(cfg,[s]),'out')
    got=rows(w)
    assert len(got)==80 and next(r for r in got if r['feature_id']=='g79')['reason']=='minimum_total_counts'
    aggregation=rows(w,'aggregation_units');assert len(aggregation)==6
    pb=matrix.reshape(6,2,80).sum(1)
    frame=pd.DataFrame(pb[:,:79],index=[r['unit_id'] for r in aggregation],columns=[f'g{i}' for i in range(79)])
    metadata=pd.DataFrame({'condition':[r['condition'] for r in aggregation],
                           'donor':[r['donor'] for r in aggregation]},index=frame.index)
    # Independent direct library invocation on independently aggregated fixture.
    infer=DefaultInference(n_cpus=1)
    dds=DeseqDataSet(counts=frame,metadata=metadata,design='~ donor + condition' if paired else '~ condition',
                     size_factors_fit_type='poscounts',refit_cooks=False,low_memory=True,
                     n_cpus=1,inference=infer,quiet=True)
    dds.deseq2();stats=DeseqStats(dds,contrast=['condition','B','A'],cooks_filter=True,
                                independent_filter=False,n_cpus=1,inference=infer,quiet=True)
    stats.summary()
    for row in [r for r in got if r['feature_id']!='g79']:
        expected=stats.results_df.loc[row['feature_id']]
        assert float(row['effect_value'])==pytest.approx(expected['log2FoldChange'],abs=1e-8)
        if np.isfinite(expected['pvalue']):assert float(row['p_value'])==pytest.approx(expected['pvalue'],abs=1e-10)
    assert result['inference_scope']=='donor_inference'
    assert result['summary']['actual_units'][0]['n_numerator']==3
    assert len(rows(w,'aggregation_members'))==12


def test_raw_gene_axis_survives_processed_feature_filter_and_direction_swap(tmp_path):
    import hashlib
    matrix,s,cfg=donor_fixture(tmp_path)
    member=s['members']['feature_mask'];mask=np.zeros(80,dtype=bool);mask[:2]=True;np.save(member['path'],mask)
    member['sha256']=hashlib.sha256(open(member['path'],'rb').read()).hexdigest()
    _,w=execute(tmp_path,payload(cfg,[s]),'forward')
    reverse=copy.deepcopy(cfg);c=reverse['contrasts'][0];c['numerator'],c['denominator']=c['denominator'],c['numerator']
    _,rw=execute(tmp_path,payload(reverse,[s]),'reverse')
    forward={r['feature_id']:r for r in rows(w)};backward={r['feature_id']:r for r in rows(rw)}
    assert len(forward)==80
    for feature,row in forward.items():
        if row['p_value']:
            assert float(backward[feature]['effect_value'])==pytest.approx(-float(row['effect_value']),abs=1e-8)
            assert float(backward[feature]['p_value'])==pytest.approx(float(row['p_value']),abs=1e-10)


def test_unpaired_crossed_batch_is_kept_in_actual_formula(tmp_path):
    matrix,s,cfg=donor_fixture(tmp_path);cfg['batch_adjustment']=True
    for i,row in enumerate(s['metadata']['observations']):row['batch']='x' if i//2%2==0 else 'y'
    result,w=execute(tmp_path,payload(cfg,[s]),'batch')
    diagnostic=result['methods']['model_diagnostics'][0]
    assert diagnostic['formula']=='~ batch + condition' and diagnostic['rank']==3
    assert result['summary']['actual_units'][0]['design_rank']==3


def test_explicit_incomplete_donor_exclusion_is_recorded_without_adding_replicates(tmp_path):
    matrix,s,cfg=donor_fixture(tmp_path,paired=True)
    s['metadata']['observations'][0]['donor']='incomplete'
    cfg['excluded_donors']=[{'donor':'incomplete','reason':'explicit synthetic missing pair exclusion'}]
    result,w=execute(tmp_path,payload(cfg,[s]),'exclude')
    assert result['summary']['actual_units'][0]['complete_pairs']==3
    assert len(rows(w,'aggregation_members'))==11
    assert rows(w,'observation_exclusions')[0]['reason']=='explicit synthetic missing pair exclusion'


@pytest.mark.parametrize('problem',['zero_library','confounded','missing_pair','fractional','no_features'])
def test_invalid_actual_counts_and_design_are_blocked(tmp_path,problem):
    matrix,s,cfg=donor_fixture(tmp_path,paired=problem=='missing_pair')
    if problem=='zero_library':
        matrix[:2]=0
        s=source(tmp_path,matrix,source_id='other',donors=[f'd{i//2}' for i in range(12)],conditions=['A']*6+['B']*6)
        cfg=config(12,mode='donor_unpaired',source_id='other')
    elif problem=='confounded':
        cfg['batch_adjustment']=True
        for row in s['metadata']['observations']:row['batch']=row['condition']
    elif problem=='missing_pair':s['metadata']['observations'][0]['donor']='unpaired'
    elif problem=='fractional':
        s=source(tmp_path,matrix.astype(float)+.5,source_id='float',donors=[f'd{i//2}' for i in range(12)],conditions=['A']*6+['B']*6)
        cfg=config(12,mode='donor_unpaired',source_id='float')
    else:cfg['minimum_total_counts']=1000000
    with pytest.raises(ValueError):execute(tmp_path,payload(cfg,[s]),'bad')
