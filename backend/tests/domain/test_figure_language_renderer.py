"""Offline deterministic language redrawing keeps horizontal frozen coordinates."""
import copy
import importlib.util
from hashlib import sha256

import pytest


def renderer():
    assert importlib.util.find_spec('app.adapters.figure_language_renderer'), 'Local language renderer is missing'
    from app.adapters.figure_language_renderer import render_boxplot
    return render_boxplot


def frozen():
    return dict(engine={'id':'openai_boxplot_v1'}, title='合成研究',x_label='数值',y_label='组别',caption='合成观测',series=[
        dict(label='对照组', n=4, q1=1.75, median=2.5, q3=3.25, whislo=1, whishi=4, fliers=[], outlier_count=0),
        dict(label='实验组', n=4, q1=2.75, median=3.5, q3=4.25, whislo=2, whishi=5, fliers=[], outlier_count=0)])


def labels(en=True):
    return dict(title='Synthetic study' if en else '合成研究', x_label='Value' if en else '数值',
        y_label='Group' if en else '组别', caption='Synthetic observations' if en else '合成观测',
        series=['Group A','Group B'] if en else ['组A','组B'])


def test_translated_images_preserve_frozen_numbers_geometry_and_sample_counts():
    fn=renderer(); source=frozen(); original=copy.deepcopy(source)
    en=fn(source,labels(), 'en'); zh=fn(source,labels(False), 'zh-CN')
    assert source==original
    assert en['data_fingerprint']==zh['data_fingerprint']
    assert en['geometry_fingerprint']==zh['geometry_fingerprint']
    assert en['geometry']['orientation']=='horizontal'
    assert en['png']==fn(source,labels(),'en')['png']
    assert sha256(en['png']).hexdigest()!=sha256(zh['png']).hexdigest()
    assert [t['text'] for t in en['text_manifest'] if t['location'].startswith('sample_count.')]==['n = 4','n = 4']


def test_renderer_rejects_unknown_type_missing_labels_and_changed_font(tmp_path,monkeypatch):
    from app.core.exceptions import StorageError
    fn=renderer(); source=frozen();source['engine']['id']='unknown'
    with pytest.raises(StorageError): fn(source,labels(),'en')
    with pytest.raises(StorageError): fn(frozen(),labels()|{'series':['only one']},'en')
    monkeypatch.setenv('PAPERASSIST_PDF_FONTS_DIR',str(tmp_path))
    with pytest.raises(StorageError,match='字体'): fn(frozen(),labels(),'en')
    (tmp_path/'arial.ttf').write_bytes(b'changed')
    (tmp_path/'simsun.ttc').write_bytes(b'changed')
    with pytest.raises(StorageError,match='字体'): fn(frozen(),labels(),'en')


def test_outliers_and_group_order_use_identical_horizontal_coordinates():
    source=frozen();source['series'][0].update(n=6,fliers=[0,6],outlier_count=2)
    en=renderer()(source,labels(),'en');zh=renderer()(source,labels(False),'zh-CN')
    first,second=en['geometry']['positions']
    assert first['y']<second['y']
    assert first['fliers'][0]<first['coordinates']['whislo']<first['coordinates']['q1']<first['coordinates']['median']<first['coordinates']['q3']<first['coordinates']['whishi']<first['fliers'][1]
    assert first['n']==6 and first['outlier_count']==2
    assert en['geometry']==zh['geometry']
    assert en['frozen_series']==source['series']


def test_interior_outlier_is_rejected():
    from app.core.exceptions import StorageError
    source=frozen();source['series'][0].update(fliers=[2],outlier_count=1)
    with pytest.raises(StorageError): renderer()(source,labels(),'en')

@pytest.mark.parametrize('field',['title','x_label','y_label','caption','series'])
def test_language_redraw_rejects_changed_scientific_numbers_in_each_label(field):
    from app.core.exceptions import StorageError
    source=frozen();source.update(title='Trial at 5 mg',x_label='Time 7 days',y_label='Dose 5 mg',caption='Outcome after 7 days')
    source['series'][0]['label']='Dose 5 mg'
    target=dict(title='Trial at 5 mg',x_label='Time 7 days',y_label='Dose 5 mg',caption='Outcome after 7 days',series=['Dose 5 mg','Group B'])
    if field=='series': target['series'][0]='Dose 50 mg'
    else: target[field]=target[field].replace('5','50').replace('7','70')
    with pytest.raises(StorageError,match='数值'): renderer()(source,target,'en')


def test_large_offset_narrow_axis_has_distinct_accurate_ticks():
    from decimal import Decimal
    source=frozen()
    for group in source['series']:
        for key in ('q1','median','q3','whislo','whishi'): group[key]=1000000+group[key]/1000
    result=renderer()(source,labels(),'en')
    tick_text=[item['text'] for item in result['text_manifest'] if item['location'].startswith('tick.')]
    values=list(map(Decimal,tick_text));lo,hi=map(Decimal,result['geometry']['axis']);step=(hi-lo)/5
    assert len(set(values))==6 and values==sorted(values)
    assert all(abs(value-(lo+step*i))<=step/100 for i,value in enumerate(values))


