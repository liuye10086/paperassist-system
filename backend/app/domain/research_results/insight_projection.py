"""Project exact published B04 scalar values and deterministic methods to facts."""
import hashlib
import json

from .contracts import ResearchFactCatalog,ResearchFact,ResearchLocator,ResearchMethod,ResearchSourceSelection
from .bio_projection import fact_id


def limitations(source):
    scope=source.content['inference_scope']
    scopes=set(source.content.get('upstream_inference_scopes',[]))|{scope}
    result=['源表数值保持原文；0、数值下溢和 NA 不互换。 / Original values, zero and NA remain distinct.']
    if 'spot_exploratory' in scopes:result.append('spot 层级区域探索，不能作为独立供体推断或纯细胞类型证据。 / Region-enriched spot exploration is not donor inference.')
    if 'external_result' in scopes:result.append('外部结果按原表承接，未升级为系统重算；原 P/q、效应单位及方法范围保持。 / External values retain their original method and correction scope.')
    if 'donor_inference' in scopes:result.append('供体独立性依赖人工确认；工程计算不等于生物学验证。 / Donor independence relies on confirmed metadata.')
    if scopes & {'sample_inference','sample_exploratory'}:result.append('真实样本轴保留尺度、缺失和每特征实际 n；观察关联不等于因果结论。 / Sample results retain scale, missingness and actual n; association is not causation.')
    if source.content.get('config',{}).get('mode')=='microbiome':result.append('微生物相对丰度不代表绝对负荷或原测序深度；Observed features 受深度和过滤限制。PERMANOVA 与 PERMDISP 分别描述组间结构与离散度，不能自动认定组差异或因果。')
    if source.content.get('config',{}).get('kind')=='integration':result.append('冻结对应与跨数据关联；matched observation count 不等于独立供体 n。描述性模式 P/q 为 NA。不同依赖组不证明独立，未显著不等于等效，相关边没有因果含义。')
    if source.content.get('config',{}).get('kind')=='feature_extract':result.append('实际序列／结构描述性提取；Cα 等权几何使用观测坐标，不代表预测质量、完整序列缺失、功能或疾病效应。不同资源对象不自动对应；B 因子不是 pLDDT。')
    if 'sample_exploratory' in scopes:result.append('样本层探索性结果；技术重复不代表独立生物学重复。 / Exploratory sample evidence; technical runs are not independent biological replicates.')
    if source.content.get('data_driven_grouping') or source.content['config'].get('data_driven_grouping'):result.append('分组来自同一表达数据，P/q 仅作探索性排序。 / Data-driven grouping is exploratory.')
    return result


