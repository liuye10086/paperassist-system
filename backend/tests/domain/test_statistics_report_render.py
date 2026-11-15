"""R3-only labels preserve source locators and survive a standalone ZIP rebuild."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def test_frozen_base_keeps_its_renderer_and_checks_current_base_bytes(monkeypatch):
    from app.adapters import research_report_render as base
    from app.domain.statistics_reader_reports.render import frozen_renderer_identity,renderer_identity
    saved=base.renderer_identity()
    assert frozen_renderer_identity(saved)==saved
    assert frozen_renderer_identity(renderer_identity())==renderer_identity()
    changed={**saved,'code_digest':'f'*64}
    monkeypatch.setattr(base,'renderer_identity',lambda:changed)
    assert frozen_renderer_identity(saved)==changed


def test_changed_statistics_adapter_cannot_execute_an_old_frozen_task(monkeypatch):
    from app.domain.statistics_reader_reports.legacy_exports import StatisticsLegacyReportService
    from app.domain.statistics_reader_reports.render import renderer_identity
    from app.core.exceptions import StorageError
    service=object.__new__(StatisticsLegacyReportService)
    monkeypatch.setattr(service,'association',lambda *args:None)
    old={**renderer_identity(),'adapter_sha256':'0'*64}
    with pytest.raises(StorageError):
        service.require_sources(None,{'input_snapshot':{'reader_export':{'renderer_identity':old}}})


@pytest.mark.parametrize('en',(False,True))
def test_statistics_location_terms_use_the_existing_table_dictionary(en):
    from app.domain.statistics_reader_reports.render_labels import labels
    terms=labels()
    assert terms['check'][en]==('Quality checks' if en else '质量与可用性')
    assert terms['excluded_count'][en]==('Excluded count' if en else '排除计数')
    assert terms['overall'][en]==('Overall summary' if en else '总体摘要')
    assert terms['mean'][en]==('Mean' if en else '均值')


@pytest.mark.skipif(sys.platform!='linux',reason='Production statistics renderer requires Linux isolation')
@pytest.mark.parametrize('language',('zh-CN','en'))
def test_docx_xlsx_and_offline_rebuild_use_identical_readable_fact_locations(tmp_path,language):
    from tests.domain.test_research_reports import sample
    from app.adapters.research_report_render import stage_report_payload,renderer_identity as base_identity
    from app.domain.statistics_reader_reports.render import execute_statistics_report,renderer_identity
    from docx import Document
    from openpyxl import load_workbook
    snapshot=sample();snapshot.update(language=language,tables=[])
    fact=snapshot['finding']['content']['facts'][0]
    snapshot['finding']['content']['facts']=[dict(fact,id='excluded',raw_value=0,display_value='0',locator={'kind':'field','field_path':'check.excluded_count'}),
        dict(fact,id='mean',raw_value=1.25,display_value='1.25',locator={'kind':'field','field_path':'overall.mean'})]
    original=deepcopy(snapshot)
    output=tmp_path/'output';output.mkdir()
    staged=tmp_path/'stage';staged.mkdir()
    payload=stage_report_payload(dict(snapshot=snapshot,tables=[],table_raws=[],figures=[],package_files=[]),staged)
    result=execute_statistics_report(payload,output)
    assert result['manifest']['renderer_identity']==renderer_identity()!=base_identity()
    members={m['role']:Path(m['path']).read_bytes() for m in result['outputs']}
    def values(docx,xlsx):
        doc=Document(BytesIO(docx));text='\n'.join(c.text for t in doc.tables for r in t.rows for c in r.cells)
        book=load_workbook(BytesIO(xlsx),data_only=False)
        ws=book['Facts'];facts=list(ws.values)
        assert ws['F2'].alignment.wrap_text and ws['G2'].alignment.wrap_text
        assert ws.row_dimensions[2].height>21
        book.close()
        expected=('Quality checks / Excluded count','Overall summary / Mean') if language=='en' else ('质量与可用性 / 排除计数','总体摘要 / 均值')
        for label in expected:
            assert label in text and label in str(facts)
        assert 'check / excluded count' not in text and 'overall / mean' not in text
        return text,facts
    before=values(members['docx'],members['xlsx'])
    root=tmp_path/'package';root.mkdir()
    with ZipFile(BytesIO(members['zip'])) as package:
        assert json.loads(package.read('report_snapshot.json'))==original
        package.extractall(root)
    subprocess.run([sys.executable,str(root/'verify_package.py')],check=True,capture_output=True)
    subprocess.run([sys.executable,str(root/'rebuild_report.py')],check=True,capture_output=True)
    assert values((root/'rebuilt/analysis.docx').read_bytes(),(root/'rebuilt/results.xlsx').read_bytes())==before
    assert snapshot==original


@pytest.mark.skipif(sys.platform!='linux',reason='Production statistics renderer requires Linux isolation')
@pytest.mark.parametrize('language',('zh-CN','en'))
@pytest.mark.parametrize('order',(('run-a','run-b'),('run-b','run-a')))
def test_word_source_numbers_follow_exact_frozen_sources_not_values_or_figures(tmp_path,language,order):
    import hashlib
    from PIL import Image
    from docx import Document
    from openpyxl import load_workbook
    from tests.domain.test_research_reports import sample
    from app.adapters.research_report_render import stage_report_payload
    from app.domain.statistics_reader_reports.render import execute_statistics_report
    snapshot=sample();snapshot.update(language=language,tables=[])
    finding=snapshot['finding']['content'];seed=finding['facts'][0]
    shas={'run-a':'a'*64,'run-b':'b'*64};numbers={key:i for i,key in enumerate(order,1)}
    titles={key:(f'Run {i} · Pearson correlation' if language=='en' else f'分析 {i} · Pearson 相关分析') for key,i in numbers.items()}
    finding['sources']=[dict(source_kind='analysis_run',source_id=key,sha256=shas[key],title=titles[key]) for key in order]
    # Fact order deliberately differs from frozen source order. Same locators
    # have both equal and unequal values; neither can establish provenance.
    facts=[]
    for key in reversed(order):
        for field,value in [('check.excluded_count',1),('overall.mean',10 if key=='run-a' else 20)]:
            facts.append(dict(seed,id=key+field,source_kind='analysis_run',source_id=key,source_sha256=shas[key],
                locator=dict(kind='field',field_path=field),raw_value=value,display_value=str(value)))
    for name,change in [('wrong-sha',{'source_sha256':'c'*64}),('wrong-id',{'source_id':'missing'}),
                        ('wrong-kind',{'source_kind':'original_file'})]:
        facts.append({**facts[0],**change,'id':name})
    finding['facts']=facts
    image=BytesIO();Image.new('RGB',(20,10),'white').save(image,'PNG');png=image.getvalue()
    figures=[];files=[]
    # Two selected figures from one result must not allocate another analysis
    # number or shift the second result to Analysis 3.
    for i,key in enumerate((order[0],order[0],order[1]),1):
        config=dict(title=f'{titles[key]} / {i}',caption='',width_mm=85,language=language,figure_language=language)
        snapshot['figures'].append(dict(id=f'figure-{i}',config=config,manifest_sha256=hashlib.sha256(png).hexdigest(),
            document_image=dict(key='figure',format='png',sha256=hashlib.sha256(png).hexdigest())))
        figures.append(dict(config=config,format='png',raw=png))
        files.append(dict(name=f'figures/figure_{i:02d}/figure.png',raw=png))
    original=deepcopy(snapshot)
    stage=tmp_path/'stage';stage.mkdir();output=tmp_path/'output';output.mkdir()
    payload=stage_report_payload(dict(snapshot=snapshot,tables=[],table_raws=[],figures=figures,package_files=files),stage)
    result=execute_statistics_report(payload,output)
    members={m['role']:Path(m['path']).read_bytes() for m in result['outputs']}
    locations={'check.excluded_count':('质量与可用性 / 排除计数','Quality checks / Excluded count'),
               'overall.mean':('总体摘要 / 均值','Overall summary / Mean')}
    def values(docx,xlsx):
        doc=Document(BytesIO(docx));header='Location' if language=='en' else '来源位置'
        table=next(t for t in doc.tables if t.cell(0,0).text==header)
        rows=[[c.text for c in row.cells] for row in table.rows[1:]]
        assert len(rows)==len(facts)
        for fact,row in zip(facts,rows,strict=True):
            label=locations[fact['locator']['field_path']][language=='en']
            if not fact['id'].startswith('wrong-'):
                prefix=('Analysis ' if language=='en' else '分析 ')+str(numbers[fact['source_id']])
                label=prefix+' / '+label
            assert row[0]==label
            assert row[1]==str(fact['raw_value'])
        book=load_workbook(BytesIO(xlsx),data_only=False)
        ws=book['Facts'];sheet=list(ws.values)
        assert ws.column_dimensions['F'].width==22 and ws.column_dimensions['G'].width==22
        assert all(ws.cell(i,c).alignment.wrap_text for i in range(2,len(facts)+2) for c in (6,7))
        assert all(ws.row_dimensions[i].height>21 for i in range(2,len(facts)+2))
        book.close()
        for fact,row in zip(facts,sheet[1:],strict=True):
            assert row[-1]==locations[fact['locator']['field_path']][language=='en']
            if not fact['id'].startswith('wrong-'):assert row[-2]==titles[fact['source_id']]
        return rows,sheet
    before=values(members['docx'],members['xlsx'])
    root=tmp_path/'package';root.mkdir()
    with ZipFile(BytesIO(members['zip'])) as package:
        assert json.loads(package.read('report_snapshot.json'))==original
        package.extractall(root)
    subprocess.run([sys.executable,str(root/'verify_package.py')],check=True,capture_output=True)
    subprocess.run([sys.executable,str(root/'rebuild_report.py')],check=True,capture_output=True)
    assert values((root/'rebuilt/analysis.docx').read_bytes(),(root/'rebuilt/results.xlsx').read_bytes())==before
    assert snapshot==original
