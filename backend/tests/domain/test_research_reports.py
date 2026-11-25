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

def test_bulk_table_budget_keeps_word_exportable_at_the_workbook_limit(monkeypatch, tmp_path):
    from hashlib import sha256
    from types import SimpleNamespace
    from app.adapters import research_results_xlsx as workbook
    from app.adapters.research_report_render import render_report, stage_report_payload
    from app.domain.bio_reader_reports.materials import MaterialBuilder
    from app.domain.reader_reports import content as reader_report
    from tests.helpers.research_report import sample_reader_record

    assets = SimpleNamespace(owner_id='test-owner', db_config=object(), directory=tmp_path)
    builder = MaterialBuilder(assets, None, 'test-project', 'en', None)
    builder.selection = {'kind': 'bulk'}
    raw_by_sha = {}
    for key, width, rows in (
        ('model_counts', 100, 8), ('comparison_results', 2, 15), ('selected_B_A', 2, 11),
        ('sample_qc', 2, 6), ('normalization_details', 2, 4),
    ):
        columns = [f'column{i}' for i in range(width)]
        raw = ('\t'.join(columns) + '\n' + ('\t'.join(['1'] * width) + '\n') * rows).encode()
        sha = sha256(raw).hexdigest()
        builder.tables.append(dict(key=key, format='tsv', columns=columns, expected_rows=rows,
            source={'selection': {'contrast_id': 'B_A'}} if key == 'selected_B_A' else {}, sha256=sha))
        builder.blobs.append(dict(sha256=sha))
        raw_by_sha[sha] = raw

    # The frozen table descriptors alone fit. Facts, narrative, and the export
    # index are also written when the report is rendered.
    monkeypatch.setattr(workbook, 'MAX_CELLS', 1024)
    monkeypatch.setattr(reader_report, 'MAX_READER_OUTPUT_BYTES', 512)
    assert sum((table['expected_rows'] + 1) * len(table['columns']) for table in builder.tables) < workbook.MAX_CELLS
    context = builder.finish(SimpleNamespace(title='Bulk report', language='en'), {})
    snapshot = sample() | {'title': context['title'], 'language': context['language'], 'tables': context['tables']}
    snapshot['reader_report'] = sample_reader_record(snapshot)
    payload = stage_report_payload(dict(snapshot=snapshot, tables=context['tables'],
        table_raws=[raw_by_sha[blob['sha256']] for blob in context['table_blobs']], figures=[], package_files=[]), tmp_path)
    output = tmp_path / 'output'
    output.mkdir()
    rendered = render_report(payload, output)

    assert (output / 'analysis.docx').read_bytes().startswith(b'PK')
    counts = rendered['manifest']['row_counts']
    assert [table['key'] for table in counts['tables']] == ['comparison_results', 'selected_B_A', 'sample_qc', 'normalization_details']
    assert counts['total_cells'] <= workbook.MAX_CELLS
    assert context['workbook_limited'] is True


def test_bulk_table_budget_counts_repeated_headers_and_export_index(monkeypatch):
    from app.adapters import research_results_xlsx as workbook
    from app.domain.bio_reader_reports.bulk import _limit_workbook_tables, _workbook_metadata_cells

    def table(key, width, rows, *, selection=False):
        return dict(key=key, columns=[f'column{i}' for i in range(width)], expected_rows=rows,
                    source={'selection': {'contrast_id': 'B_A'}} if selection else {})

    # Each sheet holds three data rows. The comparison has two headers, and
    # both of the tables that fit contribute a four-cell export index row.
    monkeypatch.setattr(workbook, 'MAX_SHEET_ROWS', 4)
    selected = table('selected_B_A', 2, 1, selection=True)
    comparison = table('comparison_results', 2, 5)
    matrix = table('model_counts', 2, 0)
    content = dict(facts=[], methods=[], figures=[], warnings=[], limitations=[], gaps=[],
        tables=[matrix, comparison, selected], table_blobs=['matrix', 'comparison', 'selected'])
    capacity = (1 + 1) * 2 + (5 + 2) * 2 + 2 * 4
    # Two cells for the omission notice and three unused cells. Forgetting
    # the repeated two-cell header would wrongly admit the six-cell matrix.
    monkeypatch.setattr(workbook, 'MAX_CELLS', _workbook_metadata_cells(content) + capacity + 2 + 3)
    _limit_workbook_tables(content)
    assert content['tables'] == [comparison, selected]
    assert content['table_blobs'] == ['comparison', 'selected']

    _, summary = workbook.build_workbook(sample(), [dict(table, rows=[['x'] * len(table['columns'])] * table['expected_rows'])
                                                   for table in content['tables']])
    assert summary['tables'][0]['sheets'] == ['comparison_results', 'comparison_results_2']
    _, base = workbook.build_workbook(sample(), [])
    assert summary['total_cells'] - base['total_cells'] == capacity


