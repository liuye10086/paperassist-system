"""Versioned, pure presentation of fixed B04 methods; never changes evidence.

This module is bundled with report rebuilds, so keep it standard-library only.
Body text selects the applicable scientific fields explicitly. Full settings,
unknown fields and bulk identities remain in the unchanged evidence/sidecars.
"""
import hashlib
import json

METHOD_PRESENTATION_VERSION = 'bio_insight_readable_v1'
KINDS = {'integration', 'comparison', 'ora', 'gsea_prerank', 'candidate', 'figure', 'result_import'}
BULK_IDENTITIES = {'observation_keys', 'excluded_observations', 'feature_ids',
                   'background_gene_ids', 'foreground_gene_ids', 'excluded_donors','sample_keys','excluded_samples'}


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


def _sample_groups(groups):
    return [dict(label=group.get('label'),selected_samples=len(group.get('sample_keys',[]))) for group in groups]


def _qpcr_method(method, language, *, reference, duplicate_of=None):
    """Present only the frozen qPCR contract; no inferred n or legacy spot groups."""
    en=language=='en';p=method['parameters'];config=p['frozen_config'];source=method['source']
    title='qPCR relative quantification' if en else 'qPCR 相对定量'
    origin=('Source: ' if en else '来源：')+source['source_kind']+' / '+source['source_id']+'; SHA256 '+source['sha256']
    pointer=('Complete fixed parameters: ' if en else '完整固定参数：')+reference
    if duplicate_of is not None:
        text=f'Same scientific method as method block {duplicate_of}.' if en else f'科学方法与方法块 {duplicate_of} 相同。'
        return dict(title=title,paragraphs=[text,origin,pointer])
    paragraphs=[('Executed: ' if en else '已执行：')+_value(method['executed'])]
    paragraphs.append('Biological inference units use the recorded biological_unit_id and pairing field. Included technical wells are averaged within sample x assay x plate; technical wells do not increase biological n. Effective biological n and complete-pair n are recorded in comparison_results; well counts and missingness are in qpcr_well_audit and qpcr_technical_summary, and are not inferred from configuration membership.' if en else
        '生物学推断按记录的 biological_unit_id 及配对字段识别单位。纳入的技术孔在样本×assay×板内先平均 Cq；技术孔不增加生物学 n。实际生物学 n 和完整对 n 见 comparison_results，逐孔数量及缺失见 qpcr_well_audit 与 qpcr_technical_summary；不从配置成员数推算实际 n。')
    quantification=config.get('quantification',p.get('quantification'))
    if quantification=='delta_delta_cq':
        paragraphs.append('The recorded delta_delta_cq method uses the explicitly confirmed equal-efficiency assumption: subtract reference mean Cq to form delta Cq, subtract the frozen calibrator to form delta-delta Cq, then report 2^(-delta-delta Cq). The assumption is not a measured assay efficiency.' if en else
            '记录的 delta_delta_cq 方法采用明确确认的等效率假设：靶标平均 Cq 减内参平均 Cq 得 ΔCq，再减冻结校准组得 ΔΔCq，报告 2^(-ΔΔCq)。等效率声明不等于已测定 assay 效率。')
    elif quantification=='efficiency':
        paragraphs.append('The recorded efficiency method uses the supplied per-assay amplification factors and their stated basis. Target efficiency ratios are divided by the geometric mean of reference efficiency ratios; missing assay efficiencies are not estimated or replaced by an equal-efficiency assumption.' if en else
            '记录的效率校正方法使用给定的各 assay 扩增因子及其出处。目标效率比除以内参效率比的几何均值；缺失效率不估计，也不替换为等效率假设。')
    paragraphs.append('Reference assays and calibration conditions/sample IDs are fixed below. Technical averaging precedes equal biological-sample weighting of calibrators; incomplete reference/calibrator quantities remain missing. Reference stability and experimental quality are not certified by software checks.' if en else
        '内参 assay、校准条件及样本 ID 按下列冻结设置保留。先平均技术孔，再按生物样本等权形成校准量；内参或校准不完整时相关量保留缺失。软件核对不证明内参稳定性或实验质量。')
    if config.get('paired_plate_policy')=='within_plate_differences':
        paragraphs.append('Only the confirmed complete same-plate pair differences enter the recorded paired test. Plates retain separate relative-quantification calibration; raw Cq is not pooled across plates and no common cross-plate calibrator is claimed.' if en else
            '仅明确确认的同板完整配对差进入记录的配对检验。相对定量仍逐板校准，不合并跨板原始 Cq，也不宣称存在通用跨板校准。')
    elif config.get('cross_plate')=='separate':
        paragraphs.append('The recorded separate-plate policy retains plate strata and separate calibration; it does not authorize pooling raw Cq or independent groups across plates.' if en else
            '记录的分板策略保留板分层及逐板校准，不据此授权合并跨板原始 Cq 或将跨板观测当作独立组。')
    else:
        paragraphs.append('Cross-plate comparability is limited to the explicitly recorded basis; the presentation adds no new calibration evidence.' if en else
            '跨板可比性仅依据明确记录的依据，方法呈现不新增校准证据。')
    paragraphs.append('Contrast strings retain numerator minus denominator direction. Positive delta Cq differences mean lower expression; expression effect_value is the log2 numerator-minus-denominator difference. The predeclared target x contrast x plate-stratum test family and recorded correction are preserved. Mean-test intervals are 95% pointwise log-scale intervals with ordered back-transformed fold endpoints; rank methods do not acquire an unimplemented fold interval.' if en else
        '对比字符串保留分子组 − 分母组方向。正的 ΔCq 差表示表达较低；表达 effect_value 为 log2 表达的分子组减分母组。保留预设靶标×对比×板分层检验族及原校正记录。均值检验区间为 95% 逐点 log 尺度区间，倍数区间按有序端点反变换；秩方法不补造尚未实现的倍数区间。')
    paragraphs.append('The system reanalysis and the relative quantities/statistical claims reported by the original authors retain separate identities. Original checks and discrepancies do not establish reproduction of the original test; undisclosed calibrators or efficiencies are not invented. These calculations are not independent biological validation.' if en else
        '本系统重分析与原作者报告的相对量、原统计声明分别保留身份。原表核对及差异不等于已复现原作者检验；未披露的校准或效率不补造。这些计算不构成独立生物学验证。')
    missing='not recorded; see fixed result tables' if en else '未记录；见固定结果表'
    values=dict(config);values.update({k:v for k,v in p.items() if k not in ('config','recipe','frozen_config')})
    def fields(zh,english,keys,data=None):
        selected=_selected(values if data is None else data,keys,missing)
        paragraphs.extend(_paragraphs(_details(selected,en),english if en else zh))
    fields('实际单位与设计','Recorded units and design',('inference_unit','observation_level','design','statistical_method','statistical_scale','independence_confirmed','independence_basis'))
    fields('原始字段角色','Frozen column roles',('sample_id','biological_unit_id','technical_replicate','plate_id','pair_id','target_id','cq'),config.get('columns',{}))
    fields('定量、内参与校准','Quantification, references and calibration',('quantification','targets','references','calibrator_conditions','calibrator_sample_ids','technical_aggregation','reference_aggregation','calibrator_aggregation','reference_basis'))
    fields('效率依据','Efficiency basis',('equal_efficiency_confirmed','equal_efficiency_basis') if quantification=='delta_delta_cq' else ('efficiency_factors','efficiencies'))
    fields('分板及配对策略','Plate and pairing policy',('cross_plate','cross_plate_basis','paired_plate_policy','paired_plate_basis','paired_plate_inference'))
    for contrast in config.get('contrasts',[]):
        paragraphs.extend(_paragraphs(_details(_selected(contrast,('contrast_id','numerator','denominator'),missing),en),'Frozen contrast' if en else '冻结对比'))
    fields('检验族、区间与缺失','Test family, intervals and missingness',('direction','correction','family_contrast_ids','interval','missing','figures'))
    original=config.get('original_checks',[])
    fields('原作者核对身份','Original-author check identity',('original_check_count','original_report_sources'),dict(original_check_count=len(original),original_report_sources=list(dict.fromkeys(item['original_report_source'] for item in original if item.get('original_report_source')))))
    fields('来源、文献与限制','Source, references and limits',('input_identity','method_references','limitations','warnings'))
    if method.get('software'):fields('执行软件','Execution software',tuple(method['software']),method['software'])
    paragraphs.extend([origin,pointer])
    return dict(title=title,paragraphs=paragraphs)


