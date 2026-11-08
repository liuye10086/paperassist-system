"""Word-only delivery of saved donor comparisons and enrichment; no computation."""
import csv
import io
import json
import math
import re

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor

from app.adapters.bio_reader_narrative import load_cached_narrative


def _value(value):
    if value is None or value == '':return 'NA'
    if isinstance(value,bool):return 'true' if value else 'false'
    return str(value)


def _table_value(value,column):
    text=_value(value)
    numeric_columns={'proportion','proportion_difference','proportion_ratio','t_statistic',
        'p_value','p_adjust','effect_value','q_within_contrast','q_global_family','nes',
        'q_value','nominal_p_value','fdr_q_value','pseudotime','weight','stability_weight','absolute_weight_difference','probability','cell_permutation_p_value','donor_p_value','donor_q_value','difference','mean_denominator','mean_numerator'}
    if column in numeric_columns and re.fullmatch(r'[+-]?(?:\d+\.\d*|\.\d+|\d+(?:\.\d*)?[eE][+-]?\d+)',text):
        number=float(text)
        if math.isfinite(number):return format(number,'.6g')
    return text


def _scalars(value,prefix='',depth=0):
    if not isinstance(value,dict) or depth>3:return []
    rows=[]
    for key,item in value.items():
        path=f'{prefix}.{key}' if prefix else key
        if isinstance(item,dict):rows.extend(_scalars(item,path,depth+1))
        elif isinstance(item,list):
            if item and len(item)<=10 and all(type(v) in (str,int,float,bool) for v in item):
                rows.append((path,', '.join(_value(v) for v in item)))
        elif item is None or type(item) in (str,int,float,bool):rows.append((path,_value(item)))
    return rows


def _table(doc,rows,columns,display_columns=None):
    display_columns=display_columns or columns
    table=doc.add_table(rows=1,cols=len(columns));table.style='Table Grid'
    table.rows[0]._tr.get_or_add_trPr().append(OxmlElement('w:tblHeader'))
    for cell,column in zip(table.rows[0].cells,display_columns):cell.text=column
    for row in rows:
        cells=table.add_row().cells
        for cell,column in zip(cells,columns):cell.text=_table_value(row.get(column),column)
    for row in table.rows:
        row._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:run.font.size=Pt(8)
    return table


def _reader_title(config, en):
    if config.get('kind')=='integration' and config.get('schema_version')==2:
        return {'slingshot':('单细胞轨迹分析报告','Single-cell trajectory report'),
                'genie3':('单细胞调控网络报告','Single-cell regulatory network report'),
                'cellchat':('单细胞通讯分析报告','Single-cell communication report')}.get(config.get('method'),('单细胞分析报告','Single-cell analysis report'))[int(en)]
    if config.get('method')=='single_cell_composition':return ('单细胞组成分析报告','Single-cell composition report')[int(en)]
    if config.get('kind') in ('ora','gsea_prerank'):return ('基因集富集分析报告','Gene-set enrichment report')[int(en)]
    if config.get('mode') in ('donor_paired','donor_unpaired'):return ('供者级差异表达报告','Donor-level differential expression report')[int(en)]
    return ('单细胞比较分析报告','Single-cell comparison report')[int(en)]


def _reader_paragraph(doc, title, text):
    doc.add_heading(title, 1)
    if isinstance(text, list):
        for item in text:
            doc.add_paragraph(str(item), style='List Bullet')
    else:
        doc.add_paragraph(str(text))


def _reader_table_title(key, en):
    labels={
        'communication_comparisons':('通讯条件比较','Communication condition comparisons'),
        'communication_results':('通讯结果','Communication results'),
        'comparison_results':('比较结果','Comparison results'),
        'composition_results':('组成结果','Composition results'),
        'enrichment_results':('富集结果','Enrichment results'),
        'trajectory_results':('轨迹结果','Trajectory results'),
        'regulation_results':('调控网络结果','Regulatory network results'),
    }
    return labels.get(key,(key,key))[int(en)]


