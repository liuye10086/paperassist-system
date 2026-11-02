"""Bounded quantitative matrices with explicit sample axes and missing masks."""
import csv
import hashlib
import io
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
import numpy as np
from scipy.cluster.hierarchy import linkage, leaves_list
from .manifest import Writer, clean, canonical
from app.domain.bioinformatics.tabular_contracts import BioImportRequestV3, TabularRecipeParameters, validate_recipe, ENGINE_VERSION, PARSER_VERSION
from app.adapters.bio_insights_engine.tables import iter_table
from app.adapters.bio_insights_engine.inputs import verify_member

MAX_CELLS=1_000_000


def _id(value):
    if not isinstance(value,str) or not value or len(value)>200 or any(ord(c)<32 for c in value):raise ValueError('tabular_identifier_invalid')
    return value


def import_tabular(payload, *, _writer=None):
    config=BioImportRequestV3.model_validate(payload['config']);files={f['id']:f for f in payload['files']}
    if len(files)!=len(payload['files']) or set(files)!=set(config.file_ids):raise ValueError('tabular_source_identity_mismatch')
    tables={};cells=0
    for spec in config.tables:
        file=files[spec.file_id]
        if file['role']!=spec.role:raise ValueError('tabular_source_role_mismatch')
        if file['size_bytes']>10*1024**2:raise ValueError('tabular_file_limit')
        rows=[]
        for number,row in iter_table(file,format=spec.format,sheet=spec.sheet,encoding=spec.encoding,delimiter=spec.delimiter,header_row=spec.header_row,max_uncompressed_bytes=64*1024**2):
            cells+=len(row)
            if len(row)>(501 if config.assay=='microbiome' else 256) or len(rows)>=(10000 if config.assay=='microbiome' else 100000) or cells>(5_100_000 if config.assay=='microbiome' else MAX_CELLS):raise ValueError('tabular_cell_limit')
            if any(len(str(v or ''))>4000 for v in row.values()):raise ValueError('tabular_cell_text_limit')
            rows.append((number,row))
        if not rows:raise ValueError('tabular_table_empty')
        tables[spec.role]=(spec,rows)
    _,sample_rows=tables['sample_metadata'];samples={}
    for number,row in sample_rows:
        sid=_id(row.get('sample_id'))
        if sid in samples:raise ValueError('duplicate_sample_id')
        samples[sid]={**row,'source_row':number}
    if set(samples)!=set(config.sample_columns):raise ValueError('sample_axis_mismatch')
    annotations={}
    if 'feature_metadata' in tables:
        for number,row in tables['feature_metadata'][1]:
            fid=_id(row.get('feature_id'))
            if fid in annotations:raise ValueError('duplicate_feature_annotation')
            annotations[fid]={**row,'annotation_source_row':number}
    ids=[];seen=set();feature_rows=[];values=[];missing=[];counts=config.assay=='bulk_rna_counts' or config.assay=='microbiome' and config.scale.kind=='raw_counts'
    for number,row in tables['quantitative_matrix'][1]:
        if set(row)!={config.feature_id_column,*config.sample_columns}:raise ValueError('matrix_columns_mismatch')
        fid=_id(row.get(config.feature_id_column))
        if fid in seen:raise ValueError('duplicate_feature_id')
        seen.add(fid);ids.append(fid);data=[];mask=[]
        for sample in config.sample_columns:
            raw=row[sample];absent=raw is None or raw in config.na_values
            if absent:
                if counts and config.assay!='microbiome':raise ValueError('counts_missing')
                data.append(0.);mask.append(True);continue
            try:value=Decimal(raw)
            except (InvalidOperation,TypeError):raise ValueError('matrix_non_numeric') from None
            if not value.is_finite():raise ValueError('matrix_nonfinite')
            if counts and (value<0 or value!=value.to_integral_value() or value>np.iinfo(np.int64).max):raise ValueError('counts_invalid')
            numeric=int(value) if counts else float(value)
            if not np.isfinite(numeric):raise ValueError('matrix_nonfinite')
            if config.scale.kind not in ('log2','ln','log10','normalized') and numeric<0:raise ValueError('negative_unlogged_intensity')
            data.append(numeric);mask.append(False)
        values.append(data);missing.append(mask)
        feature_rows.append({'feature_id':fid,'display_name':annotations.get(fid,{}).get('display_name') or fid,
            'feature_kind':{'bulk_rna_counts':'gene','normalized_expression':'gene','proteomics':'protein_group','metabolomics':'peak','microbiome':'microbial_taxon'}[config.assay],
            **annotations.get(fid,{}),'source_row':number})
    if set(annotations)-set(ids):raise ValueError('feature_annotation_axis_mismatch')
    matrix=np.asarray(values,dtype='int64' if counts else 'float64').T.copy();mask=np.asarray(missing,dtype=bool).T.copy()
    if matrix.size>(5_000_000 if config.assay=='microbiome' else MAX_CELLS):raise ValueError('tabular_cell_limit')
    writer=_writer if _writer is not None else Writer(payload['output_directory']);writer.array('matrix_values',matrix);writer.array('matrix_missing',mask)
    writer.json('samples_index',{'sample_ids':config.sample_columns})
    writer.json('features_index',{'feature_ids':ids,'display_names':[r['display_name'] for r in feature_rows],'feature_kinds':[r['feature_kind'] for r in feature_rows]})
    writer.table('samples',[samples[s] for s in config.sample_columns])
    fields=list(dict.fromkeys(k for row in feature_rows for k in row));writer.table('features',feature_rows,fields)
    writer.json('input_scale',config.scale.model_dump())
    writer.table('import_audit',[dict(check='sample_axis_exact',status='passed',value=len(samples)),dict(check='missing_preserved',status='passed',value=int(mask.sum())),dict(check='cells',status='passed',value=cells)])
    matrix_spec=tables['quantitative_matrix'][0]
    for item in writer.artifacts:
        source=tables['sample_metadata'][0] if item['key'] in ('samples','samples_index') else matrix_spec
        file=files[source.file_id]
        item.update(role=item['key'],compression='none',verification_state='verified',source_file_id=source.file_id,source_member_name=file['filename'])
    manifest=dict(schema_version=3,parser_version=PARSER_VERSION,assay=config.assay,observation_level='sample',
        storage_format='dense_mask_npy_v1',matrix_orientation='samples_by_features',input_shape={'features':len(ids),'observations':len(samples)},
        stored_entries=int(matrix.size),scale=config.scale.model_dump(),import_config=config.model_dump(),
        source_files=[{k:v for k,v in file.items() if k!='path'} for file in payload['files']],
        checks={'sample_axis_exact':True,'missing_count':int(mask.sum()),'counts_valid':counts},
        members=[{k:v for k,v in item.items() if k!='path'} for item in writer.artifacts])
    return dict(parser_version=PARSER_VERSION,manifest=manifest,outputs=writer.artifacts,n_features=len(ids),n_observations=len(samples),entry_count=int(matrix.size),checks=manifest['checks'])


