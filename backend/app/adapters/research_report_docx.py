"""Deterministic analysis report; external observations remain uncomputed."""
import io
import re
from docx import Document
from docx.shared import Mm,Pt,RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from .research_method_text import reader_method,method_fingerprint,reader_label,reader_prose
from .reader_report_presentation import append_reader_sections,reader_figure,reader_scope_text


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
    text=reader_prose(text)
    if text=='空间分析 / Spatial analysis':return 'Spatial analysis' if language=='en' else '空间分析'
    for prefix, english, chinese in (
        ('donor/组别的独立重复设计未确认：','Independent donor/group replicate design has not been confirmed.','未确认供者与分组的独立重复设计。'),
        ('线粒体规则未确定：','Mitochondrial rule has not been confirmed.','未确认线粒体基因识别规则。'),
    ):
        if text.startswith(prefix) and re.fullmatch(r'[a-z][a-z0-9_]+',text[len(prefix):]):
            return english if language=='en' else chinese
    return report_text(text,language)


def source_title(source, en, *, reader=True):
    label=source.get('title') or ''
    identifier=source.get('source_id')
    if identifier and label==identifier:
        label=''
    elif identifier:
        for sep in (' / ', ' · ', ' '):
            if label.endswith(sep+identifier):
                label=label[:-len(sep+identifier)]
                break
    if reader and label in ('comparison_results','enrichment_results','composition_results','trajectory_results','feature_sample_counts'):
        return location_label(label,en)
    return reader_text(label, 'en' if en else 'zh-CN') or ('Analysis input' if en else '分析资料')


def location_label(value, en):
    labels={
        'comparison_results':('比较结果','Comparison results'),
        'enrichment_results':('富集结果','Enrichment results'),
        'composition_results':('细胞组成结果','Cell composition results'),
        'trajectory_results':('轨迹结果','Trajectory results'),
        'feature_sample_counts':('各特征纳入样本数','Included samples by feature'),
        'effect_value':('效应估计','Effect estimate'),
        'p_value':('P 值','P value'),'q_value':('校正后 P 值','Adjusted P value'),
        'family':('检验族','Test family'),'family_size':('检验族大小','Test family size'),
        'direction':('方向','Direction'),
        'global':('整体','Overall'),'by_contrast':('按比较','By contrast'),
        'na_p_values':('缺失 P 值数','Missing P values'),'valid_p_values':('有效 P 值数','Valid P values'),
        'enrichment_status':('富集状态','Enrichment status'),
        'result_member_key':('已保存结果表','Saved result table'),
    }
    return labels[value][en] if value in labels else reader_label(reader_prose(value),'en' if en else 'zh-CN')


def _internal_path_identity(value):
    return re.fullmatch(r'[0-9a-f]{64}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',value,re.I) is not None


def _field_parts(locator):
    path=locator.get('field_path') or ''
    if path.startswith(('summary.','params.')):path=path.split('.',1)[1]
    return path.split('.')


def fact_location(locator, en, *, row_label=None, reader=True, path_labels=None):
    if locator.get('cell'):return f"{locator.get('sheet','')}!{locator['cell']}"
    if locator.get('page'):return f"Page {locator['page']}" if en else f"第 {locator['page']} 页"
    if locator.get('field_path'):
        parts=_field_parts(locator)
        if not reader:return ' / '.join(reader_label(part,'en' if en else 'zh-CN') for part in parts)
        labels=[]
        for index,part in enumerate(parts):
            if part=='family' and index+1<len(parts) and _internal_path_identity(parts[index+1]):continue
            if _internal_path_identity(part):
                labels.append((path_labels or {}).get(index) or ('Selected item' if en else '选定项目'))
            else:labels.append(location_label(part,en))
        return ' / '.join(label for label in labels if label)
    if locator.get('row_key'):
        if not reader:
            return ' · '.join(str(v) for v in (locator.get('table'),*locator['row_key'].values(),locator.get('column')) if v)
        if row_label is None:
            row_label=' · '.join(reader_prose(value) for value in locator['row_key'].values() if reader_prose(value))
        row_label=row_label or ('Selected result' if en else '选定结果')
        return ' · '.join(v for v in (location_label(locator.get('table') or '',en),row_label,
                                      location_label(locator.get('column') or '',en)) if v)
    return 'Source overview' if en else '来源概况'


def _result_member_index(fact):
    return (fact.get('source_kind') in ('bio_insight_result_version','bio_insight_result_member')
            and (fact.get('locator') or {}).get('field_path')=='summary.result_member_key')


def reader_facts(finding):
    return (fact for fact in finding['facts'] if not _result_member_index(fact))


