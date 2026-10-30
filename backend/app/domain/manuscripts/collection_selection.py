"""Saved collection reports retain every frozen item and all real file references."""
from pydantic import Field
from app.adapters.collection_store import CollectionStore
from app.adapters.task_store import source_conflict
from app.core.exceptions import StorageError
from app.domain.literature.service import digest
from .contracts import Strict
from .sources import read_source
from .analysis_selection import report_text

class CollectionSelectionRequest(Strict):
    collection_id:str=Field(min_length=1,max_length=64)
    collection_version_id:str=Field(min_length=1,max_length=64)
    report_id:str=Field(min_length=1,max_length=64)


def report_source(service,project,file_id,identity):
    repository=CollectionStore(service.assets)
    with service.store.connection() as db:
        service.require_project(db,project)
        row=db.execute('''SELECT r.*,v.collection_id,q.status,q.task_id FROM collection_reports r
            JOIN report_collection_versions v ON v.id=r.version_id JOIN report_collections c ON c.id=v.collection_id
            JOIN report_build_requests q ON q.id=r.build_request_id WHERE r.id=%s AND c.project_id=%s''',(identity,project)).fetchone()
        if not row or row['status']!='succeeded' or service.store.require_task(db,row['task_id'])['status']!='succeeded':raise source_conflict()
    collection=repository.get(project,row['collection_id'])
    if not any(v['id']==row['version_id'] for v in collection['versions']):raise source_conflict()
    preview=repository.preview(project,row['collection_id'],row['version_id'])
    report,raw=repository.download(project,row['collection_id'],identity)
    frozen=row['input_json']
    if (not preview['ready'] or preview['items']!=frozen['items'] or frozen['items'][0]['result']['file_id']!=file_id
        or report['input_sha256']!=digest(frozen)):raise source_conflict()
    items=[]
    for item in frozen['items']:
        result=item['result'];figure=item['figure'];fid=result['file_id']
        analysis=read_source(service,project,dict(kind='analysis_run',id=result['id'],file_id=fid,role='computed_results'))
        image=read_source(service,project,dict(kind='figure',id=figure['id'],file_id=fid,role='image_observation'))
        if analysis['content']!=result or image['content']!=figure:raise source_conflict()
        items.append(dict(file_id=fid,analysis_run_id=result['id'],figure_id=figure['id'],figure_sha256=image['sha256'],
            source=result['source'],figure_number=item['figure_number'],caption=item['caption']))
    return dict(report=report,report_id=identity,collection_report_id=identity,collection_id=row['collection_id'],
        collection_version_id=row['version_id'],input_sha256=report['input_sha256'],items=items,**report_text(raw))


def select(service,project,request):
    request=CollectionSelectionRequest.model_validate(request) if isinstance(request,dict) else request
    with service.store.connection() as db:
        project_row=service.require_project(db,project)
        row=db.execute('''SELECT r.input_json FROM collection_reports r JOIN report_collection_versions v ON v.id=r.version_id
            JOIN report_collections c ON c.id=v.collection_id WHERE r.id=%s AND r.version_id=%s AND v.collection_id=%s AND c.project_id=%s''',
            (request.report_id,request.collection_version_id,request.collection_id,project)).fetchone()
    if not row:raise source_conflict()
    try:file_id=row['input_json']['items'][0]['result']['file_id']
    except (KeyError,IndexError,TypeError) as exc:raise source_conflict() from exc
    report=read_source(service,project,dict(kind='collection_report',id=request.report_id,file_id=file_id,role='user_results'))
    sources=[];seen=set();runs=[];figures=[];notes=[]
    for item in report['content']['items']:
        fid=item['file_id'];run=item['analysis_run_id'];figure=item['figure_id']
        if run not in seen:
            sources.append(read_source(service,project,dict(kind='analysis_run',id=run,file_id=fid,role='computed_results')))
            seen.add(run);runs.append(run)
        sources.append(read_source(service,project,dict(kind='figure',id=figure,file_id=fid,role='image_observation')))
        seen.add(figure);figures.append(figure);notes.append(dict(figure_id=figure,caption=item['caption'],panels=[]))
    sources.append(report)
    if len(sources)>50:
        raise StorageError('manuscript_source_limit','写作资料最多支持50项来源（统计、图表和报告分别计数），请选择较小的汇总报告。',422)
    groups=[dict(id='collection-'+request.collection_version_id,title=report['label'],analysis_run_ids=runs,figure_ids=figures)]
    return dict(selection_kind='collection_report',project_id=project,project_type=project_row['project_type'],file_id=file_id,
        analysis_run_id=runs[0],analysis_run_ids=runs,setup_revision=sources[0]['content']['setup_revision'],report_status='selected',
        collection_id=request.collection_id,collection_version_id=request.collection_version_id,report_id=request.report_id,
        sources=sources,results_group=groups[0],results_groups=groups,figure_notes=notes)
