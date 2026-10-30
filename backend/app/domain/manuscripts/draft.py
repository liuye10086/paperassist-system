"""Deterministic fact transcription. No model, statistical estimation or inference."""
from copy import deepcopy
from app.core.exceptions import StorageError
from .contracts import METHOD_FIELDS,WORKFLOW
from .sources import read_source


FIELD_LABELS={
    'research_question':('Research question','研究问题'),'purpose':('Purpose','研究目的'),'hypothesis':('Hypothesis','研究假设'),
    'study_design':('Study design','研究设计'),'population':('Study population','研究对象'),'samples':('Samples','样本'),
    'groups':('Groups','分组'),'materials':('Materials','材料'),'procedures':('Procedures','步骤'),'conditions':('Conditions','条件'),
    'statistical_methods':('Statistical methods','统计方法'),'ethics':('Ethics information','伦理信息'),
    'check':('Record check','记录检查'),'overall':('Overall','总体'),'statistics':('Statistics','统计量'),
    'n':('Sample size','样本量'),'mean':('Mean','均值'),'std':('Sample standard deviation','样本标准差'),
    'min':('Minimum','最小值'),'max':('Maximum','最大值'),'median':('Median','中位数'),
    'q1':('Lower quartile','下四分位数'),'q3':('Upper quartile','上四分位数'),'iqr':('Interquartile range','四分位距'),
    'valid_count':('Complete records','有效记录数'),'excluded_count':('Excluded records','排除记录数'),
    'total_count':('Source records','来源记录数'),'total_rows':('Source rows','来源行数'),'valid':('Valid','有效'),
    'label':('Label','名称'),'variables':('Variables','变量'),'name':('Name','名称'),'unit':('Unit','单位'),
    'column':('Variable column','变量列'),'type':('Type','类型'),'method':('Method','方法'),'method_name':('Method','方法'),
    'coefficient':('Coefficient','系数'),'p_value':('P value','P值'),'p':('P value','P值'),'rho':('Correlation coefficient','相关系数'),
    'r':('Correlation coefficient','相关系数'),'ci_lower':('Lower confidence bound','置信下限'),'ci_upper':('Upper confidence bound','置信上限'),
    'coefficients':('Coefficients','系数'),'estimate':('Estimate','估计值'),'effect_size':('Effect size','效应量'),
    'statistic':('Test statistic','检验统计量'),'df':('Degrees of freedom','自由度'),'term':('Term','项'),
    'auc':('Area under ROC curve','ROC曲线下面积'),'events':('Events','事件数'),'censored':('Censored','删失数'),
    'confidence_interval':('Confidence interval','置信区间'),'lower':('Lower bound','下限'),'upper':('Upper bound','上限'),
    'ready':('Ready for analysis','可分析'),'warnings':('Warnings','注意事项'),'issues':('Issues','问题'),
    'row_count':('Source row count','来源行数'),'mode':('Analysis mode','分析模式'),'value':('Value','值'),
    'low':('Lower bound','下限'),'high':('Upper bound','上限'),'level':('Confidence level','置信水平'),
    'reason':('Reason if unavailable','无法计算原因'),'inference':('Inference settings','推断设置'),
    'alternative':('Test alternative','检验备择'),'rank_method':('Rank method','秩次方法'),
    'permutation_type':('Permutation type','置换类型'),'n_resamples':('Resampling count','重采样次数'),
    'seed':('Random seed','随机种子'),'exact':('Exact calculation','精确计算'),'matrix':('Correlation matrix','相关矩阵'),
}

def label(field,en):
    return FIELD_LABELS.get(field,(field.replace('_',' ').capitalize(),field.replace('_',' ')))[0 if en else 1]

