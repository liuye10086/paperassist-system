"""Stream complete result tables into literal, traceable XLSX cells."""
import io
import json
import re
from math import ceil
from textwrap import wrap
from unicodedata import east_asian_width
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font,PatternFill,Alignment
from openpyxl.utils import get_column_letter
from .research_method_text import reader_method,reader_label,reader_prose
from .research_report_docx import conflict_text,fact_location,source_title,reader_fact_index,reader_facts,reader_fact_value
from .reader_report_presentation import reader_figure,reader_sections,reader_scope_text

MAX_CELLS=5_000_000
MAX_SHEET_ROWS=1_048_576
WRAPPED_SHEETS=('Limitations','Methods','Figures','Report narrative')


def narrative_lines(text):
    # Excel limits visible row height. Keep prose blocks short enough for a
    # width-100 cell to display even when each character is double-width.
    for line in text.splitlines():
        yield from wrap(line,width=700,break_on_hyphens=False)


def build_workbook(snapshot,tables):
    book=Workbook(write_only=True);cells=0;used=set();summary={'tables':[],'total_cells':0}
    finding=snapshot['finding']['content']
    en=snapshot['language']=='en'
    record=snapshot.get('reader_report')
    styles={};row_numbers={}
    def row_styles(ws,header):
        style_key=(header,ws.title in WRAPPED_SHEETS)
        if style_key not in styles:
            pair=[]
            for literal in (False,True):
                template=WriteOnlyCell(ws)
                if literal:template.number_format='@'
                if header:
                    template.font=Font(bold=True,color='FFFFFF');template.fill=PatternFill('solid',fgColor='284B63')
                template.alignment=Alignment(vertical='top',wrap_text=header or style_key[1])
                pair.append(template._style)
            # These workbook-local arrays are never mutated after assignment.
            styles[style_key]=tuple(pair)
        return styles[style_key]
    def sheet(label,columns,widths=None):
        name=re.sub(r'[\\/*?:\[\]]','_',label)[:25] or 'table'
        original=name;index=1
        while name.lower() in used:
            index+=1;name=original[:25]+'_'+str(index)
        used.add(name.lower());ws=book.create_sheet(name);ws.freeze_panes='A2'
        for i in range(len(columns)):
            ws.column_dimensions[get_column_letter(i+1)].width=widths[i] if widths is not None else (22 if i else 32)
        # Write-only worksheets serialize the column metadata with the first row.
        append(ws,columns,header=True)
        return ws
    def append(ws,values,header=False):
        nonlocal cells
        cells+=len(values)
        if cells>MAX_CELLS:raise ValueError('XLSX cell limit exceeded; split the report')
        row_numbers[ws.title]=row_numbers.get(ws.title,0)+1
        if not header and ws.title in WRAPPED_SHEETS:
            lines=1
            for column,value in enumerate(values,1):
                width=ws.column_dimensions[get_column_letter(column)].width or 22
                needed=sum(max(1,ceil(sum(2 if east_asian_width(c) in ('W','F') else 1 for c in line)/max(1,width-2))) for line in str(value or '').split('\n'))
                lines=max(lines,needed)
            # Excel can wrap sooner at a word boundary than the width estimate.
            wrap_reserve=15 if lines>1 else 0
            ws.row_dimensions[row_numbers[ws.title]].height=min(409,15*lines+6+wrap_reserve)
        native_style,literal_style=row_styles(ws,header)
        output=[]
        for value in values:
            if isinstance(value,(dict,list)):value=json.dumps(value,ensure_ascii=False,sort_keys=True)
            if isinstance(value,str) and len(value)>32767:raise ValueError('XLSX cell text limit exceeded; split the report')
            if value is None:value='NA'
            cell=WriteOnlyCell(ws,value=value)
            if isinstance(value,str):cell.data_type='s';cell._style=literal_style
            else:cell._style=native_style
            output.append(cell)
        ws.append(output)
    try:
        if record is not None:
            ws=sheet('Report narrative',['Section','Explanation'] if en else ['章节','解读'],(32,100))
            append(ws,['Scope' if en else '范围',reader_scope_text(snapshot)])
            for heading,text in reader_sections(record,snapshot['language']):
                for index,line in enumerate(narrative_lines(text)):append(ws,[heading if index==0 else '',line])
        ws=sheet('Facts',['Raw value','Displayed value','Unit','Observation level','Verification','Source','Location'] if en else
            ['原值','展示值','单位','观察层级','核对状态','来源','位置'])
        _,titles,locations=reader_fact_index(finding,en)
        for fact in reader_facts(finding):
            append(ws,[reader_fact_value(fact,en),reader_fact_value(fact,en,'display_value'),fact.get('unit'),
                reader_label(fact.get('observation_level'),snapshot['language']),reader_label(fact.get('verification_status'),snapshot['language']),
                titles[fact['id']],locations[fact['id']]])
        ws=sheet('Sources',['Title','Location'] if en else ['来源名称','位置'])
        for source in finding['sources']:append(ws,[source_title(source,en),fact_location(source.get('locator') or {},en)])
        ws=sheet('Methods',['Method','Performed','Description'] if en else ['方法','是否执行','说明'],(32,22,100))
        for method in finding['methods']:
            shown=reader_method(method,snapshot['language'])
            for paragraph in shown['paragraphs']:append(ws,[reader_prose(shown['title']),method['executed'],reader_prose(paragraph)])
        ws=sheet('Figures',['Number','Title','Caption','Figure language','Caption language'] if en else ['序号','标题','图注','图内语言','图注语言'],(8,44,100,22,22))
        for i,figure in enumerate(snapshot.get('figures',[]),1):
            config=figure.get('config',{})
            figure_language=reader_label(config.get('figure_language'),snapshot['language'])
            if record is None:
                append(ws,[i,reader_prose(config.get('title')),reader_prose(config.get('caption')),figure_language,reader_label(config.get('language'),snapshot['language'])])
            else:
                shown=reader_figure(record,i)
                caption_language=reader_label(snapshot['language'],snapshot['language'])
                for index,line in enumerate(narrative_lines(shown['caption'])):
                    append(ws,[i,shown['title'],line,figure_language,caption_language] if index==0 else ['', '', line, '', ''])
        ws=sheet('Limitations',['Type','Description'] if en else ['类型','说明'],(32,100))
        for kind,label in [('gaps',('资料缺口','Missing information')),('warnings',('提醒','Cautions')),
                           ('limitations',('局限','Limitations')),('conflicts',('待核对事项','Conflicts'))]:
            for value in finding.get(kind,[]):append(ws,[label[en],conflict_text(value,en,finding,reader=True)])
        for table in tables:
            columns=table['columns'];expected=table['expected_rows']
            if not columns or len(columns)>16384 or expected<0:raise ValueError('Invalid result table shape')
            estimated=cells+(expected+1)*len(columns)
            if estimated>MAX_CELLS:raise ValueError('XLSX cell limit exceeded; split the report')
            count=0;row=1;ws=sheet(table['key'],columns);names=[ws.title]
            for values in table['rows']:
                if len(values)!=len(columns):raise ValueError('Result row width mismatch')
                if row>=MAX_SHEET_ROWS:
                    ws=sheet(table['key'],columns);names.append(ws.title);row=1
                append(ws,values);count+=1;row+=1
                if count>expected:raise ValueError('Result row count mismatch')
            if count!=expected:raise ValueError('Result row count mismatch')
            summary['tables'].append(dict(key=table['key'],rows=count,columns=len(columns),sheets=names,
                source=table.get('source'),sha256=table.get('sha256')))
        ws=sheet('Export counts',['Table','Rows','Columns','Worksheets'] if en else ['结果表','行数','列数','工作表'])
        for table in summary['tables']:append(ws,[table.get(k) for k in ('key','rows','columns')]+[' · '.join(table['sheets'])])
        summary['total_cells']=cells
        output=io.BytesIO();book.save(output)
        return output.getvalue(),summary
    finally:
        # Close streaming XML writers even when a quota/shape check rejects.
        for ws in book.worksheets:
            if not ws.closed:ws.close()
        book.close()
