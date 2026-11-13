"""Word download from saved analysis facts; no new workflow or report version."""
import hashlib
import csv
import io
import json
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor

from app.domain.research_results.bio_projection import project_bio_facts
from app.domain.research_results.contracts import FrozenResearchSource
from app.domain.bioinformatics.contracts import digest
from app.domain.bioinformatics.artifact_names import single_cell_report_name
from app.adapters.research_report_docx import build_report
from app.adapters.bio_reader_narrative import load_cached_narrative


def _reason_text(reason,en):
    if reason=='resource_insufficient':return ('Insufficient computation memory' if en else '计算内存不足')+' (resource_insufficient)'
    return str(reason)


def _integration_reason(reason,en):
    reasons={
        'single_batch':('仅有单批次','Only one batch'),
        'batch_values_missing':('批次信息缺失','Batch metadata missing'),
        'batch_too_small':('部分批次细胞不足','Too few cells in a batch'),
        'batch_group_completely_confounded':('批次与研究组完全混杂','Batch and biological group completely confounded'),
        'group_missing_confounding_unassessed':('研究组信息缺失，无法评估混杂','Missing groups; confounding could not be assessed'),
        'covariate_missing_or_nonfinite':('协变量缺失或含非有限值','Covariate missing or nonfinite'),
        'covariate_constant':('协变量为常量','Covariate is constant'),
        'mitochondrial_rule_unconfirmed':('线粒体规则未确认','Mitochondrial rule unconfirmed'),
        'covariate_design_rank_deficient':('协变量设计共线或自由度不足','Collinear covariates or insufficient degrees of freedom'),
        'insufficient_residual_variation':('回归后的变异不足','Insufficient residual variation'),
        'insufficient_cells_for_harmony_default_clusters':('细胞数不足以使用 Harmony 默认群数','Too few cells for Harmony default clusters'),
        'regression_failed':('协变量回归失败','Covariate regression failed'),
        'harmony_failed':('Harmony 运行失败','Harmony execution failed'),
        'resource_insufficient':('计算内存不足','Insufficient computation memory'),
        'disabled':('未启用','Disabled'),
    }
    if not reason:return 'None' if en else '无'
    label=reasons.get(reason,(str(reason),str(reason)))[int(en)]
    return label+' ('+str(reason)+')'


_READER_FIGURE_LABELS = {
    'qc_distribution': ('质量控制指标分布', 'Quality-control metric distributions'),
    'qc_scatter': ('总 counts 与检测基因数关系', 'Total counts and detected genes'),
    'qc_violin': ('质量控制小提琴图', 'Quality-control violin plots'),
    'qc_mitochondrial': ('线粒体指标检查', 'Mitochondrial metric review'),
    'qc_by_sample_id': ('按样本的质量概况', 'Quality overview by sample'),
    'qc_by_batch': ('按批次的质量概况', 'Quality overview by batch'),
    'integration_covariates': ('技术协变量回归前后', 'Technical covariates before and after adjustment'),
    'pca': ('主成分分析', 'Principal component analysis'),
    'pca_variance': ('主成分解释方差', 'Principal-component explained variance'),
    'umap': ('UMAP 细胞分布', 'UMAP cell distribution'),
    'marker_dotplot': ('聚类 marker 点图', 'Cluster marker dot plot'),
    'marker_heatmap': ('聚类 marker 热图', 'Cluster marker heatmap'),
}


def _reader_figure_label(key, language):
    normalized = str(key or '').replace('_page_2', '').replace('_page_3', '')
    normalized = normalized.removesuffix('_png')
    labels = _READER_FIGURE_LABELS.get(normalized)
    if labels:
        return labels[1] if language == 'en' else labels[0]
    return 'Analysis figure' if language == 'en' else '分析图件'


