"""CSR cells x genes -> R dgCMatrix genes x cells, without dense exchange."""
import os
import sys
from pathlib import Path
from .bootstrap import preload_runtime_libraries
preload_runtime_libraries()
import numpy as np
from scipy import sparse
from . import annotation

R_PREFIX=Path('/opt/paperassist-single-cell-r')
_bridge=None
_propeller_bridge=None


def classify_failure_reason(reason,logs):
    if reason=='tool_failed' and any('cannot allocate vector of size' in line.lower() or 'cannot allocate memory block of size' in line.lower() for line in logs):return 'resource_insufficient'
    return reason


def validate_counts(counts,cells,genes):
    if not sparse.isspmatrix_csr(counts) or counts.shape!=(len(cells),len(genes)) or len(set(cells))!=len(cells) or len(set(genes))!=len(genes):raise ValueError('r_counts_axis_invalid')
    counts.check_format(full_check=True)
    if counts.dtype.kind not in 'iu' or np.any(counts.data<0):raise ValueError('r_counts_integer_required')
    if sum(map(int,counts.data))>2**53-1:raise ValueError('r_counts_precision_limit')
    if counts.nnz>2**31-1 or max(counts.shape,default=0)>2**31-1:raise ValueError('r_sparse_index_limit')


class EmbeddedR:
    def __init__(self,scratch,*,propeller_only=False):
        if sys.platform!='linux':raise ValueError('single_cell_r_environment_unavailable')
        expected=str(R_PREFIX/'lib/R')
        os.environ.update(R_HOME=expected,R_LIBS_USER='/nonexistent',R_ENVIRON_USER='/nonexistent',R_PROFILE_USER='/nonexistent',TMPDIR=str(scratch),RPY2_CFFI_MODE='ABI',RCPP_PARALLEL_NUM_THREADS='1',CLI_NO_THREAD='1')
        from rpy2.rinterface_lib import embedded,callbacks
        embedded.set_initoptions(('paperassist-r','--quiet','--no-save','--no-restore','--no-environ','--no-site-file','--no-init-file','--no-readline'))
        callbacks.consolewrite_print=lambda message:sys.stderr.write(message)
        callbacks.consolewrite_warnerror=lambda message:sys.stderr.write(message)
        from rpy2 import robjects as ro
        self.ro=ro
        if propeller_only:
            ro.r(Path(__file__).with_name('propeller.R').read_text(encoding='utf-8'))
            self.propeller_function=ro.globalenv['pa_propeller']
            self.collect=ro.r('function() invisible(gc(full=TRUE))')
            version=ro.r('c(R=as.character(getRversion()),speckle=as.character(packageVersion("speckle")),limma=as.character(packageVersion("limma")),statmod=as.character(packageVersion("statmod")))')
            self.versions=dict(zip(list(version.names),map(str,version)))
            if self.versions!={'R':'4.4.3','speckle':'1.6.0','limma':'3.62.1','statmod':'1.5.2'}:raise ValueError('single_cell_propeller_version_mismatch')
            return
        ro.r(Path(__file__).with_name('tools.R').read_text(encoding='utf-8'))
        self.function=ro.globalenv['pa_run']
        self.harmony_function=ro.globalenv['pa_harmony']
        self.annotation_function=ro.globalenv['pa_singler']
        self.collect=ro.r('function() invisible(gc(full=TRUE))')
        version=ro.r('c(R=as.character(getRversion()),SingleR=as.character(packageVersion("SingleR")),scDblFinder=as.character(packageVersion("scDblFinder")),decontX=as.character(packageVersion("decontX")),harmony=as.character(packageVersion("harmony")),xgboost=as.character(packageVersion("xgboost")),RcppParallel=as.character(packageVersion("RcppParallel")))')
        self.versions=dict(zip(list(version.names),map(str,version)))
        if not self.versions['R'].startswith('4.4.') or any(self.versions[k]!=v for k,v in {'SingleR':'2.8.0','scDblFinder':'1.20.2','decontX':'1.4.0','harmony':'1.2.3','xgboost':'2.1.4.1','RcppParallel':'5.1.9'}.items()):raise ValueError('single_cell_r_version_mismatch')

    def classify(self,expression,cells,genes,reference_config,seed):
        annotation.validate_expression(expression,cells,genes)
        reference=annotation.resolve_reference(reference_config,annotation.REFERENCE_ROOT)
        matching=annotation.match_genes(genes,reference['metadata'])
        base=dict(reference={**reference['metadata'],'label_level':reference['label_level']},matching=matching)
        if matching['matched_test_genes']<50:
            return dict(status='not_computable',reason='insufficient_common_genes',logs=[],**base)
        ro=self.ro
        result=self.annotation_function(ro.FloatVector(expression.data.astype('float64')),ro.IntVector(expression.indices.astype('int32')),
            ro.IntVector(expression.indptr.astype('int32')),ro.StrVector(genes),ro.StrVector(cells),str(reference['path']),reference['label_level'],int(seed))
        answer=dict(status=str(result.rx2('status')[0]),reason=str(result.rx2('reason')[0]) or None,logs=list(map(str,result.rx2('logs'))),**base)
        answer['reason']=classify_failure_reason(answer['reason'],answer['logs'])
        if answer['status']!='completed':return answer
        if list(result.rx2('cells'))!=list(cells) or list(result.rx2('common_genes'))!=matching['common_gene_ids']:raise ValueError('r_annotation_result_axis_invalid')
        answer.update(annotation.validate_result(cells,list(map(str,result.rx2('labels'))),list(map(str,result.rx2('pruned'))),
            np.array(result.rx2('scores'),copy=True),list(map(str,result.rx2('score_labels'))),
            np.array(result.rx2('delta_next'),copy=True),np.array(result.rx2('delta_median'),copy=True)))
        return answer

    def propeller(self,counts,sample_ids,label_ids,conditions,donors,batches,mode,transform='asin',batch_adjustment=False,*,numerator=None,denominator=None):
        from .propeller import validate_input,decode_result
        values,mode,numerator,denominator=validate_input(counts,sample_ids,label_ids,conditions,donors,batches,mode,transform,batch_adjustment,numerator,denominator)
        ro=self.ro
        result=self.propeller_function(ro.FloatVector(values.ravel()),ro.StrVector(sample_ids),ro.StrVector(label_ids),ro.StrVector(conditions),
            ro.StrVector(donors),ro.StrVector(batches or ['']*len(sample_ids)),mode,transform,bool(batch_adjustment),numerator,denominator)
        answer=decode_result(result,sample_ids,label_ids)
        answer['versions']=dict(self.versions)
        answer['parameters']=dict(method='speckle::propeller.ttest',mode=mode,transform=transform,batch_adjustment=bool(batch_adjustment),
            numerator=numerator,denominator=denominator,contrast_direction='numerator - denominator',robust_requested=True,robust=answer.get('robust_effective'),trend=False,sort=False)
        return answer

    def harmony(self,pcs,cells,batches,config,seed):
        pcs=np.asarray(pcs,dtype='float64')
        if pcs.ndim!=2 or pcs.shape[0]!=len(cells) or len(cells)!=len(batches) or len(set(cells))!=len(cells) or not np.isfinite(pcs).all():raise ValueError('r_harmony_input_axis_invalid')
        ro=self.ro
        result=self.harmony_function(ro.FloatVector(pcs.ravel(order='C')),ro.StrVector(cells),ro.StrVector(batches),pcs.shape[1],int(seed),float(config.get('theta',2)),float(config.get('lambda',1)),int(config.get('max_iter',10)))
        answer=dict(status=str(result.rx2('status')[0]),reason=str(result.rx2('reason')[0]) or None,logs=list(map(str,result.rx2('logs'))))
        if answer['status']=='completed':
            matrix=np.array(result.rx2('embedding'),dtype='float32',copy=True)
            if list(result.rx2('cells'))!=list(cells) or matrix.shape!=pcs.shape or not np.isfinite(matrix).all():raise ValueError('r_harmony_result_axis_invalid')
            answer['embedding']=matrix
        if answer['status']=='failed' and any('cannot allocate' in line.lower() for line in answer['logs']):answer['reason']='resource_insufficient'
        return answer

    def run(self,counts,cells,genes,tool,seed,expected_rate=None):
        validate_counts(counts,cells,genes)
        ro=self.ro
        result=self.function(ro.FloatVector(counts.data.astype('float64')),ro.IntVector(counts.indices.astype('int32')),ro.IntVector(counts.indptr.astype('int32')),ro.StrVector(genes),ro.StrVector(cells),tool,int(seed),ro.NULL if expected_rate is None else float(expected_rate))
        value={name:result.rx2(name) for name in result.names}
        answer=dict(status=str(value['status'][0]),reason=str(value['reason'][0]) or None,logs=list(map(str,value['logs'])))
        answer['reason']=classify_failure_reason(answer['reason'],answer['logs'])
        if answer['status']!='completed':return answer
        if list(value['cells'])!=list(cells) or list(value['genes'])!=list(genes):raise ValueError('r_result_axis_invalid')
        if tool=='scdblfinder':
            score=np.array(value['score'],dtype='float64',copy=True);prediction=list(map(str,value['prediction']))
            if score.shape!=(len(cells),) or not np.isfinite(score).all() or np.any(score<0) or np.any(score>1) or len(prediction)!=len(cells) or set(prediction)-{'singlet','doublet'}:raise ValueError('r_doublet_output_invalid')
            answer.update(score=score,prediction=prediction)
        else:
            contamination=np.array(value['contamination'],dtype='float64',copy=True)
            corrected=sparse.csr_matrix((np.array(value['x'],dtype='float64',copy=True),np.array(value['i'],dtype='int32',copy=True),np.array(value['p'],dtype='int32',copy=True)),shape=counts.shape)
            corrected.check_format(full_check=True)
            if contamination.shape!=(len(cells),) or not np.isfinite(contamination).all() or np.any(contamination<0) or np.any(contamination>1) or not np.isfinite(corrected.data).all() or np.any(corrected.data<0) or (corrected-counts.astype('float64')).max()>1e-7:raise ValueError('r_decontx_output_invalid')
            answer.update(contamination=contamination,counts=corrected)
        return answer

    def release_temporaries(self):
        self.collect()


