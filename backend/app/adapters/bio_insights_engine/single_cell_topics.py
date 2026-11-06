"""Optional single-cell methods; all numeric inputs are read after isolation."""
from collections import defaultdict
import io
import numpy as np
from scipy import sparse,stats
from app.domain.bio_insights.single_cell_topic_contracts import SingleCellTopicConfig
from app.domain.bio_insights.single_cell_topics import topic_selection,validate_topic_design
from .inputs import load_processed,read_array,read_csr,document

REPRESENTATIONS={'pca':'pca','pca_unadjusted':'integration_x_pca_unadjusted','pca_harmony':'integration_x_pca_harmony'}


def _successful(result):
    if result.get('status') not in ('completed','not_computable'):
        raise ValueError('single_cell_topic_tool_failed:'+str(result.get('reason'))+':'+str(result.get('logs',[]))[:1500])


def run_topics(payload,writer):
    from app.adapters.single_cell_r.topics import get_topics_bridge
    config=SingleCellTopicConfig.model_validate(payload['config'])
    source=next(s for s in payload['sources'] if s['source_kind']=='bio_processed_dataset_version' and s['source_id']==config.processed_source_id)
    loaded=load_processed(source,'spot_exploratory' if config.method=='genie3' else 'donor_paired')
    # Validate fixed clusters against their declared source leaf, not metadata alone.
    from .inputs import iter_table
    retained_barcodes={b for _,b in loaded['retained_keys']}
    clusters={r['barcode']:str(r['cluster']) for _,r in iter_table(source['members']['observations'],format='tsv') if r.get('cluster') not in (None,'') and r['barcode'] in retained_barcodes}
    if clusters!=source['metadata'].get('cell_clusters',{}):raise ValueError('topic_cluster_axis_mismatch')
    for s in payload['sources']:
        if s['source_kind']=='bio_annotation_version' and document(s['members']['assignments'])!=s['metadata']['assignments']:raise ValueError('topic_annotation_mismatch')
    if config.method=='genie3':source['metadata']['retained_feature_ids']=loaded['feature_ids']
    selection=topic_selection(config,payload['sources'],loaded['observations'])
    preview=validate_topic_design(config,payload['sources'],loaded['observations'])
    if not preview.executable:raise ValueError('topic_design_blocked:'+','.join(r.code for r in preview.blocking_reasons))
    cell_index={b:i for i,(_,b) in enumerate(loaded['retained_keys'])}
    indices=[cell_index[r['barcode']] for r in selection['selected']]
    bridge=get_topics_bridge()
    execute={'slingshot':_trajectory,'genie3':_regulation,'cellchat':_communication}[config.method]
    result=execute(config,source,loaded,selection,indices,bridge,writer)
    writer.table('topic_selection',selection['all_cells'],['barcode','cluster','label_id','annotation_status','donor','condition','sample','batch','selected','exclusion_reason','unit_id'])
    writer.table('topic_units',selection['units'],['unit_id','donor','condition','cell_count','samples','label_counts'])
    methods=dict(name=config.method,config=config.model_dump(mode='json'),input_layer=config.representation if config.method=='slingshot' else 'unintegrated_log1p',
        source_processed_id=config.processed_source_id,source_annotation_id=config.annotation_source_id,labels_confirmed=config.labels_confirmed,label_basis=config.label_basis,
        cell_selection='explicit_conditions_clusters_and_fixed_labels_no_implicit_sampling',exclusions=selection['exclusions'],label_names=selection['label_names'],
        actual_units=[u.model_dump() for u in preview.actual_units],warnings=preview.warnings,**result['methods'])
    writer.json('topic_methods',methods)
    scope='donor_inference' if config.method=='cellchat' and config.communication_mode!='per_donor' else 'sample_exploratory'
    return dict(summary=dict(topic_method=config.method,selected_cells=len(indices),excluded_cells=sum(selection['exclusions'].values()),
        donor_count=len({r['donor'] for r in selection['selected'] if r['donor']}),unit_count=len(selection['units']),labels_confirmed=config.labels_confirmed,
        actual_units=methods['actual_units'],warnings=preview.warnings,**result['summary']),methods=methods,inference_scope=scope,
        provenance={'sources':[{k:s[k] for k in ('source_kind','source_id','sha256')} for s in payload['sources']]})


