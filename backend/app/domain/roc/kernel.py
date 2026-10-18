import math
import numpy as np
from app.domain.regression.common import NumericError,require,payload,bounded_rows
from app.domain.roc.contracts import RocStatistics
RocError=NumericError

def compute_roc(rows,selection):
    s=payload(selection);bounded_rows(rows)
    direction=s['direction'];require(direction in ('higher_is_positive','lower_is_positive'),'numeric_invalid_input','须声明分数方向。')
    scores=np.asarray([r['score'] for r in rows],dtype=float); labels=np.asarray([r['outcome'] for r in rows])
    require(np.isfinite(scores).all() and np.isin(labels,[0,1]).all(),'numeric_invalid_input','非法分数或结局。')
    if s.get('score_kind')=='probability':require(((scores>=0)&(scores<=1)).all(),'numeric_invalid_input','概率必须位于[0,1]。')
    directed=scores if direction=='higher_is_positive' else -scores
    pos=np.sort(directed[labels==1]);neg=np.sort(directed[labels==0]);m=len(pos);k=len(neg)
    require(m and k,'numeric_sample_size','ROC必须同时包含阳性和阴性。')
    v10=(np.searchsorted(neg,pos,'left')+.5*(np.searchsorted(neg,pos,'right')-np.searchsorted(neg,pos,'left')))/k
    v01=(m-np.searchsorted(pos,neg,'right')+.5*(np.searchsorted(pos,neg,'right')-np.searchsorted(pos,neg,'left')))/m
    auc=float(v10.mean());variance=float(v10.var(ddof=1)/m+v01.var(ddof=1)/k) if min(m,k)>=2 else None
    reason=None
    if s['evaluation_role'] not in ('external_validation','held_out_validation'): reason='evaluation_role_not_independent'
    elif min(m,k)<2: reason='insufficient_class_size'
    elif variance<=0:reason='degenerate_delong_variance'
    low=high=None
    if reason is None:low=max(0.,auc-1.959963984540054*math.sqrt(variance));high=min(1.,auc+1.959963984540054*math.sqrt(variance))
    points=[dict(threshold_kind='above_all' if direction=='higher_is_positive' else 'below_all',threshold=None,tpr=0.,fpr=0.,sensitivity=0.,specificity=1.)]
    order=np.argsort(-directed,kind='stable');tp=fp=0;i=0
    while i<len(order):
        j=i
        while j<len(order) and directed[order[j]]==directed[order[i]]:
            tp+=int(labels[order[j]]==1);fp+=int(labels[order[j]]==0);j+=1
        tpr=tp/m;fpr=fp/k
        points.append(dict(threshold_kind='value',threshold=float(scores[order[i]]),tpr=tpr,fpr=fpr,sensitivity=tpr,specificity=1-fpr));i=j
    trapezoid=float(np.trapezoid([p['tpr'] for p in points],[p['fpr'] for p in points]))
    require(abs(auc-trapezoid)<1e-12,'numeric_unstable','AUC核对失败。')
    return RocStatistics.model_validate(dict(method='roc_auc',n=len(rows),positive_n=m,negative_n=k,auc=auc,variance=variance,confidence_interval=dict(low=low,high=high,level=.95,method='delong_normal_clipped',reason=reason),points=points,direction=direction,evaluation_role=s['evaluation_role'],warnings=['auc_not_clinical_utility']+(['small_sample'] if min(m,k)<20 else []))).model_dump(mode='json')
