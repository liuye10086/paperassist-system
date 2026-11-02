"""Read only actual immutable PNG/JPEG members, with owner and byte checks."""
import base64
import hashlib
import io
from PIL import Image
from app.adapters.research_results_store import invalid
from app.adapters.bio_analysis_store import scoped_object
from app.adapters.research_objects import ResearchObjects


def image_metadata(raw):
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in ('PNG','JPEG'):raise ValueError()
            if max(image.size)>8000 or image.width*image.height>40_000_000:raise invalid('research_source_limit_exceeded',422)
            image.verify();return {'format':'png' if image.format=='PNG' else 'jpeg','width':image.width,'height':image.height}
    except (ValueError,OSError,Image.DecompressionBombError) as exc:raise invalid('research_source_unsupported',422) from exc


def read_figure_panel(reader,db,project,panel,*,phase,progress=None,figure_language=None,frozen_panel=None):
    source=reader._read_source_in_phase(project,panel.source,db=db,phase=phase,progress=progress);kind=source.source_kind;quality={}
    if kind=='original_file':
        if panel.member_key is not None:raise invalid('research_locator_invalid',422)
        row=db.execute('SELECT * FROM files WHERE id=%s AND project_id=%s',(source.source_id,project)).fetchone()
        raw=reader.assets.original(dict(row));sha=source.sha256;key=None
    elif kind=='analysis_run':
        if panel.member_key not in (None,'statistics'):raise invalid('research_locator_invalid',422)
        if frozen_panel is None:
            from .statistics_figures import render_statistics_figure
            try:raw=render_statistics_figure(source,language=figure_language)
            except (ValueError,KeyError,TypeError) as exc:raise invalid('research_source_unsupported',422) from exc
            sha=hashlib.sha256(raw).hexdigest()
            record=dict(source_sha256=source.sha256,sha256=sha,size_bytes=len(raw),figure_language=figure_language,png_base64=base64.b64encode(raw).decode())
        else:
            # The task owns these already frozen bytes; source resolution above still checks the live fixed run.
            record=frozen_panel.get('statistics_png')
            try:
                if (type(record) is not dict or set(record)!={'source_sha256','sha256','size_bytes','figure_language','png_base64'}
                    or record['source_sha256']!=source.sha256 or record['figure_language']!=figure_language
                    or type(record['size_bytes']) is not int or not 0<record['size_bytes']<=4*1024**2
                    or type(record['png_base64']) is not str or len(record['png_base64'])>6*1024**2):raise ValueError()
                raw=base64.b64decode(record['png_base64'],validate=True);sha=hashlib.sha256(raw).hexdigest()
                if len(raw)!=record['size_bytes'] or sha!=record['sha256']:raise ValueError()
            except (ValueError,KeyError,TypeError) as exc:raise invalid() from exc
        quality={'statistics_png':record};key='statistics'
    elif kind=='bio_figure_version':
        from app.adapters.bio_figure_store import BioFigureStore
        figures=BioFigureStore(reader.assets);view=source.content['figure']
        available=[m for m in view['members'] if m['format'] in ('png','jpeg') and (panel.member_key is None or m['key']==panel.member_key)]
        if len(available)!=1:raise invalid('research_locator_invalid',422)
        member=available[0]
        row=db.execute('SELECT * FROM bio_figure_members WHERE id=%s AND figure_version_id=%s AND project_id=%s',(member['id'],source.source_id,project)).fetchone()
        if not row:raise invalid()
        record=scoped_object(db,project,reader.store.user_id,row['storage_object_id'])
        if any(record[k]!=member[k] or row[k]!=member[k] for k in ('sha256','size_bytes')):raise invalid()
        raw=figures.reader(record).read(record);sha=member['sha256'];key=member['key']
    elif kind=='research_figure_version':
        saved=source.content['manifest'];source_dpi=saved['config']['dpi']
        # Keep the weakest panel's actual detail through repeated raster reuse.
        ratio=min(1.0,*(float(p['native_effective_dpi'])/source_dpi for p in saved['panels']))
        if not 0<ratio<=1:raise invalid()
        quality={'detail_pixels_per_pixel':ratio}
        members=db.execute("SELECT * FROM research_figure_members WHERE figure_version_id=%s AND project_id=%s AND user_id=%s AND role='figure' AND format IN ('png','jpeg') ORDER BY key",(source.source_id,project,reader.store.user_id)).fetchall()
        available=[m for m in members if panel.member_key is None or m['key']==panel.member_key]
        if len(available)!=1:raise invalid('research_locator_invalid',422)
        member=available[0];obj=scoped_object(db,project,reader.store.user_id,member['storage_object_id'])
        if any(obj[k]!=member[k] for k in ('sha256','size_bytes')):raise invalid()
        raw=ResearchObjects(reader.assets.directory).read(obj);sha=member['sha256'];key=member['key']
    elif kind in ('bio_insight_result_version','bio_insight_result_member'):
        from app.domain.bio_insights.results import BioInsightResultService
        identifier=source.content['result_version_id']
        available=[m for m in source.content['members'] if m['format'] in ('png','jpeg')
            and (panel.member_key is None or m['key']==panel.member_key)
            and (kind!='bio_insight_result_member' or m['id']==source.source_id)]
        if source.content['kind']!='figure' or len(available)!=1:raise invalid('research_locator_invalid',422)
        member=available[0]
        _,raw=BioInsightResultService(reader.assets).member(project,identifier,member['id'])
        sha=member['sha256'];key=member['key']
    else:raise invalid('research_source_unsupported',422)
    if hashlib.sha256(raw).hexdigest()!=sha:raise invalid()
    if progress is not None:progress()
    return source,dict(source=source.model_dump(mode='json'),member_key=key,sha256=sha,label=panel.label,note=panel.note,**image_metadata(raw),**quality),raw


def research_figure_source(reader,db,project,row,*,progress=None):
    """Hook for the generic source reader: verify manifest and every formal member."""
    import json
    objects=ResearchObjects(reader.assets.directory)
    manifest=scoped_object(db,project,reader.store.user_id,row['manifest_object_id'])
    if manifest['sha256']!=row['manifest_sha256']:raise invalid()
    value=json.loads(objects.read(manifest));members=[]
    for member in db.execute('SELECT * FROM research_figure_members WHERE project_id=%s AND figure_version_id=%s AND user_id=%s ORDER BY key',(project,row['id'],reader.store.user_id)):
        if progress is not None:progress()
        obj=scoped_object(db,project,reader.store.user_id,member['storage_object_id'])
        if any(obj[k]!=member[k] for k in ('sha256','size_bytes')):raise invalid()
        objects.read(obj);members.append({k:member[k] for k in ('id','key','format','role','sha256','size_bytes')})
        if progress is not None:progress()
    frozen={m['key']:m for m in value['members']}
    if len(frozen)!=len(value['members']) or {m['key'] for m in members}!=set(frozen):raise invalid()
    if any(any(m[k]!=frozen[m['key']][k] for k in ('id','key','format','role','sha256','size_bytes')) for m in members):raise invalid()
    return dict(manifest=value,members=members)
