"""Deterministic analysis report; external observations remain uncomputed."""
import io
import re
from docx import Document
from docx.shared import Mm,Pt,RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from .research_method_text import reader_method,method_fingerprint


# Only deterministic system wording is localized. Frozen source values, reason
# identifiers and user-authored text remain unchanged in the saved snapshot.
SYSTEM_ENGLISH={
    '原始质量核对 / Raw quality control':'Raw quality control',
    '过滤 / Filtering':'Filtering','标准化 / Normalization':'Normalization',
    'log1p 转换 / Transformation':'log1p transformation',
    '高变特征选择 / HVG selection':'HVG selection','主成分分析 / PCA':'PCA',
    '邻居图 / Neighbour graph':'Neighbour graph',
    '探索性聚类 / Exploratory Leiden clustering':'Exploratory Leiden clustering',
    '探索性 marker / Exploratory markers':'Exploratory markers',
    'H5AD 读回核对 / Round-trip verification':'H5AD round-trip verification',
    '已执行 / Completed':'Completed',
    'spot 层级探索性分析；spot 和区域不等同于独立 donor，聚类与 marker 不证明细胞类型或因果机制。':
        'Exploratory spot-level analysis; spots and regions are not independent donors. Clusters and markers do not establish cell types or causal mechanisms.',
    '外部结果未重算，独立样本、单位和统计口径须依据原始材料确认。':
        'External results have not been recomputed. Independent samples, units and statistical definitions must be confirmed from the original material.',
    '外部材料仅作有来源的结果或观察，未由本系统重新计算。':
        'External material is retained as sourced results or observations and has not been recomputed by this system.',
}


def report_text(text,language):
    if language!='en':return text
    if text in SYSTEM_ENGLISH:return SYSTEM_ENGLISH[text]
    for prefix,english in (
        ('donor/组别的独立重复设计未确认：','Independent donor/group replicate design has not been confirmed: '),
        ('线粒体规则未确定：','Mitochondrial rule has not been confirmed: '),
        ('空间分析 / Spatial analysis ','Spatial analysis '),
        ('未完成 / Not completed: ','Not completed: '),
    ):
        if text.startswith(prefix):return english+text[len(prefix):]
    match=re.fullmatch(r'事实目录只展示已选行 (\d+)/(\d+)；完整结果表仍保留，导出不能据此截断。',text)
    if match:return f'Selected rows shown in the fact catalog: {match[1]}/{match[2]}. Complete result tables are retained and must not be truncated on export.'
    return 'Source text (original language): '+text if re.search(r'[\u3400-\u9fff]',text) else text


def reader_text(text, language):
    if text=='空间分析 / Spatial analysis':return 'Spatial analysis' if language=='en' else '空间分析'
    for prefix, english, chinese in (
        ('donor/组别的独立重复设计未确认：','Independent donor/group replicate design has not been confirmed.','未确认供者与分组的独立重复设计。'),
        ('线粒体规则未确定：','Mitochondrial rule has not been confirmed.','未确认线粒体基因识别规则。'),
    ):
        if text.startswith(prefix) and re.fullmatch(r'[a-z][a-z0-9_]+',text[len(prefix):]):
            return english if language=='en' else chinese
    return report_text(text,language)


def source_title(source, en):
    label=source.get('title') or ''
    identifier=source.get('source_id')
    if identifier and label==identifier:
        label=''
    elif identifier:
        for sep in (' / ', ' · ', ' '):
            if label.endswith(sep+identifier):
                label=label[:-len(sep+identifier)]
                break
    return reader_text(label, 'en' if en else 'zh-CN') or ('Analysis input' if en else '分析资料')


def fact_location(locator, en):
    if locator.get('cell'):return f"{locator.get('sheet','')}!{locator['cell']}"
    if locator.get('page'):return f"Page {locator['page']}" if en else f"第 {locator['page']} 页"
    if locator.get('field_path'):return locator['field_path'].replace('_',' ')
    if locator.get('row_key'):
        return ' · '.join(str(v) for v in (locator.get('table'),*locator['row_key'].values(),locator.get('column')) if v)
    return 'Source overview' if en else '来源概况'


