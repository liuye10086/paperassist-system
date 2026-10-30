"""Read the actual existing owner-scoped material; never trust client payloads."""
import json
from app.adapters.task_store import source_conflict
from app.core.exceptions import StorageError
from app.domain.external_evidence.service import ExternalEvidenceService
from app.domain.literature.service import digest


def read_source(service,project,selection):
    selected=selection.model_dump() if hasattr(selection,'model_dump') else selection
    kind,identity,file_id=selected['kind'],selected['id'],selected['file_id']
    with service.store.connection() as db:
        service.store.require_project(db,project)
        file=db.execute('SELECT * FROM files WHERE id=%s AND project_id=%s',(file_id,project)).fetchone()
        if not file: raise source_conflict()
        file=dict(file)
    # These evidence readers verify the original themselves. Other source kinds
    # still need the original-file check here, with no cache across calls.
    if kind not in ('original','document_version','ocr_review_version','external_evidence_version'):
        service.assets.original(file)
    download=f'/api/v1/projects/{project}/files/{file_id}/download'
    label=file['filename'];content={};sha=file['sha256']
    if kind in ('original','document_version','ocr_review_version'):
        if kind=='original' and identity!=file_id: raise source_conflict()
        source,items,row,document=ExternalEvidenceService(service.assets)._source(project,file_id,kind,None if kind=='original' else identity)
        content=dict(source=source,items=items);sha=source['sha256']
        download=source['object_download_url'] or source['original_download_url']
        if kind=='document_version':
            from app.domain.documents.service import DocumentService
            documents=DocumentService(service.assets)
            images=[]
            for image in getattr(document,'images',[]):
                if image.mime not in ('image/png','image/jpeg'): continue
                documents.objects()._image_from_document(row['result_json'],image.id,document)
                associations=[a for item in items if item.get('image_id')==image.id for a in item.get('associations',[])]
                images.append(dict(id=image.id,sha256=image.sha256,caption_candidates=[a['caption_text'] for a in associations],
                    preview_url=f'/api/v1/projects/{project}/files/{file_id}/document-versions/{identity}/images/{image.id}'))
            content['images']=images
    elif kind=='external_evidence_version':
        content=ExternalEvidenceService(service.assets).get(project,identity)
        if content['file_id']!=file_id: raise source_conflict()
        sha=content['sha256'];label=content['title']
        download=content['source']['object_download_url'] or content['source']['original_download_url']
    elif kind=='collection_report':
        from .collection_selection import report_source
        content=report_source(service,project,file_id,identity)
        report=content['report'];sha=report['sha256'];label=report['filename']
        download=f'/api/v1/projects/{project}/report-collections/{content["collection_id"]}/reports/{identity}/download'
    elif kind=='analysis_report':
        from .analysis_selection import report_source
        content=report_source(service,project,file_id,identity)
        report=content['report'];sha=report['sha256'];label=report['filename']
        download=f'/api/v1/projects/{project}/files/{file_id}/analysis-runs/{report["analysis_run_id"]}/report/{identity}/download'
    elif kind=='analysis_run':
        content=service.assets.analysis_result_by_id(project,file_id,identity)
        sha=digest(content);label=file['filename']+' — '+(content.get('numeric_name') or ('Statistical result' if content.get('analysis_context',{}).get('plan',{}).get('research_request',{}).get('output_language')=='en' else '统计结果'))
        download=f'/api/v1/projects/{project}/files/{file_id}/analysis-runs/{identity}'
    elif kind=='figure_language_version':
        from .figure_language import FigureLanguageService
        versions=FigureLanguageService(service.assets)
        with service.store.connection() as db: row=versions.row(db,project,identity)
        if row['file_id']!=file_id: raise source_conflict()
        content=row['snapshot_json'];sha=content['sha256'];label=content['title']
        download=versions.view(row)['download_url']
    elif kind=='figure':
        from app.adapters.figure_workbench_store import read_bundle
        with service.store.connection() as db:
            row=db.execute('SELECT f.* FROM figures f JOIN analysis_runs a ON a.id=f.analysis_run_id WHERE f.id=%s AND a.file_id=%s',(identity,file_id)).fetchone()
        if not row: raise source_conflict()
        if row['figure_config_version_id']:
            bundle=read_bundle(service.assets,project,identity)
            content=bundle['figure']
        else:
            content=json.loads(row['figure_json'])
            result=service.assets.analysis_result_by_id(project,file_id,row['analysis_run_id'])
            if content['analysis_run_id']!=result['id']: raise source_conflict()
        service.assets.figure_png(content)
        sha=content['sha256'];label=content['title']
        download=f"/api/v1/projects/{project}/files/{file_id}/analysis-runs/{row['analysis_run_id']}/figures/{identity}/download"
    else: raise StorageError('task_input_invalid','不支持的资料类型。',422)
    return dict(**selected,label=label,sha256=sha,download_url=download,content=content)


def changes(service,project,snapshot,*,current_sources=None):
    changed=[]
    for frozen in snapshot['sources']:
        reasons=[]
        try:
            selection={k:frozen[k] for k in ('kind','id','file_id','role')}
            identity=(project,*(selection[k] for k in ('kind','id','file_id','role')))
            # The task list owns this dictionary for one request only. Every
            # frozen snapshot is still compared and current-version checks run.
            if current_sources is None or identity not in current_sources:
                current=read_source(service,project,selection)
                if current_sources is not None: current_sources[identity]=current
            else: current=current_sources[identity]
            if current!=frozen: reasons.append('source_changed')
            with service.store.connection() as db:
                if frozen['kind']=='analysis_run':
                    setup=db.execute('SELECT revision FROM analysis_setups WHERE file_id=%s',(frozen['file_id'],)).fetchone()
                    if not setup or setup['revision']!=frozen['content']['setup_revision']: reasons.append('analysis_configuration_changed')
                elif frozen['kind'] in ('document_version','ocr_review_version'):
                    table='file_parse_results' if frozen['kind']=='document_version' else 'ocr_review_versions'
                    newer=db.execute('SELECT 1 FROM '+table+' WHERE file_id=%s AND version>%s',(frozen['file_id'],frozen['content']['source']['version'])).fetchone()
                    if newer: reasons.append('newer_source_version')
                elif frozen['kind']=='external_evidence_version':
                    if db.execute('SELECT 1 FROM external_evidence_versions WHERE previous_version_id=%s',(frozen['id'],)).fetchone(): reasons.append('newer_source_version')
        except StorageError as exc:
            if exc.code in ('storage_unavailable','database_configuration'): raise
            reasons.append('source_unavailable_or_changed')
        if reasons: changed.append(dict(kind=frozen['kind'],id=frozen['id'],reasons=reasons))
    citation=snapshot.get('citation_snapshot')
    if citation:
        with service.store.connection() as db:
            reasons=service.citations.current_changes(db,project,citation)
            root=db.execute('SELECT revision FROM literature_citation_drafts WHERE id=%s',(citation['draft_id'],)).fetchone()
        if reasons or not root or root['revision']!=citation['revision']:
            changed.append(dict(kind='citation_draft',id=citation['draft_id'],reasons=['citation_current_changed']))
    return changed


def writing_changes(service,project,snapshot):
    """Explicit historical intent accepts only a later setup, never changed bytes."""
    selected={s['id'] for s in snapshot.get('sources',[]) if s['kind']=='analysis_run'}
    allowed=set(snapshot.get('analysis_handoff_run_ids',[]))&selected
    return [c for c in service.source_changes(project,snapshot)
        if not (c['kind']=='analysis_run' and c['id'] in allowed and c['reasons']==['analysis_configuration_changed'])]