def load_tabular(raw):
    members=raw['members'];manifest=raw['manifest']
    for member in members.values():verify_member(member)
    def document(key):return json.loads(Path(members[key]['path']).read_bytes())
    values=np.load(members['matrix_values']['path'],allow_pickle=False);missing=np.load(members['matrix_missing']['path'],allow_pickle=False)
    samples=document('samples_index')['sample_ids'];features=document('features_index')
    if (manifest.get('schema_version')!=3 or values.ndim!=2 or values.shape!=missing.shape or missing.dtype.kind!='b'
        or values.dtype.kind not in 'if' or values.size>(5_000_000 if manifest['assay']=='microbiome' else MAX_CELLS) or not np.isfinite(values).all()
        or values.shape!=(len(samples),len(features['feature_ids'])) or len(samples)!=len(set(samples))
        or len(features['feature_ids'])!=len(set(features['feature_ids'])) or np.any(values[missing]!=0)):
        raise ValueError('tabular_matrix_invalid')
    if manifest['assay']=='bulk_rna_counts' and (values.dtype!=np.dtype('int64') or missing.any() or np.any(values<0)):raise ValueError('counts_invalid')
    return values,missing,samples,features


def transformed(values,missing,params,manifest):
    params=validate_recipe(params,manifest);result=values.astype('float64',copy=True);valid=~missing;factors=np.ones(len(result))
    if params.normalization in ('median','display_library_size'):
        if params.normalization=='median':
            if np.any(result[valid]<=0):raise ValueError('median_requires_positive_values')
            medians=np.array([np.median(row[ok]) if ok.any() else np.nan for row,ok in zip(result,valid)])
            if not np.isfinite(medians).all() or np.any(medians<=0):raise ValueError('median_not_computable')
            factors=medians/np.median(medians)
        else:
            totals=result.sum(axis=1)
            if np.any(totals<=0):raise ValueError('empty_count_library')
            factors=totals/np.median(totals)
        result=result/factors[:,None]
    if params.transform!='none':
        if params.transform=='log1p':
            if np.any(result[valid]<0):raise ValueError('log1p_requires_nonnegative_counts')
            result[valid]=np.log1p(result[valid])
        else:
            if np.any(result[valid]<=0):raise ValueError('log_requires_positive_values')
            result[valid]={'log2':np.log2,'ln':np.log,'log10':np.log10}[params.transform](result[valid])
    result[missing]=0
    if not np.isfinite(result).all():raise ValueError('transform_nonfinite')
    return result,factors