def _reader_summary(manifest, raw_manifest, language):
    summary = manifest.get('summary') if isinstance(manifest.get('summary'), dict) else {}
    en = language == 'en'
    def value(key, default='NA'):
        item = summary.get(key, default)
        return default if item is None else str(item)
    rows = [
        ('Raw cells', value('raw_observations')) if en else ('原始细胞数', value('raw_observations')),
        ('Retained cells', value('retained_observations')) if en else ('保留细胞数', value('retained_observations')),
        ('Raw genes', value('raw_features')) if en else ('原始基因数', value('raw_features')),
        ('Retained genes', value('retained_features')) if en else ('保留基因数', value('retained_features')),
        ('Non-zero entries', value('nnz')) if en else ('非零表达值数量', value('nnz')),
        ('Exploratory clusters', value('clusters')) if en else ('探索性细胞群数', value('clusters')),
    ]
    files = [item.get('filename') for item in raw_manifest.get('source_files', []) if item.get('filename')]
    if files:
        rows.append(('Input files', ', '.join(files)) if en else ('输入文件', '、'.join(files)))
    return rows


def _fallback_reader_narrative(manifest, raw_manifest, language):
    """Reader prose used only when a model narrative has not been cached."""
    summary = manifest.get('summary') if isinstance(manifest.get('summary'), dict) else {}
    en = language == 'en'
    cells = summary.get('retained_observations', 'NA')
    genes = summary.get('retained_features', 'NA')
    clusters = summary.get('clusters', 'NA')
    excluded = summary.get('excluded_observations', 0)
    if en:
        return {
            'abstract': f'This exploratory single-cell analysis retained {cells} cells and {genes} genes and produced {clusters} exploratory clusters. No cells were automatically excluded in the saved run.',
            'design_and_data': 'The report is based on a saved gene-by-cell expression matrix. Sample and donor metadata were not supplied, so the results describe cell-level structure and do not support donor-level inference.',
            'quality_control': f'Quality-control checks completed with {excluded} cells excluded. Mitochondrial filtering and model-based doublet or ambient-RNA correction were not applied in this run.',
            'methods_summary': 'The workflow performed library-size normalization, log1p transformation, highly variable gene selection, PCA, a neighbor graph, UMAP, exploratory Leiden clustering, marker screening and H5AD round-trip verification.',
            'key_findings': f'The saved embedding and clustering workflow produced {clusters} exploratory clusters from {cells} retained cells. These groupings are useful for inspection and follow-up annotation, but they do not establish cell identity or biological mechanism.',
            'limitations': 'The absence of sample and donor mappings prevents independent-replicate assessment and donor-level aggregation. Batch correction was not applied because the required batch information was unavailable.',
            'reader_cautions': 'Treat the figures and clusters as exploratory evidence. Confirm sample provenance, mitochondrial rules, cell labels and biological replication before drawing scientific conclusions.',
        }
    return {
        'abstract': f'This exploratory single-cell analysis retained {cells} cells and {genes} genes and produced {clusters} exploratory clusters. No cells were automatically excluded in the saved run.',
        'design_and_data': 'The report is based on a saved gene-by-cell expression matrix. Sample and donor metadata were not supplied, so the results describe cell-level structure and do not support donor-level inference.',
        'quality_control': f'Quality-control checks completed with {excluded} cells excluded. Mitochondrial filtering and model-based doublet or ambient-RNA correction were not applied in this run.',
        'methods_summary': 'The workflow performed library-size normalization, log1p transformation, highly variable gene selection, PCA, a neighbor graph, UMAP, exploratory Leiden clustering, marker screening, and H5AD round-trip verification.',
        'key_findings': f'The saved embedding and clustering workflow produced {clusters} exploratory clusters from {cells} retained cells. These groupings are useful for inspection and follow-up annotation, but they do not establish cell identity or biological mechanism.',
        'limitations': 'The absence of sample and donor mappings prevents independent-replicate assessment and donor-level aggregation. Batch correction was not applied because the required batch information was unavailable.',
        'reader_cautions': 'Treat the figures and clusters as exploratory evidence. Confirm sample provenance, mitochondrial rules, cell labels, and biological replication before drawing scientific conclusions.',
    }


