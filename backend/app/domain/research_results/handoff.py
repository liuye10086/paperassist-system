"""Read-only exact selection and merge preview; no draft writes or model call."""
from copy import deepcopy
from app.domain.source_byte_verification import VerificationPhase, require_phase, phase_guard
from app.adapters.research_results_store import ResearchResultsStore,invalid
from app.domain.manuscripts.delivery_context import resolve_document_context
from app.domain.manuscripts.research_sources import project_source
from app.domain.manuscripts.service import ManuscriptService
from app.domain.bioinformatics.contracts import digest,canonical
from .sources import ResearchSourceReader
from app.adapters.research_method_text import METHOD_PRESENTATION_VERSION


class ResearchHandoffService(ResearchResultsStore):
    def freeze(self,db,project,request):
        with VerificationPhase(db,self.assets,project) as phase:
            return self._freeze_in_phase(db,project,request,phase=phase)

    @phase_guard
    def _freeze_in_phase(self,db,project,request,*,phase):
        require_phase(phase,db,self.assets,project)
        context=resolve_document_context(db,project,self.store.user_id,delivery_id=request.delivery_id,manuscript_id=request.manuscript_id)
        manuscripts=ManuscriptService(self.assets);base=None
        if request.manuscript_id:
            root=manuscripts.root(db,project,request.manuscript_id)
            if root['current_revision']!=request.expected_revision:raise invalid('research_revision_conflict')
            base=manuscripts.version(db,project,request.manuscript_id,request.expected_revision)
            if getattr(request,'base_version_id',None) not in (None,base['id']):raise invalid('research_revision_conflict')
            if self.store.require_task(db,base['task_id'])['status']!='succeeded':raise invalid('research_source_incomplete',422)
        reader=ResearchSourceReader(self.assets);sources=[]
        for kind,ids in [('research_finding_version',request.finding_version_ids),('research_figure_version',request.figure_version_ids),('research_report_version',request.report_version_ids)]:
            for identifier in ids:
                frozen=reader._read_source_in_phase(project,dict(source_kind=kind,source_id=identifier),db=db,phase=phase)
                sources.append(project_source(frozen))
                if kind=='research_report_version':
                    for figure in frozen.content.get('figures',[]):
                        sources.append(project_source(reader._read_source_in_phase(project,dict(source_kind='research_figure_version',source_id=figure['id'],sha256=figure['manifest_sha256']),db=db,phase=phase)))
        sources=list({(source['kind'],source['id']):source for source in sources}.values())
        thesis_context=None;thesis=request.thesis
        if context['document_kind']=='thesis':
            if base:
                thesis_context=deepcopy(base['snapshot_json'].get('thesis_context'));thesis=thesis or base['request_json'].get('thesis')
                if not thesis_context:raise invalid('research_source_conflict')
                from app.domain.manuscripts.school_binding import current_changes
                if current_changes(manuscripts,project,base['snapshot_json']):raise invalid()
                if request.thesis and request.thesis.model_dump(mode='json')!=base['request_json']['thesis']:raise invalid()
            else:
                if thesis is None:raise invalid('research_writing_unavailable',409)
                from app.domain.manuscripts.contracts import ManuscriptRequest
                stub=ManuscriptRequest(title='研究成果事实稿',output_language=request.output_language,thesis=thesis,results_groups=[dict(id='research-results',title='研究结果')])
                from app.domain.manuscripts.school_binding import freeze_context
                thesis_context=freeze_context(manuscripts,project,stub,document_context=context)
            for purpose in getattr(request,'sections',['results','materials_and_methods']):
                selected=[c for c in thesis_context['chapters'] if c['purpose']==purpose]
                if len(selected)!=1:raise invalid('research_writing_unavailable',409)
                if purpose=='results' and 'research-results' not in selected[0]['result_group_ids']:raise invalid('research_writing_unavailable',409)
        elif thesis is not None:raise invalid('task_input_invalid',422)
        previous=deepcopy(base['snapshot_json']) if base else None
        retained=previous.get('sources',[]) if previous else []
        merged={s['id']:s for s in retained}
        for source in sources:merged[source['id']]=source
        payload=dict(schema_version=1,method_presentation_version=METHOD_PRESENTATION_VERSION,project_id=project,document_context=context,sources=list(merged.values()),selected_source_ids=[s['id'] for s in sources],
            base_snapshot=previous,base_version_id=base['id'] if base else None,expected_revision=request.expected_revision,
            output_language=previous['output_language'] if previous else request.output_language,thesis_context=thesis_context,
            thesis=thesis.model_dump(mode='json') if hasattr(thesis,'model_dump') else thesis,
            sections=getattr(request,'sections',['results','materials_and_methods']),manual_notes=getattr(request,'manual_notes',''))
        return payload

    def preview(self,project,request):
        with self.store.connection() as db:payload=self.freeze(db,project,request)
        from .fact_draft import compose
        candidate=compose(payload)
        return dict(**payload,writing_scope='results_methods',can_execute=False,real_model_calls=False,real_network_calls=False,
            selection_sha256=digest(payload),merge_preview=candidate)

    def config(self,project,delivery_id):
        with self.store.connection() as db:
            context=resolve_document_context(db,project,self.store.user_id,delivery_id=delivery_id)
            from app.domain.manuscripts.school_binding import readiness
            thesis=readiness(ManuscriptService(self.assets),db,project) if context['document_kind']=='thesis' else None
        return dict(document_context=context,thesis=thesis,writing_scope='results_methods',result_group_id='research-results',real_model_calls=False)
