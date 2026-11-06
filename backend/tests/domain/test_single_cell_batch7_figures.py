import pytest
import matplotlib
matplotlib.use("Agg")
from app.domain.bio_insights.contracts import FigureConfig

@pytest.mark.parametrize('method',['slingshot','genie3','cellchat'])
def test_saved_topic_figure_contract(method):
    config=FigureConfig(result_source_id='r',figure_type='topic_'+method,formats=['png'])
    assert config.model_dump()['figure_type']=='topic_'+method

@pytest.mark.parametrize('option',[{'processed_source_id':'p'},{'contrast_id':'c'},{'expression_groups':[{'label':'x','observation_keys':[]}]}])
def test_topic_figure_rejects_analysis_inputs(option):
    with pytest.raises(ValueError,match='topic_figure_uses_saved_values_only'):
        FigureConfig(result_source_id='r',figure_type='topic_cellchat',**option)

@pytest.fixture(autouse=True)
def postgres_schema():
    yield None

def test_cellchat_saved_zero_and_high_values_have_valid_scale_and_contrast(tmp_path):
    import json
    from matplotlib import pyplot as plt
    from app.adapters.bio_insights_engine.topic_figures import draw_topic
    for values in ([0.,0.],[0.,2.]):
        data=dict(method='cellchat',labels=['A','B'],label_names={},rows=[dict(sender='A',receiver=r,unit_id='d',probability=v) for r,v in zip(['A','B'],values)])
        path=tmp_path/'plot.json';path.write_text(json.dumps(data))
        source=dict(source_id='r',sha256='a'*64,metadata=dict(kind='integration',plan_config=dict(schema_version=2,method='cellchat')),members={'topic_plot_data':{'path':str(path),'size_bytes':path.stat().st_size,'sha256':__import__('hashlib').sha256(path.read_bytes()).hexdigest()}})
        fig,ax=plt.subplots()
        try:
            plotted,empty=draw_topic(fig,ax,source,FigureConfig(result_source_id='r',figure_type='topic_cellchat'),False)
            assert not empty and plotted['analysis_recomputed'] is False
            assert ax.images[0].norm.vmin==0 and ax.images[0].norm.vmax>0
            assert min(fig.axes[1].get_yticks())>=0
            assert ax.texts[0].get_color()=='white'
            if max(values)>0:assert ax.texts[1].get_color()=='black'
            assert json.loads(path.read_text())==data
        finally:plt.close(fig)

def test_word_rejects_figure_from_different_source():
    from app.adapters.single_cell_insight_report import validate_report_figure
    from app.core.exceptions import StorageError
    methods=dict(figure_type='topic_cellchat',source_id='other',source_sha256='a'*64,analysis_recomputed=False)
    with pytest.raises(StorageError):validate_report_figure('r','a'*64,'cellchat',methods)
    methods['source_id']='r'
    validate_report_figure('r','a'*64,'cellchat',methods)
    methods['source_sha256']='b'*64
    with pytest.raises(StorageError):validate_report_figure('r','a'*64,'cellchat',methods)

@pytest.mark.parametrize('method,data',[
 ('slingshot',dict(coordinates=[[0,0],[1,1]],clusters=['0','1'],lineage_ids=['L1'],curves=[[[0,0],[1,1]]],representation='PCA',root='0')),
 ('genie3',dict(rows=[dict(regulator='ENSG1',target='ENSG2',regulator_symbol='TF',target_symbol='G',weight=.25,stability_weight=.3)])),
])
@pytest.mark.parametrize('language',['zh-CN','en'])
def test_all_topic_saved_views_preserve_source_values(tmp_path,method,data,language):
    import json,hashlib
    from matplotlib import pyplot as plt
    from app.adapters.bio_insights_engine.topic_figures import draw_topic
    data=dict(method=method,**data);raw=json.dumps(data).encode();path=tmp_path/'plot.json';path.write_bytes(raw)
    source=dict(source_id='r',sha256='a'*64,metadata=dict(kind='integration',plan_config=dict(schema_version=2,method=method)),members={'topic_plot_data':dict(path=str(path),size_bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())})
    fig,ax=plt.subplots()
    try:
        result,empty=draw_topic(fig,ax,source,FigureConfig(result_source_id='r',figure_type='topic_'+method,output_language=language),language=='zh-CN')
        assert not empty and result['source_id']=='r' and result['source_sha256']=='a'*64
        assert all(result[key]==value for key,value in data.items())
        assert path.read_bytes()==raw
        wrong=FigureConfig(result_source_id='r',figure_type='topic_cellchat')
        with pytest.raises(ValueError,match='topic_figure_source_mismatch'):draw_topic(fig,ax,source,wrong,False)
    finally:plt.close(fig)


