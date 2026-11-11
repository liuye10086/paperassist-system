"""Render a deterministic Bulk RNA-seq report from validated facts and saved PNGs."""
from io import BytesIO

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Mm, Pt
from PIL import Image

from .manuscript_docx import _save_document
from .single_cell_insight_report import _table, _value, create_insight_report_document


_FIGURE_TITLES = {
    'qc_missing': ('样本缺失比例', 'Missing values by sample'),
    'expression_distribution': ('样本表达分布', 'Expression distributions'),
    'pca': ('样本 PCA', 'Sample PCA'),
    'correlation_heatmap': ('样本相关性热图', 'Sample correlations'),
    'qc_expression': ('样本表达五数摘要', 'Five-number expression summaries'),
    'sample_clustering': ('样本聚类', 'Sample clustering'),
    'sample_correlation': ('样本相关性', 'Sample correlations'),
    'sample_distance': ('样本距离', 'Sample distances'),
    'pca_scores': ('样本 PCA 得分', 'Sample PCA scores'),
    'pca_variance': ('PCA 解释方差', 'PCA explained variance'),
    'bulk_volcano': ('火山图', 'Volcano plot'),
    'bulk_ma': ('MA 图', 'MA plot'),
    'bulk_summary': ('比较结果数量汇总', 'Comparison counts'),
    'bulk_heatmap': ('差异基因热图', 'DEG heatmap'),
    'bulk_variable_heatmap': ('高变基因热图', 'Variable gene heatmap'),
    'bulk_expression': ('候选基因样本表达', 'Candidate gene expression by sample'),
    'enrichment': ('功能富集图', 'Enrichment plot'),
    'gsea': ('GSEA 曲线', 'GSEA curve'),
}
_COUNTS = {
    'total': ('完整表行数', 'Complete rows'), 'tested': ('进入检验', 'Entered testing'),
    'excluded': ('排除', 'Excluded'), 'not_computable': ('不可计算', 'Not computable'),
    'missing_metric': ('缺所选统计值', 'Missing selected metric'), 'deg': ('达到阈值', 'Meets thresholds'),
    'up': ('上调', 'Up'), 'down': ('下调', 'Down'), 'selected': ('所选方向命中', 'Selected direction'),
}
_STATUS = {
    'completed': ('已执行，有显著结果', 'Performed with significant terms'),
    'no_significant_terms': ('已执行，无显著结果', 'Performed with no significant terms'),
    'not_applicable': ('不适用', 'Not applicable'),
}


def _parameters(doc, parameters, local):
    if parameters:
        rows = [{'parameter': key, 'value': _value(value)} for key, value in parameters.items()]
        _table(doc, rows, ('parameter', 'value'), (local('参数', 'Parameter'), local('值', 'Value')))


def _selection(value, local):
    return (f"{value['q_column']} ≤ {value['q_threshold']}  ·  |log2FC| ≥ {value['minimum_absolute_effect']}  ·  "
            f"{local('方向', 'Direction')} {value['direction']}")


def _contrast_label(value):
    return f"{value['numerator']} vs {value['denominator']}"


