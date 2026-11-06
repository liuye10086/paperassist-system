import io
from zipfile import ZipFile

from docx import Document
from PIL import Image
import pytest


def test_basic_word_report_uses_saved_counts_methods_and_png_only():
    from app.adapters.single_cell_report import build_single_cell_report
    manifest = dict(assay='single_cell', observation_level='cell', engine_version='visium_explore_v1.0.0',
                    code_digest='a'*64, environment_digest='b'*64, params={'min_counts': 10},
                    summary=dict(raw_observations=48, retained_observations=40, excluded_observations=8,
                                 raw_features=24, retained_features=20, excluded_features=4, shape=[40, 20]),
                    steps=[dict(key='raw_qc', status='completed', params={}),
                           dict(key='markers', status='not_computable', reason='too_few_cells', params={})])
    raw = dict(source_files=[{'filename': 'counts.h5ad'}], samples=[dict(sample_id='S1', library_id='L1', donor=None, batch='B1', group=None,species_taxon_id=9606,reference_id='GRCh38',reference_version='2024-A',library_chemistry='3prime-v3',pair_id='P1')])
    buffer = io.BytesIO()
    Image.new('RGB', (40, 30), 'white').save(buffer, format='PNG')
    content = build_single_cell_report('project', 'processed', 'f'*64, manifest, raw,
                                      [{'content': buffer.getvalue(), 'config': {'title': 'QC', 'caption': 'Saved QC'}}],
                                      samples=[dict(sample_id='S1',library_id='L1',donor='reviewed-donor',batch='B1',group='reviewed-group')])
    doc = Document(io.BytesIO(content))
    text = '\n'.join(p.text for p in doc.paragraphs) + '\n' + '\n'.join(c.text for t in doc.tables for r in t.rows for c in r.cells)
    assert '48' in text and '40' in text and '8' in text and 'counts.h5ad' in text
    assert 'S1' in text and 'L1' in text and 'B1' in text
    assert 'reviewed-donor' in text and 'reviewed-group' in text
    assert all(value in text for value in ('9606','GRCh38','2024-A','3prime-v3','P1'))
    assert 'too_few_cells' in text and '未完成' in text
    assert '研究发现版本' not in text and '交付包附' not in text
    assert len(doc.inline_shapes) == 1
    with ZipFile(io.BytesIO(content)) as archive:
        assert not any(name.lower().endswith('.pdf') for name in archive.namelist())


def test_word_reports_tool_states_versions_and_correction_boundary_without_sample_metadata():
    from app.adapters.single_cell_report import build_single_cell_report
    states=dict(doublet=dict(status='completed',reason=None,input_cells=90,computed_cells=90,predicted_doublets=3,excluded_cells=0),
        decontx=dict(status='partial',reason='some_libraries_not_computable_or_failed',corrected_cells=45,layer_emitted=False),
        versions={'scDblFinder':'1.20.2','decontX':'1.4.0'})
    manifest=dict(assay='single_cell',observation_level='cell',summary=dict(raw_observations=90,retained_observations=90,single_cell_algorithms=states),params={},steps=[])
    content=build_single_cell_report('p','v','a'*64,manifest,dict(source_files=[],samples=[]),[])
    doc=Document(io.BytesIO(content));text='\n'.join(p.text for p in doc.paragraphs)
    assert all(v in text for v in ('scDblFinder','1.20.2','decontX','1.4.0','partial','some_libraries_not_computable_or_failed'))
    assert '原始整数 counts' in text and '模型预测' in text
    assert '"status"' not in text and '"corrected_cells"' not in text


def test_word_includes_readable_library_model_outcomes():
    from app.adapters.single_cell_report import build_single_cell_report
    manifest=dict(assay='single_cell',observation_level='cell',summary=dict(single_cell_algorithms=dict(doublet=dict(status='completed'),decontx=dict(status='not_requested'),versions={})),params={},steps=[])
    outcome=dict(library_id='L1',algorithm='scdblfinder',status='completed',input_cells=80,computed_cells=80,predicted_doublets=2,excluded_cells=0,seed=23,expected_rate=.1,reason=None)
    content=build_single_cell_report('p','v','b'*64,manifest,dict(source_files=[]),[],library_algorithms=[outcome])
    doc=Document(io.BytesIO(content));text='\n'.join(p.text for p in doc.paragraphs)+'\n'+'\n'.join(c.text for t in doc.tables for r in t.rows for c in r.cells)
    assert all(v in text for v in ('L1','80','2','23','0.1'))
    assert '预测双细胞' in text and '排除细胞' in text


@pytest.mark.parametrize('language,label',[('zh-CN','计算内存不足'),('en','Insufficient computation memory')])
def test_word_allocation_failure_reason_is_readable(language,label):
    from app.adapters.single_cell_report import build_single_cell_report
    state=dict(status='failed',reason='resource_insufficient')
    manifest=dict(assay='single_cell',observation_level='cell',summary=dict(single_cell_algorithms=dict(doublet=dict(status='not_requested'),decontx=state,versions={})),params={},steps=[])
    content=build_single_cell_report('p','v','d'*64,manifest,dict(source_files=[]),[],language,library_algorithms=[dict(library_id='L1',algorithm='decontx',**state)])
    doc=Document(io.BytesIO(content));text='\n'.join(p.text for p in doc.paragraphs)+'\n'+'\n'.join(c.text for t in doc.tables for r in t.rows for c in r.cells)
    assert label in text and 'resource_insufficient' in text


def test_word_reuses_same_language_processed_marker_pages_with_selection(monkeypatch):
    from app.adapters.single_cell_report import _latest_marker_report_figures
    import app.adapters.bio_figure_store as module
    calls=[]
    class Cursor:
        def fetchone(self):return {'id':'saved-figure'}
    class DB:
        def execute(self,sql,params):
            calls.append((sql,params));return Cursor()
    class Figures:
        def __init__(self,assets):pass
        def get(self,project,identifier):
            return dict(id=identifier,config=dict(gene_ids=['ENSG1'],palette='magma',layer='log1p'),members=[dict(id='page2',key='marker_dotplot_page_2_png',format='png',sha256='a'*64),dict(id='page1',key='marker_dotplot_png',format='png',sha256='a'*64),dict(id='data',key='marker_data',format='json')])
        def member(self,*args):return {},b'preserved-png'
    monkeypatch.setattr(module,'BioFigureStore',Figures)
    figures=_latest_marker_report_figures(object(),DB(),'project','fixed-processed','en')
    assert len(figures)==4 and all(f['content']==b'preserved-png' for k,f in figures)
    assert 'marker_dotplot_png' in figures[0][1]['config']['caption']
    assert 'marker_dotplot_page_2_png' in figures[1][1]['config']['caption']
    assert all(params[:2]==('project','fixed-processed') and params[-1]=='en' for sql,params in calls)
    assert all('manifest_sha256 IS NOT NULL' in sql for sql,params in calls)
    assert all(all(text in f['config']['caption'] for text in ('saved-figure','Selected 1','marker_dotplot','magma','a'*64)) for k,f in figures)


def test_marker_pages_natural_order_for_default_and_standalone():
    from app.adapters.single_cell_report import _marker_page_order
    keys=['marker_heatmap_page_10_png','marker_dotplot_page_2_png','marker_heatmap_png','marker_dotplot_png','marker_heatmap_page_2_png']
    assert [m['key'] for m in sorted([{'key':k} for k in keys],key=_marker_page_order)]==[
        'marker_dotplot_png','marker_dotplot_page_2_png','marker_heatmap_png','marker_heatmap_page_2_png','marker_heatmap_page_10_png']