def _reader_column_label(column, en):
    labels={
        'sender':('发送者细胞类型','Sender cell type'),
        'receiver':('接收者细胞类型','Receiver cell type'),
        'difference':('条件差值','Condition difference'),
        'donor_p_value':('供者层 P 值','Donor-level p-value'),
        'donor_q_value':('供者层校正 Q 值','Donor-level adjusted q-value'),
        'probability':('预测通讯概率','Predicted communication probability'),
        'cell_permutation_p_value':('细胞层面置换检验 P 值','Cell-level permutation p-value'),
        'status':('计算状态','Computation status'),
        'effect_value':('效应值','Effect value'),
        'p_value':('P 值','P-value'),
        'q_within_contrast':('比较内校正 Q 值','Within-comparison adjusted q-value'),
        'test_status':('检验状态','Test status'),
        'effect_unit':('效应单位','Effect unit'),
        'category_label':('类别','Category'),
        'proportion_difference':('组成比例差值','Difference in proportion'),
        'proportion_ratio':('组成比例比值','Proportion ratio'),
        'p_adjust':('校正 P 值','Adjusted p-value'),
        'inference_status':('推断状态','Inference status'),
        'term_name':('基因集或通路','Gene set or pathway'),
        'nes':('标准化富集分数','Normalized enrichment score'),
        'q_value':('校正 Q 值','Adjusted q-value'),
        'fdr_q_value':('FDR 校正 Q 值','FDR-adjusted q-value'),
        'cluster':('细胞群','Cell cluster'),
        'pseudotime':('拟时序','Pseudotime'),
        'weight':('调控权重','Regulatory weight'),
        'covered':('是否覆盖','Covered'),
        'regulator':('调控因子','Regulator'),
        'target':('靶基因','Target gene'),
        'stability_weight':('稳定性权重','Stability weight'),
        'absolute_weight_difference':('权重绝对差值','Absolute weight difference'),
    }
    return labels.get(column,(column,column))[int(en)]


def _reader_columns(columns, en):
    return [_reader_column_label(column,en) for column in columns]


def _reader_figure_title(key, en):
    labels={
        'topic_plot':('通讯概率热图','Communication probability heatmap'),
        'communication_heatmap':('通讯概率热图','Communication probability heatmap'),
        'communication_comparison':('通讯条件比较图','Communication condition comparison'),
    }
    return labels.get(key,('分析图件','Analysis figure'))[int(en)]


def _build_reader_facing_report(identifier, manifest_sha256, config, manifest, tables, figures, narrative):
    en=config.get('output_language')=='en';doc=Document();record=narrative if isinstance(narrative,dict) else {};narrative=record.get('narrative',record)
    section=doc.sections[0];section.page_width=Mm(210);section.page_height=Mm(297)
    section.left_margin=section.right_margin=section.top_margin=section.bottom_margin=Mm(20)
    for name in ('Normal','Title','Heading 1','Heading 2'):
        style=doc.styles[name];style.font.name='Arial';style.element.get_or_add_rPr().get_or_add_rFonts().set(qn('w:eastAsia'),'Microsoft YaHei')
        style.font.color.rgb=RGBColor(0,0,0)
        ppr=style.element.get_or_add_pPr()
        for border in list(ppr):
            if border.tag==qn('w:pBdr'):ppr.remove(border)
    doc.styles['Normal'].font.size=Pt(10);doc.styles['Normal'].paragraph_format.space_after=Pt(6)
    doc.add_paragraph(_reader_title(config,en),style='Title')
    doc.add_paragraph('Reader-facing report generated from frozen analysis facts.' if en else '本报告基于已冻结的分析事实生成，供研究人员阅读和进一步核对。')
    _reader_paragraph(doc,'Abstract' if en else '摘要',narrative['abstract'])
    _reader_paragraph(doc,'Study design and data' if en else '研究设计与数据范围',narrative['design_and_data'])
    _reader_paragraph(doc,'Quality control and usability' if en else '质量控制与结果可用性',narrative['quality_control'])
    _reader_paragraph(doc,'Methods' if en else '分析方法',narrative['methods_summary'])
    _reader_paragraph(doc,'Key findings' if en else '主要结果',narrative['key_findings'])
    _reader_paragraph(doc,'Limitations' if en else '局限性',narrative['limitations'])
    _reader_paragraph(doc,'Reader cautions' if en else '阅读提示',narrative['reader_cautions'])
    doc.add_heading('Selected results' if en else '关键结果表',1)
    preferred={
        'communication_comparisons':('sender','receiver','difference','donor_p_value','donor_q_value','status'),
        'communication_results':('sender','receiver','probability','cell_permutation_p_value','status'),
        'comparison_results':('effect_value','p_value','q_within_contrast','test_status','effect_unit'),
        'composition_results':('category_label','proportion_difference','proportion_ratio','p_value','p_adjust','inference_status'),
        'enrichment_results':('term_name','nes','p_value','q_value','fdr_q_value','status'),
        'trajectory_results':('cluster','pseudotime','weight','covered','status'),
        'regulation_results':('regulator','target','weight','stability_weight','absolute_weight_difference','status'),
    }
    shown_any=False
    for key,columns in preferred.items():
        raw=tables.get(key)
        if not raw:continue
        rows=raw.get('rows',[]) if isinstance(raw,dict) else raw
        if not rows:continue
        available=[column for column in columns if any(column in row for row in rows)][:6]
        if not available:continue
        doc.add_heading(_reader_table_title(key,en),2);_table(doc,rows[:20],available,_reader_columns(available,en));shown_any=True
        total=raw.get('total',len(rows)) if isinstance(raw,dict) else len(rows)
        doc.add_paragraph(('The table shows %s of %s saved rows.' % (min(20,len(rows)),total)) if en else ('本表展示已保存结果中的 %s / %s 行。' % (min(20,len(rows)),total)))
    if not shown_any:doc.add_paragraph('No reader-facing result rows were available.' if en else '没有可供正文展示的结果行。')
    if figures:
        doc.add_heading('Figures' if en else '图件',1)
        from PIL import Image
        for figure in figures:
            caption=doc.add_paragraph(_reader_figure_title(figure.get('key',''),en))
            caption.paragraph_format.keep_with_next=True
            with Image.open(io.BytesIO(figure['content'])) as picture:width,height=picture.size
            ratio=min(170/width,210/height)
            doc.add_picture(io.BytesIO(figure['content']),width=Mm(width*ratio),height=Mm(height*ratio))
    output=io.BytesIO();doc.save(output);return output.getvalue()


