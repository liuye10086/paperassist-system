"""Pure reader prose presentation, also bundled for offline report rebuilding."""

import csv
import io

SECTIONS = (
    ('abstract', '摘要', 'Abstract'),
    ('design_and_data', '研究设计与数据范围', 'Study design and data'),
    ('quality_control', '质量控制与结果可用性', 'Quality control and usability'),
    ('methods_summary', '分析方法', 'Methods'),
    ('key_findings', '主要结果', 'Key findings'),
    ('limitations', '局限性', 'Limitations'),
    ('reader_cautions', '阅读提示与后续验证', 'Reader cautions and next validation steps'),
)


def reader_sections(record, language):
    narrative = record['narrative']
    return [(en if language == 'en' else zh, narrative[key]) for key, zh, en in SECTIONS]


def reader_scope_text(snapshot):
    tables=snapshot.get('tables',[])
    has_cluster_summary=any(cluster_summary_column(table) for table in tables)
    if snapshot['language']=='en':
        basis='selected summary facts and figures' if snapshot['figures'] else 'selected summary facts'
        text=f'This interpretation uses the {basis}. “Not provided” refers to the material supplied for this interpretation.'
        if tables:
            text+=' The interpretation did not read the complete tables row by row. The accompanying workbook contains the complete selected result tables.'
        if has_cluster_summary:
            text+=' The report lists the saved cluster sizes directly from the selected tables. The table values are authoritative.'
        return text
    basis='所选摘要事实和图件' if snapshot['figures'] else '所选摘要事实'
    text=f'本解读依据{basis}。文中“未提供”指本次解读材料未包含相关信息。'
    if tables:
        text+=' 本解读未逐行读取完整结果表。所选已保存结果表完整收录于配套 Excel 工作簿。'
    if has_cluster_summary:
        text+=' 报告所列分群规模直接取自所选结果表，以表中原值为准。'
    return text


def cluster_summary_column(table):
    source=table.get('source') or {}
    if (table['key']!='cluster_summary' or source.get('source_kind')!='bio_analysis_artifact'
            or not source.get('processed_version_id') or not 1<=table['expected_rows']<=200):
        return None
    columns=set(table['columns'])
    return next((name for name in ('spots','cells') if columns=={'cluster',name,'statistical_unit'}),None)


def report_table(table, raw, *, summarize=False):
    format=table.get('format','tsv')
    if format not in ('tsv','csv'):raise ValueError('Unsupported report table format')
    rows=csv.reader(io.StringIO(raw.decode('utf-8-sig' if 'format' in table else 'utf-8')),delimiter='\t' if format=='tsv' else ',',strict=True)
    columns=table['columns']
    if next(rows,None)!=columns:
        raise ValueError('Report columns changed')
    unit_column=cluster_summary_column(table) if summarize else None
    if unit_column is None:
        return dict(table,rows=rows),None
    index,count_index,unit_index=(columns.index(key) for key in ('cluster',unit_column,'statistical_unit'))
    unit={'spots':'spot','cells':'cell'}[unit_column]
    saved_rows=list(rows)
    values=[]
    seen=set()
    if len(saved_rows)!=table['expected_rows']:
        raise ValueError('Saved cluster summary row count changed')
    for row in saved_rows:
        if (len(row)!=len(columns) or row[unit_index]!=unit or row[index] in seen
                or any(not value.isascii() or not value.isdecimal() for value in (row[index],row[count_index]))):
            raise ValueError('Invalid saved cluster summary')
        seen.add(row[index])
        values.append((row[index],row[count_index]))
    return dict(table,rows=saved_rows),(unit_column,values) if values else None


def append_reader_sections(doc, record, language):
    for heading, text in reader_sections(record, language):
        doc.add_heading(heading, 1)
        for paragraph in text.split('\n'):
            if paragraph.strip():
                doc.add_paragraph(paragraph.strip())


def reader_figure(record, index):
    figure = record['figures'][index - 1]
    if figure['number'] != index:
        raise ValueError('Reader figure order mismatch')
    return figure