def conflict_text(conflict, en):
    if isinstance(conflict,str):return reader_text(conflict,'en' if en else 'zh-CN')
    decisions={'unresolved':('待核对','Unresolved'),'use_first':('采用第一项','Use first'),
        'use_second':('采用第二项','Use second'),'exclude':('已排除','Excluded'),'explained':('已说明','Explained')}
    decision=decisions.get(conflict.get('decision'),decisions['unresolved'])
    return ' · '.join(v for v in (decision[en],conflict.get('note'),conflict.get('basis')) if v)


def build_report(snapshot,figures):
    en=snapshot['language']=='en';finding=snapshot['finding']['content'];doc=Document()
    basic=snapshot.get('basic_analysis',False)
    local=lambda text:reader_text(text,snapshot['language'])
    section=doc.sections[0];section.page_width=Mm(210);section.page_height=Mm(297)
    section.top_margin=section.bottom_margin=Mm(20);section.left_margin=section.right_margin=Mm(20)
    for name in ('Normal','Title','Heading 1','Heading 2'):
        style=doc.styles[name];style.font.name='Arial';style.font.color.rgb=RGBColor(0,0,0)
        style.element.get_or_add_rPr().append(OxmlElement('w:rFonts'))
        style.element.rPr.rFonts.set(qn('w:eastAsia'),'Microsoft YaHei')
        if basic:
            for border in style.element.xpath('./w:pPr/w:pBdr'):border.getparent().remove(border)
    doc.styles['Normal'].font.size=Pt(10)
    doc.styles['Normal'].paragraph_format.space_after=Pt(6)
    doc.add_paragraph(snapshot['title'],style='Title')
    if basic:
        doc.add_paragraph('This report summarizes the saved input, quality control, methods and figures from this analysis. Cell-level results are exploratory.' if en else
            '本报告汇总本次分析已保存的输入信息、质量控制、方法与图表。细胞层级结果用于探索，不能代替独立供者验证。')
    else:
        doc.add_paragraph('Analysis results for review and Results/Methods drafting. External results have not been recomputed.' if en else
            '本报告汇总已固定的分析成果，供核对研究发现及编写结果与方法。外部结果未重算；探索性结论仍需独立验证。')
    def heading(zh,english):doc.add_heading(english if en else zh,1)
    heading('数据来源','Data sources')
    for source in finding['sources']:
        provenance={'system_computed':('系统分析结果','System analysis'),'public_reanalysis':('公开数据重分析','Public data reanalysis'),
            'external_result':('外部结果','External result'),'manual_transcription':('人工摘录','Manual transcription'),
            'research_derived':('研究整理成果','Research output')}.get(source.get('provenance'),('来源类型未登记','Source type not recorded'))
        doc.add_paragraph(source_title(source,en)+' · '+provenance[en])
    if basic:
        for filename in snapshot.get('input_files',[]):doc.add_paragraph(('Input file: ' if en else '输入文件：')+filename)
        samples=snapshot.get('samples',[])
        if samples:
            table=doc.add_table(rows=1,cols=5);table.style='Table Grid'
            for cell,label in zip(table.rows[0].cells,['Sample','Library','Donor','Batch','Group'] if en else ['样本','文库','供者','批次','分组']):cell.text=label
            table.rows[0]._tr.get_or_add_trPr().append(OxmlElement('w:tblHeader'))
            for sample in samples:
                for cell,key in zip(table.add_row().cells,['sample_id','library_id','donor','batch','group']):cell.text=str(sample.get(key) or ('Unknown' if en else '未提供'))
    heading('设计与缺口','Design and missing information')
    for text in finding.get('gaps',[]) or [('No additional design information provided.' if en else '未提供额外研究设计信息。')]:doc.add_paragraph(local(text))
    heading('数据概况与质量核对','Data overview and quality checks')
    doc.add_paragraph('Values below retain their source units and observation levels.' if en else '以下数值保留来源原值、单位及观察层级；缺失值显示 NA。')
    table=doc.add_table(rows=1,cols=4);table.style='Table Grid'
    table.autofit=False
    for column,width in zip(table.columns,(62,30,42,36)):column.width=Mm(width)
    headers=['Location','Raw value','Unit / level','Status'] if en else ['来源位置','原值','单位与层级','核对状态']
    for cell,text,width in zip(table.rows[0].cells,headers,(62,30,42,36)):cell.text=text;cell.width=Mm(width)
    props=table.rows[0]._tr.get_or_add_trPr();repeat=OxmlElement('w:tblHeader');props.append(repeat)
    for fact in finding['facts']:
        label=fact_location(fact['locator'],en)
        values=[label,'NA' if fact['raw_value'] is None else str(fact['raw_value']),fact.get('unit','')+' / '+fact.get('observation_level','unknown'),fact.get('verification_status','unverified')]
        row=table.add_row();row._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))
        for cell,text,width in zip(row.cells,values,(62,30,42,36)):cell.text=text;cell.width=Mm(width)
    heading('实际执行的方法','Methods performed')
    if not finding['methods']:doc.add_paragraph('No performed methods were provided.' if en else '未提供已执行方法；不能据此补写分析步骤。')
    method_seen={}
    for index,method in enumerate(finding['methods']):
        fingerprint=method_fingerprint(method)
        shown=reader_method(method,snapshot['language'],duplicate_of=method_seen.get(fingerprint))
        doc.add_heading(local(shown['title']),2)
        for text in shown['paragraphs']:doc.add_paragraph(local(text))
        method_seen.setdefault(fingerprint,index+1)
    heading('探索性结果与研究发现','Exploratory results and findings')
    adopted=[c for c in finding['claims'] if c['review_decision']=='adopt']
    for claim in adopted:
        doc.add_paragraph(local(claim['statement']))
        doc.add_paragraph(('Strength / origin: ' if en else '结论级别与来源：')+claim['strength']+' / '+claim['origin'])
        if claim['limitations']:doc.add_paragraph('; '.join(local(v) for v in claim['limitations']))
    if not adopted:doc.add_paragraph('No claims have been explicitly adopted; refer to the source values above.' if en else '尚未明确采用文字结论；请核对上方事实原值及完整结果表。')
    heading('图件与图注','Figures and captions')
    for i,figure in enumerate(figures,1):
        from PIL import Image
        image=Image.open(io.BytesIO(figure['content']));w,h=image.size;image.close()
        width=min(170,210*w/h)
        paragraph=doc.add_paragraph();paragraph.paragraph_format.keep_with_next=True
        paragraph.add_run().add_picture(io.BytesIO(figure['content']),width=Mm(width))
        config=figure['config'];doc.add_paragraph(('Figure ' if en else '图 ')+str(i)+' '+config.get('title','')+'\n'+config.get('caption',''))
        doc.add_paragraph(('Image language / caption language: ' if en else '图内语言与图注语言：')+config.get('figure_language','unknown')+' / '+config.get('language','unknown'))
    heading('冲突与待复核内容','Conflicts and pending review')
    for conflict in finding['conflicts']:doc.add_paragraph(conflict_text(conflict,en))
    for claim in finding['claims']:
        if claim['review_decision']!='adopt':doc.add_paragraph(claim['review_decision']+' — '+local(claim['statement']))
    if not finding['conflicts'] and not any(c['review_decision']!='adopt' for c in finding['claims']):doc.add_paragraph('None recorded.' if en else '未登记。')
    heading('局限与复现','Limitations and reproducibility')
    for text in dict.fromkeys(finding.get('limitations',[])+finding.get('warnings',[])):doc.add_paragraph(local(text))
    if basic:
        doc.add_paragraph('Download full tables, H5AD, methods and reproduction files from the analysis result page.' if en else
            '完整结果表、H5AD、方法和复现文件可从分析结果页单独下载。报告仅汇总本次实际保存的结果，未执行步骤不表示已完成。')
    else:
        doc.add_paragraph('The selected result tables are provided in full. Original matrices and reproduction material are kept separately.' if en else
            '选定的结果表完整保留，原始矩阵和复现资料另行保存。')
    output=io.BytesIO();doc.save(output);return output.getvalue()