def present_method(method, language, *, reference, duplicate_of=None):
    """Return title/paragraphs for recognized methods only; no input mutation."""
    if not insight_method(method):
        return None
    en = language == 'en'; p = method['parameters']; config = p['frozen_config']; kind = config['kind']
    if kind=='candidate' and config.get('schema_version')==2:
        return dict(title='Typed external evidence matrix' if en else '类型化外部证据与固定候选矩阵',paragraphs=[('Complete candidate by evidence cross product; source statements, locator matching, human review and independent support remain separate. Matrix computation never upgrades a biological claim.' if en else '输出候选×证据完整交叉表。原文陈述、原件定位核对、人工核对与独立数据支持分开保存；系统整理矩阵不升级原文生物学断言。'),('Unknown is not negative or zero. Species, conditions and disease descendant categories are retained; mutation association does not establish knockout mechanisms.' if en else '未知不等于阴性或零分；保留物种、组织、条件和疾病后代类别差异，突变关联不等于敲除机制。'),('Independent support requires actual fixed result/run, independent material/design, matching object/control and a complete donor overlap audit. Different dependency groups alone prove no independence.' if en else '独立支持必须同时核实实际 run 与固定结果、独立材料和设计、对象与对照以及完整供体重叠核查；不同依赖组本身不证明独立。'),json.dumps(p.get('dependency_groups',{}),ensure_ascii=False),json.dumps(p.get('gaps',[]),ensure_ascii=False),str(reference)])
    if kind=='integration':
        return dict(title='Frozen cross-data integration' if en else '冻结对应与跨数据整合',paragraphs=[('Saved quantitative layers and predeclared pairs; no upstream refit or added transformation.' if en else '复用已保存定量层，预声明特征对，不重跑上游差异、不增加变换；保留全部匹配与排除记录。'),('Descriptive mode computes coefficients only; P/q and independent donor n are NA. Correlation is not causation.' if en else '描述性模式只计算系数；P/q 和独立供体 n 为 NA，matched observations 不代表已验证独立供体。相关不等于因果。'),json.dumps(config,ensure_ascii=False),str(reference)])
    if kind=='comparison' and config.get('schema_version')==3 and config.get('mode')=='qpcr':
        return _qpcr_method(method,language,reference=reference,duplicate_of=duplicate_of)
    if kind=='comparison' and config.get('schema_version')==4:
        return dict(title='Microbiome diversity' if en else '微生物组组成与多样性',paragraphs=[str(p.get('chinese_methods','')),str(p.get('distance','')),str(p.get('ordination','')),str(p.get('limitations','')),json.dumps(p.get('beta',{}),ensure_ascii=False),json.dumps(p.get('source_semantics',{}),ensure_ascii=False),str(reference)])
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
    if kind == 'comparison' and config.get('schema_version')==2:
        paragraphs.append('The observation axis is sample. Two-group effects are groups[0] relative to groups[1]; omnibus tests have no single directional effect. Actual per-feature n_numerator/n_denominator and n_pairs are in comparison_results and feature_sample_counts; frozen group membership counts are before exclusions and missingness.' if en else
            '观测轴为 sample。两组效应为 groups[0] 相对 groups[1]；多组 omnibus 无单一方向效应。每特征实际 n_numerator/n_denominator、n_pairs 见 comparison_results 与 feature_sample_counts；冻结组成员数为排除及缺失处理之前的数量。')
        paragraphs.append('Missing values use per-feature complete cases or complete pairs, without imputation; zero is retained. LOD/nonrandom missingness can bias inference. Observational associations do not establish causality.' if en else
            '缺失按每特征完整观测或完整配对处理，不插补，零值保留；LOD/非随机缺失可能影响推断。观察关联不构成因果证据。')
        if config.get('inference_unit')=='technical':paragraphs.append('Technical measurement exploration only; independent biological n=0.' if en else '仅技术测量层探索；独立生物学 n=0。')
        if config.get('mode')=='bulk_counts':paragraphs.append('The model uses original integer counts. Library-size display normalization and explicit display/PCA transforms never replace model input. Model size factors, normalized counts, design and convergence are exported; no LFC shrinkage is applied. Original DESeq2 padj is separate from within-contrast/global predeclared BH q.' if en else
            '模型使用原始整数 counts；显示层 library-size 归一化及显式显示/PCA 变换不替代模型输入。完整导出模型 size factors、归一化 counts、设计及收敛诊断；不做 LFC shrinkage。原 DESeq2 padj 与预声明对比内/全局 BH q 分开。')
    elif kind == 'comparison':
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
    if kind == 'figure' and config.get('sample_groups'):
        paragraphs.append('The plot uses individual selected samples with their frozen layer, units and missing mask; no group averaging or automatic log is performed. Explicit z_score applies only when recorded true, using measured values and sample SD. Distribution plots retain every measured point and report measured/missing n per group. Plotting does not refit the statistical model.' if en else
            '图件读取选定样本的冻结处理层、单位及缺失掩码，不做组均值替代或自动 log。仅 z_score 明确为 true 时，按实测值及样本标准差计算。分布图保留每个实测点并标明各组实测/缺失 n；绘图不重新拟合统计模型。')
    elif kind == 'figure' and (p.get('actual_figure_type') or config.get('figure_type')) == 'heatmap':
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

    if kind=='comparison' and config.get('schema_version')==2:
        fields('样本比较与校正','Sample comparison and correction',('name','mode','design','method','direction','correction','family_contrast_ids','posthoc'))
        fields('推断单位与设计依据','Inference unit and design basis',('inference_unit','inference_goal','independence_confirmed','independence_basis','technical_exploration_confirmed','design_basis','pairing_field','batch_adjustment'))
        for contrast in config.get('contrasts',[]):
            add('固定样本分组（排除前）','Fixed sample groups (before exclusions)',dict(contrast_id=contrast.get('contrast_id'),groups=_sample_groups(contrast.get('groups',[]))))
        fields('实际处理层','Actual measurement layer',('analysis_layer','layer','biological_n_by_contrast'))
        if config.get('mode')=='bulk_counts':
            fields('模型设置','Count model settings',('minimum_total_counts','size_factor_method'))
            for diagnostic in p.get('model_diagnostics',[]):
                add('实际模型诊断','Effective model diagnostics',{k:diagnostic[k] for k in ('contrast_id','formula','rank','residual_degrees_freedom','parameters','warnings','fit_type_requested','fit_type_effective') if k in diagnostic})
        add('缺失与排除','Missingness and exclusions',dict(missing_policy=config.get('missing_policy'),excluded_samples=config.get('excluded_samples',[])))
        if config.get('inference_unit')=='technical':
            add('技术重复描述性质量','Descriptive technical repeat quality',p.get('technical_replicate_qc') or {'technical_replicate_qc':missing})
        add('方法警示原文','Recorded method caveats',{'warnings':p['warnings']} if 'warnings' in p else {})
    elif kind=='comparison':
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
        if config.get('sample_groups'):
            fields('样本图选择','Sample plot selection',('contrast_id','top_n','analysis_layer','feature_ids','z_score'))
            add('样本分组','Sample groups',_sample_groups(config['sample_groups']))
        elif figure_type=='heatmap':
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
