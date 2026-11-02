"""Read exact successful DOCX sources for Word layout and historical exports."""
from hashlib import sha256
from app.adapters.task_store import TaskStore,source_conflict
from app.core.exceptions import StorageError
from app.domain.source_byte_verification import VerificationPhase, require_phase, phase_guard


class DocxSourceReader:
    def __init__(self,assets):
        self.assets=assets
        self.store=TaskStore(assets.owner_id,assets.db_config)

    def source(self,db,project,kind,identity,*,progress=None):
        with VerificationPhase(db,self.assets,project) as phase:
            return self._source_in_phase(db,project,kind,identity,phase=phase,progress=progress)

    @phase_guard
    def _source_in_phase(self,db,project,kind,identity,*,phase,progress=None):
        require_phase(phase,db,self.assets,project)
        if progress is not None:progress()
        self.store.require_project(db,project)
        if kind=='review_document_export':
            from app.domain.research_intake.delivery_access import require_legacy_writing_db
            require_legacy_writing_db(db,project,self.store.user_id)
        if kind=='review_document_export':
            from app.domain.review_rounds.document_exports import ReviewDocumentExportService
            svc=ReviewDocumentExportService(self.assets)
            row=svc.row(db,project,identity)
            metadata,raw=svc.download(project,identity)
            doc=svc.documents.row(db,project,row['document_id'])
            version=dict(id=doc['id'],revision=doc['version'],kind=doc['kind'],language=doc['language'],document_sha256=doc['snapshot_sha256'])
        elif kind=='research_report':
            from app.domain.research_results.reports import ResearchReportService
            row=db.execute("SELECT m.*,v.revision,v.task_id FROM research_report_members m JOIN research_report_versions v ON v.id=m.report_version_id WHERE m.id=%s AND m.project_id=%s AND m.user_id=%s AND m.role='docx' AND m.format='docx'",(identity,project,self.store.user_id)).fetchone()
            if not row:raise StorageError('pdf_source_not_found','研究报告 DOCX 成员不存在。',404)
            metadata,raw=ResearchReportService(self.assets)._member_in_phase(db,project,row['report_version_id'],identity,phase=phase,progress=progress)
            version=dict(id=row['report_version_id'],revision=row['revision'],member_id=identity)
        elif kind=='layout_export':
            from app.domain.layout_exports.service import LayoutExportService
            svc=LayoutExportService(self.assets)
            row=svc.row(db,project,identity)
            metadata,raw=svc.download(project,identity)
            version=dict(id=row['id'],layout_version=row['layout_version'],input_sha256=row['input_sha256'])
        elif kind=='manuscript_export':
            from app.domain.manuscripts.service import ManuscriptService
            row=db.execute('SELECT e.*,v.manuscript_id,v.project_id,v.revision FROM manuscript_exports e JOIN manuscript_versions v ON v.id=e.version_id WHERE e.id=%s AND v.project_id=%s AND v.user_id=%s',(identity,project,self.store.user_id)).fetchone()
            if not row: raise StorageError('pdf_source_not_found','DOCX来源不存在。',404)
            from app.domain.manuscripts.delivery_context import resolve_document_context
            resolve_document_context(db,project,self.store.user_id,manuscript_id=row['manuscript_id'],active=False)
            task=self.store.require_task(db,row['task_id'])
            if task['status']!='succeeded': raise StorageError('pdf_source_not_ready','请等待 DOCX 导出成功。',409)
            metadata,raw=ManuscriptService(self.assets).export(project,row['manuscript_id'],identity,True)
            version=dict(id=row['version_id'],revision=row['revision'])
        elif kind=='collection_report':
            from app.adapters.collection_store import CollectionStore
            row=db.execute('SELECT r.*,v.collection_id,v.revision AS source_revision,q.task_id FROM collection_reports r JOIN report_collection_versions v ON v.id=r.version_id JOIN report_collections c ON c.id=v.collection_id JOIN report_build_requests q ON q.id=r.build_request_id WHERE r.id=%s AND c.project_id=%s AND c.created_by=%s',(identity,project,self.store.user_id)).fetchone()
            if not row: raise StorageError('pdf_source_not_found','DOCX来源不存在。',404)
            if self.store.require_task(db,row['task_id'])['status']!='succeeded': raise StorageError('pdf_source_not_ready','请等待 DOCX 导出成功。',409)
            metadata,raw=CollectionStore(self.assets).download(project,row['collection_id'],identity)
            version=dict(id=row['version_id'],revision=row['source_revision'],export_revision=row['export_revision'])
        elif kind=='report':
            from app.adapters.report_store import ReportStore
            row=db.execute('SELECT r.*,a.file_id FROM reports r JOIN analysis_runs a ON a.id=r.analysis_run_id JOIN files f ON f.id=a.file_id WHERE r.id=%s AND f.project_id=%s',(identity,project)).fetchone()
            if not row: raise StorageError('pdf_source_not_found','DOCX来源不存在。',404)
            repository=ReportStore(self.assets)
            metadata=repository.by_id(project,row['file_id'],row['analysis_run_id'],identity)
            raw=repository.content(metadata)
            version=dict(id=row['analysis_run_id'],revision=metadata['setup_revision'],renderer_version=row['renderer_version'])
        else: raise StorageError('task_input_invalid','DOCX来源类型无效。',422)
        if metadata.get('id',identity)!=identity or sha256(raw).hexdigest()!=metadata['sha256'] or len(raw)!=metadata['size_bytes']: raise source_conflict()
        source=dict(source_kind=kind,source_id=identity,version=version,metadata=metadata)
        if kind=='research_report':
            from app.domain.research_results.sources import ResearchSourceReader
            fixed=ResearchSourceReader(self.assets)._read_source_in_phase(project,dict(source_kind='research_report_version',source_id=row['report_version_id']),db=db,phase=phase,progress=progress)
            source['files']=[{'file_id':identifier} for identifier in fixed.source_file_ids]
        if progress is not None:progress()
        return source,raw
