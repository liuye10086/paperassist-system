"""Local modeling report with real result tables and unchanged saved PNG."""
from io import BytesIO
import json
from docx import Document
from docx.shared import Cm,Pt
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from app.adapters.report_docx import paragraph,table,clean
from app.domain.modeling_facts import method_summary


def build_report(snapshot,report,png):
    project,result,figure,explanation=(snapshot[k] for k in ('project','result','figure','explanation'))
    language=explanation['language'];zh=language=='zh-CN';stats=result['statistics'];kind=result['result_type']
    def t(a,b): return a if zh else b
    def display(value):
        if value is None:return t('无法计算或未提供','Unavailable or not supplied')
        if type(value) is float:return format(value,'.6g')
        if isinstance(value,(dict,list)):return json.dumps(value,ensure_ascii=False,allow_nan=False)
        return str(value)
    doc=Document();page=doc.sections[0]
    page.top_margin=page.bottom_margin=page.left_margin=page.right_margin=Cm(2)
    for name in ('Normal','Title','Heading 1','Heading 2','Caption'):
        style=doc.styles[name];style.font.name='Arial';style._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),'宋体')
    doc.styles['Normal'].font.size=Pt(10)
    title=t('建模与生存分析报告','Modeling and survival analysis report')
    doc.core_properties.title=title;doc.core_properties.author='PaperAssist System'
    paragraph(doc,title,'Title');paragraph(doc,project['name'],'Subtitle')
    paragraph(doc,t('导出时间','Exported')+': '+report['created_at'])
    doc.add_heading(t('1 数据与已确认声明','1 Data and confirmed declarations'),level=1)
    for label,value in [('Filename',result['filename']),('Sheet',result['selection']['sheet_name']),('Research topic',project.get('research_topic') or ''),
        ('Source SHA256',result['source_sha256']),('Setup revision',result['setup_revision'])]:paragraph(doc,label+': '+display(value))
    table(doc,[t('字段','Variable'),t('列','Column'),t('单位','Unit')],[[v['name'],v['column'],v['unit']] for v in result['variables']],[7,3,7])
    research=result.get('analysis_context',{}).get('plan',{}).get('research_request',{})
    for key,value in research.items():paragraph(doc,key+': '+display(value))
    doc.add_heading(t('确认的编码、前提与评估声明','Confirmed coding, assumptions and evaluation'),level=2)
    for key,value in result['selection'].items():
        if key!='id_column':paragraph(doc,key+': '+display(value))
    doc.add_heading(t('2 数据质量与方法','2 Data quality and methods'),level=1)
    for key in ('row_count','valid_count','excluded_count'):paragraph(doc,key+': '+display(result['check'][key]))
    paragraph(doc,method_summary(result,language))
    from app.domain.dataset_processing import append_quality
    if not append_quality(doc, snapshot, explanation['language']):
        paragraph(doc,t('未插补、去重或剔除离群值；数值最多六位有效数字，完整结果保留原精度。','No imputation, deduplication or outlier removal. Display uses six significant digits; saved results retain full precision.'))
    audit=result['row_audit'];paragraph(doc,t('纳入原始行号（前二十条）','Included original row numbers (first twenty)')+': '+display(audit['included_rows'][:20]))
    for row in audit['excluded_rows'][:20]:paragraph(doc,'Excluded: '+display(row))
    doc.add_heading(t('3 实际统计结果','3 Actual statistical results'),level=1)
    if kind=='regression':
        keys=['term','beta','se','statistic','p_value']
        table(doc,keys,[[display(c[k]) for k in keys] for c in stats['coefficients']],[5,3,3,3,3])
        keys=['term','ci_low','ci_high','or_value','or_ci_low','or_ci_high']
        table(doc,keys,[[display(c[k]) for k in keys] for c in stats['coefficients']],[4,2.6,2.6,2.6,2.6,2.6])
        keys=['n','p','df_residual','r_squared','adjusted_r_squared','residual_sd','log_likelihood','deviance','aic']
        table(doc,['Metric','Value'],[[k,display(stats[k])] for k in keys],[8,9])
        doc.add_heading(t('诊断','Diagnostics'),level=2)
        table(doc,['Diagnostic','Value'],[[k,display(v)] for k,v in stats['diagnostics'].items() if not isinstance(v,list)],[8,9])
        arrays={k:v for k,v in stats['diagnostics'].items() if isinstance(v,list)}
        if arrays:
            keys=list(arrays);n=max(map(len,arrays.values()))
            paragraph(doc,t('完整逐观察诊断保存在结果；本表展示前二十条。','Full observation diagnostics remain saved; this table shows the first twenty.'))
            table(doc,['Index',*keys],[[str(i+1),*[display(arrays[k][i]) if i<len(arrays[k]) else '' for k in keys]] for i in range(min(n,20))],[2]+[15/len(keys)]*len(keys))
    elif kind=='roc':
        table(doc,['Metric','Value'],[['AUC',display(stats['auc'])],['n',display(stats['n'])],['Positive',display(stats['positive_n'])],['Negative',display(stats['negative_n'])],
            ['AUC interval',display(stats['confidence_interval'])],['Direction',stats['direction']],['Evaluation role',stats['evaluation_role']]],[7,10])
        paragraph(doc,t('曲线表展示前二十个实际阈值；完整曲线保存在统计结果。','The curve table shows the first twenty actual thresholds; the complete curve remains in the saved result.'))
        keys=['threshold_kind','threshold','tpr','fpr','sensitivity','specificity']
        table(doc,keys,[[display(p[k]) for k in keys] for p in stats['points'][:20]],[4,2.6,2.6,2.6,2.6,2.6])
    else:
        keys=['label','n','event_n','censored_n','max_time','median','median_reason']
        table(doc,keys,[[display(g[k]) for k in keys] for g in stats['groups']],[3,2,2,2,2,2,4])
        for group in stats['groups']:
            doc.add_heading(clean(group['label']),level=2)
            paragraph(doc,t('本表展示前二十个实际时点；完整风险与区间记录保存在统计结果。','This table shows the first twenty actual times; complete risk and interval records remain in the saved result.'))
            keys=['time','n_at_risk','n_event','n_censored','survival','ci_low','ci_high']
            table(doc,keys,[[display(p[k]) for k in keys] for p in group['points'][:20]],[2,2,2,2,3,3,3])
            keys=['time','n_at_risk','events_before','censored_before']
            table(doc,keys,[[display(p[k]) for k in keys] for p in group['risk_table']],[4,4,4.5,4.5])
            for point in group['points'][:20]:
                if point['ci_reason']:paragraph(doc,'Interval unavailable: time='+display(point['time'])+'; '+point['ci_reason'])
    paragraph(doc,'Warnings: '+display(stats['warnings']))
    doc.add_heading(t('4 原始图表及图注','4 Original figure and caption'),level=1)
    shape=doc.add_paragraph().add_run().add_picture(BytesIO(png),width=Cm(17))
    if shape.height>Cm(12):shape.width=int(shape.width*Cm(12)/shape.height);shape.height=Cm(12)
    paragraph(doc,figure['title'],'Caption');paragraph(doc,figure['caption'])
    paragraph(doc,t('原 PNG 字节未改写。森林图仅核对本地效应投影；ROC/KM 根据必要匿名数值独立计算曲线。图片像素仍需人工审阅。','Saved PNG bytes are embedded unchanged. Forest checks local effect projection; ROC/KM independently compute curves from necessary anonymous observations. Image pixels require review.'))
    doc.add_heading(t('5 六节解释','5 Six-section explanation'),level=1)
    for section in explanation['sections']:doc.add_heading(section['title'],level=2);paragraph(doc,section['text'])
    doc.add_heading(t('6 限制与来源','6 Limitations and provenance'),level=1)
    for limitation in explanation['limitations']:paragraph(doc,limitation)
    records={'Analysis ID':result['id'],'Analysis engine':result['engine']['id'],'Plan SHA256':result['analysis_plan']['sha256'],
        'Figure ID':figure['id'],'PNG SHA256':figure['sha256'],'Plot engine':figure['engine']['id'],
        'Explanation ID':explanation['id'],'Explanation engine':explanation['engine']['id'],'Explanation input SHA256':explanation['provenance']['input_sha256'],
        'Report ID':report['id'],'Report engine':report['engine']['id'],'Report input SHA256':report['input_sha256']}
    for key,value in records.items():paragraph(doc,key+': '+display(value))
    # Keep each observation and its unavailable-value reason on one page.
    # Repeated table headers are already supplied by the shared table helper.
    for result_table in doc.tables:
        for row in result_table.rows:
            row._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))
    output=BytesIO();doc.save(output);return output.getvalue()