def _trajectory(config,source,loaded,selection,indices,bridge,writer):
    matrix=read_array(source['members'][REPRESENTATIONS[config.representation]])
    if matrix.shape[0]!=len(loaded['retained_keys']) or matrix.ndim!=2:raise ValueError('trajectory_embedding_axis_invalid')
    matrix=np.asarray(matrix[indices,:min(config.n_components,matrix.shape[1])],dtype='float64')
    cells=[r['barcode'] for r in selection['selected']];clusters=[r['cluster'] for r in selection['selected']]
    native=bridge.slingshot(matrix,cells,clusters,config.root_cluster,config.seed);_successful(native)
    rows=[];curves=[]
    for j,lineage in enumerate(native.get('lineage_ids',[])):
        for i,cell in enumerate(cells):
            pt=native['pseudotime'][i,j];weight=native['weights'][i,j]
            rows.append(dict(barcode=cell,cluster=clusters[i],lineage_id=lineage,pseudotime=float(pt) if np.isfinite(pt) else None,
                weight=float(weight),covered=bool(np.isfinite(pt) and weight>0)))
        curve=np.asarray(native['curves'][j])
        curves.extend(dict(lineage_id=lineage,point_index=i,**{f'dimension_{k+1}':float(x) for k,x in enumerate(point)}) for i,point in enumerate(curve))
    writer.table('trajectory_results',rows,['barcode','cluster','lineage_id','pseudotime','weight','covered'])
    writer.table('trajectory_curves',curves,['lineage_id','point_index']+[f'dimension_{j+1}' for j in range(matrix.shape[1])])
    writer.json('trajectory_native',native)
    plot=dict(method='slingshot',cells=cells,clusters=clusters,coordinates=matrix[:,:2],lineage_ids=native.get('lineage_ids',[]),curves=[np.asarray(c)[:,:2] for c in native.get('curves',[])],representation=config.representation,root=config.root_cluster)
    _plot(plot,writer)
    return dict(summary=dict(result_member_key='trajectory_results',row_count=len(rows),lineage_count=len(native.get('lineage_ids',[])),
        uncovered_cells=len(cells)-len({r['barcode'] for r in rows if r['covered']}),status=native['status'],reason=native.get('reason')),
        methods=dict(versions=native['versions'],logs=native.get('logs',[]),parameters=native.get('parameters',{}),lineage_clusters=native.get('lineage_clusters',[]),
            actual_components=matrix.shape[1],interpretation='relative_pseudotime_not_real_time_or_causality'))


