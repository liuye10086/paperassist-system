"""Report exports keep complete rows, literal values and scientific boundaries."""
import io
import json
import zipfile
import pytest

@pytest.fixture(autouse=True)
def postgres_schema():yield None

def sample():
    return dict(title='研究分析报告',language='zh-CN',finding=dict(id='finding-v1',sha256='a'*64,content=dict(
        sources=[dict(source_kind='original_file',source_id='f',sha256='b'*64,title='外部表格',provenance='external_result')],
        facts=[dict(id='fact1',raw_value='0.0000000000000000123',display_value='0.0000000000000000123',unit='',
            locator={'kind':'cell','sheet':'结果','cell':'B2'},source_id='f',source_sha256='b'*64,verification_status='unverified',observation_level='unknown')],
        methods=[],claims=[],conflicts=[],reviews=[],gaps=['独立 donor 未确认'],limitations=['spot 层级探索性分析'],warnings=[])),
        figures=[],real_model_calls=0)

def test_workbook_keeps_full_tables_exact_values_zero_na_and_formula_like_ids():
    from app.adapters.research_results_xlsx import build_workbook
    from openpyxl import load_workbook
    rows=[['=GENE','01-MAR','0','NA','0.0000000000000000123']]+[[str(i),'ENSG'+str(i),'1','not_significant','0.8'] for i in range(150)]
    content,summary=build_workbook(sample(),[dict(key='markers',columns=['feature_id','symbol','n','reason','p_value'],rows=rows,expected_rows=151,sha256='c'*64)])
    book=load_workbook(io.BytesIO(content),read_only=True,data_only=False)
    saved=list(book['markers'].values)
    assert len(saved)==152 and list(saved[1])==rows[0] and list(saved[-1])==rows[-1]
    assert book['markers']['A2'].data_type=='s'
    assert summary['tables'][0]['rows']==151 and summary['tables'][0]['sheets']==['markers']
    assert summary['tables'][0]['sha256']=='c'*64
    assert all(sha not in str(row) for name in book.sheetnames for row in book[name].values for sha in ('b'*64,'c'*64))
    book.close()

def test_workbook_splits_by_sheet_limit_without_truncation_and_rejects_over_budget(monkeypatch):
    from app.adapters import research_results_xlsx as module
    from openpyxl import load_workbook
    monkeypatch.setattr(module,'MAX_SHEET_ROWS',4)
    table=dict(key='observations',columns=['barcode'],rows=[[str(i)] for i in range(8)],expected_rows=8)
    content,summary=module.build_workbook(sample(),[table])
    book=load_workbook(io.BytesIO(content),read_only=True,data_only=False)
    names=summary['tables'][0]['sheets'];assert names==['observations','observations_2','observations_3']
    assert [row[0] for name in names for row in list(book[name].values)[1:]]==list(map(str,range(8)))
    book.close()
    monkeypatch.setattr(module,'MAX_CELLS',10)
    with pytest.raises(ValueError,match='cell'):module.build_workbook(sample(),[table])

def test_workbook_preserves_literal_and_native_cell_types_and_styles():
    from app.adapters.research_results_xlsx import build_workbook
    from openpyxl import load_workbook
    values=['=SUM(1,2)','0007',0,None,True,0.25]
    raw,_=build_workbook(sample(),[dict(key='mixed',columns=list('abcdef'),rows=[values],expected_rows=1)])
    book=load_workbook(io.BytesIO(raw),read_only=True,data_only=False)
    header,row=list(book['mixed'].rows)
    assert [c.value for c in row]==['=SUM(1,2)','0007',0,'NA',True,0.25]
    assert [c.data_type for c in row]==['s','s','n','s','b','n']
    assert [c.number_format for c in row]==['@','@','General','@','General','General']
    assert all(c.font.bold and c.fill.fgColor.rgb.endswith('284B63') and c.alignment.wrap_text for c in header)
    assert all(c.alignment.vertical=='top' and not c.alignment.wrap_text and not c.font.bold for c in row)
    book.close()

def test_workbook_row_reconciliation_fails_instead_of_silent_partial_export():
    from app.adapters.research_results_xlsx import build_workbook
    with pytest.raises(ValueError,match='row'):build_workbook(sample(),[dict(key='markers',columns=['id'],rows=[['gene']],expected_rows=100)])

def test_docx_contains_source_boundaries_and_does_not_invent_missing_methods():
    from app.adapters.research_report_docx import build_report
    from docx import Document
    doc=Document(io.BytesIO(build_report(sample(),[])))
    text='\n'.join([p.text for p in doc.paragraphs]+[c.text for t in doc.tables for r in t.rows for c in r.cells])
    assert '0.0000000000000000123' in text and '独立 donor 未确认' in text
    assert 'spot 层级探索性分析' in text and '未重算' in text
    assert '未提供已执行方法' in text and 'P < 0.05' not in text
    assert '外部表格' in text and all(value not in text for value in ('finding-v1','a'*64,'b'*64))


