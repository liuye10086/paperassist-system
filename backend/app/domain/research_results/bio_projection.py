"""Project saved scientific facts; no analysis, rounding or donor inference."""
from hashlib import sha256
import json

from .contracts import (FrozenResearchSource, ResearchFact, ResearchFactCatalog,
                        ResearchLocator, ResearchMethod, ResearchSourceSelection)


COUNTS = ('raw_features','raw_observations','retained_features','retained_observations',
          'excluded_features','excluded_observations','clusters','hvg','pca_components','nnz')
METHOD_NAMES = {'raw_qc':'原始质量核对 / Raw quality control','filter':'过滤 / Filtering',
                'normalize':'标准化 / Normalization','log1p':'log1p 转换 / Transformation',
                'hvg':'高变特征选择 / HVG selection','pca':'主成分分析 / PCA',
                'neighbors':'邻居图 / Neighbour graph','umap':'UMAP',
                'leiden':'探索性聚类 / Exploratory Leiden clustering',
                'markers':'探索性 marker / Exploratory markers',
                'h5ad_roundtrip':'H5AD 读回核对 / Round-trip verification'}
EXPLORATORY = 'spot 层级探索性分析；spot 和区域不等同于独立 donor，聚类与 marker 不证明细胞类型或因果机制。'
CELL_LIMIT = 'Cell exploratory results; cells and technical samples are not independent donors; markers and labels do not prove cell identity.'
SAMPLE_LIMIT = '样本定量处理保留实际尺度和缺失；样本编号不证明生物学独立性，PCA/聚类不是验证性或因果证据。'


def fact_id(source, locator):
    identity = [source.source_kind,source.source_id,source.sha256,locator.model_dump(mode='json')]
    return 'fact-'+sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:40]


def make_fact(source,locator,value,*,level='dataset',unit='',comparison=''):
    missing = value is None or isinstance(value,str) and value.strip().lower() in ('na','nan','null','none','')
    return ResearchFact(id=fact_id(source,locator),source_kind=source.source_kind,
        source_id=source.source_id,source_sha256=source.sha256,locator=locator,raw_value=value,
        display_value='NA' if value is None else str(value),unit=unit,observation_level=level,
        comparison=comparison,verification_status='missing' if missing else 'verified',
        origin='public_reanalysis' if source.provenance=='public_reanalysis' else 'system_computed',
        limitations=[CELL_LIMIT] if level=='cell' else [EXPLORATORY] if level in ('spot','region') else [])


def _summary(source):
    value=source.content.get('summary',{})
    if not isinstance(value,dict):raise ValueError('Invalid saved summary')
    for key in COUNTS:
        if key in value and (type(value[key]) is not int or value[key]<0):
            raise ValueError('Saved counts must be nonnegative integers')
    for name in ('features','observations'):
        keys=['raw_'+name,'retained_'+name,'excluded_'+name]
        if all(k in value for k in keys) and value[keys[0]]!=value[keys[1]]+value[keys[2]]:
            raise ValueError('Saved filtering counts disagree')
    if 'shape' in value and value['shape']!=[value.get('retained_observations'),value.get('retained_features')]:
        raise ValueError('Saved shape differs from retained counts')
    facts=[]
    for key in COUNTS:
        if key not in value:continue
        level=(source.content.get('observation_level') if source.content.get('observation_level') in ('sample','cell') else 'spot') if key.endswith('observations') else 'dataset'
        unit='cells' if level=='cell' else 'samples' if level=='sample' else 'spots' if level=='spot' else 'features' if key.endswith('features') or key=='hvg' else ''
        facts.append(make_fact(source,ResearchLocator(kind='field',field_path='summary.'+key),value[key],level=level,unit=unit))
    for key in ('target_sum','seed','resolution','neighbors','min_counts','min_genes','min_gene_spots'):
        raw=source.content.get('params',{}).get(key)
        if raw is not None:
            facts.append(make_fact(source,ResearchLocator(kind='field',field_path='params.'+key),raw))
    return facts