def test_tick_precision_that_cannot_fit_fixed_canvas_is_rejected():
    from app.core.exceptions import StorageError
    source=frozen()
    for group in source['series']:
        for key in ('q1','median','q3','whislo','whishi'): group[key]=1000000000000+group[key]/1000
    with pytest.raises(StorageError,match='画布'): renderer()(source,labels(),'en')


def test_exact_label_numbers_are_preserved_in_translation_not_reassigned_between_groups():
    from app.core.exceptions import StorageError
    source=frozen();source.update(title='研究 5 mg',x_label='时间 7 天',y_label='第 2 次',caption='5 mg，7 天，n=4')
    source['series'][0]['label']='组 5 mg';source['series'][1]['label']='组 10 mg'
    target=dict(title='Study 5 mg',x_label='Time 7 days',y_label='Visit 2',caption='5 mg, 7 days, n=4',series=['Group 5 mg','Group 10 mg'])
    result=renderer()(source,target,'en')
    assert any(entry['text']=='5 mg, 7 days, n=4' for entry in result['text_manifest'])
    target['series'].reverse()
    with pytest.raises(StorageError,match='数值'): renderer()(source,target,'en')


def test_locked_font_fallback_preserves_mathematical_minus_and_rejects_missing_glyph():
    from app.core.exceptions import StorageError
    source=frozen();source['caption']='Q1−1.5×IQR'
    target=labels()|{'caption':source['caption']}
    result=renderer()(source,target,'en')
    assert next(item['text'] for item in result['text_manifest'] if item['location']=='caption')==source['caption']
    target['caption']+='\U0010ffff'
    with pytest.raises(StorageError,match='字符'):renderer()(source,target,'en')


@pytest.mark.parametrize('sign',['−','－','﹣'])
@pytest.mark.parametrize('replacement',['','+','＋','﹢'])
def test_mathematical_negative_sign_cannot_be_deleted_or_reversed(sign,replacement):
    from app.core.exceptions import StorageError
    source=frozen();source['title']='Temperature '+sign+'5 °C'
    target=labels()|{'title':'Temperature '+replacement+'5 °C'}
    with pytest.raises(StorageError,match='数值'):renderer()(source,target,'en')


@pytest.mark.parametrize('original,target',[('−5','−5'),('−5','-5'),('-5','−5'),('－5','-5'),('﹣5','-5'),('＋5','+5'),('﹢5','+5'),('− 5','-5')])
def test_supported_equivalent_signs_preserve_numbers_and_display_string(original,target):
    source=frozen();source['title']='Temperature '+original+' °C'
    translated=labels()|{'title':'Temperature '+target+' °C'}
    result=renderer()(source,translated,'en')
    assert result['text_manifest'][0]['text']==translated['title']


@pytest.mark.parametrize('large_offset',[False,True])
def test_tick_glyph_advances_are_centered_on_axis_marks_without_clipping(monkeypatch,large_offset):
    from PIL import ImageDraw
    source=frozen()
    if large_offset:
        for group in source['series']:
            for key in ('q1','median','q3','whislo','whishi'): group[key]=1000000+group[key]/1000
    calls=[];original=ImageDraw.ImageDraw.text
    def record(self,xy,text,*args,**kwargs):
        if xy[1]==900: calls.append((xy[0],text,kwargs['font'].getlength(text)))
        return original(self,xy,text,*args,**kwargs)
    monkeypatch.setattr(ImageDraw.ImageDraw,'text',record)
    result=renderer()(source,labels(),'en')
    ticks=[item['text'] for item in result['text_manifest'] if item['location'].startswith('tick.')]
    offset=0
    for index,label in enumerate(ticks):
        glyphs=calls[offset:offset+len(label)];offset+=len(label)
        assert ''.join(char for _,char,_ in glyphs)==label
        left=glyphs[0][0];right=glyphs[-1][0]+glyphs[-1][2];axis_x=450+index*240
        assert (left+right)/2==pytest.approx(axis_x,abs=0.01)
        assert left>=axis_x-110 and right<=axis_x+110
    assert offset==len(calls)


def test_renderer_v2_centers_only_text_and_keeps_legacy_geometry_and_png_replay():
    from app.adapters.figure_language_renderer import render_boxplot
    from app.core.exceptions import StorageError
    source=frozen();old=render_boxplot(source,labels(),'en',renderer_version='paperassist_horizontal_boxplot_language_v1')
    new=render_boxplot(source,labels(),'en')
    assert new['renderer_version']=='paperassist_horizontal_boxplot_language_v2'
    assert old['renderer_version']=='paperassist_horizontal_boxplot_language_v1'
    # Captured before this fix using the existing locked font hashes and v1 renderer.
    assert sha256(old['png']).hexdigest()=='53b4afba276e2f45166490a09107bdf855664cc121f6f0c4181a851fc05d696c'
    for field in ('geometry','geometry_fingerprint','data_fingerprint','frozen_series','text_manifest','font_hashes'):
        assert new[field]==old[field]
    assert new['png']!=old['png']
    assert old==render_boxplot(source,labels(),'en',renderer_version='paperassist_horizontal_boxplot_language_v1')
    with pytest.raises(StorageError): render_boxplot(source,labels(),'en',renderer_version='unknown')
