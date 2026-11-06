"""Same locked GSEA permutation family without retaining every Python curve."""
import json
import numpy as np
import pandas as pd
import pytest
import gseapy
from bio_insights_fixtures import rows
from test_bio_gsea import setup
from test_bio_ora import execute,resource_source

@pytest.fixture(autouse=True)
def postgres_schema():yield None


def test_numeric_gsea_avoids_high_level_all_curve_dataframe_materialization(tmp_path,monkeypatch):
    source,resource,cfg=setup(tmp_path)
    def retaining_all_curves(*args,**kwargs):
        raise AssertionError('high_level_prerank_retains_all_python_running_curves')
    monkeypatch.setattr(gseapy,'prerank',retaining_all_curves)
    result,writer=execute(tmp_path,cfg,[source,resource])
    assert len(rows(writer,'enrichment_results'))==2
    assert result['methods']['native_entrypoint']=='gseapy.gse.prerank_rs'
    assert result['methods']['threads']==1


@pytest.mark.parametrize('reverse',[False,True])
def test_streamed_native_summaries_match_original_high_level_joint_null(tmp_path,reverse):
    scores=[5.,5.,4.,3.,2.,1.,0.,-1.,-2.,-3.,-4.,-5.,-6.,-7.,-8.,-9.,-10.,-11.,-12.,-13.]
    if reverse:scores=[-v for v in scores]
    source,_,cfg=setup(tmp_path,statistics=scores)
    terms=[dict(term_id='positive',name='positive',namespace='fixture',genes=[f'g{i}' for i in range(5)]),
        dict(term_id='negative',name='negative',namespace='fixture',genes=[f'g{i}' for i in range(15,20)]),
        dict(term_id='overlap',name='overlap',namespace='fixture',genes=[f'g{i}' for i in range(3,10)]),
        dict(term_id='tie_split',name='tie split',namespace='fixture',genes=['g15','g0','g10','g5'])]
    resource=resource_source(tmp_path,sid='joint',terms=terms);cfg['resource_source_ids']=['joint'];cfg['permutation_num']=1000
    result,writer=execute(tmp_path,cfg,[source,resource]);ranking=rows(writer,'gsea_ranking')
    expected=gseapy.prerank(rnk=pd.Series([float(r['statistic']) for r in ranking],index=[r['feature_id'] for r in ranking]),
        gene_sets={'joint::'+t['term_id']:t['genes'] for t in terms},method='permutation',permutation_num=1000,
        weight=1.,min_size=2,max_size=10,threads=1,seed=0,ascending=None,no_plot=True,outdir=None,verbose=False)
    assert expected.ranking.index.tolist()==[r['feature_id'] for r in ranking]
    np.testing.assert_array_equal(expected.ranking.to_numpy(),[float(r['statistic']) for r in ranking])
    assert [(r['feature_id'],float(r['statistic'])) for r in ranking]==sorted([(f'g{i}',v) for i,v in enumerate(scores)],key=lambda r:(-r[1],r[0]))
    for row in rows(writer,'enrichment_results'):
        original=expected.results[row['collection_term_id']]
        for actual,key in [('es','es'),('nes','nes'),('nominal_p_value','pval'),('fdr_q_value','fdr'),('fwer_p_value','fwerp')]:
            assert float(row[actual])==pytest.approx(original[key],rel=1e-12,abs=1e-14)
        assert json.loads(row['hit_indices'])==list(original['hits'])
        assert set(json.loads(row['leading_edge']))==set(original['lead_genes'].split(';'))
    assert result['summary']['eligible_set_count']==4