def reader_fact_value(fact, en, key='raw_value'):
    if _result_member_index(fact):
        # An existing conflict can still refer to this index. The saved
        # machine key is carried by the reproduction records.
        return 'See reproduction material' if en else '见复现资料'
    value=fact.get(key)
    if ((fact.get('locator') or {}).get('field_path')=='summary.enrichment_status'
            and fact.get('raw_value')==value=='no_significant_terms'):
        return 'No significant enrichment terms' if en else '未检出显著富集条目'
    return value


def reader_fact_index(finding, en):
    """Use only the frozen row matching the locator; never guess from latest data."""
    facts={};sources={}
    def collect(content):
        for fact in content.get('facts',[]):facts.setdefault(fact['id'],fact)
        for source in content.get('sources',[]):
            sources.setdefault(source['source_id'],[]).append(source)
            if isinstance(source.get('content'),dict):collect(source['content'])
        saved=content.get('finding')
        nested=saved.get('content') if isinstance(saved,dict) else None
        if isinstance(nested,dict):collect(nested)
    collect(finding or {})
    locations={};titles={};numbers={};path_numbers={}
    for identifier,fact in facts.items():
        locator=fact.get('locator') or {};keys=locator.get('row_key')
        candidates=[source for source in sources.get(fact.get('source_id'),[])
                    if source.get('sha256')==fact.get('source_sha256') and
                    (source.get('source_kind')==fact.get('source_kind') or not keys and not fact.get('source_kind'))]
        if keys:
            candidates=[source for source in candidates if fact.get('source_sha256') and fact.get('source_kind')
                        and source.get('content',{}).get('table_key')==locator.get('table')]
        names={source_title(source,en) for source in candidates}
        titles[identifier]=names.pop() if len(names)==1 else ('Analysis input' if en else '分析资料')
        if not keys:
            original=(locator.get('field_path') or '').split('.')
            parts=_field_parts(locator);path_labels={}
            offset=len(original)-len(parts)
            for index,part in enumerate(parts):
                if not _internal_path_identity(part):continue
                identity=(fact.get('source_kind'),fact.get('source_id'),fact.get('source_sha256'),
                          tuple(original[:index+offset+1]))
                number=path_numbers.setdefault(identity,len(path_numbers)+1)
                family=index>0 and parts[index-1]=='family'
                label=('Test family' if en else '检验族') if family else ('Selected item' if en else '选定项目')
                path_labels[index]=f'{label} {number}'
            locations[identifier]=fact_location(locator,en,path_labels=path_labels)
            continue
        identity=(fact.get('source_kind'),fact.get('source_id'),fact.get('source_sha256'),locator.get('table'),tuple(sorted(keys.items())))
        number=numbers.setdefault(identity,len(numbers)+1)
        label=f'Selected result {number}' if en else f'选定结果第 {number} 项'
        rows=[(source,row) for source in candidates for row in source.get('content',{}).get('rows',[])
              if isinstance(row,dict) and all(key in row and row[key]==value for key,value in keys.items())]
        # A missing/ambiguous row cannot establish a reader-facing source name.
        titles[identifier]='Analysis input' if en else '分析资料'
        if rows and all(row==rows[0][1] for _,row in rows):
            row=rows[0][1]
            names={source_title(source,en) for source,_ in rows}
            if len(names)==1:titles[identifier]=names.pop()
            name=next((reader_prose(row.get(key)) for key in
                ('feature_symbol','gene_symbol','symbol','term_name','feature_id','term_id','label','cell_type','cluster','sample_id','barcode')
                if row.get(key) is not None and reader_prose(row[key])), '')
            if name:label+=' · '+name
        comparison=reader_prose(fact.get('comparison'))
        if comparison:label+=' · '+comparison
        locations[identifier]=fact_location(locator,en,row_label=label)
    return facts,titles,locations