@pytest.mark.parametrize('language', ['en', 'zh-CN'])
def test_bulk_reader_cell_reserve_covers_dense_narrative_and_captions(monkeypatch, language):
    from app.adapters.research_results_xlsx import narrative_lines
    from app.domain.bio_reader_reports.bulk import _reader_text_cells
    from app.domain.reader_reports import content as reader_report

    many_lines = 'x\n' * 5900 + 'x'
    wrapped = 'y' * 11999
    narrative = {field: many_lines for field in reader_report.NARRATIVE_FIELDS}
    figure = dict(number=1, title='Fixture figure', reading=many_lines, observations=wrapped,
                  interpretation=many_lines, limitations=many_lines)
    raw = dict(narrative=narrative, figures=[figure])
    byte_count = len(json.dumps(raw, ensure_ascii=False).encode('utf-8'))
    monkeypatch.setattr(reader_report, 'MAX_READER_OUTPUT_BYTES', byte_count)
    checked = reader_report.validate_output(raw, dict(language=language, figures=[dict(number=1)]))
    narrative_cells = 2 * sum(len(list(narrative_lines(text))) for text in checked['narrative'].values())
    caption_cells = 5 * len(list(narrative_lines(checked['figures'][0]['caption'])))
    assert _reader_text_cells(1) >= narrative_cells + caption_cells


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


@pytest.mark.parametrize('language',['zh-CN','en'])
@pytest.mark.parametrize('inherited',[False,True])
@pytest.mark.parametrize('decision',['use_first','use_second'])
def test_conflict_exports_resolve_facts_in_declared_order_without_internal_ids(language,inherited,decision):
    from copy import deepcopy
    from docx import Document
    from openpyxl import load_workbook
    from app.adapters.research_report_docx import build_report
    from app.adapters.research_results_xlsx import build_workbook
    snapshot=sample();snapshot['language']=language
    finding=snapshot['finding']['content']
    first={**finding['facts'][0],'id':'internal-fact-one','raw_value':'10.25','unit':'mg','locator':{'sheet':'Assay A','cell':'B2'}}
    second={**first,'id':'internal-fact-two','raw_value':'20.75','locator':{'sheet':'Assay B','cell':'C9'}}
    finding['facts']=[first,second]
    finding['conflicts']=[dict(id='internal-conflict',fact_ids=[second['id'],first['id']],decision=decision,note='Different measurements',basis='Reviewed original assay')]
    if inherited:
        finding['sources']=[dict(source_id='internal-parent',title='Reviewed results',content=deepcopy(finding))]
        finding['facts']=[]
    before=deepcopy(snapshot)
    doc=Document(io.BytesIO(build_report(snapshot,[])))
    text='\n'.join(p.text for p in doc.paragraphs)
    xlsx,_=build_workbook(snapshot,[])
    book=load_workbook(io.BytesIO(xlsx),read_only=True)
    row=list(book['Limitations'].values)[-1][1]
    for exported in (text,row):
        assert exported.index('Assay B!C9') < exported.index('Assay A!B2')
        assert '20.75 mg' in exported and '10.25 mg' in exported
        assert ('第 1 项' if language=='zh-CN' else 'Item 1') in exported
        assert ('第 2 项' if language=='zh-CN' else 'Item 2') in exported
        assert 'Reviewed original assay' in exported and 'Different measurements' in exported
        assert ({'use_first':'Use first','use_second':'Use second'}[decision] if language=='en' else {'use_first':'采用第一项','use_second':'采用第二项'}[decision]) in exported
        assert not any(value in exported for value in ('internal-fact-one','internal-fact-two','internal-conflict','internal-parent','b'*64))
    assert snapshot==before
    book.close()