def _quality_control(doc, facts, local):
    doc.add_heading(local('数据与样本质控', 'Data and sample quality control'), 1)
    included = {(sample['processed_version_id'], sample['sample_id']) for sample in facts['design'].get('samples', [])}
    reasons = {(sample['processed_version_id'], sample['sample_id']): sample['reason']
               for sample in facts['design']['exclusions']}
    for dataset in facts['qc']['datasets']:
        version = dataset['version_id']
        if len(facts['qc']['datasets']) > 1:
            doc.add_heading(f"{local('处理版本', 'Processed version')} {version}", 2)
        summary = dataset['summary']
        doc.add_paragraph(local(
            f"保留 {summary['retained_observations']} / {summary['raw_observations']} 个样本和 "
            f"{summary['retained_features']} / {summary['raw_features']} 个输入基因。",
            f"QC retained {summary['retained_observations']} of {summary['raw_observations']} samples and "
            f"{summary['retained_features']} of {summary['raw_features']} input genes."))
        files = {item['id']: item['filename'] for item in dataset['input_files'] if 'filename' in item}
        mapping = dataset['sample_mapping'] or {}
        source = mapping.get('source', {})
        if source:
            doc.add_paragraph(f"{local('样本表', 'Sample sheet')} {files.get(source['file_id'], source['file_id'])}")
            fields = ' · '.join(f'{key} → {value}' for key, value in mapping.get('mapping', {}).items() if value)
            if fields:
                doc.add_paragraph(fields)
        positions = {row['sample_id']: row.get('source_row') for row in mapping.get('rows', [])}
        samples = [{**sample, 'source_row': positions.get(sample['sample_id'])} for sample in dataset['samples']]
        doc.add_heading(local('样本身份与源表行', 'Sample identifiers and source rows'), 2)
        _table(doc, samples, ('sample_id', 'source_row', 'condition', 'biological_unit_id', 'donor', 'batch'),
               tuple(local(*labels) for labels in (('样本 ID', 'Sample ID'), ('源表行', 'Source row'), ('组别', 'Condition'),
                     ('生物学单位', 'Biological unit'), ('供者 / 配对', 'Donor / pair'), ('批次', 'Batch'))))
        doc.add_heading(local('质控与模型纳入', 'Quality checks and model inclusion'), 2)
        for sample in samples:
            key = (version, sample['sample_id'])
            sample['model_status'] = local('纳入', 'Included') if key in included else reasons.get(key, local('未纳入', 'Excluded'))
        _table(doc, samples, ('sample_id', 'library_size', 'detected_features', 'missing_count', 'outlier_advisory', 'model_status'),
               tuple(local(*labels) for labels in (('样本 ID', 'Sample ID'), ('文库计数', 'Library counts'), ('检出基因', 'Detected genes'),
                     ('缺失数', 'Missing'), ('异常提示', 'Advisory'), ('模型纳入', 'Model inclusion'))))
        methods = dataset['methods']
        description = methods.get('description_en' if facts['language'] == 'en' else 'description_zh')
        if description:
            doc.add_paragraph(description)
        for step in dataset['steps']:
            if step['status'] != 'completed':
                doc.add_paragraph(f"{step['key']} · {step['status']} · {_value(step.get('reason'))}")
        for report in dataset['quality_reports']:
            identifier = report['file_id']
            doc.add_paragraph(f"{local('上游质控材料', 'Upstream QC material')} {files.get(identifier, identifier)}"
                              f" · {_value(report.get('report_type') or report.get('kind'))}")


def _methods(doc, facts, local):
    doc.add_heading(local('研究设计与统计方法', 'Study design and statistical methods'), 1)
    design = facts['design']
    method = facts['comparison_methods']
    doc.add_paragraph(f"{_value(method.get('name'))}  ·  {_value(design.get('formula'))}  ·  {design['inference_scope']}")
    doc.add_paragraph(local(
        f"设计矩阵秩 {_value(design.get('rank'))}，残差自由度 {_value(design.get('residual_df'))}，参考组 {_value(design.get('condition_reference'))}。",
        f"Design rank {_value(design.get('rank'))}, residual degrees of freedom {_value(design.get('residual_df'))}, "
        f"reference condition {_value(design.get('condition_reference'))}."))
    for key, label in (('species_taxon_id', ('物种 Taxon ID', 'Species taxon ID')), ('namespace', ('基因命名空间', 'Gene namespace')),
                       ('reference_version', ('参考版本', 'Reference version')), ('design_basis', ('设计依据', 'Design basis')),
                       ('independence_basis', ('独立重复依据', 'Replicate independence basis'))):
        value = design.get(key) or (local('未登记', 'Unspecified') if key in ('species_taxon_id', 'reference_version') else 'NA')
        doc.add_paragraph(f'{local(*label)}  {value}')
    confirmation = design['confirmation']
    doc.add_paragraph(f"{local('确认方案版本', 'Reviewed plan version')} {confirmation['plan_version_id']}"
                      f"  ·  {confirmation['confirmed_at']}")
    if design.get('terms'):
        _table(doc, design['terms'], ('term', 'field', 'kind', 'reference_level'),
               (local('模型项', 'Term'), local('字段', 'Field'), local('类型', 'Type'), local('参考水平', 'Reference level')))
    diagnostics = next(iter(method.get('model_diagnostics', [])), {})
    native = diagnostics.get('parameters', {})
    params = dict(design.get('filter', {}))
    params.update({key: native[key] for key in ('size_factors_fit_type', 'alpha', 'cooks_filter', 'independent_filter', 'lfc_shrinkage') if key in native})
    if 'fit_type_effective' in diagnostics:
        params['fit_type_effective'] = diagnostics['fit_type_effective']
    if method.get('correction'):
        params['correction'] = method['correction']
    _parameters(doc, params, local)


