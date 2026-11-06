"""Pinned original R APIs: numerical comparisons, never mocked."""
from pathlib import Path
from app.adapters.single_cell_r.bootstrap import preload_runtime_libraries
preload_runtime_libraries()
import numpy as np
import pytest
from scipy import sparse

def test_topics_bridge_exists():
    from app.adapters import single_cell_r
    assert Path(single_cell_r.__file__).with_name('topics.py').exists(), 'topics bridge missing'

@pytest.mark.skipif(not Path('/opt/paperassist-single-cell-r/lib/R').exists(), reason='pinned R runtime required')
@pytest.mark.parametrize('root',['root','left'])
def test_slingshot_original_axes_root_na(tmp_path,root):
    from app.adapters.single_cell_r.topics import initialize_topics
    bridge=initialize_topics(tmp_path,'slingshot');ro=bridge.ro
    rng=np.random.default_rng(23)
    x=np.vstack([rng.normal([0,0],.15,(18,2)),rng.normal([2,2],.15,(18,2)),rng.normal([2,-2],.15,(18,2))])
    cells=[f'c{i}' for i in range(len(x))];clusters=['root']*18+['left']*18+['right']*18
    result=bridge.slingshot(x,cells,clusters,root,23)
    assert result['status']=='completed',result
    ref=ro.r('''function(x,cells,labels,root) {set.seed(23); x<-matrix(x,ncol=2,byrow=TRUE,dimnames=list(cells,NULL)); s<-slingshot::slingshot(x,clusterLabels=labels,start.clus=root); list(pt=slingshot::slingPseudotime(s,na=TRUE),w=slingshot::slingCurveWeights(s),lineages=slingshot::slingLineages(s))}''')(ro.FloatVector(x.ravel()),ro.StrVector(cells),ro.StrVector(clusters),root)
    np.testing.assert_allclose(result['pseudotime'],np.asarray(ref.rx2('pt')),equal_nan=True)
    np.testing.assert_allclose(result['weights'],np.asarray(ref.rx2('w')))
    assert result['lineage_clusters']==[list(v) for v in ref.rx2('lineages')]
    assert all(v[0]==root for v in result['lineage_clusters'])
    if root=='root':assert np.isnan(result['pseudotime']).any()
    with pytest.raises(ValueError,match='root'):bridge.slingshot(x,cells,clusters,'missing',23)

@pytest.mark.skipif(not Path('/opt/paperassist-single-cell-r/lib/R').exists(), reason='pinned R runtime required')
def test_genie3_original_direction_seed_and_invalid(tmp_path):
    from app.adapters.single_cell_r.topics import initialize_topics
    bridge=initialize_topics(tmp_path,'genie3');ro=bridge.ro
    x=np.random.default_rng(19).uniform(0,4,(36,6));cells=[f'c{i}' for i in range(36)];genes=['z','a','b','q','r','s'];tf=['q','z']
    actual=bridge.genie3(sparse.csr_matrix(x),cells,genes,tf,19,50)
    assert actual['status']=='completed',actual
    ref=ro.r('''function(x,genes,tf){set.seed(19); x<-matrix(x,nrow=length(genes),dimnames=list(genes,NULL)); GENIE3::GENIE3(x,regulators=tf,nTrees=50,nCores=1,verbose=FALSE)[tf,,drop=FALSE]}''')(ro.FloatVector(x.ravel()),ro.StrVector(genes),ro.StrVector(tf))
    np.testing.assert_allclose(actual['weights'],np.asarray(ref),atol=0,rtol=0)
    repeated=bridge.genie3(sparse.csr_matrix(x),cells,genes,tf,19,50)
    np.testing.assert_array_equal(actual['weights'],repeated['weights'])
    assert actual['regulators']==tf and actual['targets']==genes
    assert actual['weights'][0,3]==actual['weights'][1,0]==0
    with pytest.raises(ValueError,match='regulator'):bridge.genie3(sparse.csr_matrix(x),cells,genes,['unknown'],19,50)
    x[0,0]=np.nan
    with pytest.raises(ValueError,match='finite'):bridge.genie3(sparse.csr_matrix(x),cells,genes,tf,19,50)