def test_conflict_export_rejects_unresolvable_fact_instead_of_ambiguous_decision():
    from app.adapters.research_report_docx import build_report
    from app.adapters.research_results_xlsx import build_workbook
    snapshot=sample()
    snapshot['finding']['content']['conflicts']=[dict(fact_ids=['fact1','missing'],decision='use_second',basis='reviewed')]
    with pytest.raises(ValueError,match='conflict fact'):build_report(snapshot,[])
    with pytest.raises(ValueError,match='conflict fact'):build_workbook(snapshot,[])


def test_reader_export_explains_system_fields_without_changing_source_values():
    from copy import deepcopy
    from app.adapters.research_report_docx import build_report
    from app.adapters.research_results_xlsx import build_workbook
    from docx import Document
    from openpyxl import load_workbook
    snapshot=sample();finding=snapshot['finding']['content']
    finding['facts'][0].update(locator={'field_path':'summary.retained_observations'},raw_value=1162,
        observation_level='spot',verification_status='verified')
    finding['methods']=[dict(title='过滤 / Filtering',executed=True,description='已执行 · SHA256 '+'c'*64+' v1.2.3',
        parameters=dict(min_counts=1,min_gene_spots=3,max_mt_fraction=None,seed=0,in_tissue_only=False,engine_version='internal-v1.2.3',code_digest='a'*64))]
    finding['claims']=[dict(statement='观察到六个探索性分群。',strength='exploratory',origin='system_candidate',review_decision='adopt',limitations=[])]
    before=deepcopy(snapshot)
    doc=Document(io.BytesIO(build_report(snapshot,[])))
    text='\n'.join([p.text for p in doc.paragraphs]+[c.text for t in doc.tables for r in t.rows for c in r.cells])
    for label in ('保留观测数','空间点','已核对','最低总计数','最少表达空间点数','未设置','探索性','系统候选'):
        assert label in text
    assert '随机种子: 0' in text and '仅保留组织内空间点: 否' in text
    for technical in ('summary.retained','min_counts','min_gene_spots','max_mt_fraction','verified','system_candidate','internal-v1.2.3','a'*64,'c'*64,'v1.2.3'):
        assert technical not in text
    raw,_=build_workbook(snapshot,[]);book=load_workbook(io.BytesIO(raw),read_only=True)
    assert book['Facts']['A2'].value==1162
    assert book['Facts']['D2'].value=='空间点' and book['Facts']['E2'].value=='已核对'
    assert book['Facts']['G2'].value=='保留观测数'
    method_text=str(list(book['Methods'].values))
    assert '已执行' in method_text and all(v not in method_text for v in ('c'*64,'SHA256','v1.2.3'))
    assert snapshot==before
    book.close()


