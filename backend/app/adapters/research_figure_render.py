"""Deterministic bitmap composition. No scientific crop, rotation or stretching."""
import base64
import hashlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys

from PIL import Image,ImageDraw,ImageFont


def renderer_identity():
    return dict(renderer_version='research_bitmap_v1',code_digest=hashlib.sha256(Path(__file__).read_bytes()+Path(__file__).with_name('research_figure_child.py').read_bytes()).hexdigest(),
        pillow_version=Image.__version__,limits=dict(timeout_seconds=60,subprocess_memory_bytes=2*1024**3,worker_memory_bytes=4*1024**3,max_edge_pixels=8000,max_pixels=40_000_000))


def label_font(config,panels,cell):
    size=max(1,round(config.get('font_size_pt',10)/72*config['dpi']))
    font=ImageFont.load_default(size=size)
    for i,panel in enumerate(panels):
        label=panel.get('label') or (chr(65+i) if config['mode']=='composite' else '')
        if label:
            left,top,right,bottom=font.getbbox(label,anchor='lt')
            if right-left>cell or bottom-top>size+4:raise ValueError('panel label exceeds its column; reduce margin, font or label length')
    return font


def render_figure(payload,output):
    config=payload['config'];output=Path(output);panels=[dict(p) for p in payload['panels']]
    if config['mode'] not in ('reuse','composite') or not (len(panels)==1 if config['mode']=='reuse' else 2<=len(panels)<=6):raise ValueError('panel limit')
    if config['mode']=='composite':
        used={p.get('label') for p in panels if p.get('label')}
        for index,panel in enumerate(panels):
            if not panel.get('label'):
                proposed=chr(65+index)
                panel['label']=proposed if proposed not in used else next(chr(x) for x in range(65,91) if chr(x) not in used)
                used.add(panel['label'])
    dpi=config['dpi'];columns=min(config.get('columns',2),len(panels))
    if dpi not in (150,300,600) or not 1<=columns<=3 or not 85<=config['width_mm']<=240:raise ValueError('figure limit')
    width=round(config['width_mm']/25.4*dpi);margin=round(config.get('margin_mm',3)/25.4*dpi)
    label_height=round(config.get('font_size_pt',10)/72*dpi)+4 if any(p.get('label') for p in panels) else 0
    cell=(width-(columns+1)*margin)//columns
    if cell<1:raise ValueError('layout limit')
    font=label_font(config,panels,cell)
    images=[];heights=[]
    for panel in panels:
        raw=Path(panel['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=panel['sha256']:raise ValueError('source integrity')
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in ('PNG','JPEG') or max(image.size)>8000 or image.width*image.height>40_000_000:raise ValueError('source limit')
            image.load();images.append((image.convert('RGBA'),raw,image.format,image.size))
            heights.append(max(1,round(cell*image.height/image.width)))
    rows=math.ceil(len(images)/columns);row_heights=[max(heights[i*columns:(i+1)*columns])+label_height for i in range(rows)]
    height=sum(row_heights)+(rows+1)*margin
    if max(width,height)>8000 or width*height>40_000_000:raise ValueError('figure pixel limit')
    canvas=Image.new('RGB',(width,height),config.get('background','#ffffff'));draw=ImageDraw.Draw(canvas)
    # Pillow's bundled default has no host font lookup and its version is frozen.
    outputs=[];descriptors=[]
    def leaf(key,fmt,content,role,properties=None):
        path=output/(key+'.'+fmt);path.write_bytes(content)
        outputs.append(dict(key=key,format=fmt,path=str(path.resolve()),role=role,sha256=hashlib.sha256(content).hexdigest(),size_bytes=len(content),properties=properties or {}))
    for index,((image,raw,fmt,size),panel) in enumerate(zip(images,panels)):
        row,col=divmod(index,columns);x=margin+col*(cell+margin);y=margin+sum(row_heights[:row])+row*margin+label_height
        h=heights[index];resized=image.resize((cell,h),Image.Resampling.LANCZOS);canvas.paste(resized,(x,y),resized)
        if panel.get('label'):draw.text((x,y-label_height),panel['label'],fill='#000000',font=font,anchor='lt')
        detail=panel.get('detail_pixels_per_pixel',1.0)
        if not isinstance(detail,(int,float)) or not 0<detail<=1:raise ValueError('panel detail identity')
        native=size[0]*dpi/cell*detail
        descriptors.append(dict(source=panel['source'],member_key=panel.get('member_key'),sha256=panel['sha256'],label=panel.get('label',''),note=panel.get('note',''),
            original_pixels=list(size),box=[x,y,cell,h],native_effective_dpi=round(native,3),effective_dpi=round(min(dpi,native),3),
            resolution_warning=native<dpi,original_member='original_'+str(index+1)))
        leaf('original_'+str(index+1),'png' if fmt=='PNG' else 'jpeg',raw,'original_panel',descriptors[-1])
    for fmt in config['formats']:
        stream=io.BytesIO()
        if fmt=='svg':
            png=io.BytesIO();canvas.save(png,'PNG',dpi=(dpi,dpi));encoded=base64.b64encode(png.getvalue()).decode('ascii')
            content=(f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{config["width_mm"]}mm" height="{height/dpi*25.4}mm" viewBox="0 0 {width} {height}"><desc>Raster panel content; noneditable scientific bitmap.</desc><image width="{width}" height="{height}" xlink:href="data:image/png;base64,{encoded}"/></svg>').encode()
        else:
            options={'compression':'tiff_lzw'} if fmt=='tiff' else {'creationDate':None,'modDate':None} if fmt=='pdf' else {}
            canvas.save(stream,{'png':'PNG','tiff':'TIFF','pdf':'PDF'}[fmt],dpi=(dpi,dpi),resolution=dpi,**options);content=stream.getvalue()
        leaf('figure_'+fmt,fmt,content,'figure',dict(width_pixels=width,height_pixels=height,dpi=dpi,width_mm=config['width_mm'],height_mm=height/dpi*25.4,
            bitmap_panel_content_editable=False,figure_language=config.get('figure_language','original'),caption_language=config.get('language','zh-CN')))
    manifest=dict(schema_version=1,renderer_version='research_bitmap_v1',config=config,width_pixels=width,height_pixels=height,panels=descriptors,
        bitmap_panel_content_editable=False,real_model_calls=False,real_network_calls=False,scientific_transformations=[],renderer_identity=renderer_identity(),
        caption=config.get('caption',''),caption_origin='user_text',caption_facts=payload.get('caption_facts',[]),
        caption_language=config.get('language','zh-CN'),figure_language=config.get('figure_language','original'),
        language_exception=config.get('figure_language','original') in ('original','unknown') or config.get('figure_language')!=config.get('language','zh-CN'),
        missing_caption_annotations=['n、单位、误差线、方法及统计标注仅以选定 caption_facts 为依据；未绑定内容视为用户未验证文字。'],
        limitations=['原图语言保留；位图 PDF/SVG 的科学面板内容不可编辑。','分辨率按原始像素报告；上采样不增加原图细节。'])
    rebuild=dict(config=config,panels=[{**{k:v for k,v in p.items() if k!='path'},'path':d['original_member']+('.png' if images[i][2]=='PNG' else '.jpeg')} for i,(p,d) in enumerate(zip(panels,descriptors))])
    rebuild.update(renderer_identity=renderer_identity(),caption_facts=payload.get('caption_facts',[]))
    leaf('rebuild_config','json',json.dumps(rebuild,ensure_ascii=False,sort_keys=True).encode(),'rebuild_config')
    script='''# Requires matching PaperAssist source checkout and Pillow. Run beside original panels.\nimport json\nfrom pathlib import Path\nfrom app.adapters.research_figure_render import render_figure, renderer_identity\npayload=json.loads(Path("rebuild_config.json").read_text(encoding="utf-8"))\nassert payload.pop("renderer_identity")==renderer_identity(), "Renderer code or Pillow differs"\nPath("rebuilt").mkdir(exist_ok=True)\nrender_figure(payload,Path("rebuilt"))\n'''
    leaf('rebuild_script','py',script.encode(),'rebuild_script')
    # Compatibility names are kept in the reconstruction config, not duplicate members.
    return dict(manifest=manifest,outputs=outputs)


def execute_research_figure(payload,output):
    """Production subprocess enforces the approved 2 GiB/60 s boundary."""
    from app.core.exceptions import StorageError
    if sys.platform!='linux':raise StorageError('research_environment_unavailable','图件安全渲染需要 Linux Worker。',409)
    command=[sys.executable,'-I','-B',str(Path(__file__).with_name('research_figure_child.py'))]
    try:
        result=subprocess.run(command,input=json.dumps(dict(payload=payload,output=str(output))).encode(),stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,timeout=60,env={},cwd='/',start_new_session=True,check=False)
        if result.returncode or len(result.stdout)>2*1024**2:raise ValueError('render failed')
        value=json.loads(result.stdout);validate_figure_result(payload,value,output);return value
    except subprocess.TimeoutExpired as exc:raise StorageError('research_render_timeout','图件渲染超时。',422) from exc
    except (ValueError,OSError) as exc:raise StorageError('research_output_invalid','图件输出未通过检查。',422) from exc


def validate_figure_result(payload,result,output):
    """Parent-side checks do not trust a child's declared dimensions or member SHA."""
    import xml.etree.ElementTree as ET
    import pdfplumber
    config=payload['config'];manifest=result['manifest'];directory=Path(output).resolve();outputs=result['outputs']
    width=round(config['width_mm']/25.4*config['dpi']);height=manifest['height_pixels']
    if (manifest['config']!=config or manifest['renderer_identity']!=renderer_identity() or manifest['width_pixels']!=width
            or type(height) is not int or not 1<=height<=8000 or max(width,height)>8000 or width*height>40_000_000
            or manifest.get('bitmap_panel_content_editable') is not False
            or len(manifest['panels'])!=len(payload['panels'])):raise ValueError('figure output identity')
    expected={'figure_'+fmt for fmt in config['formats']}|{'original_'+str(i+1) for i in range(len(payload['panels']))}|{'rebuild_config','rebuild_script'}
    if len(outputs)!=len(expected) or {m['key'] for m in outputs}!=expected:raise ValueError('figure output members')
    for item in outputs:
        path=Path(item['path'])
        if not path.is_absolute() or path.is_symlink() or path.resolve().parent!=directory or path.name!=item['key']+'.'+item['format']:raise ValueError('figure output path')
        raw=path.read_bytes()
        if len(raw)!=item['size_bytes'] or hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('figure output integrity')
        if item['key'].startswith('figure_'):
            fmt=item['format']
            if item['key']!='figure_'+fmt or fmt not in config['formats'] or item['role']!='figure':raise ValueError('figure output format')
            if fmt in ('png','tiff'):
                with Image.open(io.BytesIO(raw)) as image:
                    if image.format!={'png':'PNG','tiff':'TIFF'}[fmt] or image.size!=(width,height) or getattr(image,'n_frames',1)!=1:raise ValueError('figure pixel dimensions')
                    stored_dpi=image.info.get('dpi')
                    if not stored_dpi or any(abs(float(d)-config['dpi'])>1 for d in stored_dpi):raise ValueError('figure dpi metadata')
                    image.verify()
            elif fmt=='pdf':
                with pdfplumber.open(io.BytesIO(raw)) as document:
                    if len(document.pages)!=1:raise ValueError('figure PDF pages')
                    page=document.pages[0]
                    if abs(page.width-width/config['dpi']*72)>.1 or abs(page.height-height/config['dpi']*72)>.1:raise ValueError('figure PDF dimensions')
            elif fmt=='svg':
                if b'<!' in raw:raise ValueError('figure SVG declaration')
                root=ET.fromstring(raw)
                if root.tag!='{http://www.w3.org/2000/svg}svg' or root.attrib['viewBox']!=f'0 0 {width} {height}':raise ValueError('figure SVG dimensions')
                images=root.findall('{http://www.w3.org/2000/svg}image')
                if len(images)!=1 or not images[0].attrib.get('{http://www.w3.org/1999/xlink}href','').startswith('data:image/png;base64,'):raise ValueError('figure SVG bitmap')
        elif item['key'].startswith('original_'):
            index=int(item['key'].split('_')[1])-1
            if item['sha256']!=payload['panels'][index]['sha256'] or item['role']!='original_panel':raise ValueError('original panel identity')
    for panel,source in zip(manifest['panels'],payload['panels']):
        if panel['source']!=source['source'] or panel['sha256']!=source['sha256']:raise ValueError('panel source identity')
        x,y,w,h=panel['box'];ow,oh=panel['original_pixels']
        if not all(type(v) is int for v in (x,y,w,h,ow,oh)) or min(w,h,ow,oh)<1 or x<0 or y<0 or x+w>width or y+h>height:raise ValueError('panel bounds')
        if abs(h-w*oh/ow)>1:raise ValueError('panel aspect ratio')
        actual=ow*config['dpi']/w*source.get('detail_pixels_per_pixel',1.0)
        if abs(panel['native_effective_dpi']-actual)>.01 or abs(panel['effective_dpi']-min(config['dpi'],actual))>.01:raise ValueError('panel effective DPI')
    rebuild=json.loads(next(Path(m['path']).read_bytes() for m in outputs if m['key']=='rebuild_config'))
    if rebuild['config']!=config or rebuild['renderer_identity']!=renderer_identity():raise ValueError('rebuild identity')
    if {p.resolve() for p in directory.iterdir()}!={Path(m['path']).resolve() for m in outputs}:raise ValueError('unregistered output')
    return result
