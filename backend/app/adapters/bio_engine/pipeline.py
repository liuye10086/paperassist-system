"""Pure-dict transport to immutable B01 leaves, without DB or service imports."""
import hashlib
import json
import time
from pathlib import Path
import numpy as np
from scipy import sparse
import anndata as ad
import pandas as pd
from PIL import Image
from app.adapters.bio_engine import ENGINE_VERSION
from app.adapters.bio_engine.manifest import Writer, canonical, clean
from app.adapters.bio_engine.qc import quality_control
from app.adapters.bio_engine.preprocess import normalize, high_variable
from app.adapters.bio_engine.embedding import embed
from app.adapters.bio_engine.markers import markers
from app.adapters.bio_engine import plots
from app.domain.bioinformatics.single_cell_resources import resource_estimate,memory_bounds,analysis_limits_for
from app.adapters.single_cell_r.algorithms import run_algorithms
from app.adapters.bio_engine.subset import inherit_subset


def load_raw(raw):
    members=raw['members']; manifest=raw['manifest']
    for member in members.values():
        path=Path(member['path'])
        if path.is_symlink() or path.stat().st_size>256*1024**2 or path.stat().st_size!=member['size_bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=member['sha256']:
            raise ValueError('raw_member_hash_mismatch')
    def array(key): return np.load(members[key]['path'],allow_pickle=False,mmap_mode='r')
    def document(key): return json.loads(Path(members[key]['path']).read_bytes())
    axes=manifest['input_shape'];shape=(axes['observations'],axes['features'])
    if not(0<shape[0]<=20000 and 0<shape[1]<=100000): raise ValueError('matrix_shape_limit')
    data=array('matrix_data');indices=array('matrix_indices');indptr=array('matrix_indptr')
    if data.ndim!=1 or data.dtype.kind not in 'iu' or len(data)>10000000 or not np.isfinite(data).all() or np.any(data<0) or sum(map(int,data))>np.iinfo(np.int64).max: raise ValueError('raw_counts_invalid')
    if indices.ndim!=1 or indptr.ndim!=1 or indices.dtype.kind not in 'iu' or indptr.dtype.kind not in 'iu' or len(indptr)!=shape[0]+1 or indptr[0]!=0 or indptr[-1]!=len(data) or np.any(indptr[1:]<indptr[:-1]) or len(indices)!=len(data) or np.any(indices<0) or np.any(indices>=shape[1]): raise ValueError('csr_invalid')
    matrix=sparse.csr_matrix((data,indices,indptr),shape=shape);matrix.check_format(full_check=True)
    features=document('features_index');barcodes=document('barcodes_index')['barcodes']
    if len(barcodes)!=shape[0] or len(set(barcodes))!=len(barcodes) or any(len(v)!=shape[1] for v in features.values()) or len(set(features['feature_ids']))!=shape[1]: raise ValueError('raw_axis_invalid')
    positions=document('positions_index') if 'positions_index' in members else []
    return matrix,features,barcodes,positions


def effective_config(config,features):
    value=dict(config)
    value['min_gene_spots']=value.get('min_spots',value.get('min_gene_spots',3))
    rule=value.get('mt_rule',{'kind':'unknown'})
    if rule.get('confirmed') and rule.get('kind')=='feature_ids': value['mitochondrial_feature_ids']=rule['feature_ids']
    if rule.get('confirmed') and rule.get('kind')=='prefix':
        prefix=rule.get('prefix')
        if not isinstance(prefix,str) or not prefix: raise ValueError('invalid_mt_prefix')
        value['mitochondrial_feature_ids']=[i for i,s in zip(features['feature_ids'],features['feature_symbols']) if s.startswith(prefix)]
    for field,minimum,maximum,default in [('target_sum',1,1_000_000,10000),('pca_components',2,100,30),('neighbors',2,100,15),('seed',0,2**31-1,0),('hvg_count',3,10000,2000),('marker_top_n',1,100,5)]:
        actual=value.get(field,default)
        if isinstance(actual,bool) or not isinstance(actual,(int,float)) or not np.isfinite(actual) or not minimum<=actual<=maximum: raise ValueError('invalid_parameter_'+field)
        if field!='target_sum' and int(actual)!=actual: raise ValueError('integer_parameter_'+field)
        value[field]=actual
    for field in ['min_counts','min_genes','min_gene_spots']:
        actual=value.get(field,1 if field!='min_gene_spots' else 3)
        if isinstance(actual,bool) or not isinstance(actual,int) or actual<0:raise ValueError('invalid_parameter_'+field)
    maximum=value.get('max_counts')
    if maximum is not None and (not isinstance(maximum,int) or maximum<value.get('min_counts',1)): raise ValueError('invalid_max_counts')
    mt_max=value.get('max_mt_fraction')
    if mt_max is not None and (not isinstance(mt_max,(int,float)) or not np.isfinite(mt_max) or not 0<=mt_max<=1 or not rule.get('confirmed') or rule.get('kind')=='unknown'):raise ValueError('invalid_max_mt_fraction')
    return value


def run(payload):
    started=time.monotonic()
    selected_limits=analysis_limits_for(single_cell=payload['raw']['manifest'].get('assay')=='single_cell',params=payload.get('config',{}))
    writer=Writer(payload['output_directory'],max_output_bytes=selected_limits.max_output_bytes);writer.identity=payload.get('identity',{})
    raw,features,barcodes,positions=load_raw(payload['raw'])
    single_cell=payload['raw']['manifest'].get('assay')=='single_cell'
    config=effective_config(payload.get('config',{}),features);mode=payload['mode']
    if single_cell:
        from app.domain.bioinformatics.single_cell_contracts import SingleCellParameters
        SingleCellParameters.model_validate(payload.get('config',{}))
    if single_cell and (positions or config.get('in_tissue_only')):raise ValueError('single_cell_nonspatial_only')
    mapping_member=payload['raw']['members'].get('observation_map_index')
    mapping=json.loads(Path(mapping_member['path']).read_bytes()) if mapping_member else {'rows':[]}
    mapped={r['barcode']:r for r in mapping['rows']}
    if len(mapped)!=len(mapping['rows']) or not set(mapped).issubset(barcodes): raise ValueError('mapping_axis_invalid')
    original_member=payload['raw']['members'].get('import_observation_map_index')
    original_mapping=json.loads(Path(original_member['path']).read_bytes()) if original_member else mapping
    original_mapped={r['barcode']:r for r in original_mapping['rows']}
    if len(original_mapped)!=len(original_mapping['rows']) or not set(original_mapped).issubset(barcodes):raise ValueError('original_mapping_axis_invalid')
    library_ids=[original_mapped.get(b,{}).get('library_id') for b in barcodes] if single_cell else None
    subset_state=None
    if payload.get('subset'):
        if not single_cell or mode!='compute':raise ValueError('subset_requires_single_cell_compute')
        subset_state=inherit_subset(raw,features,barcodes,payload['processed'],payload['subset'])
        qc=subset_state['qc']
    else:qc=quality_control(raw,features,barcodes,positions,config,library_ids=library_ids)
    mask=qc['obs_mask'];fmask=qc['feature_mask'];counts=qc['filtered_counts'];preliminary=mask.copy()
    steps=[dict(key='raw_qc',status='completed',reason=None,params={}),dict(key='filter',status='completed',reason=None,params=config)]
    position_map={p['barcode']:p for p in positions}
    algorithms=None;decontx_counts=None;algorithm_rows={}
    if subset_state:
        algorithms=subset_state['algorithms'];decontx_counts=subset_state['decontx_counts'];algorithm_rows=subset_state['algorithm_rows']
        steps=[dict(key='raw_qc',status='completed',reason='inherited_parent_qc',params={}),dict(key='filter',status='completed',reason='explicit_parent_cell_selection',params={'parent_feature_filter':'inherited'})]
        writer.json('subset_provenance',subset_state['provenance']);writer.table('subset_cells',subset_state['rows'])
    if single_cell and not subset_state:
        initial_indices=np.flatnonzero(preliminary)
        algorithms=run_algorithms(counts,[barcodes[i] for i in initial_indices],
            [feature for feature,keep in zip(features['feature_ids'],fmask) if keep],
            [library_ids[i] for i in initial_indices],config,all_libraries=library_ids)
        algorithm_rows=dict(zip(map(int,initial_indices),algorithms['observations']))
        for i in initial_indices[~algorithms['keep']]:qc['reasons'][i].append('predicted_doublet')
        mask[initial_indices]=algorithms['keep'];counts=counts[algorithms['keep']].tocsr()
        if algorithms['decontx_counts'] is not None:decontx_counts=algorithms['decontx_counts'][algorithms['keep']].tocsr()
        qc['filtered_counts']=counts;qc['filtered_total']=np.asarray(counts.sum(1)).ravel();qc['filtered_detected']=np.asarray((counts>0).sum(1)).ravel()
        qc['stages']['preliminary_qc_cells']=int(preliminary.sum());qc['stages']['final_spots']=int(mask.sum())
        for row in qc['library_qc']:
            selected=np.asarray([v==row['library_id'] for v in library_ids])
            row['preliminary_qc_kept_cells']=row['kept_cells'];row['kept_cells']=int((selected&mask).sum());row['excluded_cells']=int((selected&~mask).sum())
            row['predicted_doublet_excluded_cells']=int((selected&preliminary&~mask).sum())
            row['exclusion_reason_counts']['predicted_doublet']=row['predicted_doublet_excluded_cells']
    if single_cell:
        writer.table('library_qc',qc['library_qc'])
        writer.table('library_algorithms',algorithms['library_algorithms'])
        writer.table('single_cell_tool_versions',[dict(tool=k,version=v) for k,v in algorithms['versions'].items()],['tool','version'])
        writer.add('single_cell_tool_logs',('\n'.join(algorithms['logs'])+'\n').encode(),'txt')
        for name,key in [('doublet','scdblfinder'),('decontx','decontx')]:
            state=algorithms['summary'][name]
            steps.append(dict(key=key,status='not_requested' if subset_state else state['status'],reason='inherited_parent_qc' if subset_state else state['reason'],params=config.get(name,{})))
    observation_rows=[]
    for i,b in enumerate(barcodes):
        observation_rows.append(dict(raw_index=i,barcode=b,kept=bool(mask[i]),total_counts=int(qc['raw_counts'][i]),detected_genes=int(qc['raw_detected'][i]),
            zero_fraction=float(qc['raw_zero_fraction'][i]),exclusion_reasons=';'.join(qc['reasons'][i]),
            in_tissue=qc['in_tissue'][i],
            extreme_counts_candidate=bool(qc['extreme_counts'][i]),extreme_genes_candidate=bool(qc['extreme_genes'][i]),
            mt_fraction=None if qc['mt_fraction'] is None else clean(qc['mt_fraction'][i]),mt_reason=qc['mt_reason'],
            x=position_map.get(b,{}).get('pxl_col_in_fullres'),y=position_map.get(b,{}).get('pxl_row_in_fullres'),cluster=None))
        for field in ['sample_id','section','donor','batch','group']:
            item=mapped.get(b,{}).get(field,{'status':'pending','value':None})
            observation_rows[-1][field]=item.get('value') if item.get('status')=='known' else None
            observation_rows[-1][field+'_status']=item.get('status','pending')
        if single_cell:
            observation_rows[-1].update(preliminary_qc_kept=bool(preliminary[i]),**algorithm_rows.get(i,dict(
                doublet_status='not_computable' if config.get('doublet',{}).get('enabled') else 'not_requested',doublet_score=None,doublet_prediction=None,doublet_excluded=False,doublet_reason='excluded_by_preliminary_qc',
                decontx_status='not_computable' if config.get('decontx',{}).get('enabled') else 'not_requested',decontx_contamination=None,decontx_reason='excluded_by_preliminary_qc')))
            observation_rows[-1]['library_id']=original_mapped.get(b,{}).get('library_id')
            observation_rows[-1]['original_barcode']=original_mapped.get(b,{}).get('original_barcode',b)
            for field in ('species_taxon_id','reference_id','reference_version','library_chemistry','pair_id'):
                item=original_mapped.get(b,{}).get(field,{'status':'pending','value':None})
                observation_rows[-1][field]=item.get('value') if item.get('status')=='known' else None
                observation_rows[-1][field+'_status']=item.get('status','pending')
    feature_rows=[dict(raw_index=i,feature_id=identifier,symbol=features['feature_symbols'][i],feature_type=features['feature_types'][i],kept=bool(fmask[i]),total_counts=int(qc['feature_counts'][i]),nonzero_spots=int(qc['feature_nonzero'][i])) for i,identifier in enumerate(features['feature_ids'])]
    for index,raw_i in enumerate(np.flatnonzero(mask)):
        observation_rows[raw_i]['filtered_total_counts']=int(qc['filtered_total'][index])
        observation_rows[raw_i]['filtered_detected_genes']=int(qc['filtered_detected'][index])
    for row in observation_rows:
        row.setdefault('filtered_total_counts',None);row.setdefault('filtered_detected_genes',None)
    for row in feature_rows:
        row['exclusion_reason']=None if row['kept'] else 'not_gene_expression' if row['feature_type']!='Gene Expression' else 'min_spots'
    writer.array('observation_mask',mask);writer.array('feature_mask',fmask)
    writer.json('raw_axes',{'barcodes':barcodes,**features})
    plots.qc_figures(writer,qc,config)
    strata=[]
    for field in ['sample_id','section','batch']:
        values=[r[field] or 'unknown' for r in observation_rows]
        known=sorted(set(values))
        if known==['unknown']:continue
        for i,label in enumerate(known):
            selected=np.asarray([v==label for v in values]);strata.append({'field':field,'value':label,'raw_spots':int(selected.sum()),'kept_spots':int((selected&mask).sum()),'mean_counts':float(qc['raw_counts'][selected].mean()),'independent_replicates':None,'reason':'mapping_is_descriptive_not_independent_donor_validation'})
        plots.qc_stratified(writer,qc,field,values,config)
    writer.table('mapping_strata',strata)
    reasons=sorted({reason for row in qc['reasons'] for reason in row})
    layers={};summary={'shape':list(counts.shape),'nnz':int(counts.nnz),'filter_stages':qc['stages'],
                      'raw_observations':raw.shape[0],'retained_observations':int(mask.sum()),'excluded_observations':int((~mask).sum()),
                      'raw_features':raw.shape[1],'retained_features':int(fmask.sum()),'excluded_features':int((~fmask).sum()),
                      'exclusion_reason_counts':{r:sum(r in row for row in qc['reasons']) for r in reasons},
                      'exclusion_union_count':int((~mask).sum()),'reason_counts_may_overlap':True,'mitochondrial_reason':qc['mt_reason'],
                      'quality_hints':{'candidate_observations':int((qc['extreme_counts']|qc['extreme_genes']).sum()),'automatically_excluded':False,'fences':qc['extreme_fences']},
                      'planned_dimensions':{'hvg_upper_bound':min(config['hvg_count'],int(fmask.sum())),
                          'pca_upper_bound':max(0,min(config['pca_components'],int(mask.sum())-1,min(config['hvg_count'],int(fmask.sum()))-1)),
                          'neighbors':max(0,min(config['neighbors'],int(mask.sum())-1)),
                          'reason':'effective_hvg_and_pca_require_variance_after_normalization'},
                      'statistical_unit':'cell_exploratory' if single_cell else 'spot_exploratory','replicate_consistency':{'status':'not_computable','reason':'independent_donor_design_not_confirmed'}}
    if single_cell:
        summary['single_cell_algorithms']=algorithms['summary']
        if subset_state:summary['subset']=subset_state['provenance']
        if decontx_counts is not None:
            writer.matrix('decontx_counts',decontx_counts)
            layers['decontx_counts']=dict(prefix='decontx_counts',shape=list(decontx_counts.shape),dtype=str(decontx_counts.dtype),nnz=int(decontx_counts.nnz),source='parent_decontX' if subset_state else 'decontX',axis='final_filtered_cells_by_features',downstream_use='independent_correction_only')
    if mode=='compute':
        normalized,logged=normalize(counts,target_sum=config['target_sum'])
        ids=[v for v,keep in zip(features['feature_ids'],fmask) if keep]
        symbols=[v for v,keep in zip(features['feature_symbols'],fmask) if keep]
        retained_rows=[observation_rows[i] for i in np.flatnonzero(mask)]
        hvg_hits=None
        if single_cell:
            from app.adapters.bio_engine.integration import select_hvg,publish_integration
            hvg,mean,dispersion,hvg_hits,hvg_state=select_hvg(logged,ids,int(config.get('hvg_count',2000)),retained_rows,config.get('hvg_batch_key'))
        else:hvg,mean,dispersion=high_variable(logged,ids,int(config.get('hvg_count',2000)))
        result=embed(logged,hvg,ids,np.flatnonzero(mask),config,integration_rows=retained_rows if single_cell else None)
        if single_cell:
            result['integration']['hvg']=hvg_state
            publish_integration(writer,result,retained_rows,config)
            summary['single_cell_integration']=result['integration']
            for key in ('technical_covariates','harmony'):
                state=result['integration'][key]
                steps.append(dict(key=key,status=state['status'],reason=state['reason'],params=config.get(key)))
        all_markers,marker_state=markers(counts,normalized,logged,result['clusters'],ids)
        top=[]
        for label in sorted(set(result['clusters']),key=int):
            ranked=sorted([r for r in all_markers if r['cluster']==label and r['score'] is not None],key=lambda r:(-r['score'],r['feature_id']))
            top.extend(ranked[:int(config.get('marker_top_n',5))])
        for layer,matrix in [('counts',counts),('normalized',normalized),('log1p',logged),('distances',result['distances']),('connectivities',result['connectivities'])]:
            writer.matrix(layer,matrix)
            layers[layer]={'prefix':layer,'shape':list(matrix.shape),'dtype':str(matrix.dtype),'nnz':int(matrix.nnz)}
        for name,array in [('pca',result['pca']),('umap',result['umap']),('pca_loadings',result['loadings']),('hvg_mask',hvg)]:writer.array(name,array)
        writer.array('pca_feature_raw_indices',np.flatnonzero(fmask)[result['hvg_indices']])
        writer.array('pca_variance_ratio',result['variance_ratio'])
        kept_barcodes=[b for b,keep in zip(barcodes,mask) if keep]
        for raw_i,label in zip(np.flatnonzero(mask),result['clusters']):observation_rows[raw_i]['cluster']=label
        writer.table('embedding',[dict(barcode=b,raw_index=int(i),pc1=float(pc[0]),pc2=float(pc[1]),umap1=float(um[0]),umap2=float(um[1]),cluster=c) for b,i,pc,um,c in zip(kept_barcodes,np.flatnonzero(mask),result['pca'],result['umap'],result['clusters'])])
        writer.table('hvg',[dict(feature_id=identifier,chosen=bool(hvg[i]),mean=float(mean[i]),dispersion_normalized=clean(dispersion[i]),batch_hits=int(hvg_hits[i]) if hvg_hits is not None else None,strategy=hvg_state['strategy'] if single_cell else 'global_seurat',reason=None if hvg[i] else 'dispersion_not_finite_or_constant' if not np.isfinite(dispersion[i]) else 'outside_top_rank_or_constant') for i,identifier in enumerate(ids)])
        marker_fields=['cluster','feature_id','n_group','n_rest','score','p_value','q_value','effect_log2_normalized','detected_group','detected_rest','reason']
        writer.table('markers',all_markers,marker_fields);writer.table('markers_top',top,marker_fields)
        writer.table('cluster_summary',[{'cluster':c,'cells' if single_cell else 'spots':int((result['clusters']==c).sum()),'statistical_unit':'cell' if single_cell else 'spot'} for c in sorted(set(result['clusters']),key=int)])
        plots.embedding_figures(writer,result,kept_barcodes,config)
        plots.marker_figures(writer,counts,logged,result['clusters'],ids,top,{**config,'feature_symbols':dict(zip(ids,symbols))})
        if positions:
            full_cluster=np.full(len(barcodes),np.nan);full_cluster[mask]=result['clusters'].astype(float)
            image,image_scale,radius,image_sha=spatial_image(payload['raw'])
            plots.spatial(writer,'spatial_clusters',positions,barcodes,mask,full_cluster,{**config,'tissue_image_sha256':image_sha},image,image_scale,radius)
            gene_ids=list(dict.fromkeys(r['feature_id'] for r in top))[:4]
            if not gene_ids:gene_ids=[ids[i] for i in sorted(range(len(ids)),key=lambda i:(-float(normalized[:,i].mean()),ids[i]))[:4]]
            for j,gene_id in enumerate(gene_ids):
                expression=np.full(len(barcodes),np.nan);expression[mask]=logged[:,ids.index(gene_id)].toarray().ravel()
                plots.spatial(writer,'spatial_gene_'+str(j),positions,barcodes,mask,expression,{**config,'title':gene_id,'layer':'log1p','gene_ids':[gene_id],'tissue_image_sha256':image_sha},image,image_scale,radius)
        obs=pd.DataFrame({'raw_index':np.flatnonzero(mask),'cluster':pd.Categorical(result['clusters'])},index=kept_barcodes)
        for field in ['sample_id','section','donor','batch','group']:
            obs[field]=[observation_rows[i][field] or 'unknown' for i in np.flatnonzero(mask)]
            obs[field+'_status']=[observation_rows[i][field+'_status'] for i in np.flatnonzero(mask)]
        if single_cell:
            for field in ('doublet_status','doublet_prediction','doublet_reason','decontx_status','decontx_reason'):
                obs[field]=[observation_rows[i][field] or 'none' for i in np.flatnonzero(mask)]
            for field in ('doublet_score','decontx_contamination'):
                obs[field]=[np.nan if observation_rows[i][field] is None else observation_rows[i][field] for i in np.flatnonzero(mask)]
            obs['doublet_excluded']=[observation_rows[i]['doublet_excluded'] for i in np.flatnonzero(mask)]
            for field in ['library_id','original_barcode']:
                obs[field]=[observation_rows[i][field] or 'unknown' for i in np.flatnonzero(mask)]
            for field in ('species_taxon_id','reference_id','reference_version','library_chemistry','pair_id'):
                obs[field]=[str(observation_rows[i][field]) if observation_rows[i][field] is not None else 'unknown' for i in np.flatnonzero(mask)]
                obs[field+'_status']=[observation_rows[i][field+'_status'] for i in np.flatnonzero(mask)]
        var=pd.DataFrame({'raw_index':np.flatnonzero(fmask),'symbol':symbols,'highly_variable':hvg},index=ids)
        obj=ad.AnnData(logged.copy(),obs=obs,var=var)
        obj.layers['counts']=counts;obj.layers['normalized']=normalized
        if decontx_counts is not None:obj.layers['decontx_counts']=decontx_counts
        obj.obsm['X_pca']=result['pca'];obj.obsm['X_umap']=result['umap']
        if single_cell:
            obj.obsm['X_pca_unadjusted']=result['pca_unadjusted']
            if result['pca_harmony'] is not None:obj.obsm['X_pca_harmony']=result['pca_harmony']
            obj.uns['paperassist_integration_json']=canonical(result['integration']).decode()
        if positions:obj.obsm['spatial']=np.asarray([[position_map[b]['pxl_col_in_fullres'],position_map[b]['pxl_row_in_fullres']] for b in kept_barcodes])
        obj.obsp['distances']=result['distances'];obj.obsp['connectivities']=result['connectivities']
        obj.uns['paperassist_identity_json']=canonical(payload.get('identity',{})).decode()
        obj.uns['paperassist_params_json']=canonical(config).decode()
        if single_cell:obj.uns['paperassist_import_samples_json']=canonical(payload['raw']['manifest'].get('samples',[])).decode()
        if subset_state:obj.uns['paperassist_subset_json']=canonical(subset_state['provenance']).decode()
        path=writer.root/'processed.h5ad';obj.write_h5ad(path)
        restored=ad.read_h5ad(path)
        if decontx_counts is not None and (restored.layers['decontx_counts']!=decontx_counts).nnz:raise ValueError('h5ad_roundtrip_mismatch')
        if list(restored.obs_names)!=kept_barcodes or list(restored.var_names)!=ids or (restored.X!=logged).nnz or (restored.layers['counts']!=counts).nnz or (restored.layers['normalized']!=normalized).nnz or restored.uns['paperassist_identity_json']!=obj.uns['paperassist_identity_json'] or restored.uns['paperassist_params_json']!=obj.uns['paperassist_params_json'] or not np.array_equal(restored.obs['raw_index'],obj.obs['raw_index']) or not np.array_equal(restored.var['raw_index'],obj.var['raw_index']) or any(not np.array_equal(restored.obsm[k],obj.obsm[k]) for k in obj.obsm) or any((restored.obsp[k]!=obj.obsp[k]).nnz for k in obj.obsp):
            raise ValueError('h5ad_roundtrip_mismatch')
        writer.existing('processed',path,'h5ad')
        steps.extend(dict(key=k,status='completed',reason=None,params={}) for k in ['normalize','log1p','hvg','pca','neighbors','umap','leiden','h5ad_roundtrip'])
        steps.append(dict(key='markers',params={},**marker_state))
        summary.update(clusters=len(set(result['clusters'])),hvg=int(hvg.sum()),pca_components=result['pca'].shape[1])
    elif mode!='qc': raise ValueError('unsupported_engine_mode')
    else:
        steps.extend(dict(key=k,status='not_requested',reason='qc_candidate_only',params={}) for k in ['normalize','log1p','hvg','pca','neighbors','umap','leiden','markers','h5ad_roundtrip'])
    if single_cell:
        from app.adapters.bio_engine.single_cell import aggregate_cells
        from app.domain.bioinformatics.single_cell_contracts import SingleCellParameters
        cell_params=SingleCellParameters.model_validate(payload.get('config',{}))
        labels={v.cluster:v.model_dump() for v in cell_params.cell_labels}
        if mode=='compute' and set(labels)-{r['cluster'] for r in observation_rows if r['kept']}:raise ValueError('cell_label_cluster_unknown')
        label_rows=[]
        for row in observation_rows:
            row.pop('in_tissue',None);row.pop('x',None);row.pop('y',None)
            row['cell_id']=row['barcode'];row['cell_identity_scope']='dataset_version/sample_id/barcode'
            row['cell_label']=labels.get(row['cluster'],{}).get('label','unknown')
        if mode=='compute':
            for cluster in sorted({r['cluster'] for r in observation_rows if r['kept']}):
                value=labels.get(cluster,{'cluster':cluster,'label':'unknown','marker_ids':[],'evidence_file_ids':[],'basis':'','decided_by':''})
                label_rows.append({**value,'marker_ids':';'.join(value['marker_ids']),'evidence_file_ids':';'.join(value['evidence_file_ids'])})
        writer.table('cell_label_evidence',label_rows,['cluster','label','marker_ids','evidence_file_ids','evidence_file_sha256','basis','decided_by'])
        kept_rows=[r for r in observation_rows if r['kept']]
        aggregate,units,aggregation=aggregate_cells(counts,kept_rows,design_confirmed=bool(payload.get('identity',{}).get('design_confirmed')))
        writer.table('cell_sample_donor_counts',[dict(sample_id=sample,donor=donor,cells=sum((r['sample_id'] or 'unknown')==sample and (r['donor'] or 'unknown')==donor for r in kept_rows),independent_n=None) for sample,donor in sorted({(r['sample_id'] or 'unknown',r['donor'] or 'unknown') for r in kept_rows})])
        if aggregate is not None:
            writer.matrix('cell_pseudobulk',aggregate)
            writer.table('cell_pseudobulk_units',[{**u,'unit_id':str(i),'sample_ids':';'.join(u['sample_ids'])} for i,u in enumerate(units)])
        summary['cell_sample_donor_aggregation']=aggregation
        summary['replicate_consistency']={'status':'not_computable','reason':'donor_contrast_required_even_when_mapping_ready'}
        steps.append(dict(key='cell_sample_donor_aggregation',status='completed' if aggregation['status']=='ready' else 'not_computable',reason=aggregation['reason'],params={'statistical_unit':'donor','exploration_allowed':True}))
    writer.table('observations',observation_rows);writer.table('features',feature_rows)
    tables=[dict(key=item['key'],label=item['key'],status='completed',reason=None) for item in writer.artifacts if item['format']=='tsv']
    if mode=='compute':
        for table in tables:
            if table['key'] in {'markers','markers_top'}:table.update(status=marker_state['status'],reason=marker_state['reason'])
    methods='\n'.join([f"Engine: {ENGINE_VERSION}",'Statistical unit: exploratory spot; clusters and markers are not independent-donor disease contrasts.',
        f"X=natural log1p(normalize_total target {config['target_sum']}); counts retains filtered integer input; normalized is sparse float32.",
        'HVG: Seurat log1p dispersion, 20 bins, stable feature ID breaks ties. Scale HVG only, sample SD, clip 10.',
        f"PCA arpack components={config['pca_components']} capped by data, seed={config['seed']}; neighbors={config['neighbors']} capped by observations, euclidean sklearn/umap; UMAP 2D min_dist0.5 spread1 epochs500 seed={config['seed']}.",
        'Leiden igraph undirected weighted iterations2 resolution configured; canonical cluster order by minimum raw index.',
        'Markers: tie-corrected Wilcoxon, cluster-wise all-filtered-gene BH; effect log2((mean normalized group+1e-9)/(mean normalized rest+1e-9)).',
        'Actual steps: '+canonical(steps).decode(),'Configured/effective params: '+canonical(config).decode()])
    if mode=='qc':methods=f'Engine: {ENGINE_VERSION}\nRaw QC and one-pass filtering only. No normalization, dimensionality reduction, clustering or hypothesis tests executed.\n'+canonical(steps).decode()
    if single_cell:
        methods=methods.replace('exploratory spot','exploratory cell').replace('independent-donor disease contrasts.','independent-donor disease contrasts. Cell IDs are scoped to the fixed dataset and sample; technical samples do not increase donor n.')+'\nCell labels retain marker/file evidence, reviewer and unknown status. Donor inference requires a separate confirmed donor contrast; cell aggregation is descriptive counts only.'
        methods+='\nPer-library QC uses original import library IDs. scDblFinder results are model predictions, not confirmed doublets. decontX is an independent floating correction layer; normalization, markers and pseudobulk retain original integer counts. Tool states/versions: '+canonical(algorithms['summary']).decode()
    if single_cell and mode=='compute':methods+='\nEmbedding adjustments only; raw counts, normalized/log1p, marker expression and pseudobulk are not replaced. Batch mixing metrics are descriptive, not biological quality scores. Actual integration states, parameters, versions and downstream representation: '+canonical(summary['single_cell_integration']).decode()
    if subset_state:methods+='\nSubset QC, retained genes, scDblFinder predictions and decontX correction are inherited from the frozen parent; capture models were not rerun. Normalization, HVG, embeddings, clusters and markers are recomputed for the selected cells. Parent and selection: '+canonical(subset_state['provenance']).decode()
    writer.add('methods',methods.encode(),'txt');writer.json('recipe',config)
    writer.add('reproduce',b"# Run inside supplied fixed Linux image. Payload must reference only exported authorized local input files.\nimport json, os, struct, subprocess, sys\nfrom pathlib import Path\npayload=json.loads(Path(sys.argv[1]).read_bytes())\nbody=json.dumps(payload,allow_nan=False).encode()\nworker=Path(__import__('app.adapters.bio_engine.worker',fromlist=['x']).__file__)\nr=subprocess.run([sys.executable,'-I','-B',str(worker),str(os.getpid())],input=struct.pack('!I',len(body))+body,capture_output=True,env={},timeout=1380)\nif r.returncode: raise RuntimeError(r.stderr.decode())\nprint(r.stdout.decode())\n",'py')
    if payload.get('_trusted_lock') is not None:writer.add('requirements_bio_lock',payload['_trusted_lock'],'txt')
    import resource
    resources={'wall_seconds':time.monotonic()-started,'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'peak_rss_includes_warmup':True}
    resources.update(memory_bounds(single_cell=single_cell,params=config))
    resources.update(max_output_bytes=selected_limits.max_output_bytes,max_member_bytes=selected_limits.max_member_bytes)
    manifest={'schema_version':1,'engine_version':ENGINE_VERSION,'identity':payload.get('identity',{}),
        'environment_digest':payload.get('identity',{}).get('environment_digest'),'code_digest':payload.get('identity',{}).get('code_digest'),
        'raw_source':payload.get('identity',{}).get('raw_source'),'params':config,'steps':steps,'summary':summary,'tables':tables,
        'inputs':[{k:v for k,v in member.items() if k!='path'}|{'key':key} for key,member in payload['raw']['members'].items()],
        'layers':layers,'resources':resources,'members':[{k:v for k,v in a.items() if k!='path'} for a in writer.artifacts]}
    if single_cell:
        manifest.update(assay='single_cell',observation_level='cell',samples=payload['raw']['manifest'].get('samples',[]),resource_estimate=resource_estimate(payload['raw']['manifest'],config))
    if subset_state:manifest['subset']=subset_state['provenance']
    writer.json('manifest',manifest)
    return clean(dict(status='completed',engine_version=ENGINE_VERSION,steps=steps,summary=summary,outputs=writer.artifacts,manifest=manifest,checks={'raw_hashes':'verified','h5ad_roundtrip':'verified' if mode=='compute' else 'not_requested'},effective_params=config))


def spatial_image(raw):
    images=raw['manifest'].get('spatial',{}).get('images',[])
    scales=raw['manifest'].get('spatial',{}).get('scalefactors',{})
    for info in images:
        # Alignment/detected-tissue previews are preserved source images, but
        # only an explicitly calibrated tissue image is a coordinate backdrop.
        if info.get('scale_field') not in {'tissue_hires_scalef','tissue_lowres_scalef'}:continue
        member=next((m for m in raw['members'].values() if m.get('source_member_name')==info.get('source_member_name') and m.get('role')=='tissue_image'),None)
        if member:
            scale=float(scales[info['scale_field']]);image=np.asarray(Image.open(member['path']).convert('RGB'))
            return image,scale,float(scales.get('spot_diameter_fullres',6))*scale/2,member['sha256']
    return None,1.,3.,None
