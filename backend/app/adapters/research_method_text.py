"""Versioned, pure presentation of fixed B04 methods; never changes evidence.

This module is bundled with report rebuilds, so keep it standard-library only.
Body text selects the applicable scientific fields explicitly. Full settings,
unknown fields and bulk identities remain in the unchanged evidence/sidecars.
"""
import hashlib
import json

METHOD_PRESENTATION_VERSION = 'bio_insight_readable_v1'
KINDS = {'comparison', 'ora', 'gsea_prerank', 'candidate', 'figure', 'result_import'}
BULK_IDENTITIES = {'observation_keys', 'excluded_observations', 'feature_ids',
                   'background_gene_ids', 'foreground_gene_ids', 'excluded_donors'}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def presentation_enabled(snapshot):
    version = snapshot.get('method_presentation_version')
    if version not in (None, METHOD_PRESENTATION_VERSION):
        raise ValueError('Unsupported method presentation version')
    return version == METHOD_PRESENTATION_VERSION


def insight_method(method):
    return (method.get('id', '').startswith('insight-method-')
            and method.get('source', {}).get('source_kind') in
            ('bio_insight_result_version', 'bio_insight_result_member')
            and method.get('parameters', {}).get('frozen_config', {}).get('kind') in KINDS)


def method_fingerprint(method):
    # Source-specific IDs differ for a result and its members. Only identical
    # scientific records may share prose; preserve each original metadata block.
    return canonical({k: method.get(k) for k in ('parameters', 'software', 'executed')})


def _value(value):
    if value is None:
        return 'NA (null)'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if value == '':
        return '""'
    return str(value)


def _details(value, en, path=''):
    """Flatten settings, retaining every non-bulk leaf and list order."""
    if isinstance(value, dict):
        lines = []
        for key, item in sorted(value.items()):
            label = path + '.' + key if path else key
            if key in BULK_IDENTITIES and isinstance(item, list):
                # A reference plus count/hash is exact and does not expose a
                # large barcode/gene vector as a paragraph or spreadsheet cell.
                label = label.replace('observation_keys', 'spot membership' if en else 'spot 成员')
                lines.append(f'{label}: {len(item)}; SHA256 {hashlib.sha256(canonical(item).encode()).hexdigest()}')
                if key in ('excluded_observations', 'excluded_donors'):
                    reasons = {}
                    for entry in item:
                        reason = entry.get('reason', 'NA') if isinstance(entry, dict) else 'NA'
                        reasons[reason] = reasons.get(reason, 0) + 1
                    lines.extend(_details(reasons, en, label + '.reasons'))
            else:
                lines.extend(_details(item, en, label))
        return lines or [path + ': {}']
    if isinstance(value, list):
        if not value:
            return [path + ': []']
        if all(not isinstance(item, (dict, list)) for item in value):
            return [path + ': ' + ', '.join(_value(item) for item in value)]
        return [line for i, item in enumerate(value, 1) for line in _details(item, en, f'{path}[{i}]')]
    return [path + ': ' + _value(value)]


def _paragraphs(lines, label):
    # Break between complete settings, never truncate their values. A resource
    # list can hold several long source descriptions; one paragraph/cell for the
    # entire list would recreate the original XLSX limit and poor pagination.
    group = []
    for line in lines:
        if group and len('; '.join([*group, line])) > 1200:
            yield label + ' — ' + '; '.join(group)
            group = []
        group.append(line)
    if group:
        yield label + ' — ' + '; '.join(group)


def _selected(data, keys, missing):
    return {key: data[key] if key in data else missing for key in keys}


def _groups(groups):
    return [dict(label=group.get('label'),selected_spots=len(group['observation_keys'])
                 if isinstance(group.get('observation_keys'),list) else None) for group in groups]