def _comparisons(doc, facts, local):
    doc.add_heading(local('差异表达与候选基因', 'Differential expression and candidates'), 1)
    doc.add_paragraph(local('正 log2FC 表示比较前项表达较高，负值表示后项较高。全文保留基因 ID 和比较名称。',
                           'Positive log2FC indicates higher expression in the numerator, and negative values indicate higher expression in the denominator. Gene IDs and comparison labels are preserved.'))
    for contrast in facts['contrasts']:
        doc.add_heading(_contrast_label(contrast), 2)
        units = contrast['units'] or {}
        if units:
            doc.add_paragraph(local(
                f"{contrast['numerator']} 有 {units['n_numerator']} 个样本，{contrast['denominator']} 有 {units['n_denominator']} 个样本。完整配对 {units['complete_pairs']}。",
                f"{contrast['numerator']} has {units['n_numerator']} samples and {contrast['denominator']} has {units['n_denominator']}. "
                f"Complete pairs {units['complete_pairs']}."))
        selection = contrast['selection']
        doc.add_paragraph(_selection(selection, local))
        counts = contrast['counts']
        doc.add_paragraph(' · '.join(f'{local(*_COUNTS[key])} {counts[key]}' for key in _COUNTS))
        top = contrast['top_rows']
        if top:
            doc.add_paragraph(local(f"列出所选方向下排名前 {len(top)} 行，完整筛选命中 {counts['selected']} 行。",
                                    f"Showing the first {len(top)} ranked rows from {counts['selected']} selected rows."))
            _table(doc, top, ('feature_id', 'symbol', 'effect_value', selection['q_column'], 'direction'),
                   (local('基因 ID', 'Gene ID'), local('基因符号', 'Symbol'), 'log2FC', local('所选 q', 'Selected q'), local('方向', 'Direction')))
    for candidate in facts['candidates']:
        selection, top = candidate['selection'], candidate['top_rows']
        doc.add_heading(f"{local('候选筛选', 'Candidate selection')} · {_contrast_label(selection)}", 2)
        doc.add_paragraph(_selection(selection, local))
        doc.add_paragraph(local(f"完整候选 {selection['candidate_count']}，已保存 Top N 表 {selection['displayed_count']}，本文摘录 {len(top)}。",
                                f"Full candidate set {selection['candidate_count']}, saved Top N table {selection['displayed_count']}, shown here {len(top)}."))
        if top:
            _table(doc, top, ('rank', 'feature_id', 'symbol', 'primary_effect', 'primary_q', 'direction'),
                   (local('排名', 'Rank'), local('基因 ID', 'Gene ID'), local('基因符号', 'Symbol'), 'log2FC', local('所选 q', 'Selected q'), local('方向', 'Direction')))
        doc.add_paragraph(candidate['version_id'])


def _enrichment(doc, facts, local):
    doc.add_heading(local('功能富集与 GSEA', 'Functional enrichment and GSEA'), 1)
    if not facts['enrichments']:
        doc.add_paragraph(local('本报告未选入固定功能分析版本。', 'No fixed functional analysis version was selected for this report.'))
    labels = {item['contrast_id']: _contrast_label(item) for item in facts['contrasts']}
    for result in facts['enrichments']:
        ora = result['kind'] == 'ora'
        doc.add_heading(('ORA' if ora else 'GSEA') + ' · ' + ', '.join(labels[key] for key in result['contrast_ids']), 2)
        summary = result['summary']
        metric = 'q_value' if ora else 'fdr_q_value'
        doc.add_paragraph(local(*_STATUS[result['status']]) + f" · {result['status']}")
        if result['not_applicable_reason']:
            doc.add_paragraph(f"{local('原因', 'Reason')} {result['not_applicable_reason']}")
        else:
            doc.add_paragraph(local(f"可计算条目 {summary['row_count']}，其中 {metric} ≤ 0.05 有 {summary['significant_terms']} 条。",
                                    f"Computed terms {summary['row_count']}, including {summary['significant_terms']} with {metric} ≤ 0.05."))
        source = result['source_reference']
        doc.add_paragraph(f"{local('富集使用的物种', 'Taxon used for enrichment')} {source['species_taxon_id']}"
                          f" · {source['taxon_origin']} · {_value(source.get('taxon_evidence'))}")
        for reference in result['resource_references'].values():
            doc.add_paragraph(f"{reference['release']} · {_value(reference.get('reference_status'))}"
                              f" · {local('参考版本', 'Reference version')} {_value(reference.get('reference_version'))}")
        config = result['parameters']
        keys = (('q_column', 'q_threshold', 'minimum_absolute_effect', 'direction', 'merge_collections') if ora else
                ('ranking_column', 'permutation_num', 'seed', 'weight')) + ('min_size', 'max_size')
        parameters = {key: config[key] for key in keys if key in config}
        parameters.update({key: result[key] for key in ('method', 'correction', 'background') if result.get(key)})
        _parameters(doc, parameters, local)
        for coverage in result['coverage']:
            if ora:
                doc.add_paragraph(f"{labels[coverage['contrast_id']]} · {coverage['resource_id']} · {_value(coverage.get('not_applicable_reason'))}")
                for key, label in (('background', ('背景', 'Background')), ('foreground', ('前景', 'Foreground'))):
                    values = coverage[key]
                    doc.add_paragraph(f"{local(*label)}  " + ' · '.join(f'{name} {value}' for name, value in values.items()))
            else:
                values = {key: val for key, val in coverage.items() if key.endswith('_count')}
                _parameters(doc, values, local)
                for resource_id, counts in coverage.get('resources', {}).items():
                    doc.add_paragraph(resource_id + '  ' + ' · '.join(f'{key} {_value(value)}' for key, value in counts.items()))
        if result['top_rows']:
            extra = ('GeneRatio', 'BgRatio') if ora else ('es', 'nes')
            _table(doc, result['top_rows'], ('term_id', 'term_name', metric, *extra),
                   (local('条目 ID', 'Term ID'), local('条目名称', 'Term name'), metric, *extra))
        doc.add_paragraph(result['version_id'])


