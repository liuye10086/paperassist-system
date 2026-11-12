"""Project scoped research source, finding, figure, report and writing endpoints."""
from fastapi import APIRouter,Response
from typing import Literal
from pydantic import Field
from app.api.bio_datasets import Store,Key,Page
from app.domain.research_results.contracts import StrictModel,ResearchSourceSelection,FindingVersionRequest,SourceKind
from app.domain.research_results.sources import ResearchSourceReader
from app.domain.research_results.findings import ResearchFindingService
from app.core.exceptions import StorageError


router=APIRouter(prefix='/api/v1/projects',tags=['研究成果与写作'])


class ResearchPreviewRequest(StrictModel):
    sources:list[ResearchSourceSelection]=Field(min_length=1,max_length=100)


@router.get('/{project_id}/research-results/sources')
def source_list(project_id:str,source_kind:SourceKind,store:Store,page:Page=1):
    from app.domain.research_results.catalog import ResearchCatalog
    return ResearchCatalog(store).list(project_id,source_kind,page)


@router.get('/{project_id}/research-requests/{request_key}')
def recover(project_id:str,request_key:str,kind:Literal['finding','figure','report','candidate'],store:Store):
    if store.assignment is not None and kind == 'candidate':
        raise StorageError('research_source_not_found','成果请求不存在。',404)
    from app.domain.research_results.catalog import ResearchCatalog
    return ResearchCatalog(store).request(project_id,kind,request_key)


@router.post('/{project_id}/research-results/preview')
def preview(project_id:str,request:ResearchPreviewRequest,store:Store):
    return ResearchSourceReader(store).preview(project_id,request.sources)


@router.post('/{project_id}/research-findings')
def create_finding(project_id:str,request:FindingVersionRequest,store:Store,idempotency_key:Key,response:Response):
    result,response.status_code=ResearchFindingService(store).create(project_id,request,idempotency_key)
    return result


@router.get('/{project_id}/research-findings')
def findings(project_id:str,store:Store):
    return ResearchFindingService(store).list(project_id)


@router.post('/{project_id}/research-findings/{set_id}/versions')
def next_finding(project_id:str,set_id:str,request:FindingVersionRequest,store:Store,idempotency_key:Key,response:Response):
    result,response.status_code=ResearchFindingService(store).create(project_id,request,idempotency_key,set_id)
    return result


@router.get('/{project_id}/research-findings/{set_id}/versions/{version_id}')
def finding(project_id:str,set_id:str,version_id:str,store:Store):
    return ResearchFindingService(store).get(project_id,set_id,version_id)


# CR-B03 fixed research figures. B02 plotting endpoints remain independent.
from fastapi import Query
from app.domain.research_results.contracts import ResearchFigureRequest
from app.domain.research_results.figures import ResearchFigureService


@router.post('/{project_id}/research-figures')
def create_research_figure(project_id:str,request:ResearchFigureRequest,store:Store,idempotency_key:Key,response:Response):
    result,response.status_code=ResearchFigureService(store).create(project_id,request,idempotency_key)
    return result


@router.post('/{project_id}/research-figures/{root_id}/versions')
def next_research_figure(project_id:str,root_id:str,request:ResearchFigureRequest,store:Store,idempotency_key:Key,response:Response):
    result,response.status_code=ResearchFigureService(store).create(project_id,request,idempotency_key,root_id)
    return result


@router.get('/{project_id}/research-figures')
def research_figures(project_id:str,store:Store,page:int=Query(default=1,ge=1),page_size:int=Query(default=20,ge=1,le=50)):
    return ResearchFigureService(store).list(project_id,page,page_size)


@router.get('/{project_id}/research-figures/{version_id}')
def research_figure(project_id:str,version_id:str,store:Store):
    return ResearchFigureService(store).get(project_id,version_id)


