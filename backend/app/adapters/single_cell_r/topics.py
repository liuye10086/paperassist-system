"""Pinned original Slingshot / GENIE3 / CellChat, warmed before isolation."""
import copy
import json
import os
import sys
from pathlib import Path
from .bootstrap import preload_runtime_libraries
preload_runtime_libraries()
import numpy as np
from scipy import sparse

_bridge=None
_RESOURCE_PATH=Path(__file__).with_name('topics_resource.json')
_RESOURCE=None


def get_cellchat_resource(species_taxon_id=9606):
    global _RESOURCE
    if species_taxon_id!=9606:raise ValueError('cellchat_resource_species_unsupported')
    if _RESOURCE is None:
        import hashlib
        resource=json.loads(_RESOURCE_PATH.read_text(encoding='utf-8'))
        payload={k:resource[k] for k in ('interactions','complexes','cofactors','gene_symbols')}
        actual=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if actual!=resource['metadata']['payload_sha256']:raise ValueError('cellchat_resource_hash_mismatch')
        resource.update(resource_id=resource['metadata']['resource_id'],species_taxon_id=9606,license=resource['metadata']['license'],source=resource['metadata']['sources'],sha256=actual)
        for row in resource['interactions']:
            row.update(interaction_id=row['interaction_name'],pathway=row['pathway_name'],source=row['evidence'])
        _RESOURCE=resource
    return copy.deepcopy(_RESOURCE)


def _axis(values,name):
    if not values or len(set(values))!=len(values) or any(not isinstance(v,str) or not v for v in values):raise ValueError('topics_'+name+'_axis_invalid')


def _expression(expression,cells,genes):
    _axis(cells,'cells');_axis(genes,'genes')
    if not sparse.isspmatrix_csr(expression) or expression.shape!=(len(cells),len(genes)):raise ValueError('topics_expression_axis_invalid')
    expression.check_format(full_check=True)
    if not np.isfinite(expression.data).all() or np.any(expression.data<0):raise ValueError('topics_expression_nonfinite_or_negative')
    if expression.shape[0]>20000 or expression.shape[1]>5000 or expression.nnz>20000000:raise ValueError('topics_expression_resource_limit')