def test_word_records_separate_figure_and_saved_source_without_pdf():
    import io,zipfile
    from PIL import Image
    from app.adapters.single_cell_insight_report import build_single_cell_insight_report
    image=io.BytesIO();Image.new('RGB',(80,40),'white').save(image,format='PNG')
    content=build_single_cell_insight_report('r','a'*64,dict(kind='integration',schema_version=2,method='cellchat',output_language='en'),{}, {},
        [dict(key='New figure',sha256='b'*64,content=image.getvalue(),figure_result_id='f',source_result_id='r',source_manifest_sha256='a'*64)])
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        xml=archive.read('word/document.xml').decode()
        assert 'Separately rendered figure result: f' in xml and 'Saved numeric source: r' in xml
        assert 'scientific analysis was not recomputed' in xml
        assert not any(name.endswith('.pdf') for name in archive.namelist())

def test_topic_runs_existing_figure_writer_formats_and_metadata(tmp_path,monkeypatch):
    import json,hashlib
    from pathlib import Path
    from app.adapters.bio_insights_engine import figures
    from app.adapters.bio_engine.manifest import Writer
    font=Path('C:/Windows/Fonts/msyh.ttc')
    if not font.exists():font=Path('/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc')
    if not font.exists():pytest.skip('Chinese render font unavailable')
    monkeypatch.setattr(figures,'Path',lambda path:font if str(path)=='/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc' else Path(path))
    raw=json.dumps(dict(method='cellchat',labels=['A'],label_names={},rows=[dict(sender='A',receiver='A',unit_id='d',probability=0.)])).encode()
    path=tmp_path/'saved.json';path.write_bytes(raw)
    source=dict(source_id='r',sha256='a'*64,metadata=dict(kind='integration',plan_config=dict(schema_version=2,method='cellchat')),members={'topic_plot_data':dict(path=str(path),size_bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())})
    config=FigureConfig(result_source_id='r',figure_type='topic_cellchat',output_language='zh-CN',dpi=100)
    out=tmp_path/'out';out.mkdir();writer=Writer(out)
    result=figures.run_figure(dict(config=config.model_dump(),sources=[source]),writer)
    assert result['methods']['source_id']=='r' and result['methods']['source_sha256']=='a'*64
    assert result['methods']['analysis_recomputed'] is False
    assert {'figure_png','figure_tiff','figure_svg','plot_data','figure_metadata'}=={m['key'] for m in writer.artifacts}
    assert not any(m['format']=='pdf' for m in writer.artifacts)
    assert path.read_bytes()==raw

def test_normal_worker_preloads_topic_renderer_before_landlock():
    """All render modules must load before application reads are denied."""
    import ast
    from pathlib import Path
    import app.adapters.bio_insights_engine as engine
    tree=ast.parse((Path(engine.__file__).parent/'worker.py').read_text(encoding='utf-8'))
    loops=[node for node in ast.walk(tree) if isinstance(node,ast.For) and isinstance(node.iter,ast.Tuple)
           and any(isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and call.func.attr=='import_module' for call in ast.walk(node))]
    assert len(loops)==1
    modules=ast.literal_eval(loops[0].iter)
    assert 'topic_figures' in modules
    enter_calls=[node for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='enter']
    assert len(enter_calls)==1 and loops[0].lineno<enter_calls[0].lineno
