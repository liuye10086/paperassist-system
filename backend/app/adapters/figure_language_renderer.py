"""Frozen boxplot statistics only. Never execute model code or re-estimate data."""
from decimal import Decimal, localcontext
from hashlib import sha256
from io import BytesIO
import json
import math
import os
from pathlib import Path
import re

from PIL import Image, ImageDraw, ImageFont
from app.core.exceptions import StorageError
from app.domain.literature.service import digest

LEGACY_RENDERER_VERSION='paperassist_horizontal_boxplot_language_v1'
RENDERER_VERSION='paperassist_horizontal_boxplot_language_v2'
SUPPORT_SCOPE='Frozen openai_boxplot_v1 only; independent local horizontal redraw, not original pixel layout.'
FIGURE_SIGNS=str.maketrans({'−':'-','－':'-','﹣':'-','＋':'+','﹢':'+'})
FIGURE_MARKERS=re.compile(r'(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][-+]?\d+)?|[-+±∓]')


def numeric_markers(text):
    # Normalize only the explicitly supported equivalent signs for comparison.
    # Keep standalone signs too: Q3−Q1 and a spaced − 5 must not lose a minus.
    # Display strings are never normalized. Hyphens are conservatively protected.
    return FIGURE_MARKERS.findall(text.translate(FIGURE_SIGNS))


def rejected(message):
    return StorageError('figure_language_unsupported',message,422)


def text_item(location,text):
    return dict(location=location,text=text,sha256=sha256(text.encode('utf-8')).hexdigest())


def locked_fonts():
    root=Path(os.environ.get('PAPERASSIST_PDF_FONTS_DIR') or ('C:/Windows/Fonts' if os.name=='nt' else '/usr/local/share/fonts/paperassist'))
    lock=json.loads(Path(__file__).with_name('pdf_renderer_lock.json').read_text())['fonts']
    fonts={};hashes={}
    for name in ('arial.ttf','simsun.ttc'):
        try:
            raw=(root/name).read_bytes()
            if sha256(raw).hexdigest()!=lock[name]: raise ValueError('hash')
            # Load the verified bytes, avoiding a font path time-of-check/time-of-use gap.
            fonts[name]=ImageFont.truetype(BytesIO(raw),30,layout_engine=ImageFont.Layout.BASIC)
            hashes[name]=lock[name]
        except (OSError,ValueError) as exc:
            raise rejected('固定字体缺失或字体SHA不匹配，无法重绘。') from exc
    return fonts,hashes


