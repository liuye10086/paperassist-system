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
    if source.content.get('data_driven_grouping') or source.content['config'].get('data_driven_grouping'):result.append('分组来自同一表达数据，P/q 仅作探索性排序。 / Data-driven grouping is exploratory.')
    return result


def project_insight_facts(source):
    content=source.content;facts=[];limits=limitations(source);scope=content['inference_scope']
    level='spot' if scope=='spot_exploratory' else 'donor' if scope=='donor_inference' else 'unknown'
    origin='external_result' if source.provenance=='external_result' else 'system_computed'

    def add(locator,value,row=None):
        missing=value is None or isinstance(value,str) and (value in content.get('config',{}).get('na_values',[]) or value.strip().lower() in ('','na','n/a','nan','none','null'))
        row=row or {}
        facts.append(ResearchFact(id=fact_id(source,locator),source_kind=source.source_kind,source_id=source.source_id,
            source_sha256=source.sha256,locator=locator,raw_value=value,display_value='NA' if missing else str(value),
            observation_level=row.get('observation_level') if row.get('observation_level') in ('spot','donor','sample') else level,
            unit=str(row.get('effect_unit') or '') if locator.column in ('effect_value','effect_log2fc','effect_log2_normalized') else '',
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
            else:
                fields=[key for key in ('feature_id','contrast_id','term_id','direction','collection','step') if row.get(key)]
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
