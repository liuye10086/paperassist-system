"""Read-only transfer of explicitly named saved results; no latest lookup or task."""
from io import BytesIO
import json
from docx import Document
from pydantic import Field
from app.adapters.task_store import source_conflict
from app.adapters.report_store import ReportStore
from app.domain.literature.service import digest
from .contracts import Strict
from .sources import read_source

TEXT_LIMIT=12000

def report_text(raw):
    """Project actual body text in document order, excluding provenance appendices."""
    from docx.text.paragraph import Paragraph
    from docx.table import Table
    document=Document(BytesIO(raw));pieces=[]
    stops={'附录 B 来源与版本','Appendix B Sources and versions','Appendix — Source references','附录 来源记录'}
    for block in document.element.body:
        if block.tag.endswith('}p'):
            paragraph=Paragraph(block,document);text=paragraph.text
            if text in stops and paragraph.style.name.startswith('Heading'):break
            # The modeling renderer appends these fixed source records directly.
            if text.startswith(('Project ID:','Analysis ID:','项目编号：')):break
            if text.strip():pieces.append(text)
        elif block.tag.endswith('}tbl'):
            pieces.extend(' | '.join(c.text for c in r.cells) for r in Table(block,document).rows)
    text='\n'.join(pieces)
    return dict(text=text[:TEXT_LIMIT],text_truncated=len(text)>TEXT_LIMIT,text_total_characters=len(text),text_limit=TEXT_LIMIT)

class AnalysisSelectionRequest(Strict):
    file_id:str=Field(min_length=1,max_length=64)
    analysis_run_id:str=Field(min_length=1,max_length=64)
    figure_id:str|None=Field(default=None,min_length=1,max_length=64)
    report_id:str|None=Field(default=None,min_length=1,max_length=64)
    caption:str|None=Field(default=None,max_length=6000)


def report_source(service,project,file_id,identity):
    """Validate saved metadata, all predecessors, input digest and actual DOCX."""
    reports=ReportStore(service.assets)
    with service.store.connection() as db:
        row=db.execute('SELECT r.* FROM reports r JOIN analysis_runs a ON a.id=r.analysis_run_id JOIN files f ON f.id=a.file_id WHERE r.id=%s AND f.id=%s AND f.project_id=%s',(identity,file_id,project)).fetchone()
    if not row:raise source_conflict()
    try:
        report=reports.by_id(project,file_id,row['analysis_run_id'],identity)
        snapshot=json.loads(row['input_json']);result=service.assets.analysis_result_by_id(project,file_id,row['analysis_run_id'])
        figure=read_source(service,project,dict(kind='figure',id=report['figure_id'],file_id=file_id,role='image_observation'))['content']
        explanation=snapshot['explanation']
        from app.domain.reports import validate_sources
        validate_sources(result,figure,explanation)
        with service.store.connection() as db:
            saved=db.execute('SELECT explanation_json FROM explanations WHERE id=%s AND analysis_run_id=%s',(row['explanation_id'],result['id'])).fetchone()
        if (snapshot['project']['id']!=project or snapshot['result']!=result or snapshot['figure']!=figure
            or not saved or json.loads(saved['explanation_json'])!=explanation
            or report['id']!=identity or report['analysis_run_id']!=result['id']
            or report['explanation_id']!=row['explanation_id'] or report['explanation_id']!=explanation['id']
            or report['figure_sha256']!=figure['sha256'] or report['setup_revision']!=result['setup_revision']
            or report['source_sha256']!=result['source_sha256'] or report['input_sha256']!=digest(snapshot)
            or report['engine']['id']!=row['renderer_version']):raise source_conflict()
        raw=reports.content(report)
        return dict(report=report,report_id=identity,analysis_run_id=result['id'],figure_id=figure['id'],
                    input_sha256=report['input_sha256'],**report_text(raw))
    except (KeyError,ValueError,TypeError) as exc:raise source_conflict() from exc


def select(service,project,request):
    request=AnalysisSelectionRequest.model_validate(request) if isinstance(request,dict) else request
    with service.store.connection() as db:project_row=service.require_project(db,project)
    def read(kind,identity,role):return read_source(service,project,dict(kind=kind,id=identity,file_id=request.file_id,role=role))
    analysis=read('analysis_run',request.analysis_run_id,'computed_results');sources=[analysis]
    report=read('analysis_report',request.report_id,'user_results') if request.report_id else None
    if report and report['content']['analysis_run_id']!=request.analysis_run_id:raise source_conflict()
    figure_id=request.figure_id or (report['content']['figure_id'] if report else None)
    figure=read('figure',figure_id,'image_observation') if figure_id else None
    if figure and figure['content']['analysis_run_id']!=request.analysis_run_id:raise source_conflict()
    if report and figure['id']!=report['content']['figure_id']:raise source_conflict()
    if figure:sources.append(figure)
    if report:sources.append(report)
    return dict(project_id=project,project_type=project_row['project_type'],file_id=request.file_id,
        analysis_run_id=request.analysis_run_id,setup_revision=analysis['content']['setup_revision'],
        sources=sources,report_status='selected' if report else 'not_selected',
        results_group=dict(id='analysis-'+request.analysis_run_id,title=analysis['label'],analysis_run_ids=[request.analysis_run_id],figure_ids=[figure_id] if figure else []),
        figure_notes=[dict(figure_id=figure_id,caption=request.caption if request.caption is not None else figure['content'].get('caption',''),panels=[])] if figure else [])


def options(service,project,file_id,analysis_run_id):
    read_source(service,project,dict(kind='analysis_run',id=analysis_run_id,file_id=file_id,role='computed_results'))
    with service.store.connection() as db:
        figures=[json.loads(r['figure_json']) for r in db.execute('SELECT figure_json FROM figures WHERE analysis_run_id=%s ORDER BY id',(analysis_run_id,)).fetchall()]
        reports=[json.loads(r['report_json']) for r in db.execute('SELECT report_json FROM reports WHERE analysis_run_id=%s ORDER BY id',(analysis_run_id,)).fetchall()]
    return dict(figures=[dict(id=f['id'],title=f['title']) for f in figures],reports=[dict(id=r['id'],figure_id=r['figure_id'],filename=r['filename']) for r in reports])