def initialize(scratch):
    """Only trusted synthetic bytes may reach this pre-sandbox warmup."""
    global _bridge
    if _bridge is None:
        try:candidate=EmbeddedR(scratch)
        except Exception as exc:raise ValueError('single_cell_r_environment_unavailable') from exc
        rng=np.random.default_rng(17)
        values=rng.poisson(2,(96,64)).astype('int64');values[:48,:24]+=rng.poisson(12,(48,24));values[48:,24:48]+=rng.poisson(12,(48,24))
        counts=sparse.csr_matrix(values);cells=[f'warm{i}' for i in range(96)];genes=[f'gene{i}' for i in range(64)]
        for tool in ('scdblfinder','decontx'):
            result=candidate.run(counts,cells,genes,tool,17,.1)
            candidate.release_temporaries()
            if result['status']!='completed':raise ValueError('single_cell_r_warmup_failed:'+tool+':'+str(result['reason'])+':'+str(result['logs']))
        result=candidate.harmony(rng.normal(size=(96,6)),cells,['a']*48+['b']*48,{},17)
        candidate.release_temporaries()
        if result['status']!='completed':raise ValueError('single_cell_r_warmup_failed:harmony:'+str(result))
        result=candidate.ro.globalenv['pa_singler_warmup']()
        if not bool(result[0]):raise ValueError('single_cell_r_warmup_failed:SingleR')
        candidate.release_temporaries()
        if len(os.listdir('/proc/self/task'))!=1:raise ValueError('single_cell_r_requires_single_thread')
        _bridge=candidate
    return _bridge


def get_bridge():
    if _bridge is None and _propeller_bridge is None:raise ValueError('single_cell_r_not_preloaded')
    return _bridge if _bridge is not None else _propeller_bridge


def initialize_propeller(scratch):
    """Trusted, bounded speckle-only warmup; never opens user data."""
    global _propeller_bridge
    if _propeller_bridge is None:
        # Import the decoder before the application tree is denied by Landlock.
        from . import propeller
        candidate=EmbeddedR(scratch,propeller_only=True)
        counts=np.array([[30,50,20],[36,44,20],[24,61,15],[56,31,13],[61,21,18],[53,32,15]],dtype='int64')
        result=candidate.propeller(counts,[f'warm{i}' for i in range(6)],['a','b','unknown'],['ctrl']*3+['stim']*3,
            [f'd{i}' for i in range(6)],None,'unpaired')
        candidate.release_temporaries()
        if result['status']!='completed':raise ValueError('single_cell_propeller_warmup_failed:'+str(result))
        if len(os.listdir('/proc/self/task'))!=1:raise ValueError('single_cell_r_requires_single_thread')
        _propeller_bridge=candidate
    return _propeller_bridge