def system_value(value,en,field):
    """Translate program-owned values only; source labels and user prose stay exact."""
    if not isinstance(value,str) or field not in ('warnings','issues','message','method','reason','mode','alternative','rank_method','permutation_type','design','policy','code'):
        return value
    from app.domain.correlation_facts import P_METHODS,REASONS
    from app.domain.comparison_facts import P_METHODS as COMPARISON_P,REASONS as COMPARISON_R,WARNINGS,METHODS
    values={**P_METHODS,**COMPARISON_P,**REASONS,**COMPARISON_R,**WARNINGS,**METHODS,
        'pearson':('Pearson相关','Pearson correlation'),'spearman':('Spearman秩相关','Spearman rank correlation'),
        'fisher_z':('Fisher z置信区间','Fisher z confidence interval'),
        'correlation_not_causation':('相关性不能证明因果关系。','Correlation does not establish causation.'),
        'small_sample':('小样本结果可能不稳定。','Small-sample results may be unstable.'),
        'monte_carlo_p_value':('P值使用已保存的Monte Carlo置换方法。','P values use the saved Monte Carlo permutation method.'),
        'pair':('两变量相关','Pair of variables'),'matrix':('探索性相关矩阵','Exploratory correlation matrix'),
        'two-sided':('双侧检验','Two-sided test'),'average':('平均秩','Average ranks'),'pairings':('配对置换','Pairings permutation'),
        'independent':('独立样本','Independent samples'),'paired':('配对样本','Paired samples'),'multiple':('多组比较','Multiple groups'),
        'none':('无','None'),'all_pairs_holm':('全部预设组对使用Holm校正','All predeclared pairs with Holm correction'),
        'ols':('普通最小二乘回归','Ordinary least-squares regression'),'logistic':('二元Logistic回归','Binary logistic regression'),
        'roc_auc':('ROC曲线下面积','Area under the ROC curve'),'kaplan_meier':('Kaplan–Meier生存分析','Kaplan–Meier survival analysis'),
        '样本量较小，结果可能不稳定。':('样本量较小，结果可能不稳定。','Small-sample results may be unstable.'),
        '样本量较小，推断可能不稳定。':('样本量较小，推断可能不稳定。','Small-sample inference may be unstable.'),
        '有效记录不足 2 条，样本标准差无法计算。':('有效记录不足2条，样本标准差无法计算。','Sample standard deviation is unavailable with fewer than two complete records.'),
    }
    return values[value][1 if en else 0] if value in values else value.replace('_',' ')

def flat_values(value,prefix='',*,en=True,field=None):
    if isinstance(value,dict):
        for key,item in sorted(value.items()):
            if field=='issues' and key in ('id','code','field','allowed_resolutions','requires_resolution'): continue
            yield from flat_values(item,prefix+' / '+label(str(key),en) if prefix else label(str(key),en),en=en,field=key)
    elif isinstance(value,list):
        for index,item in enumerate(value): yield from flat_values(item,prefix+f' {index+1}',en=en,field=field)
    else:
        yield [prefix,('Unavailable' if en else '无法计算或未提供') if value is None else ('Yes' if value else 'No') if isinstance(value,bool) and en else ('是' if value else '否') if isinstance(value,bool) else str(system_value(value,en,field))]

def result_text(result,en):
    """Transcribe only present numerical facts, without deriving any conclusion."""
    statistics=result.get('statistics',{})
    values=[]
    for key in ('n','coefficient','auc'):
        if key in statistics and statistics[key] is not None:
            values.append(('n' if key=='n' else label(key,en))+' = '+str(statistics[key]))
    p=statistics.get('p_value')
    if isinstance(p,dict) and p.get('value') is not None: values.append('P = '+str(p['value']))
    ci=statistics.get('confidence_interval')
    if isinstance(ci,dict) and ci.get('low') is not None and ci.get('high') is not None:
        values.append(('Confidence interval' if en else '置信区间')+' = ['+str(ci['low'])+', '+str(ci['high'])+']')
    if 'overall' in result:
        overall=result['overall']
        for key in ('n','mean','std','median','iqr'):
            if overall.get(key) is not None: values.append(('n' if key=='n' else label(key,en))+' = '+str(overall[key]))
    return '; '.join(values)


