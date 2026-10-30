"""Deterministic single figures and shared full-resolution geometry."""
import io
import colorsys
import hashlib
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
from matplotlib import pyplot as plt
from matplotlib.font_manager import FontProperties,findfont
from matplotlib.patches import Circle
from matplotlib.collections import PatchCollection
from matplotlib.colors import BoundaryNorm,ListedColormap,to_rgba
from matplotlib.lines import Line2D


def categorical_colors(labels,palette='tab20',numeric=False):
    """Frozen IDs, rather than current category counts, determine cluster RGB."""
    labels=[str(label) for label in labels]
    known=[label for label in labels if label!='unknown']
    colors={}
    for ordinal,label in enumerate(known):
        index=int(label) if numeric else ordinal
        if numeric and not 0<=index<50:raise ValueError('cluster_palette_limit')
        if palette=='tab20':
            hue=(index*137.50776405003785)%360
            colors[label]=(*colorsys.hls_to_rgb(hue/360,.52,.65),1.)
        else:
            colors[label]=plt.get_cmap(palette)(index/49 if numeric else ordinal/max(1,len(known)-1))
    if 'unknown' in labels:colors['unknown']=to_rgba('#777777')
    effective='paperassist_golden_angle_hsl_v1' if palette=='tab20' else 'matplotlib_'+palette+('_fixed50_v1' if numeric else '_categorical_v1')
    return colors,effective


def transform_coordinates(points,image_scale,preview_scale=1.):
    if not 0<image_scale<=10 or not 0<preview_scale<=1: raise ValueError('invalid_coordinate_scale')
    values=np.asarray(points,dtype=np.float64)
    if values.ndim!=2 or values.shape[1]!=2 or not np.isfinite(values).all(): raise ValueError('invalid_coordinates')
    return values*(image_scale*preview_scale)


def save(writer,key,fig,data,config=None):
    config=config or {};language=config.get('output_language','en')
    font_path=Path('/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc')
    if language=='zh-CN':
        from matplotlib.text import Text
        font=FontProperties(fname=font_path)
        translations={'Total counts':'总计数','Detected genes':'检测基因数','Raw':'原始','Filtered':'过滤后',
            'QC: raw observations':'原始观测质量控制','Explained variance ratio':'解释方差比例','Mean log1p':'平均 log1p',
            'No matrix observation':'无矩阵观测','Excluded observation':'本次过滤排除','Missing value':'缺失值',
            'Retained outside tissue':'保留的组织外观测','Mitochondrial fraction':'线粒体计数比例',
            'Mitochondrial fraction unavailable: rule unconfirmed':'线粒体比例不可用：规则未确认',
            'Fullres x × image scale':'全分辨率 x × 图像缩放','Fullres y × image scale':'全分辨率 y × 图像缩放',
            'cluster':'聚类','Markers not computable; see methods':'Marker 不可计算；详见方法记录',
            'Manual region-enriched labels (exploratory)':'人工区域富集标签（探索性）',
            'QC by section':'按切片分层 QC','QC by batch':'按批次分层 QC','QC by sample_id':'按样本分层 QC'}
        for text in fig.findobj(Text):
            value=text.get_text();text.set_text(translations.get(value,'聚类 '+value[8:] if value.startswith('Cluster ') else value));text.set_fontproperties(font)
    else:font_path=Path(findfont(FontProperties()))
    dpi=int(config.get('dpi',300));width=float(config.get('width_inches',6));height=float(config.get('height_inches',5))
    if dpi<72 or dpi>600 or max(width,height)*dpi>4096 or width*height*dpi*dpi>16000000: raise ValueError('figure_size_limit')
    fig.set_size_inches(width,height);fig.tight_layout()
    members=[]
    for fmt,metadata in [('png',{'Software':'PaperAssist'}),('pdf',{'CreationDate':None,'ModDate':None,'Creator':'PaperAssist'})]:
        stream=io.BytesIO();fig.savefig(stream,format=fmt,dpi=dpi,metadata=metadata)
        members.append(writer.add(key+'_'+fmt,stream.getvalue(),fmt,'figure_'+fmt))
    plt.close(fig)
    members.append(writer.json(key+'_data',data))
    return writer.json(key+'_manifest',{'renderer_version':'bio_plots_v1','identity':getattr(writer,'identity',{}),'language':language,'dpi':dpi,
        'width_inches':width,'height_inches':height,'font_sha256':hashlib.sha256(font_path.read_bytes()).hexdigest(),
        'config':config,'members':[{k:v for k,v in item.items() if k!='path'} for item in members]})