def _methods(source):
    result=[]
    if source.content.get('observation_level')=='sample' and source.content.get('methods'):
        methods=source.content['methods']
        result.append(ResearchMethod(id='method-'+sha256((source.source_id+':tabular').encode()).hexdigest()[:32],
            title='样本定量处理方法 / Sample quantitative processing',description=methods.get('description_zh') or methods.get('description_en') or 'Frozen quantitative processing recipe',
            source=ResearchSourceSelection(source_kind=source.source_kind,source_id=source.source_id,sha256=source.sha256),parameters=methods,
            software={k:str(source.content[k]) for k in ('engine_version','code_digest','environment_digest') if k in source.content},executed=True))
    for number,step in enumerate(source.content.get('steps',[])):
        if not isinstance(step,dict) or not isinstance(step.get('key'),str):
            raise ValueError('Invalid saved method step')
        key=step['key'];executed=step.get('status')=='completed'
        description='已执行 / Completed' if executed else '未完成 / Not completed: '+str(step.get('reason') or step.get('status','unknown'))
        parameters=dict(step.get('params') or {})
        if key=='normalize':parameters.update({k:v for k,v in source.content.get('params',{}).items() if k=='target_sum'})
        if key=='markers':parameters.update({k:step[k] for k in ('tested_genes','correction') if k in step})
        software={k:str(source.content[k]) for k in ('engine_version','code_digest','environment_digest') if k in source.content}
        result.append(ResearchMethod(id='method-'+sha256((source.source_id+':'+str(number)+':'+key).encode()).hexdigest()[:32],
            title=METHOD_NAMES.get(key,key),description=description,
            source=ResearchSourceSelection(source_kind=source.source_kind,source_id=source.source_id,sha256=source.sha256,
                locator=ResearchLocator(kind='field',field_path=f'steps[{number}]')),
            parameters=parameters,software=software,executed=executed))
    return result


def _table(source):
    rows=source.content.get('rows',[]);total=source.content.get('total_rows',len(rows))
    if not isinstance(rows,list) or len(rows)>500:raise ValueError('Please select at most 500 table rows')
    if type(total) is not int or total<len(rows):raise ValueError('Invalid total table row count')
    seen=set();facts=[];table=source.content.get('table_key','table')
    for row in rows:
        if not isinstance(row,dict):raise ValueError('Invalid table row')
        if 'feature_id' in row and 'cluster' in row:keys=('cluster','feature_id')
        elif 'barcode' in row:keys=('barcode',)
        elif 'sample_id' in row:keys=('sample_id',)
        elif 'feature_id' in row:keys=('feature_id',)
        elif 'component' in row:keys=('component',)
        elif 'cluster' in row:keys=('cluster',)
        else:raise ValueError('Table requires stable feature, barcode or cluster identities')
        row_key={k:str(row[k]) for k in keys}
        key=json.dumps(row_key,sort_keys=True)
        if key in seen:raise ValueError('Duplicate stable row key')
        seen.add(key)
        for column,raw in row.items():
            if column in keys or column in ('symbol','gene_name','feature_name'):continue
            if not (raw is None or type(raw) in (str,int,float,bool)):raise ValueError('Table cell must be scalar')
            locator=ResearchLocator(kind='row',row_key=row_key,column=column,table=table)
            comparison=str(row.get('comparison','cluster '+str(row['cluster'])+' versus rest' if 'cluster' in row and 'feature_id' in row else ''))
            facts.append(make_fact(source,locator,raw,level=source.content.get('observation_level') if source.content.get('observation_level') in ('sample','cell') else 'spot',comparison=comparison))
            if len(facts)>1000:raise ValueError('Please select fewer table columns or rows')
    warnings=[f'事实目录只展示已选行 {len(rows)}/{total}；完整结果表仍保留，导出不能据此截断。'] if total>len(rows) else []
    return facts,warnings


def project_bio_facts(source: FrozenResearchSource) -> ResearchFactCatalog:
    source=FrozenResearchSource.model_validate(source)
    if source.source_kind not in ('bio_processed_dataset_version','bio_analysis_artifact'):
        raise ValueError('A saved bio result or artifact is required')
    if source.provenance not in ('system_computed','public_reanalysis'):
        raise ValueError('External observations cannot become computed bio facts')
    facts=_summary(source) if source.source_kind=='bio_processed_dataset_version' else []
    warnings=[]
    if 'rows' in source.content:
        extra,warnings=_table(source);facts.extend(extra)
    summary=source.content.get('summary',{});gaps=[]
    if summary.get('replicate_consistency',{}).get('status')=='not_computable':
        gaps.append('donor/组别的独立重复设计未确认：'+str(summary['replicate_consistency'].get('reason','unknown')))
    if summary.get('mitochondrial_reason'):
        gaps.append('线粒体规则未确定：'+str(summary['mitochondrial_reason']))
    return ResearchFactCatalog(source=source,facts=facts,methods=_methods(source),
        gaps=gaps,warnings=warnings,limitations=[CELL_LIMIT if source.content.get('observation_level')=='cell' else SAMPLE_LIMIT if source.content.get('observation_level')=='sample' else EXPLORATORY])
