"""Stream complete result tables into literal, traceable XLSX cells."""
import io
import json
import re
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font,PatternFill,Alignment
from .research_method_text import presentation_enabled,present_method

MAX_CELLS=5_000_000
MAX_SHEET_ROWS=1_048_576


def build_workbook(snapshot,tables):
    book=Workbook(write_only=True);cells=0;used=set();summary={'tables':[],'total_cells':0}
    finding=snapshot['finding']['content']
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
        ws=sheet('Facts',['fact_id','raw_value','display_value','unit','observation_level','verification_status','source_id','source_sha256','locator'])
        for fact in finding['facts']:append(ws,[fact.get(k) for k in ('id','raw_value','display_value','unit','observation_level','verification_status','source_id','source_sha256','locator')])
        ws=sheet('Sources',['source_kind','source_id','title','provenance','sha256','locator'])
        for source in finding['sources']:append(ws,[source.get(k) for k in ('source_kind','source_id','title','provenance','sha256','locator')])
        ws=sheet('Methods',['id','title','executed','description','parameters','software','source'])
        readable=presentation_enabled(snapshot)
        for index,method in enumerate(finding['methods']):
            reference=f"parameters.json[{index}]; method_index.json / {method['id']}; report_snapshot.json (full method/software)"
            shown=present_method(method,snapshot['language'],reference=reference) if readable else None
            if shown is None:
                append(ws,[method.get(k) for k in ('id','title','executed','description','parameters','software','source')])
            else:
                # Each method paragraph is its own row, with a stable method ID.
                # Exact large configurations remain in the package sidecars.
                for paragraph in shown['paragraphs']:
                    append(ws,[method['id'],shown['title'],method['executed'],paragraph,reference,method.get('software'),method.get('source')])
        ws=sheet('Figures',['number','version_id','title','caption','figure_language','caption_language','sha256'])
        for i,figure in enumerate(snapshot.get('figures',[]),1):
            config=figure.get('config',{})
            append(ws,[i,figure['id'],config.get('title'),config.get('caption'),config.get('figure_language'),config.get('language'),figure.get('manifest_sha256')])
        ws=sheet('Limitations',['type','text'])
        for kind in ('gaps','warnings','limitations','conflicts'):
            for value in finding.get(kind,[]):append(ws,[kind,value])
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
        ws=sheet('Export counts',['table','rows','columns','sheets','sha256'])
        for table in summary['tables']:append(ws,[table.get(k) for k in ('key','rows','columns','sheets','sha256')])
        summary['total_cells']=cells
        output=io.BytesIO();book.save(output)
        return output.getvalue(),summary
    finally:
        # Close streaming XML writers even when a quota/shape check rejects.
        for ws in book.worksheets:
            if not ws.closed:ws.close()
        book.close()