@router.get('/{project_id}/research-figures/{version_id}/members/{member_id}/download')
def download_research_figure(project_id:str,version_id:str,member_id:str,store:Store):
    from urllib.parse import quote
    member,content=ResearchFigureService(store).member(project_id,version_id,member_id)
    media={'png':'image/png','jpeg':'image/jpeg','tiff':'image/tiff','pdf':'application/pdf','svg':'image/svg+xml','json':'application/json','py':'text/plain'}
    filename=member['key']+'.'+member['format']
    return Response(content,media_type=media.get(member['format'],'application/octet-stream'),headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(filename),'X-Content-Type-Options':'nosniff'})


from app.domain.research_results.contracts import ResearchReportRequest
from app.domain.research_results.reports import ResearchReportService


@router.post('/{project_id}/research-reports')
def create_research_report(project_id:str,request:ResearchReportRequest,store:Store,idempotency_key:Key,response:Response):
    result,response.status_code=ResearchReportService(store).create(project_id,request,idempotency_key)
    return result


@router.post('/{project_id}/research-reports/{root_id}/versions')
def next_research_report(project_id:str,root_id:str,request:ResearchReportRequest,store:Store,idempotency_key:Key,response:Response):
    result,response.status_code=ResearchReportService(store).create(project_id,request,idempotency_key,root_id)
    return result


@router.get('/{project_id}/research-reports')
def research_reports(project_id:str,store:Store,page:Page=1):
    return ResearchReportService(store).list(project_id,page)


@router.get('/{project_id}/research-reports/{version_id}')
def research_report(project_id:str,version_id:str,store:Store):
    return ResearchReportService(store).get(project_id,version_id)


@router.get('/{project_id}/research-reports/{version_id}/members/{member_id}/download')
def download_research_report(project_id:str,version_id:str,member_id:str,store:Store):
    from urllib.parse import quote
    member,content=ResearchReportService(store).member(project_id,version_id,member_id)
    media={'docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'txt':'text/plain; charset=utf-8','json':'application/json','zip':'application/zip'}
    return Response(content,media_type=media.get(member['format'],'application/octet-stream'),headers={
        'Content-Disposition':"attachment; filename*=UTF-8''"+quote(member['filename']),'X-Content-Type-Options':'nosniff'})

from app.domain.research_results.contracts import ResearchHandoffRequest,ResearchCandidateRequest,ResearchPublishRequest
from app.domain.research_results.handoff import ResearchHandoffService
from app.domain.research_results.candidates import ResearchCandidateService

@router.post('/{project_id}/research-results/writing-selection')
def research_writing_selection(project_id:str,request:ResearchHandoffRequest,store:Store):
    return ResearchHandoffService(store).preview(project_id,request)

@router.post('/{project_id}/research-manuscript-candidates')
def create_research_candidate(project_id:str,request:ResearchCandidateRequest,store:Store,idempotency_key:Key,response:Response):
    result,response.status_code=ResearchCandidateService(store).create(project_id,request,idempotency_key)
    return result

@router.get('/{project_id}/research-manuscript-candidates/{candidate_id}')
def research_candidate(project_id:str,candidate_id:str,store:Store):
    return ResearchCandidateService(store).get(project_id,candidate_id)

@router.post('/{project_id}/research-manuscript-candidates/{candidate_id}/publish')
def publish_research_candidate(project_id:str,candidate_id:str,request:ResearchPublishRequest,store:Store,idempotency_key:Key,response:Response):
    result,response.status_code=ResearchCandidateService(store).publish_manuscript(project_id,candidate_id,request,idempotency_key)
    return result

@router.get('/{project_id}/research-results/source-changes')
def research_source_changes(project_id:str,manuscript_id:str,revision:int,store:Store):
    from app.domain.manuscripts.service import ManuscriptService
    service=ManuscriptService(store)
    with service.store.connection() as db:version=service.version(db,project_id,manuscript_id,revision)
    return dict(items=service.source_changes(project_id,version['snapshot_json']))


@router.post('/{project_id}/research-results/source-changes')
def research_selected_source_changes(project_id:str,request:ResearchPreviewRequest,store:Store):
    from app.domain.research_results.source_changes import check_changes
    return check_changes(store,project_id,request.sources)

@router.get('/{project_id}/research-results/writing-config')
def research_writing_config(project_id:str,delivery_id:str,store:Store):
    return ResearchHandoffService(store).config(project_id,delivery_id)