def _build_reader_facing_report(manifest, raw_manifest, figures, language, narrative=None):
    """Build the reader-facing Word endpoint without traceability fields."""
    en = language == 'en'
    if isinstance(narrative, dict):
        narrative = narrative.get('narrative', narrative)
    narrative = narrative or _fallback_reader_narrative(manifest, raw_manifest, language)
    doc = Document()
    section = doc.sections[0]
    section.page_width = Mm(210); section.page_height = Mm(297)
    section.top_margin = section.bottom_margin = section.left_margin = section.right_margin = Mm(20)
    for name in ('Normal', 'Title', 'Heading 1', 'Heading 2'):
        style = doc.styles[name]
        style.font.name = 'Arial'; style.font.color.rgb = RGBColor(0, 0, 0)
        style.element.get_or_add_rPr().get_or_add_rFonts().set(qn('w:eastAsia'), 'Microsoft YaHei')
    doc.styles['Normal'].font.size = Pt(10)
    doc.styles['Normal'].paragraph_format.space_after = Pt(6)
    doc.add_paragraph('Single-cell RNA-seq analysis report' if en else '单细胞 RNA 测序分析报告', style='Title')
    doc.add_paragraph(
        'This report presents reader-facing scientific prose generated from the saved analysis facts. The language model was used only to organize explanations; it did not alter values, statuses or limitations.' if en else
        '本报告将已保存的分析事实整理为面向读者的科研正文。语言模型只用于组织解释，不修改数值、状态或局限条件。'
    )
    sections = [('Abstract', '摘要', 'abstract'), ('Study design and data', '研究设计与数据范围', 'design_and_data'),
                ('Quality control and result usability', '质量控制与结果可用性', 'quality_control'),
                ('Methods', '分析方法', 'methods_summary'), ('Key findings', '主要结果', 'key_findings'),
                ('Limitations', '局限性', 'limitations'), ('Reader cautions', '阅读提示', 'reader_cautions')]
    for english, chinese, key in sections:
        doc.add_heading(english if en else chinese, 1)
        doc.add_paragraph(str(narrative.get(key, '')))
    doc.add_heading('Key metrics' if en else '关键指标', 1)
    table = doc.add_table(rows=1, cols=2); table.style = 'Table Grid'
    table.rows[0]._tr.get_or_add_trPr().append(OxmlElement('w:tblHeader'))
    table.rows[0].cells[0].text = 'Measure' if en else '指标'
    table.rows[0].cells[1].text = 'Value' if en else '结果'
    for label, value in _reader_summary(manifest, raw_manifest, language):
        row = table.add_row().cells; row[0].text = label; row[1].text = value
    doc.add_heading('Figures' if en else '图件', 1)
    if not figures:
        doc.add_paragraph('No figures were saved for this result.' if en else '本次结果未保存图件。')
    else:
        from PIL import Image
        for index, figure in enumerate(figures, 1):
            label = _reader_figure_label(figure.get('config', {}).get('title') or figure.get('config', {}).get('key'), language)
            p = doc.add_paragraph(f'Figure {index}. {label}' if en else f'图 {index}：{label}')
            p.paragraph_format.keep_with_next = True
            with Image.open(io.BytesIO(figure['content'])) as image:
                width, height = image.size
            ratio = min(170 / width, 210 / height)
            doc.add_picture(io.BytesIO(figure['content']), width=Mm(width * ratio), height=Mm(height * ratio))
            doc.add_paragraph(
                ('The figure is shown for exploratory inspection and should be interpreted together with the limitations above.' if en else
                 '图件用于探索性观察，应结合前述局限条件解读。')
            )
    output = io.BytesIO(); doc.save(output); return output.getvalue()