def test_reader_exports_keep_science_and_remove_version_and_id_from_title_and_conflict_prose():
    from copy import deepcopy
    from docx import Document
    from openpyxl import load_workbook
    from app.adapters.research_report_docx import build_report
    from app.adapters.research_results_xlsx import build_workbook
    from tests.helpers.research_report import sample_reader_record

    identifier='681fa52c-b922-4917-9c76-72cd5daf628b'
    version='v1.9.8'
    digest='e'*64
    gene='ENSG00000141510.18'
    snapshot=sample()
    snapshot['language']='en'
    snapshot['title']=f'Spatial results for {gene} · {identifier} {version}'
    finding=snapshot['finding']['content']
    finding['facts'][0].update(raw_value=gene,display_value=gene,unit='mg/mL')
    finding['conflicts']=[dict(fact_ids=['fact1'],decision='unresolved',
        note=f'Check {gene} at 5 mg/mL · {identifier} {version}',
        basis=f'Original observation confirmed · SHA256 {digest}')]
    snapshot['reader_report']=sample_reader_record(snapshot)
    before=deepcopy(snapshot)
    doc=Document(io.BytesIO(build_report(snapshot,[])))
    raw,_=build_workbook(snapshot,[])
    book=load_workbook(io.BytesIO(raw),read_only=True)
    for visible in ('\n'.join(p.text for p in doc.paragraphs),str(list(book['Limitations'].values))):
        assert gene in visible and '5 mg/mL' in visible and 'Original observation confirmed' in visible
        assert all(token not in visible for token in (identifier,version,digest))
    assert book['Facts']['A2'].value==gene and book['Facts']['C2'].value=='mg/mL'
    book.close()
    assert snapshot==before


def test_reader_export_separates_spatial_filter_rules_from_other_frozen_settings():
    from copy import deepcopy
    from app.adapters.research_method_text import reader_method

    method=dict(title='过滤 / Filtering',description='已执行 / Completed',executed=True,
        source=dict(source_kind='bio_processed_dataset_version',locator=dict(field_path='steps[1]')),
        parameters=dict(min_counts=1,min_gene_spots=3,target_sum=10000,pca_components=30,neighbors=15,resolution=.5,
                        seed=0,mt_rule=dict(kind='prefix',prefix='MT-',confirmed=True),output_language='en'))
    before=deepcopy(method)
    shown=reader_method(method,'en')
    assert 'Filtering and recorded analysis settings' in shown['title']
    filtering,other=shown['paragraphs'][-2:]
    assert 'Minimum total counts: 1' in filtering and 'Gene name prefix: MT-' in filtering
    assert 'Normalization total per observation: 10000' in other
    assert 'Principal components: 30' in other and 'Number of neighbors: 15' in other
    assert 'Normalization total' not in filtering and 'Figure language' not in '\n'.join(shown['paragraphs'])
    assert method==before


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