def project_insight_facts(source):
    content=source.content;facts=[];limits=limitations(source);scope=content['inference_scope']
    level='spot' if scope=='spot_exploratory' else 'donor' if scope=='donor_inference' else 'sample' if scope in ('sample_inference','sample_exploratory') else 'unknown'
    upstream=set(content.get('upstream_inference_scopes',[]))
    if level=='unknown' and upstream and upstream<={'sample_inference','sample_exploratory'}:level='sample'
    evidence_matrix=content.get('config',{}).get('kind')=='candidate' and content.get('config',{}).get('schema_version')==2
    origin='external_result' if source.provenance=='external_result' or evidence_matrix and content.get('table_key')=='candidate_evidence' else 'system_computed'
    if evidence_matrix:limits.append('外部原文声明保持未系统重算；定位核对、人工核对与独立数据支持分别记录，矩阵整理不证明因果或机制。')

    def qpcr_unit(column,row):
        if column=='effect_value':return str(row.get('effect_unit') or '')
        if column=='statistical_effect_value':return {'delta_cq':'Cq','log2_signal':'log2'}.get(row.get('statistical_scale'),'')
        if column in ('relative_quantity','fold_change','ci_fold_low','ci_fold_high'):return 'fold'
        if column in ('delta_cq','delta_delta_cq','target_mean_cq','reference_mean_cq','mean_cq','sd_cq'):return 'Cq'
        if column in ('log2_quantity','log2_signal','ci_log2_low','ci_log2_high'):return 'log2'
        if column in ('original_value','recomputed_value','difference','tolerance'):return str(row.get('unit') or '')
        return ''

    def microbiome_unit(column,row):
        if column in ('relative_abundance','distance','shannon','simpson','explained_positive_ratio'):return 'dimensionless'
        if column=='observed_features':return 'nonzero features in supplied table'
        if column in ('original_sum','observed_partial_sum'):return content.get('config',{}).get('abundance_scale','')
        return str(row.get('effect_unit') or '') if column=='effect_value' else ''

    def add(locator,value,row=None):
        missing=value is None or isinstance(value,str) and (value in content.get('config',{}).get('na_values',[]) or value.strip().lower() in ('','na','n/a','nan','none','null'))
        row=row or {}
        display='NA' if missing else str(value)
        if len(display)>1000:display=display[:999]+'…'
        facts.append(ResearchFact(id=fact_id(source,locator),source_kind=source.source_kind,source_id=source.source_id,
            source_sha256=source.sha256,locator=locator,raw_value=value,display_value=display,
            observation_level=row.get('observation_level') if row.get('observation_level') in ('spot','donor','sample') else level,
            unit=('Angstrom' if locator.column in ('centroid_x','centroid_y','centroid_z','radius_of_gyration') else '') if content.get('config',{}).get('kind')=='feature_extract' else microbiome_unit(locator.column,row) if content.get('config',{}).get('mode')=='microbiome' else qpcr_unit(locator.column,row) if content.get('config',{}).get('mode')=='qpcr' else str(row.get('effect_unit') or '') if locator.column in ('effect_value','effect_log2fc','effect_log2_normalized') else str(row.get('measurement_unit') or '') if locator.column in ('mean','sample_sd') else 'dimensionless ratio' if locator.column=='coefficient_of_variation' else '',
            comparison=(str(row['numerator'])+' / '+str(row['denominator'])) if row.get('numerator') and row.get('denominator') else str(row.get('contrast_id') or ''),
            origin=origin,verification_status='missing' if missing else 'unverified' if origin=='external_result' else 'verified',limitations=limits))

    if source.source_kind=='bio_insight_result_version':
        def scalars(value,path,depth=0):
            if depth>4:return
            if isinstance(value,dict):
                for key,item in value.items():
                    if isinstance(key,str) and key.replace('_','').isalnum():scalars(item,path+'.'+key,depth+1)
            elif value is None or type(value) in (str,int,float,bool):
                locator=ResearchLocator(kind='field',field_path=path)
                if source.locator.kind!='field' or source.locator.field_path==path:add(locator,value)
        scalars(content.get('summary',{}),'summary')
        if source.locator.kind=='field' and not facts:
            value=content
            for key in source.locator.field_path.split('.'):value=value[key]
            add(source.locator,value)
    elif 'rows' in content:
        for row in content['rows']:
            if row.get('row_key'):
                row_key={'row_key':row['row_key']}
                requested=source.locator.row_key
                if (content['config'].get('kind')=='comparison' and content['config'].get('schema_version')==2
                        and scope in ('sample_inference','sample_exploratory') and source.locator.kind=='row'
                        and requested and 'row_key' in requested and len(requested)>1):
                    if not all(row.get(key)==value for key,value in requested.items()):raise ValueError('Insight fact row selector mismatch')
                    row_key=dict(requested)
            else:
                fields=[key for key in ('pair_id','concordance_id','object_id','node_id','edge_id','match_group','observation_id','feature_id','input_row','resource_version_id','model_id','chain_id','residue_number','insertion_code','contrast_id','unit_id','sample_id','component','term_id','direction','collection','step') if row.get(key)]
                if not fields:raise ValueError('Insight fact row lacks a stable key')
                row_key={key:row[key] for key in fields}
            columns=[source.locator.column] if source.locator.kind=='row' else [key for key in row if key not in row_key and key not in ('source_cells','provenance')]
            for column in columns:
                if column not in row:raise ValueError('Insight fact column missing')
                add(ResearchLocator(kind='row',row_key=row_key,column=column,table=content['table_key']),row[column],row)
                if len(facts)>1000:raise ValueError('Please select fewer insight rows or fields')
    methods=content.get('methods',{})
    parameters={key:value for key,value in methods.items() if isinstance(key,str)}
    parameters.update(inference_scope=scope,source_inference_scopes=content.get('upstream_inference_scopes',[]),
        source_data_driven_grouping=content.get('data_driven_grouping',False),provenance=content['provenance'],frozen_config=content['config'])
    method=ResearchMethod(id='insight-method-'+hashlib.sha256((content['result_version_id']+source.sha256).encode()).hexdigest()[:32],
        title='差异与功能分析方法 / Differential and functional methods',
        description=json.dumps(methods,ensure_ascii=False,sort_keys=True)[:4000],
        source=ResearchSourceSelection(source_kind=source.source_kind,source_id=source.source_id,sha256=source.sha256),
        parameters=parameters,software={key:str(content[key]) for key in ('engine_version','code_digest','environment_digest') if content.get(key)},executed=True)
    warnings=[]
    if content.get('total_rows',0)>len(content.get('rows',[])):
        warnings.append('事实预览仅显示选定行；报告导出仍读取完整固定结果表。 / Preview selection never truncates full report tables.')
    return ResearchFactCatalog(source=source,facts=facts,methods=[method],limitations=limits,warnings=warnings)
