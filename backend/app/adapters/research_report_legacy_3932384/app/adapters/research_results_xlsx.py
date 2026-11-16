"""Stream complete result tables into literal, traceable XLSX cells."""
import io
import json
import re
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font,PatternFill,Alignment
from .research_method_text import reader_method
from .research_report_docx import conflict_text,fact_location,source_title

MAX_CELLS=5_000_000
MAX_SHEET_ROWS=1_048_576


def build_workbook(snapshot,tables):
    book=Workbook(write_only=True);cells=0;used=set();summary={'tables':[],'total_cells':0}
    finding=snapshot['finding']['content']
    en=snapshot['language']=='en'
    styles={}
    def row_styles(ws,header):
        if header not in styles:
            pair=[]
            for literal in (False,True):
                template=WriteOnlyCell(ws)
                if literal:template.number_format='@'
                if header:
                    template.font=Font(bold=True,color='FFFFFF');template.fill=PatternFill('solid',fgColor='284B63')
                template.alignment=Alignment(vertical='top',wrap_text=header)
                pair.append(template._style)
            # These workbook-local arrays are never mutated after assignment.
            styles[header]=tuple(pair)
        return styles[header]
    def sheet(label,columns):
        name=re.sub(r'[\\/*?:\[\]]','_',label)[:25] or 'table'
        original=name;index=1
        while name.lower() in used:
            index+=1;name=original[:25]+'_'+str(index)
        used.add(name.lower());ws=book.create_sheet(name);ws.freeze_panes='A2'
        for i in range(len(columns)):
            from openpyxl.utils import get_column_letter
            ws.column_dimensions[get_column_letter(i+1)].width=22 if i else 32
        append(ws,columns,header=True)
        return ws
    def append(ws,values,header=False):
        nonlocal cells
        cells+=len(values)
        if cells>MAX_CELLS:raise ValueError('XLSX cell limit exceeded; split the report')
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
        ws=sheet('Facts',['Raw value','Displayed value','Unit','Observation level','Verification','Source','Location'] if en else
            ['原值','展示值','单位','观察层级','核对状态','来源','位置'])
        titles={s['source_id']:source_title(s,en) for s in finding['sources']}
        for fact in finding['facts']:
            append(ws,[*[fact.get(k) for k in ('raw_value','display_value','unit','observation_level','verification_status')],
                titles.get(fact.get('source_id')),fact_location(fact['locator'],en)])
        ws=sheet('Sources',['Title','Location'] if en else ['来源名称','位置'])
        for source in finding['sources']:append(ws,[source_title(source,en),fact_location(source.get('locator') or {},en)])
        ws=sheet('Methods',['Method','Performed','Description'] if en else ['方法','是否执行','说明'])
        for method in finding['methods']:
            shown=reader_method(method,snapshot['language'])
            for paragraph in shown['paragraphs']:append(ws,[shown['title'],method['executed'],paragraph])
        ws=sheet('Figures',['Number','Title','Caption','Figure language','Caption language'] if en else ['序号','标题','图注','图内语言','图注语言'])
        for i,figure in enumerate(snapshot.get('figures',[]),1):
            config=figure.get('config',{})
            append(ws,[i,config.get('title'),config.get('caption'),config.get('figure_language'),config.get('language')])
        ws=sheet('Limitations',['Type','Description'] if en else ['类型','说明'])
        for kind,label in [('gaps',('资料缺口','Missing information')),('warnings',('提醒','Cautions')),
                           ('limitations',('局限','Limitations')),('conflicts',('待核对事项','Conflicts'))]:
            for value in finding.get(kind,[]):append(ws,[label[en],conflict_text(value,en)])
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
