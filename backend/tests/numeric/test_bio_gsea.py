import json
import numpy as np
import pandas as pd
import pytest
import gseapy
from bio_insights_fixtures import rows
from test_bio_ora import result_source,resource_source,execute


def setup(tmp_path, *, complete=True, statistics=None):
    statistics=list(np.arange(10,-10,-1,dtype=float)) if statistics is None else statistics
    source=result_source(tmp_path,complete=complete,statistics=statistics)
    terms=[{'term_id':'positive','name':'positive','namespace':'BP','genes':[f'g{i}' for i in range(5)]},
           {'term_id':'negative','name':'negative','namespace':'BP','genes':[f'g{i}' for i in range(15,20)]}]
    resource=resource_source(tmp_path,terms=terms)
    cfg={'kind':'gsea_prerank','result_source_id':'result1','resource_source_ids':['resource1'],
         'contrast_id':'c1','ranking_column':'statistic','min_size':2,'max_size':10,'permutation_num':100,'seed':0}
    return source,resource,cfg


def test_gsea_is_reproducible_and_matches_direct_locked_library(tmp_path):
    source,resource,cfg=setup(tmp_path)
    result,w=execute(tmp_path,cfg,[source,resource])
    _,again=execute(tmp_path,cfg,[source,resource],'again')
    actual=rows(w,'enrichment_results');assert actual==rows(again,'enrichment_results')
    ranking=rows(w,'gsea_ranking');series=pd.Series([float(r['statistic']) for r in ranking],index=[r['feature_id'] for r in ranking])
    sets={'resource1::positive':[f'g{i}' for i in range(5)],'resource1::negative':[f'g{i}' for i in range(15,20)]}
    direct=gseapy.prerank(rnk=series,gene_sets=sets,method='permutation',permutation_num=100,weight=1,
                          min_size=2,max_size=10,threads=1,seed=0,ascending=None,no_plot=True,outdir=None,verbose=False)
    for row in actual:
        expected=direct.results[row['collection_term_id']]
        assert float(row['es'])==pytest.approx(expected['es'],abs=1e-8)
        assert float(row['nes'])==pytest.approx(expected['nes'],abs=1e-8)
        assert float(row['fdr_q_value'])==pytest.approx(expected['fdr'],abs=1e-10)
        assert set(json.loads(row['leading_edge']))==set(expected['lead_genes'].split(';'))
        assert row['q_value']==''
    curves=json.loads(open(next(a['path'] for a in w.artifacts if a['key']=='gsea_curves')).read())
    assert all('ranking_values' not in curve and 'res' not in curve and curve['hit_indices'] for curve in curves['terms'])
    assert result['methods']['correction']=='GSEA_joint_null_FDR_not_BH'


@pytest.mark.parametrize('problem',['top','zero','unsigned','species'])
def test_invalid_ranking_and_species_are_blocked(tmp_path,problem):
    source,resource,cfg=setup(tmp_path,complete=problem!='top',statistics=[0.]*20 if problem=='zero' else None)
    if problem=='unsigned':cfg['ranking_column']='p_value'
    elif problem=='species':source['metadata']['species_taxon_id']=10090;source['metadata']['plan_config']['species_taxon_id']=10090
    with pytest.raises(ValueError):execute(tmp_path,cfg,[source,resource])


def test_mapping_many_to_one_rank_conflict_is_excluded_and_ties_are_stable(tmp_path):
    source,_,cfg=setup(tmp_path,statistics=[5.,5.,4.,3.,2.,1.,0.,-1.,-2.,-3.,-4.,-5.,-6.,-7.,-8.,-9.,-10.,-11.,-12.,-13.])
    data={f'g{i}':f's{i}' for i in range(20)};data.update(g0='collision',g1='collision')
    mapping=resource_source(tmp_path,sid='mapping',namespace='ensembl',mapping={'source_namespace':'ensembl','target_namespace':'symbol',
        'mapping':data,'ambiguous_source_ids':['g2'],'many_to_one_target_ids':['collision'],'strip_ensembl_version':False})
    resource=resource_source(tmp_path,sid='mapped_resource',namespace='symbol',terms=[{'term_id':'p','name':'positive','namespace':'BP','genes':['s3','s4','s5']},
             {'term_id':'n','name':'negative','namespace':'BP','genes':['s17','s18','s19']}])
    cfg['mapping_source_ids']=['mapping']
    cfg['resource_source_ids']=['mapped_resource']
    result,w=execute(tmp_path,cfg,[source,resource,mapping])
    excluded=rows(w,'mapping_exclusions')
    assert {r['feature_id'] for r in excluded if r['reason']=='many_to_one_ranking_conflict'}=={'g0','g1'}
    assert any(r['feature_id']=='g2' and r['reason']=='one_to_many_mapping' for r in excluded)
    assert result['summary']['ranking_size']==17


def test_tied_ranks_use_stable_id_and_simple_es_is_one(tmp_path):
    source,_,cfg=setup(tmp_path,statistics=[3.,3.,-1.,-2.])
    resource=resource_source(tmp_path,sid='simple_resource',terms=[{'term_id':'p','name':'p','namespace':'BP','genes':['g0','g1']}])
    cfg.update(min_size=1,max_size=3,resource_source_ids=['simple_resource'])
    result,w=execute(tmp_path,cfg,[source,resource])
    ranking=rows(w,'gsea_ranking')
    assert [r['feature_id'] for r in ranking[:2]]==['g0','g1']
    assert float(rows(w,'enrichment_results')[0]['es'])==pytest.approx(1)
    assert result['methods']['tied_rank_fraction']==pytest.approx(.25)


def test_duplicate_selected_resource_cannot_duplicate_hypotheses(tmp_path):
    source,resource,cfg=setup(tmp_path);cfg['resource_source_ids']=['resource1','resource1']
    with pytest.raises(ValueError,match='duplicate'):execute(tmp_path,cfg,[source,resource])


def test_zero_weight_gene_set_has_specific_compute_block(tmp_path):
    source,_,cfg=setup(tmp_path,statistics=[2.,1.,0.,0.,0.,-1.,-2.])
    resource=resource_source(tmp_path,sid='zero_weight',terms=[{'term_id':'zero','name':'zero','namespace':'BP','genes':['g2','g3']}])
    cfg.update(resource_source_ids=['zero_weight'],min_size=1,max_size=5)
    with pytest.raises(ValueError,match='zero_weight'):execute(tmp_path,cfg,[source,resource])