def _regulation(config,source,loaded,selection,indices,bridge,writer):
    positions={g:i for i,g in enumerate(loaded['feature_ids'])}
    if not set(config.gene_ids)<=set(positions):raise ValueError('regulation_gene_axis_mismatch')
    expression=loaded['log1p'][indices][:,[positions[g] for g in config.gene_ids]].tocsr()
    cells=[r['barcode'] for r in selection['selected']]
    runs=[]
    for seed in (config.seed,config.stability_seed):
        native=bridge.genie3(expression,cells,config.gene_ids,config.tf_ids,seed,config.n_trees);_successful(native)
        if native['status']!='completed':raise ValueError('regulation_not_computable:'+str(native.get('reason')))
        runs.append(native);bridge.release_temporaries()
    rows=[]
    for i,tf in enumerate(config.tf_ids):
        for j,gene in enumerate(config.gene_ids):
            if tf==gene:continue
            a,b=float(runs[0]['weights'][i,j]),float(runs[1]['weights'][i,j])
            rows.append(dict(regulator=tf,target=gene,regulator_symbol=loaded['symbols'].get(tf),target_symbol=loaded['symbols'].get(gene),
                weight=a,stability_weight=b,absolute_weight_difference=abs(a-b)))
    rows.sort(key=lambda r:(-r['weight'],r['regulator'],r['target']))
    first=np.asarray([r['weight'] for r in rows]);second=np.asarray([r['stability_weight'] for r in rows])
    rho=float(stats.spearmanr(first,second).statistic) if np.ptp(first)>0 and np.ptp(second)>0 else None
    k=min(20,len(rows));top1={(r['regulator'],r['target']) for r in rows[:k]};top2={(r['regulator'],r['target']) for r in sorted(rows,key=lambda r:(-r['stability_weight'],r['regulator'],r['target']))[:k]}
    stability=dict(seeds=[config.seed,config.stability_seed],spearman_weight_rank=rho,top_k=k,top_k_overlap=len(top1&top2),top_k_jaccard=len(top1&top2)/len(top1|top2) if top1|top2 else None,
        note='two_seed_random_stability_not_external_replication')
    writer.table('regulation_results',rows);writer.json('regulation_stability',stability)
    writer.json('regulation_native',runs)
    _plot(dict(method='genie3',rows=rows[:20],stability=stability),writer)
    return dict(summary=dict(result_member_key='regulation_results',row_count=len(rows),gene_count=len(config.gene_ids),tf_count=len(config.tf_ids),status='completed',stability=stability),
        methods=dict(versions=runs[0]['versions'],logs=[line for r in runs for line in r.get('logs',[])],parameters=dict(n_trees=config.n_trees,seeds=stability['seeds']),
            tf_ids=config.tf_ids,gene_ids=config.gene_ids,tf_basis=config.tf_basis,interpretation='predictive_importance_not_pvalue_or_causality'))


def symbol_expression(counts,feature_ids,symbols,wanted):
    """Sum exact duplicate symbols, normalize with all raw Gene Expression counts."""
    selected=[(i,symbols.get(g)) for i,g in enumerate(feature_ids) if symbols.get(g) in wanted]
    axis=sorted({symbol for _,symbol in selected})
    mapping={g:i for i,g in enumerate(axis)}
    projection=sparse.csr_matrix((np.ones(len(selected)),([i for i,_ in selected],[mapping[g] for _,g in selected])),shape=(len(feature_ids),len(axis)))
    expression=(counts@projection).tocsr().astype('float64')
    total=np.asarray(counts.sum(axis=1)).ravel()
    expression=expression.multiply(np.divide(10000.,total,out=np.zeros_like(total,dtype=float),where=total>0)[:,None]).tocsr()
    expression.data=np.log1p(expression.data)
    return expression,axis,dict(total_input_genes=len(feature_ids),matched_feature_ids=len(selected),matched_symbols=len(axis),duplicate_symbols_aggregated=len(selected)-len(axis),missing_resource_symbols=sorted(set(wanted)-set(axis)),normalization_denominator='all_raw_gene_expression_counts',target_sum=10000)


def communication_comparison(rows,units,config):
    """Only independent donor network scores enter these tests, never cells."""
    if config.communication_mode=='per_donor':return []
    left,right=config.condition_values;by_unit={u['unit_id']:u for u in units};families=defaultdict(dict)
    for row in rows:
        values=families[(row['sender'],row['receiver'],row['interaction_id'])]
        if row['status']!='computed':continue
        u=by_unit[row['unit_id']]
        values[(u['donor'],u['condition'])]=row['probability']
    output=[]
    for key,values in sorted(families.items()):
        donors=[sorted({d for d,c in values if c==condition}) for condition in (left,right)]
        paired=config.communication_mode=='paired'
        if paired:donors=[sorted(set(donors[0])&set(donors[1]))]*2
        a=np.asarray([values[d,left] for d in donors[0]],float);b=np.asarray([values[d,right] for d in donors[1]],float)
        reason='insufficient_computable_donors' if min(len(a),len(b))<3 else None
        statistic=p=None
        if reason is None:
            if paired and np.ptp(b-a)==0 or not paired and np.ptp(a)==0 and np.ptp(b)==0:reason='no_estimable_variance'
            else:
                test=stats.ttest_rel(b,a) if paired else stats.ttest_ind(b,a,equal_var=False)
                if np.isfinite(test.statistic) and np.isfinite(test.pvalue):statistic,p=float(test.statistic),float(test.pvalue)
                else:reason='nonfinite_test'
        output.append(dict(sender=key[0],receiver=key[1],interaction_id=key[2],denominator=left,numerator=right,
            n_denominator=len(a),n_numerator=len(b),complete_pairs=len(a) if paired else 0,
            mean_denominator=float(a.mean()) if len(a) else None,mean_numerator=float(b.mean()) if len(b) else None,
            difference=float(b.mean()-a.mean()) if len(a) and len(b) else None,t_statistic=statistic,donor_p_value=p,donor_q_value=None,
            status='tested' if p is not None else 'not_computable',reason=reason,donors_denominator=donors[0],donors_numerator=donors[1]))
    valid=[r for r in output if r['donor_p_value'] is not None]
    if valid:
        for row,q in zip(valid,stats.false_discovery_control([r['donor_p_value'] for r in valid],method='bh')):row['donor_q_value']=float(q)
    return output