def build_single_cell_report(project, identifier, manifest_sha256, manifest, raw_manifest, figures, language='zh-CN', *, samples=None, library_algorithms=None, annotation=None, reader_mode=False, narrative=None):
    if reader_mode:
        return _build_reader_facing_report(manifest, raw_manifest, figures, language, narrative=narrative)
    source = FrozenResearchSource(
        project_id=project, source_kind='bio_processed_dataset_version', source_id=identifier,
        sha256=manifest_sha256, title='Single-cell analysis' if language=='en' else '单细胞分析结果',
        provenance='system_computed', content={key:manifest[key] for key in (
            'summary','params','steps','engine_version','code_digest','environment_digest','observation_level','assay') if key in manifest})
    catalog = project_bio_facts(source).model_dump(mode='json')
    finding = {key:catalog[key] for key in ('facts','methods','gaps','warnings','limitations','conflicts')}
    finding.update(sources=[source.model_dump(mode='json')], claims=[])
    samples=raw_manifest.get('samples',[]) if samples is None else samples
    if not samples or not any(sample.get('sample_id') for sample in samples):
        finding['gaps'].append('Sample and donor metadata were not supplied.' if language=='en' else '未提供样本与供者清单；本次结果仅用于细胞层级探索。')
    snapshot = dict(language=language, title='Single cell analysis report' if language=='en' else '单细胞分析报告',
                    basic_analysis=True, input_files=[item['filename'] for item in raw_manifest.get('source_files',[])],
                    samples=samples, finding=dict(id=identifier, sha256=manifest_sha256, content=finding))
    content=build_report(snapshot,figures)
    imported_samples=raw_manifest.get('samples',[])
    algorithms=manifest.get('summary',{}).get('single_cell_algorithms')
    integration=manifest.get('summary',{}).get('single_cell_integration')
    subset=manifest.get('summary',{}).get('subset')
    if not imported_samples and not algorithms and not integration and not subset and not annotation:return content
    doc=Document(io.BytesIO(content));en=language=='en'
    if subset:
        doc.add_heading('Parent selection and subpopulation analysis' if en else '父结果选择与亚群分析',1)
        doc.add_paragraph(('Parent processed result: ' if en else '父处理结果：')+str(subset.get('parent_processed_source',{}).get('processed_dataset_version_id','unknown')))
        doc.add_paragraph(('Selected cells: ' if en else '选中细胞数：')+str(subset.get('selected_cells'))+('；Retained genes: ' if en else '；保留基因数：')+str(subset.get('retained_features')))
        doc.add_paragraph('Cell identities, integer counts, retained genes and capture-library QC are inherited from the fixed parent. scDblFinder and decontX are not rerun on a subpopulation. Normalization, variable genes, embeddings, clustering and markers are computed for the selected cells with the recorded parameters.' if en else
            '细胞身份、整数 counts、保留基因和捕获文库 QC 继承固定父结果。亚群不重新运行 scDblFinder 或 decontX；规范化、可变基因、降维、聚类与 marker 按本次记录的参数对选中细胞重新计算。')
    if annotation:
        _annotation_section(doc,annotation,en)
    if integration:
        doc.add_heading('Covariates and batch integration' if en else '技术协变量与批次整合',1)
        doc.add_paragraph('Adjustments affect the embedding only. Original counts, normalized/log1p expression, marker and pseudobulk inputs are preserved. Batch mixing metrics describe batch structure; they are not biological quality scores. Harmony axes are corrected dimensions and do not have PCA explained-variance labels.' if en else
            '调整仅用于降维表示；原始 counts、normalized/log1p 表达、marker 与 pseudobulk 输入保留。批次混合指标只描述批次结构，不是生物学质量评分。Harmony 轴是校正后的维度，不代表 PCA 解释方差。')
        doc.add_paragraph(('Actual neighbors / UMAP / Leiden representation: ' if en else '邻居图 / UMAP / Leiden 实际使用：')+integration.get('downstream_representation','X_pca'))
        hvg=integration.get('hvg',{})
        strategies={'global_seurat':('全局 Seurat dispersion','Global Seurat dispersion'),'batch_aware_seurat':('批次感知 Seurat dispersion','Batch-aware Seurat dispersion')}
        strategy=strategies.get(hvg.get('strategy'),('未记录','Not recorded'))[int(en)]
        doc.add_paragraph(('Actual HVG strategy: ' if en else 'HVG 实际策略：')+strategy)
        if hvg.get('fallback_reason'):doc.add_paragraph(('Fallback reason: ' if en else '回退原因：')+_integration_reason(hvg['fallback_reason'],en))
        statuses={'completed':('已完成','Completed'),'not_requested':('未启用','Not requested'),'not_computable':('条件不足，未计算','Not computable'),'failed':('运行失败','Failed')}
        for key,label in [('technical_covariates','Technical covariates' if en else '技术协变量'),('harmony','Harmony'),('design','Batch / group design' if en else '批次与研究组设计')]:
            state=integration.get(key,{})
            status=statuses.get(state.get('status'),('未记录','Not recorded'))[int(en)]
            description=label+' · '+status
            if key!='design':
                requested=('Yes' if bool(state.get('requested')) else 'No') if en else ('是' if bool(state.get('requested')) else '否')
                applied=('Applied' if state.get('applied') else 'Not applied') if en else ('已应用' if state.get('applied') else '未应用')
                description+=('; Requested: ' if en else '；请求启用：')+requested+'；'+applied
            doc.add_paragraph(description)
            if state.get('reason'):doc.add_paragraph(('Reason: ' if en else '原因：')+_integration_reason(state['reason'],en))
            if state.get('columns'):doc.add_paragraph(('Covariates: ' if en else '协变量：')+', '.join(state['columns']))
            if state.get('actual_params'):doc.add_paragraph(json.dumps(state['actual_params'],ensure_ascii=False,sort_keys=True))
        doc.add_paragraph(('Actual tool versions: ' if en else '实际工具版本：')+json.dumps(integration.get('versions',{}),ensure_ascii=False,sort_keys=True))
        for diagnostic in integration.get('diagnostics',[]):
            values=[('representation','表示','Representation'),('sampled_cells','抽样细胞','Sampled cells'),('dimensions','维数','Dimensions'),('batch_silhouette','批次轮廓系数','Batch silhouette'),('knn_cross_batch_fraction','异批邻居比例','Cross-batch neighbor fraction')]
            doc.add_paragraph('；'.join((english if en else zh)+': '+str(diagnostic[field]) for field,zh,english in values if diagnostic.get(field) is not None))
            if diagnostic.get('reason'):doc.add_paragraph(_integration_reason(diagnostic['reason'],en))
    if algorithms:
        doc.add_heading('Library quality models' if en else '文库质量模型',1)
        if algorithms.get('inherited_from_parent'):
            doc.add_paragraph('The following model outcomes were inherited from the parent analysis; these are not new model runs on the selected cells.' if en else '下列模型结果继承自父分析，不表示对选中细胞再次运行模型。')
        doc.add_paragraph('Doublet calls are model predictions. Original integer counts remain the basis for normalization, markers and pseudobulk. The floating decontX correction is independent and is exported only when all preliminary-QC libraries succeed.' if en else
            '双细胞分类为模型预测。规范化、marker 和 pseudobulk 保留原始整数 counts；decontX 浮点校正结果独立保存，仅在全部初步 QC 文库成功时输出完整校正层。')
        for key,label in [('doublet','scDblFinder'),('decontx','decontX')]:
            state=algorithms.get(key,{})
            status=state.get('status','unknown')
            labels={'completed':'已完成','partial':'部分完成','not_computable':'不适用或条件不足','failed':'运行失败','not_requested':'未启用'}
            doc.add_paragraph(label+' '+str(algorithms.get('versions',{}).get(label,'unknown'))+' · '+(status if en else labels.get(status,'未知')+' ('+status+')'))
            if state.get('reason'):doc.add_paragraph(('Reason: ' if en else '原因：')+_reason_text(state['reason'],en))
            metrics=[('input_cells','输入细胞','Input cells'),('computed_cells','已计算细胞','Computed cells'),('completed_libraries','完成文库','Completed libraries'),('libraries','文库总数','Total libraries')]
            metrics+=([('predicted_doublets','预测双细胞','Predicted doublets'),('excluded_cells','排除细胞','Excluded cells')] if key=='doublet' else [('corrected_cells','已有污染率结果细胞','Cells with contamination estimates'),('layer_emitted','完整校正层已输出','Complete correction layer exported')])
            doc.add_paragraph('；'.join((english if en else zh)+'：'+str(state[field]) for field,zh,english in metrics if field in state))
        versions=algorithms.get('versions',{})
        doc.add_paragraph(('Actual package versions: ' if en else '实际软件版本：')+'；'.join(f'{key} {value}' for key,value in versions.items()))
        for outcome in library_algorithms or []:
            algorithm='scDblFinder' if outcome.get('algorithm')=='scdblfinder' else 'decontX'
            doc.add_heading(('Library ' if en else '文库 ')+str(outcome.get('library_id') or ('Unknown' if en else '未知'))+' '+algorithm,2)
            fields=[('status','状态','Status'),('reason','适用性或失败原因','Applicability or failure reason'),('input_cells','输入细胞','Input cells'),('computed_cells','已计算细胞','Computed cells'),('seed','随机种子','Random seed')]
            fields+=([('expected_rate','预期双细胞率','Expected doublet rate'),('predicted_doublets','预测双细胞','Predicted doublets'),('excluded_cells','排除细胞','Excluded cells')] if algorithm=='scDblFinder' else [('mean_contamination','平均污染率','Mean contamination')])
            table=doc.add_table(rows=1,cols=2);table.style='Table Grid'
            table.rows[0].cells[0].text='Measure' if en else '指标';table.rows[0].cells[1].text='Actual value' if en else '实际值'
            for field,zh,english in fields:
                if field not in outcome:continue
                row=table.add_row();row.cells[0].text=english if en else zh
                value=outcome.get(field);row.cells[1].text=(_reason_text(value,en) if field=='reason' else str(value)) if value is not None and value!='' else ('Automatic or not supplied' if en else '自动或未提供')
            actual=outcome.get('actual_params')
            if isinstance(actual,str):
                try:actual=json.loads(actual)
                except ValueError:actual=None
            if isinstance(actual,dict):
                names=[('dims','PCA 维数','PCA dimensions'),('nfeatures','模型基因数','Model genes'),('BPPARAM','执行模式','Execution mode'),('maxIter','最大迭代','Maximum iterations'),('umap_threads','UMAP 线程','UMAP threads')]
                details='；'.join((english if en else zh)+'：'+str(actual[field]) for field,zh,english in names if field in actual)
                if details:doc.add_paragraph(details)
    if not imported_samples:
        buffer=io.BytesIO();doc.save(buffer);return buffer.getvalue()
    doc.add_heading('Imported library metadata' if en else '导入文库来源信息',1)
    doc.add_paragraph('Declarations retained from the original import; missing values are unknown. Mapping edits do not replace these declarations.' if en else
        '以下保留原始导入声明；未提供的信息保持未知，后续样本映射修改不覆盖这些来源信息。')
    fields=[('sample_id','原始样本','Original sample'),('library_id','文库','Library'),('donor','原始供者','Original donor'),
        ('species_taxon_id','物种 Taxon ID','Species Taxon ID'),('reference_id','参考标识','Reference ID'),
        ('reference_version','参考版本','Reference version'),('library_chemistry','建库方案','Library chemistry'),('pair_id','配对编号','Pair ID')]
    for sample in imported_samples:
        doc.add_heading(('Library ' if en else '文库 ')+str(sample.get('library_id') or ('Unknown' if en else '未知')),2)
        for key,zh,english in fields:
            doc.add_paragraph((english if en else zh)+'：'+str(sample.get(key) if sample.get(key) is not None else ('Unknown' if en else '未提供')))
    buffer=io.BytesIO();doc.save(buffer);return buffer.getvalue()


