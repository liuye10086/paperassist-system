"""Exact saved numeric projection and complete audit exports; no statistical calls."""
import csv,io,json,hashlib
from .contracts import ResearchFact,ResearchFactCatalog,ResearchLocator,ResearchMethod,ResearchSourceSelection
from .bio_projection import fact_id

def leaves(value,path=''):
    if isinstance(value,dict):
        for key,item in sorted(value.items()):yield from leaves(item,f'{path}.{key}' if path else key)
    elif isinstance(value,list):
        for i,item in enumerate(value):yield from leaves(item,f'{path}[{i}]')
    else:yield path,value

def metric_unit(result,path):
    import re
    selection=result['selection'];unit=selection.get('unit',selection.get('outcome_unit',''))
    match=re.match(r'statistics.coefficients\[(\d+)\]\.(beta|se|ci_low|ci_high)$',path)
    if match:return result['statistics']['coefficients'][int(match[1])].get('unit','')
    if selection.get('method')=='kaplan_meier' and path.rsplit('.',1)[-1] in ('time','median','max_time'):return selection.get('time_unit','')
    if path in ('statistics.confidence_interval.low','statistics.confidence_interval.high') and selection.get('task_type')=='group_comparison' and result.get('statistics',{}).get('estimate',{}).get('unit')=='outcome':return unit
    if path.endswith('.n') or path.endswith('_n') or any(x in path.split('.') for x in ('p_value','statistic','coefficient','auc','survival','sample_sizes','df_numerator','df_denominator','matrix')):return ''
    if path=='statistics.estimate.value' and result.get('statistics',{}).get('estimate',{}).get('unit')=='outcome':return unit
    if path.startswith(('overall.','groups.','groups[')) and path.rsplit('.',1)[-1] in ('mean','std','min','q1','median','q3','max','iqr'):return unit
    return ''

def project_statistics_facts(source):
    result=source.content['result'];selection=result['selection'];method=selection.get('method','descriptive_statistics')
    verified=source.content.get('execution_verification')=='verified'
    limitation='统计来源为已保存结果的投影，报告不会重新计算原检验；个体独立性由研究设计确认。'
    multiplicity='多重比较仅保留原结果的预设检验族与校正记录；缺少联合校正依据时状态未知，不补称已控制。'
    facts=[];wanted=source.locator.field_path if source.locator.kind=='field' else None
    for top in ('check','overall','groups','statistics'):
        for path,value in leaves(result.get(top,{}),top):
            if wanted and path!=wanted:continue
            # Numeric facts and explicit NA only; large curves and diagnostics remain complete in tables.
            if type(value) not in (int,float,bool) and value is not None:continue
            if not wanted and len(facts)>=1000:continue
            locator=ResearchLocator(kind='field',field_path=path)
            facts.append(ResearchFact(id=fact_id(source,locator),source_kind='analysis_run',source_id=source.source_id,source_sha256=source.sha256,
                locator=locator,raw_value=value,display_value='NA' if value is None else str(value),unit=metric_unit(result,path),
                verification_status='missing' if value is None else 'verified' if verified else 'unverified',origin='system_computed',
                observation_level='unknown',comparison=method,limitations=[limitation]))
    if wanted and not facts:raise ValueError('Unknown numeric statistics field')
    parameters={k:result[k] for k in ('selection','check','source','setup_revision','analysis_plan') if k in result}
    parameters.update(result_sha256=source.sha256,execution_verification=source.content.get('execution_verification','legacy_unverified'),output_language=source.content.get('output_language','unknown'))
    title=f'Saved statistics: {method}' if source.content.get('output_language')=='en' else f'常规统计 / Saved statistics: {method}'
    en=source.content.get('output_language')=='en'
    description=('Projected from a completed saved run; entering a report does not refit or recompute the original test. Missing intervals and multiplicity remain unknown. '
        if en else '从已完成运行保留实际样本量、原始数值、单位、假设和缺失规则；进入报告不重新计算原检验。')
    source_selection=ResearchSourceSelection(source_kind='analysis_run',source_id=source.source_id,sha256=source.sha256)
    methods=[ResearchMethod(id='statistics-method-'+source.source_id,title=title,description=description,source=source_selection,parameters=parameters,
        software={k:str(v) for k,v in result.get('engine',{}).items() if v is not None},executed=True)]
    return ResearchFactCatalog(source=source,facts=facts,methods=methods,limitations=[limitation,multiplicity],
        warnings=['事实目录最多1000项；完整结果、曲线、逐行审计及配置通过完整表和复现材料导出。'])

def statistics_tables(source):
    result=source.content['result'];tables=[];raws=[]
    # Long tables retain field paths, raw types and null distinctly from zero/empty text.
    sections={k:result[k] for k in ('statistics','overall','groups','check','selection','row_audit') if k in result}
    for key in ('role_records','frozen_role_audit','frozen_plot'):
        if key in source.content:sections[key]=source.content[key]
    sections['provenance']={k:result[k] for k in ('id','file_id','source_sha256','source','setup_revision','analysis_plan','analysis_context','engine','started_at','completed_at') if k in result}
    for key,value in sections.items():
        out=io.StringIO(newline='');writer=csv.writer(out,delimiter='\t',lineterminator='\n');columns=['field_path','raw_type','raw_value','unit'];writer.writerow(columns);n=0
        for path,raw in leaves(value):
            typ='null' if raw is None else 'boolean' if type(raw) is bool else 'integer' if type(raw) is int else 'number' if type(raw) is float else 'string'
            writer.writerow([path,typ,json.dumps(raw,ensure_ascii=False) if typ!='string' else raw,metric_unit(result,key+'.'+path)]);n+=1
        raw=out.getvalue().encode('utf8');name='statistics_'+hashlib.sha256(source.source_id.encode()).hexdigest()[:12]+'_'+key
        tables.append(dict(key=name,columns=columns,expected_rows=n,source=dict(source_kind='analysis_run',source_id=source.source_id),sha256=hashlib.sha256(raw).hexdigest(),provenance='system_computed'))
        raws.append(raw)
    return tables,raws