def render_boxplot(source,texts,output_language,*,renderer_version=RENDERER_VERSION):
    if renderer_version not in (LEGACY_RENDERER_VERSION,RENDERER_VERSION):
        raise rejected('图件语言渲染版本不受支持。')
    if source.get('engine',{}).get('id')!='openai_boxplot_v1' or output_language not in ('en','zh-CN'):
        raise rejected('仅支持已冻结的 openai_boxplot_v1 横向箱线图。')
    series=source.get('series')
    if not isinstance(series,list) or not 1<=len(series)<=8:
        raise rejected('本地重绘仅支持1至8个已冻结分组。')
    if set(texts)!={'title','x_label','y_label','caption','series'} or not isinstance(texts['series'],list) or len(texts['series'])!=len(series):
        raise rejected('必须逐项提供标题、坐标轴、图注及全部分组的目标文字。')
    all_text=[texts[k] for k in ('title','x_label','y_label','caption')]+texts['series']
    if any(not isinstance(t,str) or not t.strip() or len(t)>2000 or any(ord(c)<32 for c in t) for t in all_text):
        raise rejected('目标文字为空、过长或包含不支持的控制字符。')
    original_text=[source.get(k) for k in ('title','x_label','y_label','caption')]+[entry.get('label') for entry in series]
    if any(not isinstance(text,str) for text in original_text): raise rejected('原始图文字字段不完整，无法核验数值对应。')
    if any(numeric_markers(old)!=numeric_markers(new) for old,new in zip(original_text,all_text)):
        raise rejected('语言重绘必须逐字段保持原始标题、轴名、图注和分组标签的精确数值标记。')
    numeric=[]
    for entry in series:
        keys={'n','q1','median','q3','whislo','whishi','fliers','outlier_count'}
        if set(entry)!=(keys|{'label'}): raise rejected('冻结series结构不受支持。')
        if type(entry['n']) is not int or entry['n']<1 or type(entry['outlier_count']) is not int or not 0<=entry['outlier_count']<=entry['n']:
            raise rejected('冻结样本量无效。')
        if not isinstance(entry['fliers'],list) or len(entry['fliers'])>10000: raise rejected('冻结离群点无效。')
        values=[entry[k] for k in ('whislo','q1','median','q3','whishi')]
        if any(type(v) not in (int,float) or not math.isfinite(v) for v in values+entry['fliers']) or values!=sorted(values):
            raise rejected('冻结坐标无效或不是有限数值。')
        if (entry['fliers']!=sorted(set(entry['fliers'])) or len(entry['fliers'])>entry['outlier_count']
                or any(entry['whislo']<=value<=entry['whishi'] for value in entry['fliers'])):
            raise rejected('冻结离群点标记无效。')
        numeric.append({k:entry[k] for k in sorted(keys)})
    fonts,hashes=locked_fonts()
    def font_for(char):
        order=('arial.ttf','simsun.ttc') if ord(char)<128 else ('simsun.ttc','arial.ttf')
        for name in order:
            font=fonts[name]
            if char.isspace() or bytes(font.getmask(char))!=bytes(font.getmask('\U0010ffff')): return font
        raise rejected('固定字体不支持图内某些字符。')
    for text in all_text:
        for char in text: font_for(char)
    image=Image.new('RGB',(1800,1200),'white');draw=ImageDraw.Draw(image)
    manifest=[]
    def write(location,text,x,y,width,max_lines=1):
        manifest.append(text_item(location,text));line=0;cursor=x
        for char in text:
            font=font_for(char);advance=font.getlength(char)
            if cursor+advance>x+width:
                line+=1;cursor=x
                if line>=max_lines: raise rejected('目标文字超出固定画布，请缩短后重试。')
            draw.text((cursor,y+line*38),char,font=font,fill='#202b38');cursor+=advance
    write('title',texts['title'],100,36,1600,2)
    write('y_label',texts['y_label'],65,145,340,1)
    write('x_label',texts['x_label'],450,945,1200,1)
    write('caption',texts['caption'],100,1020,1600,4)
    all_values=[Decimal(str(e[k])) for e in series for k in ('whislo','whishi')]+[Decimal(str(v)) for e in series for v in e['fliers']]
    with localcontext() as ctx:
        ctx.prec=80
        lo=min(all_values);hi=max(all_values);span=hi-lo
        if span==0: span=max(abs(lo)*Decimal('.1'),Decimal(1))
        lo-=span*Decimal('.05');hi+=span*Decimal('.05');span=hi-lo
        def point(value): return round(450+float((Decimal(str(value))-lo)/span)*1200,6)
        ticks=[lo+span*Decimal(i)/5 for i in range(6)]
        # Increase precision until every displayed tick is ordered and its rounding
        # error is at most one percent of a tick interval. Fixed-width drawing
        # below rejects labels that cannot fit; it never silently rounds them back.
        step=span/5
        for precision in range(5,81):
            tick_labels=[format(tick,f'.{precision}g') for tick in ticks]
            shown=[Decimal(label) for label in tick_labels]
            if all(a<b for a,b in zip(shown,shown[1:])) and all(abs(a-b)<=step/100 for a,b in zip(shown,ticks)): break
        else: raise rejected('固定画布无法准确区分坐标刻度，请选择其他图表处理路径。')
        draw.line((450,880,1650,880),fill='black',width=3)
        for index,tick in enumerate(ticks):
            x=450+index*240;draw.line((x,880,x,890),fill='black',width=2)
            label=tick_labels[index]
            left=x-110
            if renderer_version==RENDERER_VERSION:
                # Match write()'s actual per-character fallback font and advances.
                width=sum(font_for(char).getlength(char) for char in label)
                if width>220: raise rejected('目标文字超出固定画布，请缩短后重试。')
                left=x-width/2
            write('tick.'+str(index),label,left,900,220)
        positions=[]
        for index,e in enumerate(series):
            y=220+(index+.5)*620/len(series)
            coords={k:point(e[k]) for k in ('q1','median','q3','whislo','whishi')}
            positions.append(dict(index=index,y=y,coordinates=coords,fliers=[point(v) for v in e['fliers']],n=e['n'],outlier_count=e['outlier_count']))
            draw.line((coords['whislo'],y,coords['whishi'],y),fill='#243e55',width=3)
            for k in ('whislo','whishi'): draw.line((coords[k],y-18,coords[k],y+18),fill='#243e55',width=3)
            draw.rectangle((coords['q1'],y-24,coords['q3'],y+24),fill='#d8e8f0',outline='#243e55',width=3)
            draw.line((coords['median'],y-24,coords['median'],y+24),fill='#993d30',width=4)
            for value in e['fliers']:
                x=point(value);draw.ellipse((x-5,y-5,x+5,y+5),outline='#243e55',width=2)
            write('series.'+str(index),texts['series'][index],60,y-36,350,1)
            write('sample_count.'+str(index),'n = '+str(e['n']),60,y+3,350,1)
        geometry=dict(canvas=[1800,1200],plot=[450,220,1650,880],orientation='horizontal',
            # Geometry algorithm is still v1; text-only alignment must not change its fingerprint.
            axis=[str(lo),str(hi)],positions=positions,renderer_version=LEGACY_RENDERER_VERSION)
    buffer=BytesIO();image.save(buffer,format='PNG',optimize=False,compress_level=9)
    return dict(png=buffer.getvalue(),text_manifest=manifest,data_fingerprint=digest(numeric),geometry_fingerprint=digest(geometry),
        geometry=geometry,frozen_series=series,renderer_version=renderer_version,font_hashes=hashes,support_scope=SUPPORT_SCOPE)