@pytest.mark.skipif(not Path('/opt/paperassist-single-cell-r/lib/R').exists(), reason='pinned R runtime required')
def test_cellchat_original_probabilities_complex_and_group_sizes(tmp_path):
    from app.adapters.single_cell_r.topics import initialize_topics,get_cellchat_resource
    bridge=initialize_topics(tmp_path,'cellchat');ro=bridge.ro
    resource=get_cellchat_resource();genes=resource['gene_symbols'];cells=[f'c{i}' for i in range(36)];labels=['z']*18+['a']*18
    x=np.random.default_rng(9).uniform(.1,3,(36,len(genes)));ids=[r['interaction_id'] for r in resource['interactions']]
    actual=bridge.cellchat(sparse.csr_matrix(x),cells,genes,labels,9606,ids,9,20,5)
    assert actual['status']=='completed',actual
    # Independent literal custom DB and direct original pipeline; do not reuse wrapper builder.
    ref=ro.r('''function(x,genes,cells,labels) {
      future::plan(future::sequential)
      data<-matrix(x,nrow=length(genes),dimnames=list(genes,cells))
      meta<-data.frame(labels=factor(labels,levels=unique(labels)),row.names=cells)
      cc<-CellChat::createCellChat(data,meta=meta,group.by='labels')
      interactions<-data.frame(interaction_name=c('DEMO_CCL19_CCR7','DEMO_MIF_CD74_CD44','DEMO_CXCL12_CXCR4'),pathway_name=c('CCL','MIF','CXCL'),ligand=c('CCL19','MIF','CXCL12'),receptor=c('CCR7','DEMO_CD74_CD44','CXCR4'),agonist='',antagonist='',co_A_receptor='',co_I_receptor='',evidence='Jin2021',annotation='Secreted Signaling',interaction_name_2=c('DEMO_CCL19_CCR7','DEMO_MIF_CD74_CD44','DEMO_CXCL12_CXCR4'))
      rownames(interactions)<-interactions$interaction_name
      cc@DB<-list(interaction=interactions,complex=data.frame(subunit_1='CD74',subunit_2='CD44',subunit_3='',subunit_4='',row.names='DEMO_CD74_CD44'),cofactor=data.frame(cofactor1=character(),cofactor2=character()),geneInfo=data.frame(Symbol=genes))
      cc<-CellChat::subsetData(cc)
      cc<-CellChat::computeCommunProb(cc,LR.use=interactions,type='triMean',raw.use=TRUE,population.size=FALSE,nboot=20,seed.use=9,distance.use=FALSE)
      cc<-CellChat::filterCommunication(cc,min.cells=5)
      list(prob=cc@net$prob,pval=cc@net$pval,groups=as.integer(table(cc@idents)))
    }''')(ro.FloatVector(x.ravel()),ro.StrVector(genes),ro.StrVector(cells),ro.StrVector(labels))
    probs=np.asarray(ref.rx2('prob'));pvals=np.asarray(ref.rx2('pval'))
    assert actual['group_sizes']=={'z':18,'a':18}
    assert len(actual['edge_rows'])==12
    groups=['z','a']
    for row in actual['edge_rows']:
        idx=(groups.index(row['sender']),groups.index(row['receiver']),ids.index(row['interaction_id']))
        np.testing.assert_allclose(row['probability'],probs[idx],atol=1e-14,rtol=1e-12)
        np.testing.assert_allclose(row['p_value'],pvals[idx],atol=0,rtol=0)
    missing=bridge.cellchat(sparse.csr_matrix(x[:,:3]),cells,genes[:3],labels,9606,[ids[1]],9,20,5)
    assert missing['reason']=='cellchat_required_genes_missing'
    small=bridge.cellchat(sparse.csr_matrix(x),cells,genes,labels,9606,ids,9,20,18)
    assert small['reason']=='cellchat_group_too_small'
