"""Standalone render from a frozen processed object; no reclustering."""
import json
from pathlib import Path
import numpy as np
import anndata as ad
from matplotlib import pyplot as plt
from matplotlib.patches import Polygon
from matplotlib.lines import Line2D
from app.adapters.bio_engine import ENGINE_VERSION
from app.adapters.bio_engine.manifest import Writer,clean
from app.adapters.bio_engine.pipeline import load_raw,spatial_image
from app.adapters.bio_engine import plots


def render(payload):
    raw,features,barcodes,positions=load_raw(payload['raw']);writer=Writer(payload['output_directory']);writer.identity=payload.get('identity',{})
    processed=payload['processed']; members=processed['members']
    import hashlib
    for member in members.values():
        path=Path(member['path'])
        if path.stat().st_size!=member['size_bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=member['sha256']:
            raise ValueError('processed_hash_mismatch')
    obj=ad.read_h5ad(members['processed']['path'])
    config=dict(payload['config']);kind=config['kind']
    panel=config.get('panel','default')
    permitted={'qc':{'default','distribution','scatter','violin','mitochondrial','sample_id','section','batch'},'pca':{'default','scores','variance'},'umap':{'default','scores'}}
    if panel not in permitted.get(kind,{'default'}):raise ValueError('invalid_parameter_figure_panel')
    config.update(width_inches=config.get('width',1800)/config.get('dpi',300),height_inches=config.get('height',1500)/config.get('dpi',300),cmap=config.get('palette','viridis'))
    if config['cmap'] not in {'viridis','magma','tab20'}: raise ValueError('unsupported_palette')
    if len(config.get('title',''))>200: raise ValueError('title_limit')
    mask=np.zeros(len(barcodes),dtype=bool);mask[obj.obs['raw_index'].to_numpy(dtype=int)]=True
    clusters=obj.obs['cluster'].astype(str).to_numpy()
    if kind=='pca' and panel=='variance':
        variance=np.asarray(json.loads(Path(members['pca_variance_data']['path']).read_bytes())['variance_ratio'])
        plots.pca_variance_figure(writer,variance,config)
    elif kind in {'pca','umap'}:
        points=obj.obsm['X_'+kind]
        color_by=config.get('color_by','cluster')
        if color_by not in {'cluster','sample_id','section','batch'}:raise ValueError('invalid_parameter_color_by')
        labels=clusters if color_by=='cluster' else obj.obs[color_by].astype(str).to_numpy() if color_by in obj.obs else np.asarray(['unknown']*len(clusters))
        plots.embedding_figure(writer,points,clusters,list(obj.obs_names),kind,config,labels)
    elif kind in {'spatial_cluster','spatial_gene'}:
        image,scale,radius,image_sha=spatial_image(payload['raw']);config['tissue_image_sha256']=image_sha
        if not positions: raise ValueError('spatial_coordinates_unavailable')
        if kind=='spatial_cluster':
            values=np.full(len(barcodes),np.nan);values[mask]=clusters.astype(float)
            plots.spatial(writer,kind,positions,barcodes,mask,values,config,image,scale,radius)
        else:
            genes=config.get('gene_ids',[])
            if not 1<=len(genes)<=16 or len(set(genes))!=len(genes): raise ValueError('gene_panel_limit')
            matrix=obj.X if config.get('layer','log1p')=='log1p' else obj.layers[config['layer']]
            for i,gene in enumerate(genes):
                if gene not in obj.var_names: raise ValueError('stable_feature_id_not_found')
                values=np.full(len(barcodes),np.nan);values[mask]=matrix[:,list(obj.var_names).index(gene)].toarray().ravel()
                plots.spatial(writer,kind+'_'+str(i),positions,barcodes,mask,values,{**config,'title':config.get('title') or gene,'gene_ids':[gene]},image,scale,radius)
    elif kind in {'marker_dotplot','marker_heatmap'}:
        import csv
        rows=list(csv.DictReader(Path(members['markers_top']['path']).read_text().splitlines(),delimiter='\t'))
        saved=members.get(kind+'_data')
        symbols=dict(zip(obj.var_names,obj.var['symbol'])) if 'symbol' in obj.var else {}
        data=json.loads(Path(saved['path']).read_bytes()) if saved else None
        if data is not None and (not config.get('gene_ids') or set(config['gene_ids'])<=set(data.get('feature_ids',[]))):
            plots.marker_figures_from_saved(writer,data,config,symbols)
        else:
            plots.marker_figures(writer,obj.layers['counts'],obj.X,clusters,list(obj.var_names),rows,{**config,'feature_symbols':symbols})
    elif kind=='qc':
        from app.adapters.bio_engine.qc import quality_control
        qc=quality_control(raw,features,barcodes,positions,processed['manifest']['params'])
        if panel in {'sample_id','section','batch'}:
            import csv
            rows=list(csv.DictReader(Path(members['observations']['path']).read_text().splitlines(),delimiter='\t'))
            mapping={row['barcode']:row for row in rows}
            values=[mapping.get(b,{}).get(panel) if mapping.get(b,{}).get(panel+'_status')=='known' else 'unknown' for b in barcodes]
            plots.qc_stratified(writer,qc,panel,values,config)
        else:plots.qc_figures(writer,qc,config)
    elif kind=='annotation' and raw is not None and payload['raw']['manifest'].get('assay')=='single_cell':
        render_cell_annotation(writer,obj,payload.get('annotation'),config)
    elif kind=='annotation':
        annotation=payload.get('annotation')
        if not annotation: raise ValueError('annotation_required')
        for item in annotation['members'].values():
            if hashlib.sha256(Path(item['path']).read_bytes()).hexdigest()!=item['sha256']: raise ValueError('annotation_hash_mismatch')
        geometry=json.loads(Path(annotation['members']['geometry']['path']).read_bytes())
        assignments=json.loads(Path(annotation['members']['assignments']['path']).read_bytes())
        image,scale,radius,image_sha=spatial_image(payload['raw']);config['tissue_image_sha256']=image_sha;fig,ax=plt.subplots()
        if image is not None:ax.imshow(image,origin='upper')
        labels={l['id']:l for l in annotation['labels']}
        ordered=sorted(labels)
        label_colors,effective=plots.categorical_colors(ordered,config.get('cmap','tab20'))
        for i,region in enumerate(geometry['regions']):
            points=plots.transform_coordinates(region['points'],scale)
            color=label_colors[region['label_id']]
            ax.add_patch(Polygon(points,facecolor=color,edgecolor=color,alpha=.25))
        pmap={p['barcode']:p for p in positions}
        for row in assignments['rows']:
            if row['barcode'] in pmap:
                p=pmap[row['barcode']];ax.plot(p['pxl_col_in_fullres']*scale,p['pxl_row_in_fullres']*scale,'.',color='#777777' if row['label_id'] is None else label_colors[row['label_id']],markersize=2)
        if image is None:ax.invert_yaxis()
        handles=[Line2D([],[],marker='o',linestyle='none',color=label_colors[identifier],label=labels[identifier]['name']+' ['+labels[identifier].get('status','unknown')+']') for identifier in ordered]
        if any(row['label_id'] is None for row in assignments['rows']):handles.append(Line2D([],[],marker='o',linestyle='none',color='#777777',label='unknown'))
        ax.set_aspect('equal');ax.legend(handles=handles,fontsize=7);ax.set_title(config.get('title') or 'Manual region-enriched labels (exploratory)')
        plots.save(writer,'annotation',fig,{'geometry':geometry,'assignments':assignments,'labels':annotation['labels'],'label_colors':label_colors,'image_scale':scale},{**config,'panel':'default','effective_palette':effective})
    else:raise ValueError('unsupported_figure_kind')
    manifest={'schema_version':1,'engine_version':ENGINE_VERSION,'renderer_version':'bio_plots_v1','identity':payload.get('identity',{}),'config':config,
              'members':[{k:v for k,v in a.items() if k!='path'} for a in writer.artifacts]}
    writer.json('manifest',manifest)
    return clean({'status':'completed','engine_version':ENGINE_VERSION,'outputs':writer.artifacts,'manifest':manifest,'summary':{'figures':sum(m['format']=='png' for m in writer.artifacts)},'steps':[{'key':'render','status':'completed','reason':None,'params':config}], 'checks':{'source_hashes':'verified'},'effective_params':config})


def render_cell_annotation(writer,obj,annotation,config):
    import hashlib
    if not annotation:raise ValueError('annotation_required')
    for item in annotation['members'].values():
        path=Path(item['path'])
        if path.stat().st_size!=item['size_bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
            raise ValueError('annotation_hash_mismatch')
    assignments=json.loads(Path(annotation['members']['assignments']['path']).read_bytes())['rows']
    by_cell={r['barcode']:r for r in assignments};cells=list(obj.obs_names)
    labels={l['id']:l for l in annotation['labels']}
    if len(by_cell)!=len(assignments) or set(by_cell)!=set(cells) or any(r.get('label_id') is not None and r['label_id'] not in labels for r in assignments):
        raise ValueError('annotation_cell_axis_invalid')
    display=[]
    for cell in cells:
        row=by_cell[cell];label=labels.get(row.get('label_id'));status=row.get('status')
        if label is None or status=='unknown' or label.get('status')=='unknown':display.append('unknown')
        else:display.append(label['name']+' ['+('uncertain' if status=='uncertain' else label.get('status','proposed'))+']')
    display=np.asarray(display);points=np.asarray(obj.obsm['X_umap'])
    if points.shape!=(len(cells),2) or not np.isfinite(points).all():raise ValueError('annotation_embedding_invalid')
    colors,effective=plots.categorical_colors(sorted(set(display)),config.get('cmap','tab20'))
    fig,ax=plt.subplots()
    for label in sorted(set(display)):
        selected=display==label;ax.scatter(points[selected,0],points[selected,1],s=8,label=label,color=colors[label])
    ax.set(xlabel='UMAP1',ylabel='UMAP2',title=config.get('title') or 'Cell annotation candidates')
    ax.legend(fontsize=7)
    plots.save(writer,'annotation',fig,dict(barcodes=cells,coordinates=points,color_labels=display,category_colors=colors,
        labels=annotation['labels'],assignments=assignments,basis='saved_X_umap_no_recomputation'),{**config,'effective_palette':effective})