def _rows(member):return list(csv.DictReader(io.StringIO(Path(member['path']).read_text(encoding='utf-8')),delimiter='\t'))


def layer_scale(params, manifest):
    """Describe stored values separately from the immutable upstream scale."""
    params=validate_recipe(params,manifest)
    scale=manifest['scale']['kind'];unit=manifest['scale']['unit']
    if params.normalization=='display_library_size':
        scale='normalized';unit='library_size_normalized_counts'
    elif params.normalization=='median':
        scale='normalized';unit=f'median_normalized({unit})'
    if params.transform!='none':
        scale=params.transform;unit=f'{params.transform}({unit})'
    result=dict(input_scale=manifest['scale'],normalization=params.normalization,transform=params.transform,
                scale=scale,unit=unit,is_raw_integer_counts=manifest['assay']=='bulk_rna_counts' and scale=='raw_counts')
    if params.transform=='log1p':result.update(transform_offset=params.log1p_offset,transform_formula='ln(1+x)')
    return result


def _figure(writer,key,title,plot,data,params):
    from matplotlib import pyplot as plt
    from matplotlib.font_manager import FontProperties
    font=Path('/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc')
    if font.is_file():plt.rcParams.update({'font.family':FontProperties(fname=str(font)).get_name(),'axes.unicode_minus':False})
    fig,ax=plt.subplots(figsize=(6,4));plot(ax)
    ax.set_title(title,fontproperties=FontProperties(fname=str(font)) if font.is_file() else None)
    fig.tight_layout()
    for fmt in ('png','tiff','svg'):
        path=writer.root/(key+'_'+fmt+'.'+fmt);fig.savefig(path,format=fmt,dpi=150,metadata={'Date':None} if fmt=='svg' else None)
        writer.existing(key+'_'+fmt,path,fmt,'figure')
    plt.close(fig)
    writer.json(key+'_data',data)
    writer.json(key+'_manifest',dict(schema_version=2,kind='quantitative_figure',observation_level='sample',title=title,
        config={'kind':key,'output_language':params.output_language},data_member=key+'_data',formats=['png','tiff','svg'],
        caption='Sample-level quantitative measurements; processing is not biological validation.',dpi=150,width_inches=float(fig.get_figwidth()),height_inches=float(fig.get_figheight())))