def build_single_cell_insight_report(identifier,manifest_sha256,config,manifest,tables,figures,*,narrative=None):
    """Use recorded values only; table excerpts explicitly retain their totals."""
    if narrative is not None:
        return _build_reader_facing_report(identifier,manifest_sha256,config,manifest,tables,figures,narrative)
    en=config.get('output_language')=='en';doc=Document()
    local=lambda zh,english:english if en else zh
    section=doc.sections[0];section.page_width=Mm(210);section.page_height=Mm(297)
    section.left_margin=section.right_margin=section.top_margin=section.bottom_margin=Mm(20)
    for name in ('Normal','Title','Heading 1','Heading 2'):
        style=doc.styles[name];style.font.name='Arial'
        style.element.get_or_add_rPr().get_or_add_rFonts().set(qn('w:eastAsia'),'Microsoft YaHei')
    doc.styles['Normal'].font.size=Pt(10)
    doc.styles['Normal'].paragraph_format.space_after=Pt(6)
    topic=config.get('kind')=='integration' and config.get('schema_version')==2
    composition=config.get('method')=='single_cell_composition'
    enrichment=config.get('kind') in ('ora','gsea_prerank')
    donor=config.get('mode') in ('donor_paired','donor_unpaired') and config.get('schema_version') is None
    title=local('单细胞组成分析报告','Single-cell composition report') if composition else local('基因集富集分析报告','Gene-set enrichment report') if enrichment else local('供者级差异表达报告','Donor-level differential expression report') if donor else local('比较分析报告','Comparison analysis report')
    if topic:title=local(*{'slingshot':('单细胞轨迹分析报告','Single cell trajectory report'),'genie3':('单细胞调控网络报告','Single cell regulatory network report'),'cellchat':('单细胞通讯分析报告','Single cell communication report')}[config['method']])
    doc.add_paragraph(title,style='Title')
    doc.add_paragraph(local('本报告读取已发布结果，不重新计算。完整表格、参数及日志保留在结果下载中。','This report reads published results without recomputation. Complete tables, parameters and logs remain in the result downloads.'))
    doc.add_paragraph(local('表格小数以6位有效数字展示，0与NA保留；下载表保留完整精度。','Table decimals use 6 significant digits; zero and NA are retained. Downloadable tables retain full precision.'))
    doc.add_paragraph(local('结果标识：','Result ID: ')+identifier)
    doc.add_paragraph('SHA256 '+manifest_sha256)
    def heading(zh,english):doc.add_heading(local(zh,english),1)
    heading('固定输入与标签来源','Fixed inputs and label sources')
    for source in manifest.get('source_bindings',[]):
        doc.add_paragraph(f"{source.get('source_kind','')} · {source.get('source_id','')}")
        doc.add_paragraph('SHA256 '+str(source.get('sha256','')))
    for key in ('purpose','label_basis','independence_basis','root_basis','tf_basis'):
        if config.get(key):doc.add_paragraph(key+': '+str(config[key]))
    selection=config.get('single_cell_selection') or {}
    if selection.get('label_basis'):doc.add_paragraph('label_basis: '+selection['label_basis'])
    heading('实际设计与方法','Actual design and methods')
    contrasts=config.get('contrasts',[])
    if contrasts and all(isinstance(c.get('numerator'),dict) and isinstance(c.get('denominator'),dict) for c in contrasts):
        doc.add_paragraph(local('比较方向按分子组相对于分母组解释；效应单位以保存方法为准。','Contrast direction is numerator relative to denominator; effect units follow the saved method.'))
        _table(doc,[dict(contrast_id=c.get('contrast_id'),numerator=c['numerator'].get('label'),denominator=c['denominator'].get('label')) for c in contrasts],['contrast_id','numerator','denominator'])
    if topic:
        notes={'slingshot':('Slingshot使用固定表示、聚类和明确根节点。拟时序不是实际时间或因果；未覆盖细胞保留NA。','Slingshot uses a fixed representation, clusters and an explicit root. Pseudotime is not elapsed time or causality; uncovered cells retain NA.'),'genie3':('GENIE3使用未整合log1p表达及明确TF集合。保存两种子结果和稳定性；权重不是P值或因果。','GENIE3 uses unintegrated log1p expression and explicit TFs. Two seeds and stability are recorded; weights are not P values or causality.'),'cellchat':('CellChat按供者和条件独立建模。当前资源是3条CC BY 4.0文献LR的演示集合，并非官方CellChatDB或全库。细胞置换P与供者层P分别记录，未知值不改成零。','CellChat models donor and condition units separately. The resource contains three literature-derived CC BY 4.0 demo interactions, not official CellChatDB or a full catalog. Cell-permutation and donor-level P values are separate; missing values are not zero.') }
        doc.add_paragraph(local(*notes[config['method']]))
    elif composition:
        doc.add_paragraph(local('分母包含所选条件中的全部保留细胞；未分配、未知、不确定及冲突单独记录，不静默丢弃。技术样本按供者和条件合并，不增加独立重复数。','Denominators contain all retained cells in the selected conditions. Unlabeled, unknown, uncertain and conflicting assignments are recorded separately. Technical samples are combined by donor and condition and do not increase independent replication.'))
        if config.get('mode')=='descriptive':doc.add_paragraph(local('本次仅描述组成，未执行推断检验；不提供推断性 P/q。','No inferential test was performed. This analysis describes composition without inferential P/q values.'))
    elif donor:
        doc.add_paragraph(local('原始整数 counts 按供者和条件汇总为 pseudobulk；不使用整合表示或取整后的环境校正层作为差异检验输入。','Original integer counts are aggregated by donor and condition into pseudobulk. Integrated representations and rounded ambient-corrected values are not differential-test inputs.'))
    elif enrichment:
        doc.add_paragraph(local('富集使用固定差异结果、实际受检背景或完整排序及已登记基因集；物种、ID 命名空间和校正范围以保存方法为准。','Enrichment uses fixed differential results, the tested background or complete ranking, and registered gene sets. Species, ID namespace and correction scope follow the saved methods.'))
    else:
        doc.add_paragraph(local('本次比较的观测单位、检验和解释范围以保存方法及配置为准；探索性观测比较不能解释为独立供者推断。','Observation units, tests and inference scope follow the saved methods and configuration. Exploratory observation comparisons do not establish independent donor inference.'))
    methods=manifest.get('methods',{})
    overview={k:v for k,v in methods.items() if k not in ('config','actual_units','model_diagnostics','upstream','upstream_methods')}
    params={k:v for k,v in config.items() if k not in ('contrasts','single_cell_selection','excluded_observations','excluded_donors','label_ids','family_contrast_ids','purpose','label_basis','independence_basis')}
    details=_scalars({'config':params,'methods':overview})
    if details:_table(doc,[dict(parameter=k,value=v) for k,v in details],['parameter','value'])
    for warning in methods.get('warnings',[]):doc.add_paragraph(local('限制：','Limitation: ')+str(warning))
    for resource in methods.get('resources',[]):
        if isinstance(resource,dict):
            doc.add_paragraph(local('固定基因集资源','Fixed gene-set resource'))
            _table(doc,[dict(parameter=k,value=v) for k,v in _scalars(resource)],['parameter','value'])
    heading('保存结果概况','Saved result summary')
    values=_scalars(manifest.get('summary',{}))
    if values:_table(doc,[dict(field=k,value=v) for k,v in values],['field','value'])
    units=manifest.get('summary',{}).get('actual_units') or methods.get('actual_units') or []
    if isinstance(units,dict):units=[units]
    if units:
        if topic:doc.add_paragraph(local('下表为设计入选数量；逐边有效供者数和不可计算原因见结果表。','The following counts describe design inclusion; edge-specific effective donor counts and non-computable reasons are listed with results.'))
        columns=[k for k in (('contrast_id','n_numerator','n_denominator','complete_pairs') if topic else ('contrast_id','n_numerator','n_denominator','complete_pairs','design_rank','residual_degrees_freedom')) if any(k in r for r in units)]
        if columns:_table(doc,units,columns)
    heading('供者单位与组成分母','Donor units and composition denominators') if composition else heading('保存结果表','Saved result tables')
    preferred={
        'trajectory_results':('barcode','cluster','lineage_id','pseudotime','weight','covered'),
        'regulation_results':('regulator','target','weight','stability_weight','absolute_weight_difference'),
        'communication_units':('donor','condition','cell_count','status','reason'),
        'communication_results':('sender','receiver','interaction_id','probability','cell_permutation_p_value','unit_id'),
        'communication_comparisons':('sender','receiver','interaction_id','difference','donor_p_value','donor_q_value'),
        'composition_units':('unit_id','donor','condition','batch','cell_count'),
        'composition_counts':('unit_id','category_label','cell_count','denominator_cells','proportion','condition','label','count','total'),
        'composition_results':('category_label','proportion_difference','proportion_ratio','t_statistic','p_value','p_adjust'),
        'aggregation_units':('unit_id','donor','condition','batch','spot_count','library_counts'),
        'comparison_results':('feature_id','contrast_id','effect_value','p_value','q_within_contrast','test_status'),
        'ora_background':('contrast_id','N','n','resource_id'),
        'enrichment_results':('term_id','term_name','nes','p_value','q_value','nominal_p_value','fdr_q_value'),
    }
    for key,choices in preferred.items():
        if key not in tables:continue
        raw=tables[key];rows=raw.get('rows',[]) if isinstance(raw,dict) else raw
        total=raw.get('total',len(rows)) if isinstance(raw,dict) else len(rows)
        doc.add_heading(key,2)
        limit=200 if key in ('composition_units','composition_counts','aggregation_units') else 20
        shown=rows[:limit]
        if key=='comparison_results':
            for effect,unit in sorted({(str(r.get('effect_name','')),str(r.get('effect_unit',''))) for r in shown}):
                if effect or unit:doc.add_paragraph(local('效应与单位：','Effect and unit: ')+effect+' / '+unit)
        if key=='ora_background':doc.add_paragraph(local('N 为实际受检背景基因数，n 为按已保存阈值选择的前景基因数。','N is the actual tested background size; n is the foreground size under the saved thresholds.'))
        if key in ('composition_counts','composition_results'):
            names=methods.get('label_names',{})
            shown=[{**r,'category_label':names.get(r.get('label_id'),r.get('label_id')) if r.get('category')=='label' else r.get('category') or r.get('label') or r.get('label_id')} for r in shown]
        doc.add_paragraph(local('本报告展示行数：','Rows shown in this report: ')+f'{len(shown)} / {total}'+local('。完整表保留在结果下载中。','. The complete table remains in the result downloads.'))
        if not total:
            doc.add_paragraph(local('无结果行；不能解释为不存在生物学效应。','No result rows; this does not establish absence of a biological effect.'))
            continue
        columns=[k for k in choices if any(k in row for row in shown)][:6]
        if not columns:columns=list(shown[0])[:6]
        _table(doc,shown,columns)
        if key=='communication_comparisons':
            doc.add_paragraph(local('逐边实际供者数与计算状态','Edge-specific donor counts and computation status'))
            counts=[dict(edge=str(r.get('sender'))+' → '+str(r.get('receiver'))+' / '+str(r.get('interaction_id')),**{k:r.get(k) for k in ('n_denominator','n_numerator','complete_pairs','status','reason')}) for r in shown]
            _table(doc,counts,['edge','n_denominator','n_numerator','complete_pairs','status','reason'])
        if key=='composition_results' and any('inference_status' in r for r in shown):
            doc.add_paragraph(local('逐类别推断状态与原因','Per-category inference status and reason'))
            _table(doc,shown,['category_label','inference_status','reason','ratio_status'])
    if figures:
        heading('已保存图件','Saved figures')
    communication=tables.get('communication_results',{})
    if topic and config['method']=='cellchat' and not any(f.get('figure_result_id') for f in figures) and isinstance(communication,dict) and communication.get('all_modeled_probabilities_zero'):
        doc.add_paragraph(local('本次已计算的通讯评分全部为0。原图自动色标扩展出的负刻度仅为显示范围，保存值没有负概率。供者检验的NA和原因见逐边结果；不能据此认定不存在通讯或条件差异。','All computed communication scores in this run are zero. Negative ticks from automatic color scaling are display bounds, not negative saved probabilities. See edge-specific results for NA tests and reasons; these do not establish absence of communication or condition differences.'))
    if figures:
        from PIL import Image
        for figure in figures:
            doc.add_heading(figure['key'],2)
            with Image.open(io.BytesIO(figure['content'])) as picture:width,height=picture.size
            ratio=min(170/width,210/height)
            doc.add_picture(io.BytesIO(figure['content']),width=Mm(width*ratio),height=Mm(height*ratio))
            doc.add_paragraph('SHA256 '+figure['sha256'])
            if figure.get('figure_result_id'):
                doc.add_paragraph(local('独立重绘结果：','Separately rendered figure result: ')+figure['figure_result_id'])
                doc.add_paragraph(local('数值来源：','Saved numeric source: ')+figure['source_result_id']+' | SHA256 '+figure['source_manifest_sha256'])
                doc.add_paragraph(local('仅重绘保存数值；未重算科学分析。原图保留在原结果下载中。','Saved values rendered only; scientific analysis was not recomputed. Original figures remain in original result downloads.'))
    heading('解释边界','Interpretation limits')
    doc.add_paragraph(local('细胞和技术文库不是独立供者。最小重复数是工程门槛，不保证统计功效；标签、配对和独立性依据需要科学审核。计算成功与用户验收不等于生物学验证。','Cells and technical libraries are not independent donors. Minimum replication is an engineering threshold, not a power guarantee. Labels, pairing and independence require scientific review. Successful computation and user acceptance are not biological validation.'))
    doc.add_paragraph(local('0 与 NA 保持原值；未检验、不可计算和空结果不改写为阴性结论。','Zero and NA retain their saved values. Untested, non-computable and empty results are not rewritten as negative findings.'))
    output=io.BytesIO();doc.save(output);return output.getvalue()


