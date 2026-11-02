import hashlib
import io
from pathlib import Path

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