def _annotation_section(doc,annotation,en):
    from collections import Counter
    doc.add_heading('Cell annotation and evidence' if en else '细胞注释与依据',1)
    doc.add_paragraph(('Annotation snapshot: ' if en else '注释快照：')+str(annotation['id'])+' · '+str(annotation.get('name','')))
    doc.add_paragraph('Labels are stored independently of the base analysis. Proposed, uncertain and unknown labels remain distinct from researcher-confirmed labels. Model suggestions do not establish biological cell identity.' if en else
        '标签独立于基础分析保存。候选、未确定和未知标签均与研究者确认标签区分；模型建议不能直接确立生物学细胞身份。')
    if annotation.get('is_current') is False or annotation.get('current') is False:
        doc.add_paragraph('This report uses an earlier annotation snapshot. A newer label revision is available.' if en else '本报告引用历史注释快照；已有更新的标签修订。')
    counts=Counter(row.get('label_id') for row in annotation.get('assignments',[]) if row.get('label_id') is not None)
    statuses={'proposed':('候选','Proposed'),'confirmed':('研究者已确认','Researcher confirmed'),'unknown':('未知','Unknown'),'uncertain':('未确定','Uncertain')}
    for label in annotation.get('labels',[]):
        doc.add_heading(str(label['name']),2)
        state=statuses.get(label.get('status'),('未知','Unknown'))[int(en)]
        doc.add_paragraph(('Status: ' if en else '状态：')+state+('; Linked cells: ' if en else '；对应细胞：')+str(counts[label['id']]))
        if label.get('cluster_ids'):doc.add_paragraph('Cluster: '+', '.join(label['cluster_ids']))
        if label.get('note'):doc.add_paragraph(label['note'])
        for evidence in annotation.get('evidence',[]):
            if evidence['label_id']!=label['id']:continue
            source=evidence.get('analysis_artifact_id') or evidence.get('file_id') or ''
            doc.add_paragraph(('Evidence: ' if en else '依据：')+str(evidence['kind'])+(' · '+str(source) if source else '')+' · '+str(evidence.get('note','')))
    unassigned=sum(row.get('label_id') is None for row in annotation.get('assignments',[]))
    doc.add_paragraph(('Unassigned or ambiguous cells: ' if en else '未分配或归属有歧义的细胞：')+str(unassigned))
    algorithm=annotation.get('algorithm')
    if isinstance(algorithm,dict):
        doc.add_heading('Reference based model suggestions' if en else '参考模型建议',2)
        doc.add_paragraph(str(algorithm.get('tool','SingleR'))+' '+str(algorithm.get('version') or algorithm.get('tool_version') or ''))
        reference=algorithm.get('reference',{})
        for field in ('id','reference_id','name','version','source','source_url','license','species','species_taxon_id','gene_id_type','label_level','sha256'):
            if reference.get(field) is not None:doc.add_paragraph(field+': '+str(reference[field]))
        if algorithm.get('matching'):doc.add_paragraph(json.dumps(algorithm['matching'],ensure_ascii=False,sort_keys=True))
        doc.add_paragraph('Scores describe reference similarity, not probabilities or biological validation. Pruned predictions remain unknown or uncertain. Full cell candidates, scores and logs are available with the annotation downloads.' if en else
            '分数表示参考相似性，不是概率或生物学验证。被剪枝的预测保留为未知或未确定；完整逐细胞候选、分数与日志见注释下载。')


