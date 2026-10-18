"""Local bilingual comparison reports with preserved inference and declared research context."""
from io import BytesIO
from docx import Document
from docx.shared import Cm,Pt,RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.adapters.report_docx import clean,paragraph,table
from app.domain.comparison_facts import build_payload,method_summary,assumptions_summary,local,REASONS,EXCLUSIONS


def build_report(snapshot,report,png):
    project,result,figure,explanation=(snapshot[key] for key in ('project','result','figure','explanation'))
    language=explanation['language']; stats=result['statistics']; paired=stats['design']=='paired'
    def t(zh,en): return local((zh,en),language)
    def display(value): return t('无法计算','Unavailable') if value is None else format(value,'.6g') if isinstance(value,float) else str(value)
    title=t('组间比较分析报告','Group comparison report')
    document=Document(); page=document.sections[0]
    page.page_width,page.page_height=Cm(21.59),Cm(27.94)
    page.top_margin=page.bottom_margin=page.left_margin=page.right_margin=Cm(2)
    page.header_distance=page.footer_distance=Cm(.9)
    for name,size in [('Normal',11),('Title',22),('Subtitle',12),('Heading 1',15),('Heading 2',12),('Caption',10)]:
        style=document.styles[name]; style.font.name='Arial'; style.font.size=Pt(size); style.font.color.rgb=RGBColor(0,0,0)
        style._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),'宋体')
        style.paragraph_format.space_after=Pt(6); style.paragraph_format.line_spacing=1.15
    document.core_properties.title=title; document.core_properties.author='PaperAssist System'; document.core_properties.subject=clean(project['name'])[:255]
    page.header.paragraphs[0].text='PaperAssist · '+title
    footer=page.footer.paragraphs[0]; footer.alignment=WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run(t('第 ','Page ')); field=OxmlElement('w:fldSimple'); field.set(qn('w:instr'),'PAGE'); footer._p.append(field)
    if language=='zh-CN': footer.add_run(' 页')
    paragraph(document,title,'Title'); paragraph(document,project['name'],'Subtitle')
    paragraph(document,t('配置版本','Configuration revision')+f' {result["setup_revision"]} · '+t('导出时间','Exported')+f' {report["created_at"]} (UTC)')
    paragraph(document,t('本报告保留已确认组间或配对设计、真实本地统计、单一主要图与六节解释。研究者须审核前提、结果适用性及表述。',
        'This report retains the confirmed independent-group or paired design, local statistics, one primary figure and six-section explanation. Researchers must review assumptions, applicability and wording.'))
    document.add_heading(t('1 数据与研究声明','1 Data and research declarations'),level=1)
    for label,value in [(t('原始文件','Source file'),result['filename']),(t('工作表','Worksheet'),result['selection']['sheet_name']),
                        (t('研究主题 用户填写','Research topic entered by user'),project['research_topic'] or t('未填写','Not specified'))]: paragraph(document,label+': '+str(value))
    source=result.get('source')
    if source:
        paragraph(document,t('数据版本','Dataset version')+': '+str(source['dataset_version']))
        if source.get('parent_dataset_version') is not None: paragraph(document,t('原始数据版本','Parent dataset version')+': '+str(source['parent_dataset_version']))
    for variable in result['variables']: paragraph(document,t('变量','Variable')+f': {variable["name"]} ({variable["column"]}); '+t('单位','Unit')+': '+(variable['unit'] or t('未填写','Not specified')))
    plan=result.get('analysis_context',{}).get('plan',{}); research=plan.get('research_request')
    if research:
        document.add_heading(t('用户研究声明','User research declarations'),level=2)
        for key,zh,en in [('question','研究问题','Research question'),('population','研究人群或对象','Study population or subjects'),
                         ('study_design','研究设计','Study design'),('observation_unit','观察单位','Observation unit'),
                         ('relationship_description','配对或组间关系说明','Pairing or group relationship description'),('output_requirements','输出要求','Output requirements')]:
            paragraph(document,t(zh,en)+': '+(research.get(key) or t('未提供','Not provided')))
        structures={'independent':t('独立观察','Independent observations'),'paired':t('配对观察','Paired observations'),'repeated':t('重复测量','Repeated measurements'),'unknown':t('未明确','Not specified')}
        paragraph(document,t('观察结构','Observation structure')+': '+structures.get(research.get('observation_structure'),t('未明确','Not specified')))
        paragraph(document,t('上述文字为用户声明，程序不证明研究设计、样本来源或测量真实性。','These are user declarations; the program does not establish design validity, sample provenance or measurement authenticity.'))
    document.add_heading(t('确认的分析前提','Confirmed analysis assumptions'),level=2); paragraph(document,assumptions_summary(result,language))
    document.add_heading(t('2 数据质量与处理','2 Data quality and processing'),level=1)
    check=result['check']
    paragraph(document,t(f'原始行数 {check["row_count"]}；纳入 {check["valid_count"]} 个完整对；排除 {check["excluded_count"]} 行。',
        f'Source rows: {check["row_count"]}; {check["valid_count"]} complete pairs; {check["excluded_count"]} excluded source rows.') if paired else
        t(f'原始行数 {check["row_count"]}；纳入 {check["valid_count"]} 条独立观察；排除 {check["excluded_count"]} 行。',
          f'Source rows: {check["row_count"]}; {check["valid_count"]} independent observations; {check["excluded_count"]} excluded source rows.'))
    from app.domain.dataset_processing import append_quality
    if not append_quality(document, snapshot, explanation['language']):
        paragraph(document,t('仅纳入已确认参与组或完整对；未插补、去重或删除离群值。配对 ID 保留本地，不展示其真实值。',
            'Only confirmed groups or complete pairs are included; no imputation, deduplication or outlier removal. Pair identifiers remain local and their actual values are not displayed.'))
    audit=result['row_audit']
    paragraph(document,t('纳入原始行号 前二十行','Included original row numbers first twenty')+': '+', '.join(str(row) for row in audit['included_rows'][:20]))
    for excluded in audit['excluded_rows'][:20]:
        reason=local(EXCLUSIONS.get(excluded['reason'],('排除原因：'+excluded['reason'],'Exclusion reason: '+excluded['reason'])),language)
        paragraph(document,t('排除原始行','Excluded original row')+f' {excluded["row"]}: '+', '.join(excluded['coordinates'])+'; '+reason)
    paragraph(document,t('报告展示前二十条坐标，完整审计保存在统计结果中。','The report shows the first twenty coordinates; the complete audit is preserved in the saved result.'))
    document.add_heading(t('3 分析方法','3 Analysis methods'),level=1); paragraph(document,method_summary(result,language))
    paragraph(document,t('数字显示最多 6 位有效数字，保存统计保留完整精度。','Numbers display at most 6 significant digits; saved statistics retain full precision.'))
    document.add_heading(t('4 统计结果','4 Statistical results'),level=1)
    payload=build_payload(result,{**figure,'figure_number':1})
    facts=payload['facts']
    from app.domain.explanation_content import METRICS as ZH_METRICS
    from app.domain.descriptive_facts import METRICS as EN_METRICS
    metrics=ZH_METRICS if language=='zh-CN' else EN_METRICS
    for keys in [('n','mean','std','min','max'),('q1','median','q3','iqr')]:
        table(document,[t('分组或测量','Group or measurement'),*[metrics[key] for key in keys]],
            [[group['label'],*[display(group['statistics'][key]) for key in keys]] for group in result['groups']],[4]+[13/len(keys)]*len(keys))
    primary=['comparison.statistic','comparison.df_numerator','comparison.df_denominator','comparison.p_value','comparison.estimate','comparison.estimate_unit','comparison.confidence_interval','comparison.inference_summary']
    for key in primary: paragraph(document,facts[key]['label']+': '+facts[key]['value'])
    for key in ['comparison.direction','comparison.decision','comparison.family.policy','comparison.family.size','comparison.family.alpha','comparison.interval_caveat','comparison.warnings']:
        paragraph(document,facts[key]['label']+': '+facts[key]['value'])
    if paired: paragraph(document,facts['comparison.zero_count']['label']+': '+facts['comparison.zero_count']['value'])
    if stats['pairwise']:
        document.add_heading(t('完整预声明组对比较族','Complete predeclared pairwise family'),level=2)
        # One pair per small table keeps all statistics and ordinary CI readable in portrait.
        for index,pair in enumerate(stats['pairwise']):
            paragraph(document,facts[f'pairwise.{index}.label']['value'],'Heading 2')
            keys=['method','statistic','df','estimate','p_value','adjusted_p_value','confidence_interval','decision','inference_summary']
            for key in keys:
                fact=facts[f'pairwise.{index}.{key}']; paragraph(document,fact['label']+': '+fact['value'])
    document.add_heading(t('5 图表与图注','5 Figure and caption'),level=1)
    p=document.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.keep_with_next=True
    shape=p.add_run().add_picture(BytesIO(png),width=Cm(17))
    if shape.height>Cm(12): shape.width=int(shape.width*Cm(12)/shape.height); shape.height=Cm(12)
    shape._inline.docPr.set('descr',clean(figure['title']))
    paragraph(document,figure['title'],'Caption'); paragraph(document,figure['caption'])
    paragraph(document,t('嵌入已保存 PNG 原字节；云端仅独立核对绘图 n 和描述摘要，未独立复现本地推断算法，图片像素仍需人工确认。',
        'Saved PNG bytes are embedded unchanged. Cloud verification covers drawing n and descriptive summaries only, without independently reproducing local inference algorithms; image pixels still require review.'))
    document.add_heading(t('6 分析解释与论文表述','6 Interpretation and manuscript wording'),level=1)
    for section in explanation['sections']: document.add_heading(section['title'],level=2); paragraph(document,section['text'])
    document.add_heading(t('7 适用限制','7 Applicability and limitations'),level=1)
    for limitation in explanation['limitations']: paragraph(document,limitation)
    paragraph(document,explanation['verification']['note'])
    document.add_heading(t('附录 A 解释依据','Appendix A Interpretation evidence'),level=1)
    for section in explanation['sections']:
        document.add_heading(section['title'],level=2)
        for evidence in section['evidence']: paragraph(document,f'{evidence["label"]}: {evidence["value"]}\n'+t('引用键','Reference key')+': '+evidence['key'])
    document.add_heading(t('附录 B 来源与版本','Appendix B Sources and versions'),level=1)
    records=[('Project ID',project['id']),('File ID',result['file_id']),('Source SHA256',result['source_sha256']),
        ('Analysis ID',result['id']),('Analysis engine',result['engine']['id']),('Plan SHA256',result['analysis_plan']['sha256']),
        ('Figure ID',figure['id']),('PNG SHA256',figure['sha256']),('Plot engine',figure['engine']['id']),
        ('Explanation ID',explanation['id']),('Explanation engine',explanation['engine']['id']),('Explanation input SHA256',explanation['provenance']['input_sha256']),
        ('Report ID',report['id']),('Report renderer',report['engine']['id']),('Report input SHA256',report['input_sha256'])]
    for label,value in records: paragraph(document,label+': '+str(value))
    for key,label in [('id','Plan ID'),('decision_id','Plan decision ID'),('plan_revision','Plan revision'),('workflow_version','Plan workflow'),('rules_version','Plan rules')]:
        if key in plan: paragraph(document,label+': '+str(plan[key]))
    output=BytesIO(); document.save(output); return output.getvalue()
