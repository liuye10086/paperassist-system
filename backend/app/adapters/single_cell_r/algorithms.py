"""Per-capture modeling; predictions, filtering and correction stay distinct."""
import numpy as np
from scipy import sparse
from .bridge import get_bridge


def run_algorithms(counts,cells,genes,libraries,config,*,all_libraries=None):
    options={'doublet':config.get('doublet',{}),'decontx':config.get('decontx',{})}
    enabled=any(v.get('enabled',False) for v in options.values())
    bridge=get_bridge() if enabled else None
    rows=[dict(doublet_status='not_requested',doublet_score=None,doublet_prediction=None,doublet_excluded=False,doublet_reason='disabled',decontx_status='not_requested',decontx_contamination=None,decontx_reason='disabled') for _ in cells]
    keep=np.ones(len(cells),dtype=bool);reports=[];logs=[];corrected={}
    unique=sorted(set(libraries if all_libraries is None else all_libraries),key=lambda v:v or '')
    for library in unique:
        indices=np.asarray([i for i,v in enumerate(libraries) if v==library],dtype='int64')
        subset=counts[indices].tocsr();subset_cells=[cells[i] for i in indices]
        for name,tool in [('doublet','scdblfinder'),('decontx','decontx')]:
            params=options[name];requested=params.get('enabled',False)
            if not requested:result=dict(status='not_requested',reason='disabled',logs=[])
            elif not len(indices):result=dict(status='not_computable',reason='no_preliminary_qc_cells',logs=[])
            elif library is None:result=dict(status='not_computable',reason='original_library_id_missing',logs=[])
            else:
                result=bridge.run(subset,subset_cells,genes,tool,int(config.get('seed',0)),params.get('expected_rate'))
                bridge.release_temporaries()
            report=dict(library_id=library,algorithm=tool,status=result['status'],reason=result['reason'],input_cells=len(indices),computed_cells=len(indices) if result['status']=='completed' else 0,predicted_doublets=0,excluded_cells=0,mean_contamination=None,seed=int(config.get('seed',0)),expected_rate=params.get('expected_rate'),execution='embedded_R_SerialParam_single_thread',version=bridge.versions.get('scDblFinder' if name=='doublet' else 'decontX') if bridge else None)
            dims=min(20,len(indices)-1,len(genes)-1)
            report['actual_params']=dict(seed=int(config.get('seed',0)),dbr=params.get('expected_rate'),clusters=False,dims=dims,includePCs=min(19,dims),nfeatures=min(1352,len(genes)),BPPARAM='SerialParam',xgboost_threads=1) if name=='doublet' else dict(seed=int(config.get('seed',0)),z='automatic',batch=None,background=None,maxIter=500,delta=[10,10],estimateDelta=True,convergence=.001,iterLogLik=10,varGenes=5000,dbscanEps=1,umap_threads=1)
            if not requested or not len(indices) or library is None:report['actual_params']=None
            logs.append(f'library={library!r} tool={tool} status={result["status"]} reason={result["reason"]}')
            logs.extend(str(v) for v in result['logs'])
            for j,index in enumerate(indices):
                rows[index][name+'_status']=result['status'];rows[index][name+'_reason']=result['reason']
                if result['status']=='completed':
                    if name=='doublet':
                        prediction=result['prediction'][j];exclude=bool(params.get('exclude_predicted',False) and prediction=='doublet')
                        rows[index].update(doublet_score=float(result['score'][j]),doublet_prediction=prediction,doublet_excluded=exclude)
                        keep[index]=not exclude
                        report['predicted_doublets']+=int(prediction=='doublet');report['excluded_cells']+=int(exclude)
                    else:rows[index]['decontx_contamination']=float(result['contamination'][j])
            if name=='decontx' and result['status']=='completed':
                corrected[library]=(indices,result['counts']);report['mean_contamination']=float(np.mean(result['contamination']))
            reports.append(report)
    summary={}
    for name,tool in [('doublet','scdblfinder'),('decontx','decontx')]:
        selected=[r for r in reports if r['algorithm']==tool];success=sum(r['status']=='completed' for r in selected)
        if not options[name].get('enabled',False):status,reason='not_requested','disabled'
        elif success==len(selected) and selected:status,reason='completed',None
        elif success:status,reason='partial','some_libraries_not_computable_or_failed'
        else:status,reason='failed' if any(r['status']=='failed' for r in selected) else 'not_computable','no_library_completed'
        if status=='failed' and selected and all(r['reason']=='resource_insufficient' for r in selected):reason='resource_insufficient'
        summary[name]=dict(status=status,reason=reason,input_cells=len(cells),computed_cells=sum(r['computed_cells'] for r in selected),libraries=len(selected),completed_libraries=success,failed_libraries=sum(r['status']=='failed' for r in selected),not_computable_libraries=sum(r['status']=='not_computable' for r in selected))
    summary['doublet'].update(predicted_doublets=sum(r['predicted_doublets'] for r in reports),excluded_cells=int((~keep).sum()),prediction_interpretation='model_prediction_not_confirmed_doublet')
    full=None
    if summary['decontx']['status']=='completed' and len(cells):
        # Stacking in original row order avoids data-dense assignments and
        # preserves interleaved library axes.
        lookup={int(index):matrix[j] for indices,matrix in corrected.values() for j,index in enumerate(indices)}
        full=sparse.vstack([lookup[i] for i in range(len(cells))],format='csr',dtype='float64')
    summary['decontx'].update(corrected_cells=sum(len(v[0]) for v in corrected.values()),layer_emitted=full is not None,layer_scope='all_preliminary_qc_cells_then_final_filter' if full is not None else 'none',downstream_expression='original_counts')
    summary['versions']=bridge.versions if bridge else {}
    if bridge is not None:bridge.release_temporaries()
    return dict(observations=rows,library_algorithms=reports,keep=keep,decontx_counts=full,summary=summary,logs=logs,versions=bridge.versions if bridge else {})