def qc_figures(writer,qc,config):
    palette_name=config.get('cmap') or config.get('palette') or 'viridis';palette=plt.get_cmap(palette_name)
    chosen=config.get('panel','default') if config.get('kind')=='qc' else None
    if chosen=='default':chosen='distribution'
    if chosen not in {None,'distribution','scatter','violin','mitochondrial'}:raise ValueError('invalid_parameter_qc_panel')
    panels={}
    # The bounded synthetic caller tests artist output; close unselected panels
    # before saving so one standalone request always publishes one real figure.
    fig,axes=plt.subplots(1,2)
    for ax,field,filtered_field,title in zip(axes,['raw_counts','raw_detected'],['filtered_total','filtered_detected'],['Total counts','Detected genes']):
        values=qc[field];ax.hist(values,bins=min(40,max(5,len(values)//2)),alpha=.6,label='Raw',color=palette(.2))
        ax.hist(qc[filtered_field],bins=min(40,max(5,len(values)//2)),alpha=.6,label='Filtered',color=palette(.8));ax.set_xlabel(title);ax.legend()
    panels['distribution']=(fig,{'total_counts':qc['raw_counts'],'detected_genes':qc['raw_detected'],'filtered_total_counts':qc['filtered_total'],'filtered_detected_genes':qc['filtered_detected'],'kept':qc['obs_mask']})
    fig,ax=plt.subplots();ax.scatter(qc['raw_counts'],qc['raw_detected'],s=6,c=[palette(.75) if kept else (.6,.6,.6,1.) for kept in qc['obs_mask']])
    ax.set(xlabel='Total counts',ylabel='Detected genes',title='QC: raw observations')
    panels['scatter']=(fig,{'total_counts':qc['raw_counts'],'detected_genes':qc['raw_detected'],'kept':qc['obs_mask']})
    fig,axes=plt.subplots(1,2)
    for ax,field,filtered_field,title in zip(axes,['raw_counts','raw_detected'],['filtered_total','filtered_detected'],['Total counts','Detected genes']):
        for ordinal,(label,values) in enumerate([('Raw',qc[field]),('Filtered',qc[filtered_field])],start=1):
            if len(values)>1 and np.ptp(values)>0:
                parts=ax.violinplot([values],positions=[ordinal],showmedians=True)
                for body in parts['bodies']:body.set_facecolor(palette(.2 if ordinal==1 else .8))
            elif len(values):ax.plot([ordinal],[values[0]],'o')
        ax.set_xticks([1,2],['Raw','Filtered']);ax.set_ylabel(title)
    panels['violin']=(fig,{'total_counts':qc['raw_counts'],'detected_genes':qc['raw_detected'],'filtered_total_counts':qc['filtered_total'],'filtered_detected_genes':qc['filtered_detected'],'extreme_candidate_rule':qc['extreme_fences']})
    fig,ax=plt.subplots()
    if qc['mt_fraction'] is None:
        ax.axis('off');ax.text(.05,.5,'Mitochondrial fraction unavailable: rule unconfirmed',transform=ax.transAxes)
        data={'status':'not_computable','reason':qc['mt_reason'],'fraction':None}
    else:
        finite=np.isfinite(qc['mt_fraction'])
        ax.scatter(qc['raw_counts'][finite],qc['mt_fraction'][finite],s=6,color=palette(.6))
        ax.set(xlabel='Total counts',ylabel='Mitochondrial fraction')
        data={'status':'completed' if finite.any() else 'not_computable','reason':None if finite.any() else 'all_zero_total_counts',
              'fraction':qc['mt_fraction'],'total_counts':qc['raw_counts'],'missing_zero_denominator':~finite}
    panels['mitochondrial']=(fig,data)
    for panel,(fig,data) in panels.items():
        if chosen is None or panel==chosen:
            if config.get('title'):fig.axes[0].set_title(config['title'])
            save(writer,'qc_'+panel,fig,data,{**config,'kind':'qc','panel':panel,'palette':palette_name,'cmap':palette_name})
        else:plt.close(fig)


def qc_stratified(writer,qc,field,values,config):
    if field not in {'sample_id','section','batch'} or len(values)!=len(qc['raw_counts']):raise ValueError('invalid_parameter_qc_panel')
    fig,ax=plt.subplots();palette_name=config.get('cmap') or config.get('palette') or 'tab20'
    labels=sorted(set(values))
    colors,effective=categorical_colors(labels,palette_name)
    for i,label in enumerate(labels):
        selected=np.asarray([v==label for v in values]);ax.scatter(qc['raw_counts'][selected],qc['raw_detected'][selected],s=5,label=label,color=colors[label])
    ax.set(xlabel='Total counts',ylabel='Detected genes',title=config.get('title') or 'QC by '+field);ax.legend(fontsize=6)
    save(writer,'qc_by_'+field,fig,{'field':field,'values':values,'total_counts':qc['raw_counts'],'detected_genes':qc['raw_detected'],'category_colors':colors},{**config,'kind':'qc','panel':field,'palette':palette_name,'cmap':palette_name,'effective_palette':effective})


def embedding_figures(writer,result,barcodes,config):
    for kind in ['pca','umap']:
        embedding_figure(writer,result[kind],result['clusters'],barcodes,kind,{**config,'kind':kind,'panel':'scores','color_by':'cluster'})
    pca_variance_figure(writer,result['variance_ratio'],config)


def embedding_figure(writer,points,clusters,barcodes,kind,config,labels=None):
    labels=clusters if labels is None else labels;color_by=config.get('color_by','cluster')
    ordered=sorted(set(labels),key=int if color_by=='cluster' else str);palette=config.get('cmap') or config.get('palette') or 'tab20'
    colors,effective=categorical_colors(ordered,palette,numeric=color_by=='cluster')
    fig,ax=plt.subplots()
    for index,label in enumerate(ordered):
        selected=labels==label;ax.scatter(points[selected,0],points[selected,1],s=8,label='Cluster '+label if color_by=='cluster' else label,color=colors[label])
    ax.set(xlabel='PC1' if kind=='pca' else 'UMAP1',ylabel='PC2' if kind=='pca' else 'UMAP2',title=config.get('title') or '');ax.legend(fontsize=7)
    save(writer,kind,fig,{'barcodes':barcodes,'coordinates':points[:,:2],'clusters':clusters,'color_by':color_by,'color_labels':labels,'category_colors':colors},
         {**config,'kind':kind,'panel':'scores','palette':palette,'cmap':palette,'effective_palette':effective})


def pca_variance_figure(writer,variance,config):
    fig,ax=plt.subplots();palette=config.get('cmap') or config.get('palette') or 'viridis'
    ax.plot(np.arange(1,len(variance)+1),variance,'o-',color=plt.get_cmap(palette)(.6));ax.set(xlabel='PC',ylabel='Explained variance ratio',title=config.get('title') or '')
    save(writer,'pca_variance',fig,{'variance_ratio':variance},{**config,'kind':'pca','panel':'variance','palette':palette,'cmap':palette})


def spatial(writer,key,positions,barcodes,obs_mask,values,config,image=None,scale=1.,radius=3.):
    points=np.asarray([[p['pxl_col_in_fullres'],p['pxl_row_in_fullres']] for p in positions],dtype=float)
    fullres=points.copy();tissue=[p.get('in_tissue') for p in positions]
    points=transform_coordinates(points,scale)
    bmap={b:i for i,b in enumerate(barcodes)}
    fig,ax=plt.subplots()
    if image is not None: ax.imshow(image,origin='upper')
    missing=np.array([p['barcode'] not in bmap for p in positions])
    dropped=np.array([p['barcode'] in bmap and not obs_mask[bmap[p['barcode']]] for p in positions])
    ax.add_collection(PatchCollection([Circle(p,radius) for p in points[missing]],facecolors='#dddddd',edgecolors='none',label='No matrix observation'))
    ax.add_collection(PatchCollection([Circle(p,radius) for p in points[dropped]],facecolors='none',edgecolors='#777777',linewidths=.5,label='Excluded observation'))
    kept=np.array([p['barcode'] in bmap and obs_mask[bmap[p['barcode']]] for p in positions])
    indexes=[bmap[p['barcode']] for p in positions if p['barcode'] in bmap and obs_mask[bmap[p['barcode']]]]
    selected=np.asarray([values[i] for i in indexes],dtype=float)
    finite=np.isfinite(selected)
    use=points[kept]
    discrete=config.get('kind')=='spatial_cluster' or key in {'spatial_cluster','spatial_clusters'}
    palette=config.get('cmap') or config.get('palette') or ('tab20' if discrete else 'viridis')
    color=PatchCollection([Circle(p,radius) for p in use[finite]],cmap=palette,edgecolors='none')
    color.set_array(selected[finite])
    if discrete:
        classes=sorted(set(selected[finite]));categories=max(1,int(max(classes,default=0))+1)
        if categories>50:raise ValueError('cluster_palette_limit')
        category_colors,effective=categorical_colors([str(i) for i in range(categories)],palette,numeric=True)
        color.set_cmap(ListedColormap(list(category_colors.values()),name=effective))
        color.set_norm(BoundaryNorm(np.arange(-.5,categories+.5),color.cmap.N))
    else:color.set_clim(config.get('vmin'),config.get('vmax'))
    ax.add_collection(color)
    if np.any(~finite): ax.scatter(use[~finite,0],use[~finite,1],c='#555555',marker='x',label='Missing value')
    bar=fig.colorbar(color,ax=ax,label='cluster' if discrete else config.get('layer','log1p'))
    if discrete:bar.set_ticks(classes);bar.ax.tick_params(labelsize=6 if len(classes)<=20 else 4)
    ax.set_aspect('equal');ax.set_title(config.get('title',key))
    handles=[]
    if missing.any():handles.append(Line2D([],[],marker='o',linestyle='none',markerfacecolor='#dddddd',markeredgecolor='none',label='No matrix observation'))
    if dropped.any():handles.append(Line2D([],[],marker='o',linestyle='none',markerfacecolor='none',markeredgecolor='#777777',label='Excluded observation'))
    if (~finite).any():handles.append(Line2D([],[],marker='x',linestyle='none',color='#555555',label='Missing value'))
    outside=np.asarray([value==0 for value in tissue])&kept
    if outside.any():
        ax.add_collection(PatchCollection([Circle(p,radius) for p in points[outside]],facecolors='none',edgecolors='black',linewidths=.6,linestyles='dashed'))
        handles.append(Line2D([],[],marker='o',linestyle='none',markerfacecolor='none',markeredgecolor='black',label='Retained outside tissue'))
    if handles:ax.legend(handles=handles,fontsize=6,loc='upper center',bbox_to_anchor=(.5,-.20),ncol=min(3,len(handles)),borderaxespad=0)
    if image is None: ax.autoscale_view();ax.invert_yaxis()
    ax.set(xlabel='Fullres x × image scale',ylabel='Fullres y × image scale')
    save(writer,key,fig,{'coordinates':points,'fullres_coordinates':fullres,'in_tissue':tissue,'barcodes':[p['barcode'] for p in positions],
                       'no_matrix_observation':missing,'excluded':dropped,'kept_values':selected,
                       'image_scale':scale,'spot_radius_fullres':radius/scale,'effective_color_limits':color.get_clim(),'gene_ids':config.get('gene_ids',[]),
                       'value_kind':'cluster' if discrete else 'expression','category_colors':{str(int(c)):color.cmap(color.norm(c)) for c in classes} if discrete else None},
                       {**config,'kind':'spatial_cluster' if discrete else 'spatial_gene','panel':'default','cmap':palette,'palette':palette,
                        **({'effective_palette':effective} if discrete else {})})


def marker_figures(writer,counts,logged,clusters,ids,top_rows,config):
    selected=list(config.get('gene_ids') or list(dict.fromkeys(r['feature_id'] for r in top_rows))[:100])
    if len(selected)>100 or len(set(selected))!=len(selected) or not set(selected)<=set(ids):raise ValueError('stable_feature_id_not_found')
    kinds=[config['kind']] if config.get('kind') in {'marker_dotplot','marker_heatmap'} else ['marker_dotplot','marker_heatmap']
    if config.get('layer','log1p')!='log1p':raise ValueError('invalid_parameter_marker_layer')
    palette=config.get('cmap') or config.get('palette') or 'viridis'
    config={**config,'gene_ids':selected,'layer':'log1p','cmap':palette,'palette':palette}
    labels=sorted(set(clusters),key=int)
    if not selected:
        for key in kinds:
            fig,ax=plt.subplots();ax.axis('off');ax.text(.1,.5,'Markers not computable; see methods')
            save(writer,key,fig,{'status':'not_computable'},config)
        return
    ix=[ids.index(i) for i in selected]
    means=np.array([np.asarray(logged[clusters==c][:,ix].mean(0)).ravel() for c in labels])
    detection=np.array([np.asarray((counts[clusters==c][:,ix]>0).mean(0)).ravel() for c in labels])
    for key in kinds:
        fig,ax=plt.subplots()
        if key=='marker_dotplot':
            yy,xx=np.indices(means.shape)
            artist=ax.scatter(xx.ravel(),yy.ravel(),s=detection.ravel()*150,c=means.ravel(),cmap=palette,vmin=config.get('vmin'),vmax=config.get('vmax'))
        else:artist=ax.imshow(means,aspect='auto',cmap=palette,vmin=config.get('vmin'),vmax=config.get('vmax'))
        ax.set_xticks(range(len(selected)),selected,rotation=90,fontsize=6);ax.set_yticks(range(len(labels)),labels);ax.set_title(config.get('title') or key)
        fig.colorbar(artist,ax=ax,label='Mean log1p')
        save(writer,key,fig,{'feature_ids':selected,'clusters':labels,'mean_log1p':means,'detection_fraction':detection,'effective_color_limits':artist.get_clim()},
             {**config,'kind':key,'panel':'default'})