def test_english_report_translates_system_caveats_without_mutating_frozen_sources():
    from copy import deepcopy
    from app.adapters.research_report_docx import build_report
    from app.domain.research_results.bio_projection import EXPLORATORY,METHOD_NAMES
    from docx import Document
    snapshot=sample();snapshot['language']='en';snapshot['title']='Fixed analysis'
    content=snapshot['finding']['content']
    content['sources'][0]['title']='空间分析 / Spatial analysis fixed-id'
    content['sources'][0]['source_id']='fixed-id'
    content['facts'][0]['source_id']='fixed-id'
    content['gaps']=['donor/组别的独立重复设计未确认：independent_donors_not_confirmed','线粒体规则未确定：mitochondrial_rule_unconfirmed','用户提供的备注原文']
    content['limitations']=[EXPLORATORY]
    content['warnings']=['事实目录只展示已选行 2/100；完整结果表仍保留，导出不能据此截断。']
    content['methods']=[dict(title=title,description='已执行 / Completed',executed=True,parameters={'seed':0},software={}) for title in METHOD_NAMES.values()]
    before=deepcopy(snapshot)
    doc=Document(io.BytesIO(build_report(snapshot,[])));text='\n'.join(p.text for p in doc.paragraphs)
    assert 'Independent donor/group replicate design has not been confirmed.' in text
    assert 'Mitochondrial rule has not been confirmed.' in text
    assert 'independent_donors_not_confirmed' not in text and 'mitochondrial_rule_unconfirmed' not in text and 'fixed-id' not in text
    assert 'spots and regions are not independent donors' in text
    assert 'Selected rows shown in the fact catalog: 2/100' in text
    assert 'Source text (original language): 用户提供的备注原文' in text
    assert '已执行 / Completed' not in text and '空间分析 / Spatial analysis' not in text
    assert '聚类与 marker' not in text and '线粒体规则未确定' not in text
    assert snapshot==before

def test_zip_members_are_frozen_and_checked_and_unsafe_names_rejected():
    from app.domain.research_results.report_package import make_package,verify_package
    inputs={'report.docx':b'docx','results.xlsx':b'xlsx','methods.txt':b'methods'}
    content,manifest=make_package(inputs,{'schema_version':1,'finding_version_id':'v1'})
    assert verify_package(content)==manifest
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        assert archive.read('report.docx')==b'docx'
    with pytest.raises(ValueError,match='name'):make_package({'../escape':b'bad'}, {})
    inputs['report.docx']=b'changed'
    assert verify_package(content)==manifest


@pytest.mark.parametrize('fmt',['tiff','svg'])
def test_successful_non_png_bitmap_figure_is_a_report_image(fmt,tmp_path):
    from app.adapters.research_figure_render import render_figure
    from app.adapters.research_report_images import as_png
    from PIL import Image
    import hashlib
    image=io.BytesIO();Image.new('RGB',(100,50),'red').save(image,'PNG')
    path=tmp_path/'input.png';path.write_bytes(image.getvalue());out=tmp_path/'out';out.mkdir()
    result=render_figure(dict(config={'mode':'reuse','width_mm':85.0,'dpi':150,'formats':[fmt]},
        panels=[dict(path=str(path),sha256=hashlib.sha256(image.getvalue()).hexdigest(),source={})]),out)
    converted=as_png((out/('figure_'+fmt+'.'+fmt)).read_bytes(),fmt)
    with Image.open(io.BytesIO(converted)) as rendered:
        assert rendered.size==(result['manifest']['width_pixels'],result['manifest']['height_pixels'])
        assert rendered.getpixel((rendered.width//2,rendered.height//2))[0]>240


def test_rebuild_uses_exact_table_bytes_including_empty_strings(tmp_path):
    from app.adapters.research_report_render import render_report
    import hashlib,subprocess,sys
    raw=b'feature_id\tvalue\nGENE1\t\nGENE2\tNA\n'
    source=tmp_path/'table.tsv';source.write_bytes(raw)
    table=dict(key='markers',columns=['feature_id','value'],expected_rows=2,sha256=hashlib.sha256(raw).hexdigest())
    snapshot=sample();snapshot['tables']=[table];out=tmp_path/'out';out.mkdir()
    result=render_report(dict(snapshot=snapshot,tables=[dict(table,path=str(source))],figures=[],package_files=[]),out)
    with zipfile.ZipFile(out/'analysis_package.zip') as archive:
        assert archive.read('tables/table_000.tsv')==raw
        archive.extractall(tmp_path/'package')
    completed=subprocess.run([sys.executable,str(tmp_path/'package/rebuild_report.py')],capture_output=True,text=True)
    assert completed.returncode==0,completed.stderr
    from openpyxl import load_workbook
    first=load_workbook(io.BytesIO((out/'results.xlsx').read_bytes()),read_only=True,data_only=False)
    second=load_workbook(tmp_path/'package/rebuilt/results.xlsx',read_only=True,data_only=False)
    assert list(first['markers'].values)==list(second['markers'].values)
    first.close();second.close()


def test_child_quota_failure_keeps_actionable_public_code(monkeypatch,tmp_path):
    from app.adapters import research_report_render as module
    from app.core.exceptions import StorageError
    from types import SimpleNamespace
    monkeypatch.setattr(module.sys,'platform','linux')
    monkeypatch.setattr(module.signal,'SIGALRM',14,raising=False)
    monkeypatch.setattr(module.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=0,stdout=b'{"error":"research_export_limit_exceeded"}'))
    with pytest.raises(StorageError) as error:module.execute_research_report({},tmp_path)
    assert error.value.code=='research_export_limit_exceeded'