def _communication(config,source,loaded,selection,indices,bridge,writer):
    from app.adapters.single_cell_r.topics import get_cellchat_resource
    resource=get_cellchat_resource(9606)
    if resource['resource_id']!=config.lr_resource_id:raise ValueError('communication_resource_identity_mismatch')
    allowed={r['interaction_id'] for r in resource['interactions']};lr_ids=config.lr_ids or sorted(allowed)
    if not set(lr_ids)<=allowed:raise ValueError('communication_lr_unknown')
    expression,genes,matching=symbol_expression(loaded['counts'][indices],loaded['feature_ids'],loaded['symbols'],resource['gene_symbols'])
    cells=selection['selected'];positions=defaultdict(list)
    for i,row in enumerate(cells):positions[row['unit_id']].append(i)
    results=[];unit_status=[];logs=[];versions={};native_results=[]
    for unit in selection['units']:
        take=positions[unit['unit_id']];counts=unit['label_counts']
        if any(counts.get(label,0)<=config.min_cells for label in config.label_ids):
            native=dict(status='not_computable',reason='group_too_small',edge_rows=[],logs=[],versions={})
        elif not genes:native=dict(status='not_computable',reason='no_resource_genes',edge_rows=[],logs=[],versions={})
        else:
            native=bridge.cellchat(expression[take].tocsr(),[cells[i]['barcode'] for i in take],genes,[cells[i]['label_id'] for i in take],9606,lr_ids,config.seed,config.n_boot,config.min_cells)
            _successful(native);bridge.release_temporaries()
        versions.update(native.get('versions',{}));logs.extend([unit['unit_id']+': '+str(v) for v in native.get('logs',[])])
        native_results.append(dict(unit_id=unit['unit_id'],**native))
        by_key={(r['sender'],r['receiver'],r['interaction_id']):r for r in native.get('edge_rows',[])}
        unit_status.append(dict(**unit,status=native['status'],reason=native.get('reason'),modeled_edges=len(by_key)))
        for sender in config.label_ids:
            for receiver in config.label_ids:
                for identity in lr_ids:
                    row=by_key.get((sender,receiver,identity))
                    results.append(dict(unit_id=unit['unit_id'],donor=unit['donor'],condition=unit['condition'],sender=sender,receiver=receiver,
                        interaction_id=identity,pathway=row.get('pathway') if row else None,probability=row['probability'] if row else None,
                        cell_permutation_p_value=row['p_value'] if row else None,status='computed' if row else 'not_computable',
                        reason=None if row else native.get('reason') or 'interaction_not_modeled'))
    comparison=communication_comparison(results,selection['units'],config)
    writer.table('communication_results',results);writer.table('communication_units',unit_status)
    writer.table('communication_comparisons',comparison,['sender','receiver','interaction_id','denominator','numerator','n_denominator','n_numerator','complete_pairs','mean_denominator','mean_numerator','difference','t_statistic','donor_p_value','donor_q_value','status','reason','donors_denominator','donors_numerator'])
    writer.json('communication_native',native_results);writer.json('communication_resource',resource)
    _plot(dict(method='cellchat',rows=results,labels=config.label_ids,label_names=selection['label_names']),writer)
    return dict(summary=dict(result_member_key='communication_results',row_count=len(results),status='completed' if any(r['status']=='computed' for r in results) else 'not_computable',
        computable_units=sum(u['status']=='completed' for u in unit_status),modeled_edges=sum(r['status']=='computed' for r in results),donor_tested_edges=sum(r['status']=='tested' for r in comparison),
        resource_id=resource['resource_id'],resource_interactions=len(lr_ids)),methods=dict(versions=versions,logs=logs,matching=matching,resource={k:v for k,v in resource.items() if k not in ('interactions','complexes')},
        parameters=dict(n_boot=config.n_boot,min_cells_exclusive=config.min_cells,seed=config.seed,lr_ids=lr_ids),
        donor_test='paired_t' if config.communication_mode=='paired' else 'welch_t' if config.communication_mode=='unpaired' else 'not_requested',
        correction='BH_over_computable_predeclared_sender_receiver_LR_family',comparison_direction='condition_values[1] - condition_values[0]',
        interpretation='model_predictions_not_measured_interactions_cell_permutation_not_donor_inference'))