def download_single_cell_report(assets, project, identifier, annotation_version_id=None):
    from app.adapters.bio_analysis_store import BioAnalysisStore,error
    store = BioAnalysisStore(assets)
    annotation=None
    with store.store.connection() as db:
        row,manifest,members = store.processed_record(db,project,identifier)
        task = store.store.require_task(db,row['task_id'])
        if task['status']!='succeeded' or manifest.get('assay')!='single_cell':
            raise error('bio_source_conflict')
        if annotation_version_id:
            from app.adapters.bio_annotation_store import BioAnnotationStore
            annotation_store=BioAnnotationStore(assets)
            annotation_row=annotation_store.require(db,'bio_annotation_versions',project,annotation_version_id)
            if annotation_row['processed_dataset_version_id']!=identifier:raise error('bio_source_conflict')
            annotation=annotation_store.get(project,annotation_row['set_id'],annotation_version_id)
        raw_source = manifest.get('raw_source') or manifest['identity']['raw_source']
        _,raw_manifest = store.raw_store.require_version(db,project,raw_source['dataset_id'],raw_source['dataset_version_id'])
        language = task['input_snapshot'].get('output_language','zh-CN')
        figures = []
        marker_overlays=_latest_marker_report_figures(assets,db,project,identifier,language)
        refreshed_kinds={kind for kind,figure in marker_overlays}
        samples = {}
        library_algorithms=[]
        for member in sorted(members,key=_marker_page_order):
            if member['key']=='library_algorithms' and member['format']=='tsv':
                library_algorithms=list(csv.DictReader(io.StringIO(store.objects.read(member).decode('utf-8')),delimiter='\t'))
            if member['key']=='observations' and member['format']=='tsv':
                for observation in csv.DictReader(io.StringIO(store.objects.read(member).decode('utf-8')),delimiter='\t'):
                    sample={field:observation.get(field) or None for field in ('sample_id','library_id','donor','batch','group')}
                    samples.setdefault(tuple(sample.values()),sample)
            if member['format']=='png' and member['role']=='figure_png':
                if any(member['key'].startswith(kind) for kind in refreshed_kinds):
                    continue
                figures.append(dict(content=store.objects.read(member),config=dict(
                    title=member['key'],caption=member['key']+' · SHA256 '+member['sha256'],
                    language=language,figure_language=manifest.get('params',{}).get('output_language','en'))))
        figures.extend(figure for kind,figure in marker_overlays)
        if annotation:
            from app.adapters.bio_figure_store import BioFigureStore
            figure_row=db.execute("""SELECT id FROM bio_figure_versions WHERE project_id=%s
                AND processed_dataset_version_id=%s AND annotation_version_id=%s AND manifest_sha256 IS NOT NULL
                ORDER BY created_at DESC,id DESC LIMIT 1""",(project,identifier,annotation['id'])).fetchone()
            if figure_row:
                figure_store=BioFigureStore(assets);figure=figure_store.get(project,figure_row['id'])
                for member in figure['members']:
                    if member['format']!='png':continue
                    _,image=figure_store.member(project,figure['id'],member['id'])
                    figures.append(dict(content=image,config=dict(title='Cell annotation UMAP' if language=='en' else '细胞注释 UMAP',
                        caption=('Annotation snapshot ' if language=='en' else '注释快照 ')+annotation['id']+' · SHA256 '+member['sha256'],
                        language=language,figure_language=figure['config']['output_language'])))
    narrative = load_cached_narrative(store.assets.directory, project, identifier, language)
    content = build_single_cell_report(project,identifier,row['manifest_sha256'],manifest,raw_manifest,figures,language,
        samples=list(samples.values()),library_algorithms=library_algorithms,annotation=annotation,
        reader_mode=True, narrative=narrative)
    source_file_ids = set(raw_source['source_file_ids'])
    provenance = dict(version_id=identifier, manifest_sha256=row['manifest_sha256'], language=language,
                      figures_sha256=[hashlib.sha256(figure['content']).hexdigest() for figure in figures],
                      narrative_sha256=digest(narrative) if narrative is not None else None)
    if annotation:
        source_file_ids.update(item['file_id'] for item in annotation['evidence'] if item['file_id'])
        provenance['annotation'] = dict(version_id=annotation['id'],
                                        geometry_sha256=annotation_row['geometry_sha256'],
                                        assignments_sha256=annotation_row['assignments_sha256'])
    provenance['source_file_ids'] = sorted(source_file_ids)
    return dict(format='docx', filename=single_cell_report_name(bool(annotation)), sha256=hashlib.sha256(content).hexdigest(),
                provenance=provenance), content