def freeze(service,project,request,*,frozen_sources=None,frozen_citation=None):
    en=request.output_language=='en'
    sources=deepcopy(frozen_sources) if frozen_sources is not None else [read_source(service,project,s) for s in request.sources]
    lookup={s['id']:s for s in sources};issues=[];methods=[]
    def issue(identity,kind,field,message,values=None):
        if any(i['id']==identity for i in issues): return
        issues.append(dict(id=identity,kind=kind,field=field,message=message,values=values or []))
    conflicts={c.field:c for c in request.method_conflicts}
    for field,text in request.methods.model_dump().items():
        if field in conflicts:
            conflict=conflicts[field]
            issue('conflict:'+field,'conflict',field,
                label(field,en)+(': Conflicting facts excluded; verification required. ' if en else '：矛盾事实已排除，待核实。')+conflict.note,conflict.values)
        elif not text.strip():
            issue('missing:'+field,'missing',field,label(field,en)+(': Not supplied; to be completed.' if en else '：资料未提供，待补充。'))
        else:
            methods.append(dict(id='methods:'+field,text=label(field,en)+(' (user provided): ' if en else '（用户提供）：')+text,
                origin='user_provided',source_ids=request.method_source_ids.get(field,[]),citations=[]))
    groups=[];figure_count=0;table_count=0;used_results=set();used_figures=set();used_notes=set();notes={n.figure_id:n for n in request.figure_notes}
    image_lookup={s['id']+':'+image['id']:(s,image) for s in sources if s['role']=='image_observation' and s['kind']=='document_version' for image in s['content'].get('images',[])}
    def expanded(ids):
        result=[]
        for identity in ids:
            source=lookup.get(identity)
            if source and source['kind']=='document_version':
                selected=[key for key,(s,image) in image_lookup.items() if s['id']==identity]
                if not selected: issue('missing:image:'+identity,'missing',identity,'No saved image pixels available in this document version.' if en else '此文档版本没有已保存的图片字节，待补充。')
                result.extend(selected)
            else: result.append(identity)
        return result
    def figure(identity):
        nonlocal figure_count
        source,image=image_lookup.get(identity,(lookup.get(identity),None))
        if not source or source['role']!='image_observation' or source['kind'] not in ('figure','figure_language_version','original','document_version'):
            raise StorageError('task_input_invalid','图表必须关联已选图表或原始图片。',422)
        if identity in used_figures: raise StorageError('task_input_invalid','图表不能重复编号。',422)
        used_figures.add(identity);content=source['content']
        if image is not None:
            title=source['label']+' — '+image['id']
            candidate='; '.join(image['caption_candidates'])
            caption=(('Candidate source caption (verify): ' if en else '候选来源图注（待核对）：')+candidate) if candidate else ('Document image observation; caption to be supplied.' if en else '文档图片观察；图注待补充。')
            explicit=notes.get(identity) or notes.get(source['id'])
            if not candidate and not (explicit and explicit.caption): issue('missing:caption:'+identity,'missing',identity,'Image caption not supplied.' if en else '图片图注未提供，待补充。')
        elif source['kind'] in ('figure','figure_language_version'):
            language=content.get('language') or content.get('output_language') or 'zh-CN'
            if language!=request.output_language: raise StorageError('task_source_conflict','图中文字语言与事实稿不一致，请先生成对应语言图表。',409)
            title=content.get('title') or source['label'];caption=content.get('caption') or ''
        else:
            if content['source']['file_type'] not in ('png','jpeg'): raise StorageError('task_input_invalid','仅图片原件可作为观察图。',422)
            title=source['label'];caption='User-provided image; no statistical values inferred.' if en else '用户提供原始图片；未从图片推断统计值。'
        figure_count+=1;note=notes.get(identity) or notes.get(source['id'])
        if note: used_notes.add(note.figure_id)
        supplied=bool(note and note.caption.strip())
        source_caption=bool(image and candidate.strip() or source['kind'] in ('figure','figure_language_version') and caption.strip())
        caption_status='supplied' if supplied else 'candidate' if image and source_caption else 'source' if source_caption else 'missing'
        if caption_status=='missing':
            issue('missing:caption:'+identity,'missing',identity,
                f'Figure {figure_count}: Image caption not supplied; additional material required.' if en else f'图 {figure_count}：图片图注未提供，待补充。')
            caption='Image caption to be supplied; no statistical values inferred.' if en else '图片图注待补充；未从图片推断统计值。'
        elif caption_status=='candidate':
            issue('verify:caption:'+identity,'limitation',identity,
                f'Figure {figure_count}: The source caption candidate requires researcher verification.' if en else f'图 {figure_count}：来源候选图注需研究人员核对。')
        return dict(id=identity,number=figure_count,title=title,caption=note.caption if supplied else caption,caption_status=caption_status,
            caption_origin='user_provided' if supplied else 'source',panels=[p.model_dump() for p in note.panels] if note else [],
            sha256=image['sha256'] if image else source['sha256'],source_ids=[source['id']],
            preview_url=image['preview_url'] if image else source['download_url'],**(dict(image_id=image['id']) if image else {}))
    for group in request.results_groups:
        paragraphs=[];tables=[]
        for identity in group.analysis_run_ids:
            source=lookup.get(identity)
            if not source or source['kind']!='analysis_run' or source['role']!='computed_results' or identity in used_results:
                raise StorageError('task_input_invalid','Results必须绑定不同的已选系统统计结果。',422)
            used_results.add(identity);result=source['content'];kind=result.get('result_type','descriptive')
            table_count+=1;table_number=('Table ' if en else '表 ')+str(table_count)
            facts_text=result_text(result,en)
            paragraphs.append(dict(id='results:'+identity,text=(f'{source["label"]}: {facts_text}. Saved numerical facts are listed in {table_number}.' if en else f'{source["label"]}：{facts_text}。冻结数值事实见{table_number}。'),origin='computed_result',source_ids=[identity],citations=[]))
            facts={k:deepcopy(result[k]) for k in ('check','overall','groups','statistics','variables') if k in result}
            rows=list(flat_values(facts,en=en))
            tables.append(dict(id='table:'+identity,number=table_count,title=table_number+'. '+source['label'],columns=['Saved fact','Value'] if en else ['冻结事实','值'],rows=rows,source_ids=[identity]))
            actual_method=result.get('statistics',{}).get('method') or result['selection'].get('method')
            method_labels={'descriptive':('Descriptive summaries of complete selected observations. Sample standard deviation uses n-1; quantiles use linear interpolation at (n-1)p. No significance test was performed.','对选定字段的完整记录进行描述统计。样本标准差采用n−1，分位数采用(n−1)p线性插值；未进行显著性检验。'),
                'correlation':('Correlation analysis of the saved variables.','对冻结变量进行相关分析。'),
                'group_comparison':('Comparison of the saved groups.','对冻结组别进行比较。'),
                'regression':('Regression analysis of the saved outcome and predictors.','对冻结结局和预测变量进行回归分析。'),
                'roc':('ROC analysis of the saved outcome and score.','对冻结结局与评分进行ROC分析。'),
                'survival':('Survival analysis of the saved event and follow-up variables.','对冻结事件与随访变量进行生存分析。')}
            method_text=method_labels.get(kind,('Saved statistical analysis.','已保存的统计分析。'))[0 if en else 1]
            method_names={'pearson':('Pearson correlation','Pearson相关分析'),'spearman':('Spearman rank correlation','Spearman秩相关分析'),
                'welch_t':('Welch t test','Welch t检验'),'paired_t':('Paired t test','配对t检验'),'mann_whitney_u':('Mann–Whitney U test','Mann–Whitney U检验'),
                'wilcoxon':('Wilcoxon signed-rank test','Wilcoxon符号秩检验'),'welch_anova':('Welch analysis of variance','Welch方差分析'),'kruskal_wallis':('Kruskal–Wallis test','Kruskal–Wallis检验')}
            if actual_method: method_text+=(' Saved method: ' if en else ' 已保存方法：')+method_names.get(actual_method,(actual_method,actual_method))[0 if en else 1]
            variable_names=[v['name'] for v in result.get('variables',[]) if isinstance(v,dict) and v.get('name')]
            if variable_names: method_text+=(' Variables: ' if en else ' 变量：')+', '.join(variable_names)
            methods.append(dict(id='methods:analysis:'+identity,text=method_text,origin='computed_result',source_ids=[identity],citations=[]))
        groups.append(dict(id=group.id,title=group.title,paragraphs=paragraphs,tables=tables,figures=[figure(i) for i in expanded(group.figure_ids)]))
    extra_figures=[i for i in expanded([s['id'] for s in sources if s['role']=='image_observation' and s['kind'] in ('original','figure','figure_language_version','document_version')]) if i not in used_figures]
    if extra_figures: groups.append(dict(id='source-observations',title='Source image observations' if en else '来源图片观察',paragraphs=[],tables=[],figures=[figure(i) for i in extra_figures]))
    if set(notes)-used_notes: raise StorageError('task_input_invalid','图注必须绑定已选图片。',422)
    from .illustrations import attach_references
    attach_references(groups,request.output_language,issue)
    for source in sources:
        if source['role']=='user_results':
            issue('uncomputed:'+source['id'],'limitation',source['id'],'User-provided material was not recomputed and is not included as computed Results.' if en else '用户资料未重算，未作为系统统计结果写入Results。')
        if source['role'] in ('image_observation','literature'):
            issue('origin:'+source['id'],'limitation',source['id'],'Image observations and literature findings are not this study’s computed results.' if en else '图片观察及文献发现不属于本研究计算结果。')
        if source['kind']=='analysis_run' and source['id'] not in used_results:
            issue('ungrouped:'+source['id'],'missing',source['id'],'Selected result is not assigned to a Results group.' if en else '所选统计结果未分配到Results分组。')
    if not used_results: issue('missing:results','missing','results','No computed Results selected.' if en else '尚未选择系统统计结果。')
    references=[];citation=None
    if request.citation_draft:
        if frozen_citation is not None:
            citation=deepcopy(frozen_citation)
        else:
            with service.store.connection() as db:
                root,row=service.citations.draft_row(db,project,request.citation_draft.id,request.citation_draft.revision)
                citation=deepcopy(row['snapshot_json'])
                if root['revision']!=request.citation_draft.revision or citation['output_language']!=request.output_language or service.citations.current_changes(db,project,citation):
                    raise StorageError('task_source_conflict','引用样稿语言或当前支持来源已变化，请重新核对。',409)
                # Re-run the complete current source/review/metadata gate, never copy decisions to changed text.
                resolved=service.citations.resolve(db,project,row['request_json'])
                if any(citation[k]!=v for k,v in resolved.items()): raise StorageError('task_source_conflict','引用冻结内容不一致。',409)
        references=deepcopy(citation['output']['references'])
        for paragraph in citation['output']['paragraphs']:
            methods.append(dict(id='literature:'+paragraph['id'],text=('Literature finding (not this study’s results): ' if en else '文献发现（并非本研究结果）：')+paragraph['text'],origin='literature',source_ids=[],citations=[]))
    issue('scope','limitation','scope','Local deterministic fact draft; Results and Materials and methods only. Missing facts require completion; no complete manuscript or model writing.' if en else '本地确定性事实稿，仅含Results与Materials and methods。缺失事实待补充，不代表完整论文或模型写作。')
    notice=issues[-1]['message']
    from .illustrations import check_references
    for item in check_references(groups,request.output_language,methods):
        issue(item['id'],item['kind'],item['field'],item['message'],item['values'])
    snapshot = dict(schema_version=1,illustration_check_version=1,workflow_version=WORKFLOW,project_id=project,title=request.title,output_language=request.output_language,
        notice=notice,methods=methods,results_groups=groups,references=references,issues=issues,sources=sources,citation_snapshot=citation)
    if request.analysis_handoff_run_ids:
        snapshot['analysis_handoff_run_ids']=request.analysis_handoff_run_ids
    if getattr(request, 'thesis', None) is not None:
        from .school import seed_school_snapshot
        snapshot = seed_school_snapshot(snapshot, service.freeze_school_context(project, request))
    return snapshot