def _plot(data,writer):
    from matplotlib import pyplot as plt
    writer.json('topic_plot_data',data)
    fig,ax=plt.subplots(figsize=(8,5))
    if data['method']=='slingshot':
        coords=np.asarray(data['coordinates']);clusters=np.asarray(data['clusters'])
        for group in sorted(set(clusters)):
            take=clusters==group;ax.scatter(coords[take,0],coords[take,1],s=7,alpha=.6,label=str(group))
        for name,curve in zip(data['lineage_ids'],data['curves']):
            curve=np.asarray(curve);ax.plot(curve[:,0],curve[:,1],linewidth=2,label=name)
        ax.set(xlabel=data['representation']+' dimension 1',ylabel=data['representation']+' dimension 2',title='Slingshot | root cluster '+data['root']);ax.legend(bbox_to_anchor=(1,1),fontsize=7)
    elif data['method']=='genie3':
        rows=list(reversed(data['rows']));labels=[(r.get('regulator_symbol') or r['regulator'])+' → '+(r.get('target_symbol') or r['target']) for r in rows]
        y=np.arange(len(rows));ax.barh(y-.18,[r['weight'] for r in rows],height=.35,label='Primary seed');ax.barh(y+.18,[r['stability_weight'] for r in rows],height=.35,label='Second seed')
        ax.set_yticks(y,labels,fontsize=7);ax.set(xlabel='GENIE3 predictive importance (not P)',title='Top 20 edges | two fixed seeds');ax.legend(fontsize=8)
    else:
        labels=data['labels'];matrix=np.full((len(labels),len(labels)),np.nan)
        for i,sender in enumerate(labels):
            for j,receiver in enumerate(labels):
                by_unit=defaultdict(list)
                for r in data['rows']:
                    if r['sender']==sender and r['receiver']==receiver and r['probability'] is not None:by_unit[r['unit_id']].append(r['probability'])
                if by_unit:matrix[i,j]=np.mean([sum(values) for values in by_unit.values()])
        im=ax.imshow(np.ma.masked_invalid(matrix),cmap='viridis',vmin=0);fig.colorbar(im,ax=ax,label='Mean per-unit sum of modeled LR probabilities')
        names=[data['label_names'].get(v,v) for v in labels];ax.set_xticks(range(len(labels)),names,rotation=35,ha='right');ax.set_yticks(range(len(labels)),names)
        ax.set(xlabel='Receiver',ylabel='Sender',title='CellChat | literature demo LR subset')
        for i in range(len(labels)):
            for j in range(len(labels)):ax.text(j,i,'NA' if not np.isfinite(matrix[i,j]) else f'{matrix[i,j]:.3g}',ha='center',va='center',fontsize=8,color='white' if np.isfinite(matrix[i,j]) else 'black')
    fig.tight_layout();stream=io.BytesIO();fig.savefig(stream,format='png',dpi=180);plt.close(fig)
    writer.add('topic_plot',stream.getvalue(),'png','figure')