def _latest_marker_report_figures(assets,db,project,identifier,language):
    """Reuse successful immutable render outputs; API hosts never import science libraries."""
    from app.adapters.bio_figure_store import BioFigureStore
    figure_store=BioFigureStore(assets)
    figures=[]
    for kind in ('marker_dotplot','marker_heatmap'):
        row=db.execute("""SELECT id FROM bio_figure_versions WHERE project_id=%s
            AND processed_dataset_version_id=%s AND manifest_sha256 IS NOT NULL
            AND request_key NOT LIKE 'default:%%'
            AND config_json->>'kind'=%s AND config_json->>'output_language'=%s
            ORDER BY created_at DESC,id DESC LIMIT 1""",(project,identifier,kind,language)).fetchone()
        if not row:continue
        figure=figure_store.get(project,row['id'])
        config=figure['config']
        selection=config.get('gene_ids') or []
        selection_text=(f'Selected {len(selection)} feature IDs; see saved config' if language=='en' else f'选定 {len(selection)} 个基因 ID；详见图表配置') if selection else ('Saved top marker panel, at most 100 genes' if language=='en' else '保存的 top marker 面板，最多100基因')
        for member in sorted(figure['members'],key=_marker_page_order):
            if member['format']!='png':continue
            _,image=figure_store.member(project,figure['id'],member['id'])
            title=('Marker dot plot' if language=='en' else 'Marker 点图') if kind=='marker_dotplot' else ('Marker mean expression' if language=='en' else 'Marker 平均表达')
            figures.append((kind,dict(content=image,config=dict(title=title,
                caption=(('Saved figure ' if language=='en' else '已保存图表 ')+figure['id']+' · '+member['key']+' · '+selection_text+' · '+str(config.get('palette','viridis'))+' / '+str(config.get('layer','log1p'))+' · SHA256 '+member['sha256']),
                language=language,figure_language=language))))
    return figures


def _marker_page_order(member):
    """The unsuffixed first PNG precedes numbered continuation PNGs, including page 10+."""
    import re
    key=member['key']
    match=re.fullmatch(r'(marker_(?:dotplot|heatmap))(?:_page_(\d+))?_png',key)
    return (match.group(1),int(match.group(2) or 1)) if match else (key,0)