def test_reader_scope_and_saved_cluster_sizes_use_only_selected_verified_table(tmp_path):
    import hashlib
    import subprocess
    import sys
    from docx import Document
    from openpyxl import load_workbook
    from app.adapters.research_report_render import render_report
    from tests.helpers.research_report import sample_reader_record

    columns=['cluster','spots','statistical_unit']
    lines=[f'{index}\t{count}\tspot' for index,count in enumerate(('007','11','29','31','42','64'))]
    cluster_raw=('\t'.join(columns)+'\n'+'\n'.join(lines)+'\n').encode()
    unrelated_raw=b'cluster\tspots\tstatistical_unit\n0\t999\tspot\n'
    second_raw=b'cluster\tspots\tstatistical_unit\n8\t50\tspot\n'
    large_raw=('\t'.join(columns)+'\n'+''.join(f'{index}\t29\tspot\n' for index in range(201))).encode()
    snapshot=sample()
    snapshot['language']='en'
    snapshot['reader_report']=sample_reader_record(snapshot)
    snapshot['finding']['content']['sources'].append(dict(source_kind='bio_processed_dataset_version',
        source_id='fixed-source',title='Spatial tissue sample',provenance='system_computed'))
    selected=[]
    for index,(raw,source) in enumerate((
        (cluster_raw,dict(source_kind='bio_analysis_artifact',processed_version_id='fixed-source')),
        (unrelated_raw,dict(source_kind='bio_insight_result_member',result_version_id='unrelated')),
        (second_raw,dict(source_kind='bio_analysis_artifact',processed_version_id='another-source')),
        (large_raw,dict(source_kind='bio_analysis_artifact',processed_version_id='large-source')),
    )):
        path=tmp_path/f'table_{index}.tsv'
        path.write_bytes(raw)
        selected.append(dict(key='cluster_summary',columns=columns,sha256=hashlib.sha256(raw).hexdigest(),
            source=source,expected_rows=len(raw.splitlines())-1,path=str(path)))
    snapshot['tables']=[{key:value for key,value in table.items() if key!='path'} for table in selected]
    output=tmp_path/'export'
    output.mkdir()
    render_report(dict(snapshot=snapshot,tables=selected,figures=[],package_files=[]),output)
    doc=Document(output/'analysis.docx')
    scope=next(p.text for p in doc.paragraphs if 'selected summary facts' in p.text)
    assert 'not provided' in scope.lower() and 'workbook' in scope
    assert 'did not read the complete tables row by row' in scope and 'directly from the selected tables' in scope
    assert list(p.text for p in doc.paragraphs).index(scope)<list(p.text for p in doc.paragraphs).index('Abstract')
    assert len(doc.tables)==3
    labels=[p.text for p in doc.paragraphs if p.text.startswith('Selected result table')]
    assert labels==['Selected result table 1 · Spatial tissue sample','Selected result table 3']
    observed=[[cell.text for cell in row.cells] for row in doc.tables[0].rows]
    assert observed==[['Cluster','Spatial spots']]+[line.split('\t')[:2] for line in lines]
    book=load_workbook(output/'results.xlsx',read_only=True)
    assert list(book['Report narrative'].values)[1][1]==scope
    assert book['cluster_summary']['B2'].value=='007'
    assert book['cluster_summary_2']['B2'].value=='999'
    assert book['cluster_summary_4']['A202'].value=='200'
    book.close()
    with zipfile.ZipFile(output/'analysis_package.zip') as archive:
        assert json.loads(archive.read('report_snapshot.json'))['reader_report']==snapshot['reader_report']
        archive.extractall(tmp_path/'package')
    completed=subprocess.run([sys.executable,str(tmp_path/'package/rebuild_report.py')],capture_output=True,text=True)
    assert completed.returncode==0,completed.stderr
    rebuilt=Document(tmp_path/'package/rebuilt/analysis.docx')
    assert [[cell.text for cell in row.cells] for row in rebuilt.tables[0].rows]==observed


def test_reader_workbook_persists_display_widths_in_saved_sheets():
    from openpyxl import load_workbook
    from app.adapters.research_results_xlsx import build_workbook
    from tests.helpers.research_report import sample_reader_record

    snapshot=sample()
    snapshot['reader_report']=sample_reader_record(snapshot)
    raw,_=build_workbook(snapshot,[])
    workbook=load_workbook(io.BytesIO(raw))
    try:
        expected={'Report narrative': {'B':100}, 'Methods': {'C':100},
                  'Figures': {'A':8,'B':44,'C':100}, 'Limitations': {'B':100}}
        actual={sheet:{column:workbook[sheet].column_dimensions[column].width for column in widths}
                for sheet,widths in expected.items()}
        assert actual==expected
    finally:
        workbook.close()


def test_saved_reader_rows_reserve_a_line_for_excel_word_wrapping():
    from openpyxl import load_workbook
    from app.adapters.research_results_xlsx import build_workbook
    from tests.helpers.research_report import sample_reader_record

    snapshot=sample()
    snapshot['language']='en'
    snapshot['figures']=[dict(config={})]
    record=sample_reader_record(snapshot)
    record['narrative']['abstract']='\n'.join(['A short line.']*7)
    record['narrative']['methods_summary']=('word '*116).strip()
    caption_lengths={3:387,13:285,42:289,47:489,51:385}
    record['figures'][0]['caption']='\n'.join(
        ('word '*100)[:caption_lengths[row]].strip() if row in caption_lengths else 'Short.'
        for row in range(2,52)
    )
    snapshot['reader_report']=record

    raw,_=build_workbook(snapshot,[])
    workbook=load_workbook(io.BytesIO(raw))
    try:
        assert workbook['Report narrative'].row_dimensions[12].height==111
        assert {row:workbook['Figures'].row_dimensions[row].height for row in caption_lengths}=={
            3:81,13:66,42:66,47:96,51:81}
        assert workbook['Figures'].row_dimensions[2].height==21
    finally:
        workbook.close()