def validate_report_figure(identifier,sha256,method,methods):
    from app.adapters.bio_insights_store import invalid
    if (methods.get('figure_type')!='topic_'+method or methods.get('source_id')!=identifier
            or methods.get('source_sha256')!=sha256 or methods.get('analysis_recomputed') is not False):
        raise invalid('bio_insight_source_conflict',409)


def list_report_figures(store,project,identifier):
    from app.domain.bio_insights.results import BioInsightResultService,checked_members
    from app.adapters.bio_insights_store import invalid
    service=BioInsightResultService(store)
    with service.store.connection() as db:
        original=service.require(db,'bio_insight_result_versions',project,identifier)
        manifest,_=checked_members(service,db,project,original)
        rows=db.execute("SELECT * FROM bio_insight_result_versions WHERE project_id=%s AND user_id=%s AND kind='figure' AND methods_json->>'source_id'=%s AND methods_json->>'source_sha256'=%s ORDER BY created_at DESC LIMIT 100",
            (project,service.store.user_id,identifier,original['manifest_sha256'])).fetchall()
        output=[]
        for row in rows:
            task=service.store.require_task(db,row['task_id'])
            if task['status']!='succeeded':continue
            methods=row['methods_json'];kind=methods.get('figure_type','')
            if not kind.startswith('topic_') or methods.get('analysis_recomputed') is not False or 'png' not in methods.get('config',{}).get('formats',[]):continue
            output.append(dict(id=row['id'],title=methods.get('config',{}).get('title',''),figure_type=kind,
                task_id=row['task_id'],manifest_sha256=row['manifest_sha256'],output_language=methods.get('config',{}).get('output_language'),source_id=identifier,source_sha256=original['manifest_sha256']))
        return dict(items=output)