def conflict_text(conflict, en, finding=None, *, reader=False):
    if isinstance(conflict,str):return reader_text(conflict,'en' if en else 'zh-CN')
    # Inherited conflicts can refer to facts in a frozen source's content, not
    # just the currently selected facts. Resolve within this snapshot only.
    if reader:
        facts,titles,locations=reader_fact_index(finding,en)
    else:
        # This projection also binds saved paid model requests. Preserve its
        # existing bytes; reader-only labels are applied by the two exporters.
        facts={};sources={}
        def collect(content):
            for fact in content.get('facts',[]):facts.setdefault(fact['id'],fact)
            for source in content.get('sources',[]):
                sources.setdefault(source['source_id'],source)
                if isinstance(source.get('content'),dict):collect(source['content'])
        collect(finding or {})
        titles={identifier:source_title(sources.get(fact.get('source_id'),{}),en,reader=False)
                for identifier,fact in facts.items()}
        locations={identifier:fact_location(fact.get('locator') or {},en,reader=False)
                   for identifier,fact in facts.items()}
    items=[]
    for index,identifier in enumerate(conflict.get('fact_ids',[]),1):
        fact=facts.get(identifier)
        if fact is None:raise ValueError('Unresolvable conflict fact in report snapshot')
        raw=reader_fact_value(fact,en) if reader else fact.get('raw_value')
        value='NA' if raw is None else str(raw)
        if fact.get('unit'):value+=' '+fact['unit']
        label=f'Item {index}: ' if en else f'第 {index} 项：'
        items.append(label+' · '.join((titles[identifier],locations[identifier],value)))
    decisions={'unresolved':('待核对','Unresolved'),'use_first':('采用第一项','Use first'),
        'use_second':('采用第二项','Use second'),'exclude':('已排除','Excluded'),'explained':('已说明','Explained')}
    decision=decisions.get(conflict.get('decision'),decisions['unresolved'])
    note,basis=(reader_prose(conflict.get(key)) for key in ('note','basis'))
    items.append(' · '.join(v for v in (decision[en],note,basis) if v))
    return '\n'.join(items)


