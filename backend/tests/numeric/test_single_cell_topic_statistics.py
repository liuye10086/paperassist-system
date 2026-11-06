import numpy as np
import pytest
from scipy import sparse,stats
from app.adapters.bio_insights_engine.single_cell_topics import symbol_expression,communication_comparison
from app.domain.bio_insights.single_cell_topic_contracts import SingleCellTopicConfig

@pytest.fixture(autouse=True)
def postgres_schema():yield None

def test_duplicate_symbols_use_full_raw_library_denominator():
    counts=sparse.csr_matrix([[2,3,5],[0,4,6]])
    result,genes,matching=symbol_expression(counts,['g1','g2','other'],{'g1':'MIF','g2':'MIF','other':'OTHER'},['MIF','CD74'])
    assert genes==['MIF'] and matching['duplicate_symbols_aggregated']==1
    np.testing.assert_allclose(result.toarray().ravel(),np.log1p([5000,4000]))
    assert matching['missing_resource_symbols']==['CD74']

def fixture():
    cfg=SingleCellTopicConfig(method='cellchat',processed_source_id='p',annotation_source_id='a',label_ids=['T','B'],condition_values=['ctrl','stim'],communication_mode='paired')
    units=[];rows=[]
    for i,(a,b) in enumerate(zip([.01,.02,.03,.04],[.02,.04,.04,.08])):
        for condition,v in [('ctrl',a),('stim',b)]:
            uid=f'd{i}_{condition}';units.append(dict(unit_id=uid,donor=f'd{i}',condition=condition))
            rows.append(dict(unit_id=uid,sender='T',receiver='B',interaction_id='MIF',status='computed',probability=v))
    return cfg,units,rows

def test_donor_comparison_matches_paired_donor_test_not_cell_pvalues():
    cfg,units,rows=fixture();result=communication_comparison(list(reversed(rows)),units,cfg)[0]
    expected=stats.ttest_rel([.02,.04,.04,.08],[.01,.02,.03,.04])
    assert result['complete_pairs']==4 and result['n_denominator']==4
    assert result['donor_p_value']==pytest.approx(expected.pvalue)
    assert result['donor_q_value']==pytest.approx(expected.pvalue)

def test_uncomputed_units_are_excluded_not_replaced_by_zero():
    cfg,units,rows=fixture()
    for row in rows:
        if row['unit_id'] in ('d0_ctrl','d1_stim'):row.update(status='not_computable',probability=None)
    result=communication_comparison(rows,units,cfg)[0]
    assert result['complete_pairs']==2 and result['donor_p_value'] is None
    assert result['reason']=='insufficient_computable_donors'

def test_no_variance_keeps_na_and_descriptive_mode_has_no_tests():
    cfg,units,rows=fixture()
    for row in rows:row['probability']=0.
    result=communication_comparison(rows,units,cfg)[0]
    assert result['difference']==0 and result['donor_p_value'] is None
    assert result['reason']=='no_estimable_variance'
    assert communication_comparison(rows,units,cfg.model_copy(update={'communication_mode':'per_donor'}))==[]


def test_entirely_uncomputable_predeclared_edge_remains_in_family():
    cfg,units,rows=fixture()
    for row in rows:row.update(status='not_computable',probability=None)
    result=communication_comparison(rows,units,cfg)
    assert len(result)==1 and result[0]['interaction_id']=='MIF'
    assert result[0]['n_denominator']==0 and result[0]['donor_p_value'] is None
    assert result[0]['status']=='not_computable'