def download_single_cell_insight_report(store,project,identifier,figure_version_ids=None,language=None):
    from app.domain.bio_insights.results import BioInsightResultService,checked_members
    from app.domain.bio_insights.service import BioInsightsService
    from app.adapters.bio_insights_store import invalid
    service=BioInsightResultService(store)
    with service.store.connection() as db:
        row=service.require(db,'bio_insight_result_versions',project,identifier)
        task=service.store.require_task(db,row['task_id'])
        BioInsightsService(service.assets).require_sources(db,task,runtime=False)
        manifest,members=checked_members(service,db,project,row)
        recipe=next((m for m in members if m['key']=='recipe'),None)
        if recipe is None:raise invalid('bio_insight_source_incomplete',422)
        config=json.loads(service.objects.read(recipe))['config']
        selected_language=language or config.get('output_language','zh-CN')
        if config['kind'] not in ('comparison','ora','gsea_prerank') and not (config['kind']=='integration' and config.get('schema_version')==2):raise invalid('bio_insight_source_incomplete',422)
        tables={};figures=[]
        allowed={'trajectory_results','regulation_results','communication_units','communication_results','communication_comparisons','composition_units','composition_counts','composition_results','aggregation_units','comparison_results','enrichment_results'}
        for member in members:
            if member['key']=='ora_sets' and member['format']=='json':
                families=json.loads(service.objects.read(member)).get('families',[])
                rows=[{k:f.get(k) for k in ('contrast_id','N','n','resource_id')} for f in families]
                tables['ora_background']=dict(rows=rows,total=len(rows))
            if member['key'] in allowed and member['format'] in ('tsv','csv'):
                rows=[];total=0;computed=zero=0
                with service.objects.path(member['object_key']).open(encoding='utf-8-sig',newline='') as stream:
                    for item in csv.DictReader(stream,delimiter='\t' if member['format']=='tsv' else ','):
                        total+=1
                        if member['key']=='communication_results' and item.get('status')=='computed':
                            computed+=1;zero+=float(item['probability'])==0
                        if len(rows)<200:rows.append(item)
                tables[member['key']]=dict(rows=rows,total=total)
                if member['key']=='communication_results':tables[member['key']]['all_modeled_probabilities_zero']=computed>0 and zero==computed
            elif member['format']=='png':figures.append(dict(key=member['key'],sha256=member['sha256'],content=service.objects.read(member)))
        if figure_version_ids:
            if len(figure_version_ids)>10 or len(set(figure_version_ids))!=len(figure_version_ids) or config.get('kind')!='integration' or config.get('schema_version')!=2:
                raise invalid('bio_insight_source_conflict',409)
            replacements=[]
            for figure_id in figure_version_ids:
                fixed=service.require(db,'bio_insight_result_versions',project,figure_id)
                figure_task=service.store.require_task(db,fixed['task_id'])
                BioInsightsService(service.assets).require_sources(db,figure_task,runtime=False)
                figure_manifest,figure_members=checked_members(service,db,project,fixed)
                methods=figure_manifest.get('methods',{})
                validate_report_figure(identifier,row['manifest_sha256'],config['method'],methods)
                png=next((m for m in figure_members if m['key']=='figure_png' and m['format']=='png'),None)
                if png is None:raise invalid('bio_insight_source_incomplete',422)
                replacements.append(dict(key=methods.get('config',{}).get('title') or methods['figure_type'],sha256=png['sha256'],content=service.objects.read(png),
                    figure_result_id=figure_id,source_result_id=identifier,source_manifest_sha256=row['manifest_sha256']))
            figures=replacements
        narrative=load_cached_narrative(service.assets.directory,project,identifier,selected_language)
        content=build_single_cell_insight_report(identifier,row['manifest_sha256'],{**config,'output_language':selected_language},manifest,tables,figures,narrative=narrative)
    return content
