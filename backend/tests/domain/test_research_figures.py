import hashlib
import io
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image


def raster(size, color):
    stream=io.BytesIO();Image.new('RGB',size,color).save(stream,'PNG');return stream.getvalue()


def test_asymmetric_panels_keep_order_ratio_and_original_dpi(tmp_path):
    from app.adapters.research_figure_render import render_figure
    panels=[]
    for index,(size,color) in enumerate([((300,100),'red'),((100,300),'blue')]):
        value=raster(size,color);path=tmp_path/f'in{index}.png';path.write_bytes(value)
        panels.append(dict(path=str(path),sha256=hashlib.sha256(value).hexdigest(),label=chr(65+index),source={'source_id':str(index)}))
    out=tmp_path/'out';out.mkdir()
    result=render_figure(dict(config={'mode':'composite','columns':2,'width_mm':85.0,'dpi':150,'formats':['png','svg','tiff'],'margin_mm':3.0},panels=panels),out)
    manifest=result['manifest'];a,b=manifest['panels']
    assert a['source']['source_id']=='0' and b['source']['source_id']=='1'
    assert a['box'][2]/a['box'][3]==pytest.approx(3,rel=.02)
    assert b['box'][2]/b['box'][3]==pytest.approx(1/3,rel=.02)
    assert a['effective_dpi']<=150 and b['effective_dpi']<=150
    assert manifest['bitmap_panel_content_editable'] is False
    assert {x['format'] for x in result['outputs']}>={'png','svg','tiff','py','json'}
    assert (out/'original_1.png').read_bytes()==Path(panels[0]['path']).read_bytes()
    with Image.open(out/'figure_png.png') as image:
        x,y,w,h=a['box'];assert image.getpixel((x+w//2,y+h//2))[:3]==(255,0,0)
        x,y,w,h=b['box'];assert image.getpixel((x+w//2,y+h//2))[:3]==(0,0,255)


def test_tiff_first_page_renders_without_reserializing_the_original(tmp_path):
    from app.adapters.research_figure_render import render_figure, validate_figure_result
    from app.domain.research_results.figure_members import image_metadata

    stream = io.BytesIO()
    Image.new('RGB', (40, 20), 'blue').save(stream, 'TIFF', save_all=True,
        append_images=[Image.new('RGB', (20, 40), 'yellow')])
    raw = stream.getvalue()
    source = tmp_path / 'source.tif'
    source.write_bytes(raw)
    output = tmp_path / 'output'
    output.mkdir()
    config = dict(mode='reuse', columns=1, width_mm=85.0, dpi=150, formats=['png'])
    panel = dict(path=str(source), sha256=hashlib.sha256(raw).hexdigest(), label='A', source={}, format='tiff')
    payload = dict(config=config, panels=[panel])
    result = render_figure(payload, output)
    validate_figure_result(payload, result, output)
    assert image_metadata(raw) == dict(format='tiff', width=40, height=20)
    assert (output / 'original_1.tiff').read_bytes() == raw
    assert result['manifest']['panels'][0]['original_pixels'] == [40, 20]
    with Image.open(output / 'figure_png.png') as image:
        x, y, width, height = result['manifest']['panels'][0]['box']
        assert image.getpixel((x + width // 2, y + height // 2)) == (0, 0, 255)


def test_tiff_16_bit_grayscale_retains_midtones_in_png_composition(tmp_path):
    from app.adapters.research_figure_render import render_figure

    source = tmp_path / 'grayscale.tiff'
    Image.new('I;16', (40, 20), 32768).save(source, 'TIFF')
    raw = source.read_bytes()
    output = tmp_path / 'output'
    output.mkdir()
    config = dict(mode='reuse', columns=1, width_mm=85.0, dpi=150, formats=['png'])
    panel = dict(path=str(source), sha256=hashlib.sha256(raw).hexdigest(), source={}, format='tiff')
    result = render_figure(dict(config=config, panels=[panel]), output)
    assert (output / 'original_1.tiff').read_bytes() == raw
    with Image.open(output / 'figure_png.png') as image:
        x, y, width, height = result['manifest']['panels'][0]['box']
        assert image.getpixel((x + width // 2, y + height // 2)) == (127, 127, 127)


def test_source_tamper_and_output_overlimit_fail_before_publication(tmp_path):
    from app.adapters.research_figure_render import render_figure
    path=tmp_path/'input.png';value=raster((10,1000),'red');path.write_bytes(value)
    payload=dict(config={'mode':'reuse','width_mm':240.0,'dpi':600,'formats':['png'],'margin_mm':0.0},panels=[dict(path=str(path),sha256=hashlib.sha256(value).hexdigest(),source={})])
    with pytest.raises(ValueError,match='limit'):render_figure(payload,tmp_path)
    payload['panels'][0]['sha256']='0'*64
    with pytest.raises(ValueError,match='integrity'):render_figure(payload,tmp_path)


def test_renderer_output_properties_and_rebuild_are_checked_independently(tmp_path,monkeypatch):
    from app.adapters.research_figure_render import render_figure,validate_figure_result
    raw=raster((100,50),'green');path=tmp_path/'input.png';path.write_bytes(raw);out=tmp_path/'out';out.mkdir()
    panel=dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest(),source={'source_id':'fixed'})
    payload=dict(config={'mode':'composite','columns':1,'width_mm':85.0,'dpi':150,'formats':['png','tiff','svg'],'margin_mm':3.0},panels=[panel,panel])
    result=render_figure(payload,out)
    assert [p['label'] for p in result['manifest']['panels']]==['A','B']
    validate_figure_result(payload,result,out)
    again=tmp_path/'again';again.mkdir();rebuilt=render_figure(payload,again)
    assert {m['key']:m['sha256'] for m in result['outputs']}=={m['key']:m['sha256'] for m in rebuilt['outputs']}
    result['manifest']['width_pixels']+=1
    with pytest.raises(ValueError):validate_figure_result(payload,result,out)


def test_long_panel_label_cannot_overflow_a_narrow_column(tmp_path):
    from app.adapters.research_figure_render import render_figure
    raw=raster((10,10),'red');path=tmp_path/'in.png';path.write_bytes(raw)
    panel=dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest(),source={},label='ABCDEFGH')
    payload=dict(config={'mode':'composite','columns':3,'width_mm':85.0,'dpi':150,'formats':['png'],
        'margin_mm':20.0,'font_size_pt':24},panels=[panel,{**panel,'label':'IJKLMNOP'},{**panel,'label':'QRSTUVWX'}])
    with pytest.raises(ValueError,match='label'):render_figure(payload,tmp_path)


def test_completed_latest_figure_rejects_an_older_edit_base(monkeypatch):
    from app.core.exceptions import StorageError
    from app.domain.research_results.figures import ResearchFigureService

    entrypoint = 'sci_figures'
    parent = dict(id='version2', revision=2, task_id='task2')
    task = dict(task_type='research_figure', input_snapshot={'entrypoint': entrypoint}, status='succeeded')
    rows = iter((None, parent))
    db = SimpleNamespace(execute=lambda *_: SimpleNamespace(fetchone=lambda: next(rows)))
    service = ResearchFigureService(SimpleNamespace(owner_id='owner', db_config=object()), entrypoint=entrypoint)
    monkeypatch.setattr(service, 'lock', lambda *_: None)
    monkeypatch.setattr(service.store, 'connection', lambda **_: nullcontext(db))
    monkeypatch.setattr(service.store, 'require_task', lambda *_: task)
    request = dict(title='Stale edit', mode='reuse', root_id='root', expected_revision=parent['revision'],
                   panels=[dict(source=dict(source_kind='original_file', source_id='file'))])

    with pytest.raises(StorageError) as conflict:
        service.create('project', request, 'stale-edit', base_revision=1)

    assert (conflict.value.status, conflict.value.code) == (409, 'research_revision_conflict')


def test_retired_figure_renderer_exposes_a_permanent_public_error(tmp_path, monkeypatch):
    from app.adapters.research_figure_render import renderer_identity
    from app.core.errors import error_detail
    from app.core.exceptions import StorageError
    from app.domain.bioinformatics.contracts import digest
    from app.domain.research_results import figures
    from app.domain.research_results.execution import recovery_actions

    config = dict(mode='reuse', panels=[dict(source=dict(source_kind='original_file', source_id='file'))])
    snapshot = dict(kind='research_figure', project_id='project', figure_version_id='figure', config=config,
                    renderer_identity={**renderer_identity(), 'code_digest': '0' * 64},
                    real_model_calls=False, real_network_calls=False)
    task = dict(id='task', task_type='research_figure', project_id='project', status='running',
                workflow_version='research_figure_v1', input_snapshot=snapshot, input_digest=digest(snapshot))
    row = dict(task_id='task', config_json=config, config_sha256=digest(config))
    service = figures.ResearchFigureService(SimpleNamespace(owner_id='owner', db_config=object(), directory=tmp_path))
    monkeypatch.setattr(service, 'require', lambda *_: row)
    monkeypatch.setattr(figures, 'VerificationPhase', lambda *_: nullcontext())
    monkeypatch.setattr(figures, 'require_phase', lambda *_: None)

    with pytest.raises(StorageError) as error:
        service.require_sources(None, task)

    assert error.value.status == 409
    detail = error_detail(error.value.code, error.value.message, error.value.params)
    assert detail == dict(code='research_figure_renderer_retired',
                          message='此图件任务使用的旧版绘图流程已停用。请使用当前流程新建图件。', params={})
    assert recovery_actions(None, {**task, 'status': 'failed', 'error_code': detail['code']}) == []
    assert digest(snapshot) == task['input_digest']
