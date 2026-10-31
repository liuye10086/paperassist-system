"""Deterministic analysis report; external observations remain uncomputed."""
import io
import json
import re
from docx import Document
from docx.shared import Mm,Pt,RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from .research_method_text import presentation_enabled,present_method,method_fingerprint


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


def build_report(snapshot,figures):
    en=snapshot['language']=='en';finding=snapshot['finding']['content'];doc=Document()
    local=lambda text:report_text(text,snapshot['language'])
    section=doc.sections[0];section.page_width=Mm(210);section.page_height=Mm(297)
    section.top_margin=section.bottom_margin=Mm(20);section.left_margin=section.right_margin=Mm(20)
    for name in ('Normal','Title','Heading 1','Heading 2'):
        style=doc.styles[name];style.font.name='Arial';style.font.color.rgb=RGBColor(0,0,0)
        style.element.get_or_add_rPr().append(OxmlElement('w:rFonts'))
        style.element.rPr.rFonts.set(qn('w:eastAsia'),'Microsoft YaHei')
    doc.styles['Normal'].font.size=Pt(10)
    doc.styles['Normal'].paragraph_format.space_after=Pt(6)
    doc.add_paragraph(snapshot['title'],style='Title')
    doc.add_paragraph('Versioned analysis results for review and Results/Methods drafting. External results have not been recomputed.' if en else
        '本报告汇总已固定的分析成果，供核对研究发现及编写结果与方法。外部结果未重算；探索性结论仍需独立验证。')
    doc.add_paragraph(('Finding version: ' if en else '研究发现版本：')+snapshot['finding']['id'])
    doc.add_paragraph('SHA256 '+snapshot['finding']['sha256'])
    def heading(zh,english):doc.add_heading(english if en else zh,1)
    heading('数据来源','Data sources')
    for source in finding['sources']:
        doc.add_paragraph(local(source.get('title',''))+' — '+source['source_kind']+' / '+source['source_id'])
        doc.add_paragraph(('Provenance: ' if en else '来源类型：')+source.get('provenance','unknown')+'; SHA256 '+source['sha256'])
    heading('设计与缺口','Design and missing information')
    for text in finding.get('gaps',[]) or [('No additional design information provided.' if en else '未提供额外研究设计信息。')]:doc.add_paragraph(local(text))
    heading('数据概况与质量核对','Data overview and quality checks')
    doc.add_paragraph('Values below retain their source units and observation levels.' if en else '以下数值保留来源原值、单位及观察层级；缺失值显示 NA。')
    table=doc.add_table(rows=1,cols=4);table.style='Table Grid'
    table.autofit=False
    for column,width in zip(table.columns,(62,30,42,36)):column.width=Mm(width)
    headers=['Location','Raw value','Unit / level','Status'] if en else ['来源位置','原值','单位与层级','核对状态']
    for cell,text in zip(table.rows[0].cells,headers):cell.text=text
    props=table.rows[0]._tr.get_or_add_trPr();repeat=OxmlElement('w:tblHeader');props.append(repeat)
    for fact in finding['facts']:
        location=fact['locator'];label=location.get('field_path') or (str(location.get('sheet',''))+'!'+str(location.get('cell','')) if location.get('cell') else json.dumps(location,ensure_ascii=False,separators=(',',':')))
        values=[label,'NA' if fact['raw_value'] is None else str(fact['raw_value']),fact.get('unit','')+' / '+fact.get('observation_level','unknown'),fact.get('verification_status','unverified')]
        row=table.add_row();row._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))
        for cell,text,width in zip(row.cells,values,(62,30,42,36)):cell.text=text;cell.width=Mm(width)
    heading('实际执行的方法','Methods performed')
    if not finding['methods']:doc.add_paragraph('No performed methods were provided.' if en else '未提供已执行方法；不能据此补写分析步骤。')
    software_seen=set();method_seen={};readable=presentation_enabled(snapshot)
    for index,method in enumerate(finding['methods']):
        fingerprint=method_fingerprint(method)
        shown=present_method(method,snapshot['language'],reference=f"parameters.json[{index}]; method_index.json / {method['id']}; report_snapshot.json (full method/software)",
            duplicate_of=method_seen.get(fingerprint)) if readable else None
        if shown is not None:
            doc.add_heading(shown['title'],2)
            for text in shown['paragraphs']:doc.add_paragraph(text)
            method_seen.setdefault(fingerprint,index+1)
            continue
        first_paragraph=len(doc.paragraphs)
        doc.add_heading(local(method['title']),2)
        doc.add_paragraph(local(method.get('description','')))
        doc.add_paragraph(('Executed: ' if en else '已执行：')+('Yes' if en else '是') if method['executed'] else ('Not performed' if en else '未执行'))
        for label,key in [('Parameters','parameters'),('Software','software')]:
            if method.get(key):
                value=json.dumps(method[key],ensure_ascii=False,sort_keys=True)
                if key=='software' and value in software_seen:continue
                doc.add_paragraph((label if en else {'Parameters':'参数','Software':'软件与复现标识'}[label])+': '+value)
                if key=='software':software_seen.add(value)
        for paragraph in doc.paragraphs[first_paragraph:-1]:paragraph.paragraph_format.keep_with_next=True
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
    for conflict in finding['conflicts']:doc.add_paragraph(json.dumps(conflict,ensure_ascii=False))
    for claim in finding['claims']:
        if claim['review_decision']!='adopt':doc.add_paragraph(claim['review_decision']+' — '+local(claim['statement']))
    if not finding['conflicts'] and not any(c['review_decision']!='adopt' for c in finding['claims']):doc.add_paragraph('None recorded.' if en else '未登记。')
    heading('局限与复现','Limitations and reproducibility')
    for text in dict.fromkeys(finding.get('limitations',[])+finding.get('warnings',[])):doc.add_paragraph(local(text))
    doc.add_paragraph('The package contains complete selected tables, methods, figure configurations and file hashes. Raw matrices remain fixed references.' if en else
        '交付包附完整选定结果表、方法、图件配置及文件哈希。原始大矩阵保留固定引用，不重复打包。')
    output=io.BytesIO();doc.save(output);return output.getvalue()
