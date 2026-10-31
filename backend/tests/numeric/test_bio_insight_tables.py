import hashlib
from zipfile import ZipFile
import pytest
from test_bio_result_import import make_xlsx


def member(path,fmt):
    return {'path':str(path),'size_bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'format':fmt,'role':'table'}


def test_shared_table_csv_preserves_raw_values_and_explicit_header(tmp_path):
    from app.adapters.bio_insights_engine.inputs import iter_table
    path=tmp_path/'table.csv';path.write_text('preamble\nid,value\n0001,0\n=literal,NA\n',encoding='utf-8')
    assert list(iter_table(member(path,'csv'),header_row=2))==[(3,{'id':'0001','value':'0'}),(4,{'id':'=literal','value':'NA'})]


@pytest.mark.parametrize('problem',['duplicate_header','width','limit','formula','macro','path','external','shared_negative'])
def test_table_unsafe_or_ambiguous_inputs_rejected(tmp_path,problem):
    from app.adapters.bio_insights_engine.inputs import iter_table
    if problem in ('duplicate_header','width','limit'):
        path=tmp_path/'table.csv';path.write_text('id,id\ng,1\n' if problem=='duplicate_header' else 'id,value\ng,1,2\n' if problem=='width' else 'id,value\ng,1\n')
        with pytest.raises(ValueError):list(iter_table(member(path,'csv'),max_uncompressed_bytes=4 if problem=='limit' else 100))
        return
    path=tmp_path/'table.xlsx';make_xlsx(path,formula=problem=='formula')
    if problem=='macro':
        with ZipFile(path,'a') as z:z.writestr('xl/vbaProject.bin',b'never execute')
    elif problem=='path':
        with ZipFile(path,'a') as z:z.writestr('../private',b'never extract')
    elif problem=='external':
        with ZipFile(path,'a') as z:z.writestr('xl/_rels/evil.rels','<Relationships><Relationship TargetMode="External" Target="https://example.invalid"/></Relationships>')
    elif problem=='shared_negative':
        with ZipFile(path) as z:parts={i.filename:z.read(i.filename) for i in z.infolist()}
        parts['xl/sharedStrings.xml']=b'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>wrong gene</t></si></sst>'
        parts['xl/worksheets/sheet1.xml']=parts['xl/worksheets/sheet1.xml'].replace(b'<c r="A2" t="inlineStr"><is><t>0012</t></is></c>',b'<c r="A2" t="s"><v>-1</v></c>')
        with ZipFile(path,'w') as z:
            for name,value in parts.items():z.writestr(name,value)
    with pytest.raises(ValueError):list(iter_table(member(path,'xlsx'),sheet='DE'))