def test_report_package_reuses_exact_reader_record_and_rebuilds_historical_pdf_figure(tmp_path):
    import hashlib
    import subprocess
    import sys
    from docx import Document
    from openpyxl import load_workbook
    from PIL import Image
    from app.adapters.research_report_render import render_report
    from tests.helpers.research_report import sample_reader_record

    old_pdf=tmp_path/'legacy.pdf'
    Image.new('RGB',(100,50),'red').save(old_pdf,'PDF')
    sha=hashlib.sha256(old_pdf.read_bytes()).hexdigest()
    config=dict(title='旧图题',caption='旧图注',figure_language='en',language='zh-CN')
    snapshot=sample()
    snapshot['tables']=[]
    snapshot['figures']=[dict(id='legacy-figure',manifest_sha256='b'*64,config=config,
        document_image=dict(key='figure_pdf',format='pdf',sha256=sha))]
    record=sample_reader_record(snapshot)
    snapshot['reader_report']=record
    output=tmp_path/'output'
    output.mkdir()
    result=render_report(dict(snapshot=snapshot,tables=[],figures=[
        dict(config=config,path=str(old_pdf),format='pdf',sha256=sha)],package_files=[]),output)
    assert result['manifest']['reader_report_provenance']==record['provenance']
    with zipfile.ZipFile(output/'analysis_package.zip') as archive:
        assert json.loads(archive.read('report_snapshot.json'))['reader_report']==record
        captions=archive.read('captions.txt').decode()
        assert record['figures'][0]['observations'] in captions and '旧图注' not in captions
        assert not any(name.endswith('.pdf') for name in archive.namelist())
        archive.extractall(tmp_path/'package')
    completed=subprocess.run([sys.executable,str(tmp_path/'package/rebuild_report.py')],capture_output=True,text=True)
    assert completed.returncode==0,completed.stderr
    first=Document(output/'analysis.docx')
    rebuilt=Document(tmp_path/'package/rebuilt/analysis.docx')
    assert len(first.inline_shapes)==len(rebuilt.inline_shapes)==1
    first_text='\n'.join(p.text for p in first.paragraphs)
    assert first_text=='\n'.join(p.text for p in rebuilt.paragraphs)
    assert all(text in first_text for text in record['narrative'].values())
    assert record['figures'][0]['limitations'] in first_text and '旧图注' not in first_text
    final_caption=next(p for p in first.paragraphs if p.text==record['figures'][0]['limitations'])
    assert final_caption.paragraph_format.keep_with_next is True
    workbook=load_workbook(output/'results.xlsx',read_only=True)
    assert all(text in str(list(workbook['Report narrative'].values)) for text in record['narrative'].values())
    assert record['figures'][0]['observations'] in str(list(workbook['Figures'].values))
    workbook.close()


def test_child_quota_failure_keeps_actionable_public_code(monkeypatch,tmp_path):
    from app.adapters import research_report_render as module
    from app.core.exceptions import StorageError
    from types import SimpleNamespace
    monkeypatch.setattr(module.sys,'platform','linux')
    monkeypatch.setattr(module.signal,'SIGALRM',14,raising=False)
    monkeypatch.setattr(module.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=0,stdout=b'{"error":"research_export_limit_exceeded"}'))
    with pytest.raises(StorageError) as error:module.execute_research_report({},tmp_path)
    assert error.value.code=='research_export_limit_exceeded'