def run_tabular(payload):
    raw=payload['raw'];values,missing,samples,features=load_tabular(raw);params=validate_recipe(payload.get('config',{}),raw['manifest'])
    ids=features['feature_ids']
    if not set(params.exclude_samples)<=set(samples) or not set(params.exclude_features)<=set(ids):raise ValueError('unknown_exclusion')
    om=np.array([s not in params.exclude_samples for s in samples]);fm=np.array([f not in params.exclude_features for f in ids])
    if not om.any() or not fm.any():raise ValueError('all_observations_or_features_excluded')
    writer=Writer(payload['output_directory']);writer.array('observation_mask',om);writer.array('feature_mask',fm)
    writer.json('raw_axes',{'sample_ids':samples,'feature_ids':ids,'display_names':features['display_names'],'feature_kinds':features['feature_kinds']})
    sample_rows=_rows(raw['members']['samples']);feature_rows=_rows(raw['members']['features'])
    for i,row in enumerate(sample_rows):row.update(kept=bool(om[i]),exclusion_reason='' if om[i] else 'explicit_sample_exclusion')
    for j,row in enumerate(feature_rows):row.update(kept=bool(fm[j]),exclusion_reason='' if fm[j] else 'explicit_feature_exclusion')
    writer.table('samples',sample_rows);writer.table('features',feature_rows)
    qc=[dict(sample_id=s,missing_count=int(missing[i].sum()),zero_count=int(((values[i]==0)&~missing[i]).sum()),
        measured_features=int((~missing[i]).sum()),library_size=sum(map(int,values[i])) if raw['manifest']['assay']=='bulk_rna_counts' else None,
        kept=bool(om[i])) for i,s in enumerate(samples)]
    writer.table('sample_qc',qc)
    writer.table('feature_qc',[dict(feature_id=f,missing_count=int(missing[:,j].sum()),measured_samples=int((~missing[:,j]).sum()),kept=bool(fm[j])) for j,f in enumerate(ids)])
    zh=params.output_language=='zh-CN'
    def qc_plot(ax):
        ax.bar(range(len(samples)),missing.mean(1));ax.set_ylim(0,1)
        ax.set_xlabel('样本' if zh else 'Sample');ax.set_ylabel('缺失比例' if zh else 'Missing fraction')
        if len(samples)<=30:ax.set_xticks(range(len(samples)),samples,rotation=60,ha='right',fontsize=7)
    _figure(writer,'qc_missing','样本缺失比例' if zh else 'Missing fraction by sample',qc_plot,{'sample_ids':samples,'missing_fraction':missing.mean(1).tolist()},params)
    steps=[dict(key='qc',status='completed',reason=None),dict(key='filter',status='completed',reason=None)]
    summary=dict(raw_observations=len(samples),retained_observations=int(om.sum()),excluded_observations=int((~om).sum()),
        raw_features=len(ids),retained_features=int(fm.sum()),excluded_features=int((~fm).sum()),shape=[int(om.sum()),int(fm.sum())],observation_level='sample',missing_values=int(missing.sum()))
    layers={}
    if payload['mode']=='compute':
        sub=values[om][:,fm];mask=missing[om][:,fm];analysis,factors=transformed(sub,mask,params,raw['manifest'])
        for prefix in ('analysis','display'):
            writer.array(prefix+'_values',analysis);writer.array(prefix+'_missing',mask)
            layers[prefix]=dict(values=prefix+'_values',missing=prefix+'_missing',shape=list(analysis.shape),
                **layer_scale(params,raw['manifest']))
        writer.table('normalization_factors',[dict(sample_id=s,factor=float(f)) for s,f in zip(np.asarray(samples)[om],factors)])
        complete=~mask.any(axis=0);pca_mask=complete & (np.var(analysis,axis=0)>0);writer.array('pca_feature_mask',pca_mask)
        writer.table('pca_feature_selection',[dict(feature_id=f,included=bool(pca_mask[j]),reason='' if pca_mask[j] else 'missing_values' if not complete[j] else 'constant') for j,f in enumerate(np.asarray(ids)[fm])])
        n=int(om.sum());status='completed' if n>=3 and pca_mask.sum()>=2 else 'not_computable';reason=None if status=='completed' else 'insufficient_complete_nonconstant_features_or_samples'
        steps.extend([dict(key='transform',status='completed',reason=None),dict(key='pca',status=status,reason=reason),dict(key='sample_clustering',status=status,reason=reason)])
        if status=='completed':
            x=analysis[:,pca_mask];x=x-x.mean(0)
            if params.scaling=='unit_variance':x=x/np.std(x,axis=0,ddof=1)
            u,s,v=np.linalg.svd(x,full_matrices=False);k=min(params.pca_components,n-1,x.shape[1]);scores=u[:,:k]*s[:k];loads=v[:k].T
            for j in range(k):
                sign=1 if loads[np.argmax(abs(loads[:,j])),j]>=0 else -1;scores[:,j]*=sign;loads[:,j]*=sign
            variance=s[:k]**2/np.sum(s**2);selected_samples=np.asarray(samples)[om].tolist();selected_features=np.asarray(ids)[fm][pca_mask].tolist()
            writer.table('pca_scores',[dict(sample_id=s,**{f'pc{j+1}':float(v) for j,v in enumerate(score)}) for s,score in zip(selected_samples,scores)])
            writer.table('pca_loadings',[dict(feature_id=f,**{f'pc{j+1}':float(v) for j,v in enumerate(row)}) for f,row in zip(selected_features,loads)])
            writer.table('pca_variance_ratio',[dict(component=j+1,variance_ratio=float(v)) for j,v in enumerate(variance)])
            linked=linkage(x,method='average',metric='euclidean');order=leaves_list(linked)
            writer.table('sample_clustering',[dict(order=i,sample_id=selected_samples[j]) for i,j in enumerate(order)])
            writer.array('sample_linkage',linked)
            def pca_plot(ax):
                from matplotlib import pyplot as plt
                import textwrap
                columns=max(1,int(np.ceil(len(selected_samples)/30)))
                labels=[textwrap.fill(label,24) for label in selected_samples]
                rows=int(np.ceil(len(labels)/columns));lines=max(label.count('\n')+1 for label in labels)
                ax.figure.set_size_inches(min(26,6+2.2*columns),min(26,max(4.5,1.5+.18*rows*lines)))
                markers=('o','s','^','v','D','P','X','<','>','h','*','p','8')
                for i,(label,point) in enumerate(zip(labels,scores)):
                    ax.scatter(point[0],point[1],label=label,color=plt.get_cmap('tab20')(i%20),marker=markers[(i//20)%len(markers)],s=30,edgecolors='black',linewidths=.3)
                ax.set_xlabel(f'PC1 ({variance[0]:.1%})');ax.set_ylabel(f'PC2 ({variance[1]:.1%})')
                ax.legend(loc='upper left',bbox_to_anchor=(1.02,1),ncol=columns,fontsize=7,title='样本身份' if zh else 'Sample identity',title_fontsize=8,frameon=False,borderaxespad=0)
            def cluster_plot(ax):
                import textwrap
                image=ax.imshow(x[order],aspect='auto',cmap='viridis');ax.set_xlabel('完整且非恒定特征' if zh else 'Complete nonconstant features');ax.set_ylabel('样本' if zh else 'Samples')
                ticks=np.unique(np.linspace(0,len(selected_features)-1,min(20,len(selected_features)),dtype=int))
                ax.set_xticks(ticks,[selected_features[j] for j in ticks],rotation=60,ha='right',fontsize=7)
                if len(selected_features)>20:ax.set_xlabel('完整且非恒定特征（刻度抽稀；完整轴见图数据）' if zh else 'Complete nonconstant features (ticks sampled; complete axis in plot data)')
                ax.figure.set_size_inches(max(6,min(12,4+len(ticks)/3)),max(4.5,min(9,2+len(selected_samples)*.15)))
                if len(selected_samples)<=30:ax.set_yticks(range(len(order)),[selected_samples[j] for j in order],fontsize=7)
                unit=layers['analysis']['unit']
                label=(f'中心化 / 样本标准差（无量纲；输入单位：{unit}）' if zh else f'Centered / sample SD (dimensionless; input unit: {unit})') if params.scaling=='unit_variance' else (f'中心化值（单位：{unit}）' if zh else f'Centered {unit}')
                ax.figure.colorbar(image,ax=ax,label=textwrap.fill(label,50))
            _figure(writer,'pca','样本 PCA' if zh else 'Sample PCA',pca_plot,{'sample_ids':selected_samples,'scores':scores.tolist(),'variance_ratio':variance.tolist()},params)
            _figure(writer,'sample_clustering','样本聚类' if zh else 'Sample clustering',cluster_plot,{'sample_ids':[selected_samples[j] for j in order],'feature_ids':selected_features,'values':x[order].tolist(),'method':'average_euclidean'},params)
            summary['pca_components']=k
        else:
            for key,field in [('pca_scores','sample_id'),('pca_loadings','feature_id'),('pca_variance_ratio','component'),('sample_clustering','sample_id')]:writer.table(key,[],[field,'reason'])
    elif payload['mode']!='qc':raise ValueError('unsupported_tabular_mode')
    methods=dict(name='tabular_quantitative_v1',assay=raw['manifest']['assay'],observation_level='sample',input_scale=raw['manifest']['scale'],
        transform_formula='ln(1+x)' if params.transform=='log1p' else params.transform,transform_offset=params.log1p_offset if params.transform=='log1p' else 0,
        params=params.model_dump(),steps=steps,missing='preserved; PCA uses complete nonconstant features; no imputation',
        statistical_inference='not_performed',replicates='sample identity does not establish independent biological replication',
        pca='centered SVD; optional sample-SD feature scaling; canonical loading signs',clustering='average linkage Euclidean on exact PCA feature matrix')
    methods['description_zh']=f"以样本为观测单位；输入尺度为 {raw['manifest']['scale']['kind']}，单位 {raw['manifest']['scale']['unit']}。标准化 {params.normalization}，变换 {params.transform}；缺失保持，不插补。PCA与样本聚类仅使用完整且非恒定特征，缩放 {params.scaling} 仅作用于PCA/聚类；本步骤未作组间检验或独立生物学重复验证。"
    methods['description_en']=f"Observations are samples; input scale {raw['manifest']['scale']['kind']} ({raw['manifest']['scale']['unit']}). Normalization {params.normalization}; transform {params.transform}. Missing values are preserved without imputation. PCA and sample clustering use complete nonconstant features; scaling {params.scaling} applies only to PCA/clustering. No group tests or biological independence validation were performed."
    writer.json('methods',methods);writer.json('recipe',params.model_dump())
    writer.add('reproduce',b'# Use the fixed /opt/paperassist-bio-insights/bin/python environment and exported verified raw members.\nimport json,sys\nfrom app.adapters.bio_engine.tabular_assays import run_tabular\nrun_tabular(json.load(open(sys.argv[1],encoding="utf-8")))\n','py')
    if payload.get('_trusted_lock'):writer.add('requirements_bio_lock',payload['_trusted_lock'],'lock')
    manifest=dict(schema_version=2,engine_version=ENGINE_VERSION,identity=payload['identity'],raw_source=payload['identity'].get('raw_source'),
        environment_digest=payload['identity'].get('environment_digest'),code_digest=payload['identity'].get('code_digest'),assay=raw['manifest']['assay'],observation_level='sample',
        scale=raw['manifest']['scale'],params=params.model_dump(),summary=summary,steps=steps,layers=layers,methods=methods,
        tables=[dict(key=m['key'],label=m['key'],status=next((s['status'] for s in steps if s['key']=='pca'),'not_requested') if m['key'] in ('pca_scores','pca_loadings','pca_variance_ratio','sample_clustering') else 'completed',reason=next((s['reason'] for s in steps if s['key']=='pca'),None) if m['key'] in ('pca_scores','pca_loadings','pca_variance_ratio','sample_clustering') else None) for m in writer.artifacts if m['format']=='tsv'],
        members=[{k:v for k,v in m.items() if k!='path'} for m in writer.artifacts])
    writer.json('manifest',manifest)
    return clean(dict(status='completed',engine_version=ENGINE_VERSION,outputs=writer.artifacts,manifest=manifest,summary=summary,steps=steps,checks={},effective_params=params.model_dump()))