def present_method(method, language, *, reference, duplicate_of=None):
    """Return title/paragraphs for recognized methods only; no input mutation."""
    if not insight_method(method):
        return None
    en = language == 'en'; p = method['parameters']; config = p['frozen_config']; kind = config['kind']
    names = {
        'comparison': ('差异比较', 'Differential comparison'),
        'ora': ('过度富集分析', 'Over-representation analysis'),
        'gsea_prerank': ('预排序基因集富集', 'Preranked gene-set enrichment'),
        'candidate': ('候选筛选', 'Candidate selection'),
        'figure': ('结果图件', 'Result figure'),
        'result_import': ('外部结果导入', 'External result import'),
    }
    title = names[kind][1 if en else 0]
    source = method['source']
    origin = ('Source: ' if en else '来源：') + source['source_kind'] + ' / ' + source['source_id'] + '; SHA256 ' + source['sha256']
    pointer = ('Complete fixed parameters: ' if en else '完整固定参数：') + reference
    if duplicate_of is not None:
        text = (f'Same scientific method as method block {duplicate_of}.' if en else f'科学方法与方法块 {duplicate_of} 相同。')
        return dict(title=title, paragraphs=[text, origin, pointer])
    paragraphs = [('Executed: ' if en else '已执行：') + _value(method['executed'])]
    scopes = [p.get('inference_scope'), *p.get('source_inference_scopes', []), *p.get('upstream_inference_scopes', [])]
    if config.get('mode') == 'spot_exploratory' or 'spot_exploratory' in scopes:
        paragraphs.append('Spot counts are not independent donors. Region enrichment is exploratory and does not establish pure cell identity, mechanism or independent validation.' if en else
                          'spot 数不等于独立供体数。区域富集属于探索，不能据此确认纯细胞类型、机制或独立验证。')
    if config.get('data_driven_grouping') is True or p.get('source_data_driven_grouping') is True or p.get('data_driven_grouping') is True:
        paragraphs.append('Groups were data-driven; testing the same expression data is not an independent confirmatory comparison.' if en else
                          '分组由数据驱动；在同一表达数据上检验不属于独立确认性比较。')
    if kind == 'comparison':
        paragraphs.append('Effects are numerator relative to denominator. Frozen group membership counts spots before exclusions, not the effective sample size. Effective spot/donor counts are in the fixed comparison_results table (spots_numerator/denominator, donors_numerator/denominator); donor counts are not recorded in this method metadata and must not be inferred from spots.' if en else
                          '效应方向为分子组相对分母组。冻结分组成员数为排除前的 spot 数，不是有效样本量。实际 spot／供体数见固定 comparison_results 表（spots_numerator/denominator、donors_numerator/denominator）；本方法元数据未记录实际供体数，不能由 spot 数推算。')
    if kind == 'ora':
        paragraphs.append('Background and mapping exclusions are recorded below. Mapped background/foreground sizes and coverage are in the fixed ora_sets and mapping tables; classification counts may overlap and are not an additive denominator.' if en else
                          '背景与映射排除规则见下文。映射后背景、前景大小与覆盖情况见固定 ora_sets 及映射表；分类计数可能重叠，不应相加作为分母。')
    if kind == 'gsea_prerank':
        paragraphs.append('Use the complete signed ranking, not a significance-filtered gene list. Preserve empirical P = 0 as zero; it does not imply infinite significance. FDR follows the recorded GSEA joint-null family, not BH.' if en else
                          '使用完整有符号排序，不以显著基因筛选列表代替。经验 P = 0 保留为零，不代表无限显著性。FDR 按记录的 GSEA 联合零分布族计算，不是 BH。')
    if kind == 'candidate':
        paragraphs.append('Support counts express dependency-group consistency, not independent biological replication or a biological confidence probability.' if en else
                          '支持数表示依赖组的一致性，不等于独立生物学重复或生物学置信概率。')
    if kind == 'figure' and (p.get('actual_figure_type') or config.get('figure_type')) == 'heatmap':
        paragraphs.append('Heatmap values are group mean log1p expression; no row z-score is applied. Analysis is not rerun by plotting.' if en else
                          '热图数值为分组 mean log1p 表达；未进行逐行 z-score 标准化。绘图不重新执行统计分析。')
    if kind == 'result_import':
        recomputed = p.get('system_recomputed_q', {}).get('recomputed')
        paragraphs.append('Original external effects/P/q are preserved and not recomputed. System q recomputation is separate and explicitly recorded below; missing values remain NA, with custom missing tokens retained.' if en else
                          '外部原始效应、P/q 原值保留且未重算。系统 q 重算是独立字段，执行状态见下文；缺失值仍为 NA，并保留自定义缺失标记。')
        if recomputed is False:
            paragraphs.append('System q was not recomputed (recomputed: false).' if en else '系统 q 未重算（recomputed: false）。')
    # No generic config dump: mode-specific scientific fields are explicit.
    # Missing is different from null, zero or false, and never filled by guesses.
    missing='not recorded; see fixed result tables' if en else '未记录；见固定结果表'
    values=dict(config);values.update({k:v for k,v in p.items() if k not in ('config','recipe','frozen_config')})
    def add(zh,english,data):
        if data:paragraphs.extend(_paragraphs(_details(data,en),english if en else zh))
    def fields(zh,english,keys,data=None):
        add(zh,english,_selected(values if data is None else data,keys,missing))
    common=('inference_scope','source_inference_scopes','provenance','source_data_driven_grouping')
    add('范围','Scope',{k:p[k] for k in common if k in p})
    add('特征标识','Feature identity',{k:values[k] for k in ('species_taxon_id','namespace','reference_version') if k in values})

    if kind=='comparison':
        fields('比较与校正','Comparison and correction',('name','mode','direction','correction','family_contrast_ids','minimum_total_counts'))
        for contrast in config.get('contrasts',[]):
            add('固定分组（排除前）','Fixed groups (before exclusions)',dict(contrast_id=contrast.get('contrast_id'),
                numerator=_groups([contrast.get('numerator',{})])[0],denominator=_groups([contrast.get('denominator',{})])[0]))
        fields('统计参数','Statistical parameters',
            ('continuity_correction','effect_pseudocount','ties') if config.get('mode')=='spot_exploratory' else
            ('cooks_filter','independent_filter','lfc_shrinkage','minimum_total_counts','refit_cooks','size_factors_fit_type'),p.get('parameters',{}))
        if config.get('mode') in ('donor_paired','donor_unpaired'):
            fields('供体设计','Donor design',('mapping_confirmed','independence_confirmed','independence_basis','batch_adjustment'))
            add('实际模型诊断','Effective model diagnostics',p.get('model_diagnostics') or {'model_diagnostics':missing})
        for key in ('excluded_observations','excluded_donors'):
            if key in config:
                reasons={}
                for entry in config[key]:
                    reason=entry.get('reason',missing) if isinstance(entry,dict) else missing
                    reasons[reason]=reasons.get(reason,0)+1
                add('排除','Exclusions',{key+'_count':len(config[key]),**({'reasons':reasons} if reasons else {})})
        add('方法警示原文','Recorded method caveats',{'warnings':p['warnings']} if 'warnings' in p else {})
    elif kind=='ora':
        fields('富集检验与筛选','Enrichment test and selection',('name','correction','contrast_ids','direction','q_column','q_threshold','minimum_absolute_effect','min_size','max_size','merge_collections'))
        fields('背景与映射口径','Background and mapping policy',('background','many_to_one_mapping','mapping_excluded_count','classification_counts_mutually_exclusive'))
        for key in ('foreground_member_key','background_source_id','background_member_key'):
            if config.get(key) is not None:add('显式集合来源','Explicit set source',{key:config[key]})
        families=[{k:v for k,v in item.items() if k in ('contrast_ids','direction','family_size')} |
                  {'collection_count':len(item.get('collections',[]))} for item in p.get('family',{}).values()]
        add('多重校正族','Multiplicity families',families)
    elif kind=='gsea_prerank':
        fields('完整排序','Complete ranking',('name','contrast_id','ranking_column','ranking_order','complete_ranking','signed_ranking','complete_input_universe'))
        fields('富集与置换','Enrichment and permutations',('correction','method','permutation_num','seed','weight','min_size','max_size','threads'))
        fields('秩与映射质量','Rank and mapping quality',('many_to_one_mapping','exclusions','tied_rank_fraction','tied_rank_fraction_definition','zero_empirical_p_note'))
        add('映射','Mapping',{k:p.get('mapping',{})[k] for k in ('source_namespace','target_namespace','strip_ensembl_version') if k in p.get('mapping',{})})
    elif kind=='candidate':
        fields('候选筛选规则','Candidate selection policy',('ranking_mode','set_step_policy','same_direction_comparability','support_count_definition','source_step_semantics'))
        if config.get('ranking_mode')=='weighted':
            paragraphs.append('Actual weighted order: score_status complete → partial → unavailable, then score DESC within each status; the recorded ranking below is the tie-break for equal status and score.' if en else
                              '实际加权排序：先按 score_status complete → partial → unavailable 分层，同层按 score DESC；下列记录的排序键仅用于同层同分时继续排序。')
            add('同层同分排序键','Tie-break',{'tie_break':p.get('ranking',missing)})
        else:
            fields('实际候选排序','Actual candidate ranking',('ranking',))
        dependency=p.get('dependencies',{})
        add('依赖与独立性','Dependency and independence',dict(independence_verified=dependency.get('independence_verified',missing),
            dependency_group_count=len(dependency['groups']) if 'groups' in dependency else missing,
            unknown_source_count=len(dependency['unknown_sources']) if 'unknown_sources' in dependency else missing))
        source_ids=config.get('result_source_ids',[])
        source_numbers={identifier:index+1 for index,identifier in enumerate(source_ids)}
        add('主比较','Primary comparison',dict(primary_result_source_id=config.get('primary_result_source_id',missing)))
        for identifier in source_ids:
            add('结果来源与比较','Result source and contrast',dict(source_number=source_numbers[identifier],source_id=identifier,
                contrast_id=config.get('source_contrasts',{}).get(identifier,missing),q_column=p.get('q_columns',{}).get(identifier,missing)))
        for index,step in enumerate(config.get('steps',[]),1):
            operation=step.get('operation');keys={'threshold':('q_column','q_threshold','minimum_absolute_effect'),
                'at_least_k':('k',),'include':('feature_ids',),'exclude':('feature_ids',),
                'annotation':('annotation_field','annotation_operator','annotation_value')}.get(operation,())
            add('有序筛选步骤','Ordered filter step',dict(step=index,operation=operation,source_numbers=[source_numbers.get(s,s) for s in step.get('source_ids',[])],
                **_selected(step,keys,missing)))
        if config.get('ranking_mode')=='weighted':
            fields('加权评分','Weighted scoring',('weights','weighted_components','weighted_unknown'))
    elif kind=='figure':
        figure_type=p.get('actual_figure_type',config.get('figure_type'))
        fields('绘图口径','Figure interpretation',('figure_type','actual_figure_type','analysis_recomputed','raw_values_unchanged','empty_result'))
        add('图轴与固定输入','Axes and fixed input',{k:p[k] for k in ('axes','input_member') if k in p})
        if figure_type=='heatmap':
            fields('表达选择','Expression selection',('contrast_id','top_n'))
            add('表达分组','Expression groups',_groups(config.get('expression_groups',[])))
        elif config.get('figure_type') in ('venn','upset'):
            fields('集合交集','Set intersection',('intersection_mode',))
            if config.get('intersection_mode')=='at_least_k':fields('交集门槛','Intersection threshold',('intersection_k',))
            add('实际集合定义','Selected set definitions',config.get('selected_sets',[]))
        elif config.get('figure_type')=='gsea':
            fields('富集曲线选择','Enrichment curve selection',('contrast_id','term_row_key','member_key'))
        else:
            keys=['contrast_id','top_n','q_column']
            if config.get('figure_type')=='enrichment':keys+=['enrichment_style']
            fields('图示选择','Displayed selection',keys)
        if config.get('figure_type') in ('volcano','enrichment'):
            fields('零值绘图下限','Zero-value display floor',('zero_q_display_floor',))
    elif kind=='result_import':
        fields('外部方法与范围','External method and scope',('original_method','original_correction_scope','observation_level','inference_scope'))
        fields('效应与缺失','Effect and missing-value rules',('contrast_id','numerator','denominator','effect_name','effect_unit','na_values','duplicate_policy','complete_tested_universe'))
        fields('系统 q 执行状态','System q execution',('system_recomputed_q',))
        add('原始字段对应','Original column mapping',config.get('columns',{}))

    if kind in ('ora','gsea_prerank'):
        if not p.get('resources'):add('资源版本','Resource release',{'resources':missing})
        for resource in p.get('resources',[]):
            selected={k:resource[k] for k in ('resource_id','release','namespace','species_taxon_id','sha256') if k in resource}
            selected['source']={k:resource.get('source',{})[k] for k in ('name','institution','release_date','url') if k in resource.get('source',{})}
            if resource.get('usage'):selected['usage']=resource['usage']
            add('资源版本','Resource release',selected)
        upstream=p.get('upstream',[]) or ([dict(methods=p['upstream_methods'],inference_scope=p.get('upstream_inference_scope'))] if 'upstream_methods' in p else [])
        for item in upstream:
            add('上游比较口径','Upstream comparison',dict(inference_scope=item.get('inference_scope',missing),
                **{k:item.get('methods',{})[k] for k in ('name','correction','direction') if k in item.get('methods',{})}))
    if method.get('software',{}).get('engine_version'):
        add('执行软件','Execution software',{'engine_version':method['software']['engine_version']})
    paragraphs.append('Only applicable scientific settings are summarized here. Full settings, resource descriptions, identities and software digests remain in the fixed method record and the referenced machine-readable parameters.' if en else
                      '此处汇总适用的科学设置；完整参数、资源说明、身份列表与软件摘要仍保留在固定方法记录及下列机器可读引用中。')
    paragraphs.extend([origin, pointer])
    return dict(title=title, paragraphs=paragraphs)
