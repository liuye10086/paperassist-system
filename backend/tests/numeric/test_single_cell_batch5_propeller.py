"""Real speckle 1.6.0 comparisons; no mock or synthetic replacement method."""
from pathlib import Path
import os
from app.adapters.single_cell_r.bootstrap import preload_runtime_libraries
preload_runtime_libraries()
import numpy as np
import pytest

pytestmark=pytest.mark.skipif(not Path('/opt/paperassist-single-cell-r/lib/R').is_dir(),reason='pinned R runtime required')


def fixture(mode):
    counts=np.array([[30,50,20],[36,44,20],[24,61,15],[42,38,20],[56,31,13],[61,21,18],[53,32,15],[65,22,13]],dtype='int64')
    conditions=['ctrl']*4+['stim']*4
    donors=['d1','d2','d3','d4']*2 if mode=='paired' else ['d'+str(i) for i in range(8)]
    return counts,['z8','z7','z6','z5','z4','z3','z2','z1'],['T','B','unknown'],conditions,donors,['b1','b2','b1','b2']*2


@pytest.mark.parametrize('mode,batch,transform,zero',[('unpaired',False,'asin',False),('paired',False,'asin',False),('unpaired',True,'asin',False),('paired',False,'logit',True)])
def test_propeller_matches_direct_speckle(tmp_path,mode,batch,transform,zero):
    from app.adapters.single_cell_r import bridge as module
    assert hasattr(module,'initialize_propeller'),'minimal speckle-only warmup is missing'
    bridge=module.initialize_propeller(tmp_path);ro=bridge.ro
    counts,samples,labels,groups,donors,batches=fixture(mode)
    if zero:counts[0,2]=0;counts[0,0]+=20
    actual=bridge.propeller(counts,samples,labels,groups,donors,batches,mode,transform,batch,numerator='stim',denominator='ctrl')
    assert actual['status']=='completed',actual
    reference=ro.r('''function(values,samples,labels,groups,donors,batches,paired,adjust,trans) {
      counts <- matrix(values,nrow=length(samples),byrow=TRUE)
      cells.sample <- rep(samples,rowSums(counts))
      cells.label <- unlist(lapply(seq_len(nrow(counts)),function(i) rep(labels,counts[i,])))
      p <- speckle::getTransformedProps(factor(cells.label,levels=labels),factor(cells.sample,levels=samples),transform=trans)
      group <- factor(groups,levels=c("ctrl","stim")); donor <- factor(donors,levels=unique(donors)); batch <- factor(batches,levels=unique(batches))
      design <- if(paired) model.matrix(~0+group+donor) else if(adjust) model.matrix(~0+group+batch) else model.matrix(~0+group)
      cont <- c(-1,1,rep(0,ncol(design)-2))
      result <- speckle::propeller.ttest(p,design=design,contrasts=cont,robust=TRUE,trend=FALSE,sort=FALSE)
      list(result=as.matrix(result),trans=t(p$TransformedProps),prop=t(p$Proportions),design=design,contrast=cont)
    }''')(ro.FloatVector(counts.ravel()),ro.StrVector(samples),ro.StrVector(labels),ro.StrVector(groups),ro.StrVector(donors),ro.StrVector(batches),mode=='paired',batch,transform)
    expected=np.asarray(reference.rx2('result'))
    np.testing.assert_allclose(actual['transformed'],np.asarray(reference.rx2('trans')),rtol=0,atol=1e-14)
    np.testing.assert_allclose(actual['proportions'],np.asarray(reference.rx2('prop')),rtol=0,atol=1e-14)
    np.testing.assert_allclose(actual['design'],np.asarray(reference.rx2('design')),rtol=0,atol=0)
    np.testing.assert_allclose(actual['contrast'],np.asarray(reference.rx2('contrast')),rtol=0,atol=0)
    assert [r['label_id'] for r in actual['rows']]==labels
    for index,row in enumerate(actual['rows']):
        np.testing.assert_allclose([row[k] for k in ['mean_proportion_denominator','mean_proportion_numerator','proportion_ratio','t_statistic','p_value','p_adjust']],expected[index],rtol=1e-12,atol=1e-14)
    assert actual['rows'][0]['t_statistic']>0
    assert bridge.versions['speckle']=='1.6.0'
    assert len(os.listdir('/proc/self/task'))==1


def test_propeller_blocks_false_independence_rank_deficiency_and_no_variation(tmp_path):
    from app.adapters.single_cell_r import bridge as module
    assert hasattr(module,'initialize_propeller'),'minimal speckle-only warmup is missing'
    bridge=module.initialize_propeller(tmp_path)
    c,s,l,g,d,b=fixture('unpaired')
    with pytest.raises(ValueError,match='independent'):bridge.propeller(c,s,l,g,['same']*8,b,'unpaired')
    result=bridge.propeller(c,s,l,g,d,g,'unpaired',batch_adjustment=True)
    assert result['status']=='not_computable' and result['reason']=='design_rank_deficient'
    result=bridge.propeller(np.tile([20,30,50],(8,1)),s,l,g,d,b,'unpaired')
    assert result['status']=='not_computable' and result['reason']=='no_testable_variation'
    with pytest.raises(ValueError,match='integer'):bridge.propeller(c.astype(float)+.1,s,l,g,d,b,'unpaired')
    with pytest.raises(ValueError,match='pairs'):bridge.propeller(c,s,l,g,d,b,'paired')


def test_propeller_preserves_constant_label_denominator_and_explicit_reverse_direction(tmp_path):
    from app.adapters.single_cell_r.bridge import initialize_propeller
    bridge=initialize_propeller(tmp_path)
    c,s,l,g,d,b=fixture('unpaired')
    c=np.column_stack((c,np.zeros(len(s),dtype='int64')));l=l+['unassigned']
    forward=bridge.propeller(c,s,l,g,d,b,'unpaired',numerator='stim',denominator='ctrl')
    reverse=bridge.propeller(c,s,l,g,d,b,'unpaired',numerator='ctrl',denominator='stim')
    assert forward['status']==reverse['status']=='completed'
    constant=forward['rows'][-1]
    assert constant['label_id']=='unassigned' and constant['status']=='not_computable'
    assert constant['p_value'] is None and constant['p_adjust'] is None
    assert constant['mean_proportion_numerator']==constant['mean_proportion_denominator']==0
    np.testing.assert_allclose(np.asarray(forward['proportions']).sum(axis=1),1)
    for a,b in zip(forward['rows'][:3],reverse['rows'][:3]):
        np.testing.assert_allclose(a['t_statistic'],-b['t_statistic'],rtol=1e-12)
        np.testing.assert_allclose(a['p_value'],b['p_value'],rtol=1e-12)
        np.testing.assert_allclose(a['proportion_ratio'],1/b['proportion_ratio'],rtol=1e-12)


def test_propeller_records_effective_robust_and_native_messages(tmp_path):
    from app.adapters.single_cell_r.bridge import initialize_propeller
    bridge=initialize_propeller(tmp_path)
    c,s,l,g,d,b=fixture('unpaired')
    result=bridge.propeller(c[:,:2],s,l[:2],g,d,b,'unpaired',numerator='stim',denominator='ctrl')
    assert result['status']=='completed'
    assert result['parameters']['robust_requested'] is True
    assert result['parameters']['robust'] is False
    assert any('Setting robust to FALSE' in line for line in result['logs'])