class TopicsBridge:
    def __init__(self,scratch):
        if sys.platform!='linux':raise ValueError('single_cell_topics_environment_unavailable')
        os.environ.update(R_HOME='/opt/paperassist-single-cell-r/lib/R',R_LIBS_USER='/nonexistent',R_ENVIRON_USER='/nonexistent',R_PROFILE_USER='/nonexistent',TMPDIR=str(scratch),RPY2_CFFI_MODE='ABI',RCPP_PARALLEL_NUM_THREADS='1',CLI_NO_THREAD='1')
        from rpy2.rinterface_lib import embedded,callbacks
        if not embedded.isready():embedded.set_initoptions(('paperassist-r','--quiet','--no-save','--no-restore','--no-environ','--no-site-file','--no-init-file','--no-readline'))
        callbacks.consolewrite_print=lambda message:sys.stderr.write(message)
        callbacks.consolewrite_warnerror=lambda message:sys.stderr.write(message)
        from rpy2 import robjects as ro
        self.ro=ro
        ro.r('loadNamespace("Matrix")')
        ro.r(Path(__file__).with_name('topics.R').read_text(encoding='utf-8'))
        self.functions={name:ro.globalenv['pa_topics_'+name] for name in ('slingshot','genie3','cellchat')}
        self.collect=ro.r('function() invisible(gc(full=TRUE))')
        self.versions={'R':str(ro.r('as.character(getRversion())')[0])}
        if self.versions['R']!='4.4.3':raise ValueError('topics_r_version_mismatch')
        self.warmed=set()

    def _result(self,result):
        answer=dict(status=str(result.rx2('status')[0]),reason=str(result.rx2('reason')[0]) or None,logs=list(map(str,result.rx2('logs'))),versions=dict(self.versions))
        return answer

    def _sparse_args(self,expression,cells,genes):
        ro=self.ro
        expression=expression.copy();expression.sum_duplicates();expression.sort_indices()
        return (ro.FloatVector(expression.data.astype('float64')),ro.IntVector(expression.indices.astype('int32')),ro.IntVector(expression.indptr.astype('int32')),ro.StrVector(genes),ro.StrVector(cells))

    def slingshot(self,embedding,cells,clusters,root_cluster,seed):
        _axis(cells,'cells')
        embedding=np.asarray(embedding,dtype='float64')
        if embedding.ndim!=2 or embedding.shape[0]!=len(cells) or not 2<=embedding.shape[1]<=50 or not np.isfinite(embedding).all() or len(clusters)!=len(cells) or len(cells)>20000 or any(not isinstance(c,str) or not c for c in clusters):raise ValueError('slingshot_embedding_axis_invalid')
        if root_cluster not in clusters:raise ValueError('slingshot_root_cluster_invalid')
        if len(set(clusters))<2:return dict(status='not_computable',reason='slingshot_two_clusters_required',logs=[],versions=dict(self.versions))
        if any(clusters.count(c)<3 for c in set(clusters)):return dict(status='not_computable',reason='slingshot_cluster_too_small',logs=[],versions=dict(self.versions))
        ro=self.ro
        result=self.functions['slingshot'](ro.FloatVector(embedding.ravel()),ro.StrVector(cells),ro.StrVector(clusters),str(root_cluster),embedding.shape[1],int(seed))
        answer=self._result(result)
        if answer['status']=='completed':
            if list(result.rx2('cells'))!=list(cells):raise ValueError('slingshot_output_cells_invalid')
            pt=np.array(result.rx2('pseudotime'),copy=True);weights=np.array(result.rx2('weights'),copy=True)
            ids=list(map(str,result.rx2('lineage_ids')))
            if pt.shape!=(len(cells),len(ids)) or weights.shape!=pt.shape or np.isinf(pt).any() or not np.isfinite(weights).all() or (weights<0).any() or (weights>1).any():raise ValueError('slingshot_output_axis_invalid')
            curves=[np.array(v,copy=True) for v in result.rx2('curves')]
            if len(curves)!=len(ids) or any(v.ndim!=2 or v.shape[1]!=embedding.shape[1] or not np.isfinite(v).all() for v in curves):raise ValueError('slingshot_output_curve_invalid')
            answer.update(pseudotime=pt,weights=weights,lineage_ids=ids,lineage_clusters=[list(map(str,v)) for v in result.rx2('lineage_clusters')],curves=curves)
        return answer

    def genie3(self,expression,cells,genes,tf_ids,seed,n_trees):
        _expression(expression,cells,genes);_axis(tf_ids,'regulator')
        if set(tf_ids)-set(genes):raise ValueError('genie3_regulator_missing')
        if not 10<=n_trees<=1000 or len(cells)<5 or len(genes)<2:raise ValueError('genie3_parameters_invalid')
        ro=self.ro
        result=self.functions['genie3'](*self._sparse_args(expression,cells,genes),ro.StrVector(tf_ids),int(seed),int(n_trees))
        answer=self._result(result)
        if answer['status']=='completed':
            weights=np.array(result.rx2('weights'),copy=True)
            if list(result.rx2('regulators'))!=list(tf_ids) or list(result.rx2('targets'))!=list(genes) or weights.shape!=(len(tf_ids),len(genes)) or not np.isfinite(weights).all() or (weights<0).any():raise ValueError('genie3_output_axis_invalid')
            answer.update(regulators=list(tf_ids),targets=list(genes),weights=weights)
        return answer

    def cellchat(self,expression,cells,genes,labels,species_taxon_id,lr_ids,seed,n_boot,min_cells,lr_resource=None):
        _expression(expression,cells,genes)
        if len(labels)!=len(cells) or len(set(labels))<2 or any(not isinstance(v,str) or not v for v in labels):raise ValueError('cellchat_labels_invalid')
        if not 10<=n_boot<=1000 or min_cells<3:raise ValueError('cellchat_parameters_invalid')
        resource=get_cellchat_resource(species_taxon_id) if lr_resource is None else copy.deepcopy(lr_resource)
        if resource['species_taxon_id']!=species_taxon_id:raise ValueError('cellchat_resource_species_mismatch')
        ids={r['interaction_id']:r for r in resource['interactions']}
        _axis(lr_ids,'interaction')
        if set(lr_ids)-set(ids):raise ValueError('cellchat_interaction_missing')
        required=set()
        for identity in lr_ids:
            for side in ('ligand','receptor'):
                symbol=ids[identity][side];required.update(resource['complexes'].get(symbol,[symbol]))
        if required-set(genes):return dict(status='not_computable',reason='cellchat_required_genes_missing',logs=[],versions=dict(self.versions),resource=resource)
        if any(labels.count(label)<=min_cells for label in set(labels)):return dict(status='not_computable',reason='cellchat_group_too_small',logs=[],versions=dict(self.versions),resource=resource)
        if expression.max()<=0:return dict(status='not_computable',reason='cellchat_no_expression',logs=[],versions=dict(self.versions),resource=resource)
        ro=self.ro
        result=self.functions['cellchat'](*self._sparse_args(expression,cells,genes),ro.StrVector(labels),json.dumps(resource),ro.StrVector(lr_ids),int(seed),int(n_boot),int(min_cells))
        answer=self._result(result);answer['resource']=resource
        if answer['status']=='completed':
            rows=[]
            for sender,receiver,identity,prob,pvalue in zip(result.rx2('sender'),result.rx2('receiver'),result.rx2('interaction_id'),result.rx2('probability'),result.rx2('p_value')):
                if identity not in ids or not np.isfinite(prob) or not np.isfinite(pvalue) or not 0<=prob<=1 or not 0<=pvalue<=1:raise ValueError('cellchat_output_invalid')
                rows.append(dict(sender=str(sender),receiver=str(receiver),interaction_id=str(identity),pathway=ids[identity]['pathway'],probability=float(prob),p_value=float(pvalue)))
            answer.update(edge_rows=rows,group_sizes=dict(zip(map(str,result.rx2('group_names')),map(int,result.rx2('group_sizes')))))
        return answer

    def release_temporaries(self):self.collect()


