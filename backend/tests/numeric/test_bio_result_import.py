import hashlib
import json
from pathlib import Path
from zipfile import ZipFile
import pytest
from app.adapters.bio_engine.manifest import Writer
from bio_insights_fixtures import rows


def external(tmp_path, content, fmt='csv', **overrides):
    path=tmp_path/('input.'+fmt);path.write_bytes(content)
    member={'path':str(path),'size_bytes':len(content),'sha256':hashlib.sha256(content).hexdigest(),'format':fmt,'role':'original_file'}
    cfg={'kind':'result_import','file_source_id':'f1','parse_version_id':'parse1',
         'columns':{'feature_id':'id','effect':'lfc','p_value':'p','q_value':'q'},
         'contrast_id':'c1','numerator':'B','denominator':'A','effect_name':'log2fc','effect_unit':'log2',
         'original_method':'external test','original_correction_scope':'original family',**overrides}
    cfg.update(species_taxon_id=9606,namespace='ensembl',reference_version='GRCh38.1')
    source={'source_kind':'original_file','source_id':'f1','role':'table','sha256':member['sha256'],
            'members':{'original_file':member},'metadata':{'parse_version_id':'parse1','parser_version':'bio_insight_table_v1',
            'encoding':'utf-8-sig','delimiter':',' if fmt=='csv' else '\t','header_row':1,'sheet':cfg.get('sheet')}}
    return {'schema_version':1,'kind':'bio_result_import','config':cfg,'identity':{'plan_version_id':'p1'},'sources':[source]}


def run(tmp_path,value):
    from app.adapters.bio_insights_engine.result_import import run_result_import
    out=tmp_path/'output';out.mkdir();w=Writer(out);result=run_result_import(value,w)
    return result,rows(w)


def test_external_original_zero_na_precision_and_recomputed_q(tmp_path):
    value=external(tmp_path,b'id,lfc,p,q\n000123,2,0,0\ng2,-2,0.04,0.05\ng3,NA,NA,NA\ng4,1,1e-400,0\n',
                   complete_tested_universe=True,recompute_q=True)
    result,got=run(tmp_path,value)
    assert got[0]['feature_id']=='000123'
    assert got[0]['original_p_value']=='0' and got[0]['original_q']=='0'
    assert got[2]['p_value']==got[2]['system_recomputed_q']==''
    assert got[3]['original_p_value']=='1e-400' and got[3]['p_value_underflow']=='True'
    assert got[1]['q_within_contrast']==got[1]['q_global_family']==''
    assert float(got[1]['system_recomputed_q'])==pytest.approx(.04*4/3)
    assert result['summary']['external_not_recomputed'] is False
    assert result['inference_scope']=='external_result'


@pytest.mark.parametrize('problem',['top_q','invalid_p','duplicate','parse_drift','missing_column','formula_numeric'])
def test_bad_external_import_is_blocked(tmp_path,problem):
    content=b'id,lfc,p,q\ng1,1,.01,.02\n'
    kwargs={}
    if problem=='top_q':kwargs={'recompute_q':True}
    elif problem=='invalid_p':content=b'id,lfc,p,q\ng1,1,1.01,.02\n'
    elif problem=='duplicate':content+=b'g1,2,.02,.03\n'
    elif problem=='missing_column':content=b'id,lfc,other,q\ng1,1,.01,.02\n'
    elif problem=='formula_numeric':content=b'id,lfc,p,q\ng1,=1+1,.01,.02\n'
    value=external(tmp_path,content,**kwargs)
    if problem=='parse_drift':value['sources'][0]['metadata']['parse_version_id']='other'
    with pytest.raises(ValueError):run(tmp_path,value)


def make_xlsx(path,formula=False):
    with ZipFile(path,'w') as z:
        z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="DE" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        headers=''.join(f'<c r="{col}1" t="inlineStr"><is><t>{name}</t></is></c>' for col,name in zip('ABCD',['id','lfc','p','q']))
        body='<c r="A2" t="inlineStr"><is><t>0012</t></is></c><c r="B2"><v>2.00000000000000001</v></c><c r="C2">'+('<f>1/100</f>' if formula else '')+'<v>0.0100000000000000001</v></c><c r="D2"><v>0</v></c>'
        z.writestr('xl/worksheets/sheet1.xml',f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1">{headers}</row><row r="2">{body}</row></sheetData></worksheet>')


def test_xlsx_original_xml_numeric_text_and_formula_rejection(tmp_path):
    path=tmp_path/'raw.xlsx';make_xlsx(path)
    value=external(tmp_path,path.read_bytes(),'xlsx',sheet='DE')
    _,got=run(tmp_path,value)
    assert got[0]['feature_id']=='0012' and got[0]['original_p_value']=='0.0100000000000000001'
    bad=tmp_path/'bad';bad.mkdir();make_xlsx(path,True)
    value=external(bad,path.read_bytes(),'xlsx',sheet='DE')
    with pytest.raises(ValueError,match='formula'):run(bad,value)


def test_duplicate_policy_excludes_all_and_keeps_original_rows(tmp_path):
    value=external(tmp_path,b'id,lfc,p,q\ng1,1,.01,.1\ng1,2,.02,.2\ng2,3,.03,.3\n',
                   duplicate_policy='exclude_all',complete_tested_universe=True,recompute_q=True)
    result,got=run(tmp_path,value)
    assert len(got)==3 and result['summary']['excluded_rows']==2
    assert got[0]['original_p_value']=='.01' and got[1]['original_p_value']=='.02'
    assert got[0]['system_recomputed_q']==got[1]['system_recomputed_q']==''
    assert float(got[2]['system_recomputed_q'])==pytest.approx(.03)