def build_report(snapshot,figures,*,cluster_summaries=()):
    en=snapshot['language']=='en';finding=snapshot['finding']['content'];doc=Document()
    basic=snapshot.get('basic_analysis',False)
    record=snapshot.get('reader_report')
    local=lambda text:reader_text(text,snapshot['language'])
    section=doc.sections[0];section.page_width=Mm(210);section.page_height=Mm(297)
    section.top_margin=section.bottom_margin=Mm(20);section.left_margin=section.right_margin=Mm(20)
    for name in ('Normal','Title','Heading 1','Heading 2'):
        style=doc.styles[name];style.font.name='Arial';style.font.color.rgb=RGBColor(0,0,0)
        style.element.get_or_add_rPr().append(OxmlElement('w:rFonts'))
        style.element.rPr.rFonts.set(qn('w:eastAsia'),'Microsoft YaHei')
        for border in style.element.xpath('./w:pPr/w:pBdr'):border.getparent().remove(border)
    doc.styles['Normal'].font.size=Pt(10)
    doc.styles['Normal'].paragraph_format.space_after=Pt(6)
    title=snapshot['title']
    if record is not None:
        title=reader_prose(title) or ('Analysis report' if en else '分析报告')
    doc.add_paragraph(title,style='Title')
    if record is not None:
        doc.add_paragraph(reader_scope_text(snapshot))
        append_reader_sections(doc,record,snapshot['language'])
        if cluster_summaries:
            doc.add_heading('Saved cluster sizes' if en else '已保存的分群规模',1)
            titles={source['source_id']:source_title(source,en) for source in finding['sources']}
            for index,source,unit,rows in cluster_summaries:
                label=f'Selected result table {index}' if en else f'所选结果表 {index}'
                name=titles.get(source.get('processed_version_id')) or titles.get(source.get('source_id'))
                doc.add_heading(f'{label} · {name}' if name else label,2)
                table=doc.add_table(rows=1,cols=2);table.style='Table Grid'
                header=table.rows[0]
                header._tr.get_or_add_trPr().append(OxmlElement('w:tblHeader'))
                header.cells[0].text='Cluster' if en else '分群'
                header.cells[1].text=({'spots':'Spatial spots','cells':'Cells'} if en else {'spots':'空间点数','cells':'细胞数'})[unit]
                for cluster,count in rows:
                    row=table.add_row()
                    row.cells[0].text=cluster
                    row.cells[1].text=count
    elif basic:
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
    if record is None:
        heading('设计与缺口','Design and missing information')
        for text in finding.get('gaps',[]) or [('No additional design information provided.' if en else '未提供额外研究设计信息。')]:doc.add_paragraph(local(text))
        heading('数据概况与质量核对','Data overview and quality checks')
    else:
        heading('原值核对表','Source values')
    doc.add_paragraph('Values below retain their source units and observation levels.' if en else '以下数值保留来源原值、单位及观察层级；缺失值显示 NA。')
    table=doc.add_table(rows=1,cols=4);table.style='Table Grid'
    table.autofit=False
    for column,width in zip(table.columns,(62,30,42,36)):column.width=Mm(width)
    headers=['Location','Raw value','Unit / level','Status'] if en else ['来源位置','原值','单位与层级','核对状态']
    for cell,text,width in zip(table.rows[0].cells,headers,(62,30,42,36)):cell.text=text;cell.width=Mm(width)
    props=table.rows[0]._tr.get_or_add_trPr();repeat=OxmlElement('w:tblHeader');props.append(repeat)
    _,_,locations=reader_fact_index(finding,en)
    for fact in reader_facts(finding):
        label=locations[fact['id']]
        raw=reader_fact_value(fact,en)
        values=[label,'NA' if raw is None else str(raw),
            ' / '.join(v for v in (reader_label(fact.get('unit',''),snapshot['language']),reader_label(fact.get('observation_level','unknown'),snapshot['language'])) if v),
            reader_label(fact.get('verification_status','unverified'),snapshot['language'])]
        row=table.add_row();row._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))
        for cell,text,width in zip(row.cells,values,(62,30,42,36)):cell.text=text;cell.width=Mm(width)
    if finding['methods'] or record is None:
        if record is None:heading('实际执行的方法','Methods performed')
        else:heading('来源方法记录','Source method records')
        if not finding['methods']:doc.add_paragraph('No performed methods were provided.' if en else '未提供已执行方法；不能据此补写分析步骤。')
    method_seen={}
    for index,method in enumerate(finding['methods']):
        fingerprint=method_fingerprint(method)
        shown=reader_method(method,snapshot['language'],duplicate_of=method_seen.get(fingerprint))
        doc.add_heading(local(shown['title']),2)
        for text in shown['paragraphs']:doc.add_paragraph(local(text))
        method_seen.setdefault(fingerprint,index+1)
    if record is None:heading('探索性结果与研究发现','Exploratory results and findings')
    else:heading('已采纳的研究发现','Adopted research findings')
    adopted=[c for c in finding['claims'] if c['review_decision']=='adopt']
    for claim in adopted:
        doc.add_paragraph(local(claim['statement']))
        doc.add_paragraph(('Strength / origin: ' if en else '结论级别与来源：')+reader_label(claim['strength'],snapshot['language'])+' / '+reader_label(claim['origin'],snapshot['language']))
        if claim['limitations']:doc.add_paragraph('; '.join(local(v) for v in claim['limitations']))
    if not adopted:doc.add_paragraph('No claims have been explicitly adopted; refer to the source values above.' if en else '尚未明确采用文字结论；请核对上方事实原值及完整结果表。')
    if figures:heading('图件与图注','Figures and captions')
    for i,figure in enumerate(figures,1):
        from PIL import Image
        image=Image.open(io.BytesIO(figure['content']));w,h=image.size;image.close()
        width=min(170,145*w/h)
        paragraph=doc.add_paragraph();paragraph.paragraph_format.keep_with_next=True
        paragraph.add_run().add_picture(io.BytesIO(figure['content']),width=Mm(width))
        config=figure['config']
        if record is None:
            title,caption=local(config.get('title','')),config.get('caption','')
            caption_language=config.get('language','unknown')
        else:
            shown=reader_figure(record,i)
            title,caption=shown['title'],shown['caption']
            caption_language=snapshot['language']
        doc.add_paragraph(('Figure ' if en else '图 ')+str(i)+' '+title)
        last_caption=None
        for paragraph in caption.split('\n'):
            if paragraph.strip():last_caption=doc.add_paragraph(local(paragraph) if record is None else paragraph)
        if last_caption is not None and record is not None:
            last_caption.paragraph_format.keep_with_next=True
        doc.add_paragraph(('Image language / caption language: ' if en else '图内语言与图注语言：')+reader_label(config.get('figure_language','unknown'),snapshot['language'])+' / '+reader_label(caption_language,snapshot['language']))
    heading('冲突与待复核内容','Conflicts and pending review')
    for conflict in finding['conflicts']:doc.add_paragraph(conflict_text(conflict,en,finding,reader=True))
    for claim in finding['claims']:
        if claim['review_decision']!='adopt':doc.add_paragraph(reader_label(claim['review_decision'],snapshot['language'])+' — '+local(claim['statement']))
    if not finding['conflicts'] and not any(c['review_decision']!='adopt' for c in finding['claims']):doc.add_paragraph('None recorded.' if en else '未登记。')
    if record is None:
        heading('局限与复现','Limitations and reproducibility')
        for text in dict.fromkeys(finding.get('limitations',[])+finding.get('warnings',[])):doc.add_paragraph(local(text))
    else:
        heading('结果表与复现资料','Result tables and reproduction material')
        for text in dict.fromkeys(finding.get('gaps',[])+finding.get('limitations',[])+finding.get('warnings',[])):
            doc.add_paragraph(local(text))
    if basic:
        doc.add_paragraph('Download full tables, H5AD, methods and reproduction files from the analysis result page.' if en else
            '完整结果表、H5AD、方法和复现文件可从分析结果页单独下载。报告仅汇总本次实际保存的结果，未执行步骤不表示已完成。')
    else:
        doc.add_paragraph('The selected result tables are provided in full. Original matrices and reproduction material are kept separately.' if en else
            '选定的结果表完整保留，原始矩阵和复现资料另行保存。')
    output=io.BytesIO();doc.save(output);return output.getvalue()