def initialize_topics(scratch,method):
    """Each method warms only trusted in-memory fixtures before isolation."""
    global _bridge
    if method not in ('slingshot','genie3','cellchat'):raise ValueError('topics_method_unsupported')
    if _bridge is None:_bridge=TopicsBridge(scratch)
    if method in _bridge.warmed:return _bridge
    package={'slingshot':'slingshot','genie3':'GENIE3','cellchat':'CellChat'}[method]
    expected={'slingshot':'2.14.0','genie3':'1.28.0','cellchat':'2.2.0.9001'}[method]
    version=str(_bridge.ro.r('function(p) {loadNamespace(p); as.character(packageVersion(p))}')(package)[0])
    if version!=expected:raise ValueError('topics_package_version_mismatch')
    _bridge.versions[package]=version
    rng=np.random.default_rng(17);cells=[f'warm{i}' for i in range(24)]
    if method=='slingshot':
        x=np.vstack([rng.normal([0,0],.1,(12,2)),rng.normal([2,2],.1,(12,2))])
        result=_bridge.slingshot(x,cells,['root']*12+['end']*12,'root',17)
    elif method=='genie3':result=_bridge.genie3(sparse.csr_matrix(rng.uniform(0,2,(24,4))),cells,['a','b','c','d'],['a','b'],17,10)
    else:
        resource=get_cellchat_resource();genes=resource['gene_symbols']
        x=rng.uniform(.1,2,(24,len(genes)))
        result=_bridge.cellchat(sparse.csr_matrix(x),cells,genes,['a']*12+['b']*12,9606,[resource['interactions'][0]['interaction_id']],17,10,3)
    _bridge.release_temporaries()
    if result['status']!='completed':raise ValueError('topics_warmup_failed:'+method+':'+str(result))
    if len(os.listdir('/proc/self/task'))!=1:raise ValueError('single_cell_r_requires_single_thread')
    _bridge.warmed.add(method)
    return _bridge


def get_topics_bridge():
    if _bridge is None:raise ValueError('single_cell_topics_not_preloaded')
    return _bridge


def exercise_topics(method=None):
    """Trusted deterministic probes usable after sandbox entry; no file access."""
    bridge=get_topics_bridge()
    methods=('slingshot','genie3','cellchat') if method is None else (method,)
    flags={}
    for current in methods:
        if current not in bridge.warmed:raise ValueError('topics_probe_not_preloaded')
        rng=np.random.default_rng(71);cells=[f'probe{i}' for i in range(36)];labels=['a']*18+['b']*18
        if current=='slingshot':
            x=np.vstack([rng.normal([0,0],.1,(18,2)),rng.normal([2,2],.1,(18,2))])
            result=bridge.slingshot(x,cells,labels,'a',71)
            valid=result['status']=='completed' and result['pseudotime'].shape==(36,1) and result['lineage_clusters']==[['a','b']]
        elif current=='genie3':
            result=bridge.genie3(sparse.csr_matrix(rng.uniform(.1,3,(36,6))),cells,list('abcdef'),['a','b'],71,50)
            valid=result['status']=='completed' and result['weights'].shape==(2,6) and result['weights'][0,0]==0 and result['weights'][1,1]==0
        else:
            db=get_cellchat_resource();genes=db['gene_symbols']
            result=bridge.cellchat(sparse.csr_matrix(rng.uniform(.1,3,(36,len(genes)))),cells,genes,labels,9606,[r['interaction_id'] for r in db['interactions']],71,20,5)
            valid=result['status']=='completed' and len(result['edge_rows'])==12 and result['group_sizes']=={'a':18,'b':18}
        bridge.release_temporaries()
        if not valid:raise ValueError('topics_probe_failed:'+current+':'+str(result.get('reason')))
        flags['topic_'+current]=True
    flags['topic_versions']=dict(bridge.versions)
    return flags