def _figures(doc, facts, images, local):
    doc.add_heading(local('已保存图件', 'Saved figures'), 1)
    for index, (figure, content) in enumerate(zip(facts['figures'], images, strict=True), 1):
        kind = figure['figure_type']
        title = figure['title'] or local(*_FIGURE_TITLES.get(figure.get('panel') or kind, (kind, kind)))
        caption = doc.add_paragraph(f"{local('图', 'Figure')} {index}  {title}")
        caption.paragraph_format.keep_with_next = True
        if content:
            with Image.open(BytesIO(content)) as png:
                width, height = png.size
            ratio = min(158 / width, 102 / height)
            picture = doc.add_picture(BytesIO(content), width=Mm(width * ratio), height=Mm(height * ratio))
            picture._inline.docPr.set('descr', title)
            picture_paragraph = doc.paragraphs[-1]
            picture_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            picture_paragraph.paragraph_format.keep_with_next = True
        else:
            doc.add_paragraph(local('此版本未保存可嵌入的 PNG。完整包保留可用格式。',
                                    'This version has no embeddable PNG. The complete package retains available formats.'))
        source = doc.add_paragraph(f"{local('图件版本', 'Figure version')} {figure['version_id']}  ·  "
                                   f"{local('来源版本', 'Source version')} {figure['source_version_id']}")
        source.paragraph_format.space_after = Pt(3)
        if figure['png']:
            doc.add_paragraph(f"PNG SHA256 {figure['png']['sha256']}")
        if figure.get('selection'):
            summary = figure['summary']
            prefix = _contrast_label(summary) + ' · ' if 'numerator' in summary and 'denominator' in summary else ''
            doc.add_paragraph(prefix + _selection(figure['selection'], local))
        if figure['summary'].get('empty_result'):
            doc.add_paragraph(f"{local('空图原因', 'Empty plot reason')} {_value(figure['summary'].get('empty_reason'))}")


def _support(doc, facts, local):
    sensitivity = facts['sensitivity']
    if sensitivity:
        doc.add_heading(local('敏感性对照', 'Sensitivity comparison'), 1)
        doc.add_paragraph(local('同一固定结果的筛选对照', 'Filter comparison on one fixed result')
                          if sensitivity['comparison_type'] == 'threshold_only'
                          else local('单独确认的运行对照', 'Comparison of separately reviewed runs'))
        for key, label in (('baseline', ('基线', 'Baseline')), ('scenario', ('对照', 'Scenario'))):
            side = sensitivity[key]
            doc.add_paragraph(f"{local(*label)}  {_contrast_label(side)}  ·  {side['result_version_id']}")
            doc.add_paragraph(_selection(side['selection'], local))
        doc.add_paragraph(local('入选变化按各侧的 q 值、效应阈值和方向筛选统计。',
                                'Selection changes use each side’s q value, effect threshold and direction filter.'))
        change_labels = {
            'stable_up': ('均入选且上调', 'Selected and up in both'),
            'stable_down': ('均入选且下调', 'Selected and down in both'),
            'changed_direction': ('入选方向变化', 'Selected direction changed'),
            'gained': ('新增入选', 'Newly selected'), 'lost': ('移出筛选', 'Dropped from selection'),
            'unchanged': ('均未入选', 'Unselected in both'), 'ineligible': ('至少一侧不可比较', 'Ineligible on one or both sides'),
        }
        _parameters(doc, {local(*change_labels[key]): value for key, value in sensitivity['counts'].items()}, local)
        for key, label in (('added', ('新增样本', 'Added samples')), ('removed', ('移除样本', 'Removed samples')),
                           ('reassigned', ('分组变化', 'Reassigned samples')), ('metadata_changed', ('元数据变化', 'Changed sample metadata'))):
            samples = sensitivity['sample_changes'][key]
            if samples:
                doc.add_paragraph(f"{local(*label)}  {', '.join(samples)}")
        if sensitivity['parameter_changes']:
            doc.add_paragraph(f"{local('变更字段', 'Changed parameters')}  {', '.join(sensitivity['parameter_changes'])}")
    if facts['evidence']:
        doc.add_heading(local('独立计算与实验材料', 'Independent computation and experimental materials'), 1)
    for item in facts['evidence']:
        source = item.get('filename') or item['source_id']
        doc.add_paragraph(f"{source}  ·  {item['classification']}  ·  {item['verification_status']}")
        if item['kind'] == 'independent_analysis':
            doc.add_paragraph(f"{local('生物学独立性状态', 'Biological independence status')} {_value(item.get('independence_status'))}")
            if item.get('shared_processed_source_ids'):
                doc.add_paragraph(f"{local('共享的处理来源版本', 'Shared processed source versions')} "
                                  + ', '.join(item['shared_processed_source_ids']))
        if item.get('note'):
            doc.add_paragraph(item['note'])
        doc.add_paragraph(f"SHA256 {item['sha256']}")


def _references(doc, facts, local):
    doc.add_heading(local('来源、版本与复现', 'Sources, versions and reproduction'), 1)
    doc.add_paragraph(f"{local('事实摘要', 'Facts digest')} SHA256 {facts['facts_digest']}")
    references = facts['references']
    doc.add_paragraph(f"{local('设计确认摘要', 'Reviewed design digest')} SHA256 {facts['design']['confirmation']['reviewed_design_sha256']}")
    for item in facts['qc']['input_files']:
        doc.add_paragraph(f"{item.get('filename', item['id'])}  ·  {item['id']}  ·  SHA256 {item['sha256']}")
    for ref in [references['comparison'], *references['processed'], *references['results'], *references['resources']]:
        doc.add_paragraph(f"{ref.get('kind') or local('处理数据', 'Processed dataset')}  ·  {ref['version_id']}")
        identity = ref.get('identity', {})
        version = ref.get('engine_version')
        doc.add_paragraph(f"SHA256 {ref['manifest_sha256']}" + (f"  ·  {version}" if version else ''))
        for key in ('environment_digest', 'code_digest', 'lock_sha256'):
            if identity.get(key):
                doc.add_paragraph(f"{key} {identity[key]}")
        if ref.get('release'):
            doc.add_paragraph(f"{_value(ref.get('title'))} · {ref['release']} · {ref['namespace']} · Taxon {ref['species_taxon_id']}")
    doc.add_paragraph(local('完整包提供结果表、样本映射、图件、参数、输入清单与复现资料。',
                           'The complete package provides result tables, sample mappings, figures, parameters, an input inventory and reproduction materials.'))


def build_bulk_insight_report(facts, images, *, narrative=None):
    en = facts['language'] == 'en'
    def local(zh, english):
        return english if en else zh

    doc = create_insight_report_document(reader_style=True)
    title = local('Bulk RNA-seq 矩阵下游分析报告', 'Bulk RNA-seq downstream analysis report')
    doc.core_properties.title = title
    doc.core_properties.language = 'en' if en else 'zh-CN'
    doc.add_paragraph(title, style='Title')
    doc.add_paragraph(local('本报告汇总已发布的 Bulk RNA-seq 结果。正文展示摘要，下载表保留完整精度和原始标识。',
                           'This report summarizes published Bulk RNA-seq results. Downloadable tables retain full precision and original identifiers.'))
    for section in (_quality_control, _methods, _comparisons, _enrichment, _support):
        section(doc, facts, local)
    if narrative:
        doc.add_heading(local('辅助解读', 'Reader interpretation'), 1)
        doc.add_paragraph(narrative['narrative']['key_findings'])
        doc.add_paragraph(narrative['narrative']['reader_cautions'])
        doc.add_paragraph(f"{local('解读摘要', 'Interpretation digest')} SHA256 {narrative['narrative_sha256']}")
    if facts['figures']:
        _figures(doc, facts, images, local)
    doc.add_heading(local('解释边界', 'Interpretation limits'), 1)
    for item in facts['limitations']:
        doc.add_paragraph(item)
    _references(doc, facts, local)
    return _save_document(doc)
