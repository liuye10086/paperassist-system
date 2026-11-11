"""Project-owned differential analyses, resources and reproducible results."""
from typing import Annotated,Literal
from urllib.parse import quote

from fastapi import APIRouter,File,Query,Response,UploadFile

from app.api.bio_datasets import Store,Key,Page
from app.adapters.bio_insights_store import invalid
from app.domain.bio_insights.contracts import BulkQColumn,InsightPlanRequest,InsightRunRequest,ResourceImportRequest,SourceKind
from app.domain.bio_insights.service import BioInsightsService
from app.domain.bio_insights.resources import BioResourceService
from app.domain.bio_insights.results import BioInsightResultService
from app.domain.bio_insights.sources import InsightSourceReader

router=APIRouter(prefix='/api/v1/projects',tags=['差异富集与候选筛选'])
PageSize=Annotated[int,Query(ge=1,le=100)]
ObservationPageSize=Annotated[int,Query(ge=1,le=1000)]


@router.get('/{project_id}/bio-insights/capabilities')
def capabilities(project_id:str,store:Store):
    from app.domain.bio_insights.settings import runtime_identity,BioInsightsLimits
    service=BioInsightsService(store)
    with service.store.connection() as db:service.store.require_project(db,project_id)
    runtime=runtime_identity()
    return dict(methods=['spot_exploratory','donor_unpaired','donor_paired','result_import','ora','gsea_prerank','candidate','figure'],
        runtime=runtime,bulk_model_runtime=runtime_identity(bulk_model=True),bulk_display_runtime=runtime_identity(bulk_display=True),
        bulk_enrichment_runtime=runtime_identity(bulk_enrichment=True),
        configured=runtime['available'],worker_online=None,limits=BioInsightsLimits().model_dump(),
        blocking_reasons=[] if runtime['available'] else [runtime['reason']],real_model_calls=False,real_network_calls=False)


@router.post('/{project_id}/bio-resource-files')
def upload_resource_file(project_id:str,store:Store,idempotency_key:Key,response:Response,file:Annotated[UploadFile,File()]):
    content=file.file.read(268435457)
    from app.domain.bio_insights.uploads import BioResourceUploadService
    value,response.status_code=BioResourceUploadService(store).upload(project_id,file.filename,content,idempotency_key)
    return value


@router.get('/{project_id}/bio-resource-files/requests/{request_key}')
def recover_resource_file(project_id:str,request_key:str,store:Store):
    from app.domain.bio_insights.uploads import BioResourceUploadService
    return BioResourceUploadService(store).recover(project_id,request_key)


@router.get('/{project_id}/bio-insights/sources')
def source_catalog(project_id:str,source_kind:SourceKind,store:Store,page:Page=1,page_size:PageSize=20):
    return InsightSourceReader(store).catalog(project_id,source_kind,page,page_size)


@router.get('/{project_id}/bio-insights/sources/{source_kind}/{source_id}/observations')
def observations(project_id:str,source_kind:SourceKind,source_id:str,store:Store,page:Page=1,page_size:ObservationPageSize=100):
    return InsightSourceReader(store).observations(project_id,source_kind,source_id,page,page_size)


@router.post('/{project_id}/bio-insight-plans/preview')
def preview(project_id:str,request:InsightPlanRequest,store:Store):return BioInsightsService(store).preview(project_id,request)


@router.post('/{project_id}/bio-insight-plans')
def create_plan(project_id:str,request:InsightPlanRequest,store:Store,idempotency_key:Key,response:Response):
    value,response.status_code=BioInsightsService(store).create_plan(project_id,request,idempotency_key)
    return value


@router.post('/{project_id}/bio-insight-plans/{plan_id}/versions')
def version_plan(project_id:str,plan_id:str,request:InsightPlanRequest,store:Store,idempotency_key:Key,response:Response):
    value,response.status_code=BioInsightsService(store).create_plan(project_id,request,idempotency_key,plan_id)
    return value


@router.get('/{project_id}/bio-insight-plans')
def plans(project_id:str,store:Store,page:Page=1,page_size:PageSize=20):return BioInsightsService(store).list_plans(project_id,page,page_size)


@router.get('/{project_id}/bio-insight-plans/{plan_id}/versions/{version_id}')
def plan(project_id:str,plan_id:str,version_id:str,store:Store):return BioInsightsService(store).get_plan(project_id,plan_id,version_id)


@router.post('/{project_id}/bio-insight-runs')
def create_run(project_id:str,request:InsightRunRequest,store:Store,idempotency_key:Key,response:Response):
    value,response.status_code=BioInsightsService(store).create_run(project_id,request,idempotency_key)
    return value


@router.get('/{project_id}/bio-insight-runs')
def runs(project_id:str,store:Store,page:Page=1,page_size:PageSize=20):return BioInsightsService(store).list_runs(project_id,page,page_size)


@router.get('/{project_id}/bio-insight-runs/{run_id}')
def run(project_id:str,run_id:str,store:Store):return BioInsightsService(store).get_run(project_id,run_id)


@router.get('/{project_id}/bio-insight-requests/{request_key}')
def recover(project_id:str,request_key:str,kind:Literal['plan','run','resource'],store:Store):return BioInsightsService(store).recover(project_id,kind,request_key)


@router.post('/{project_id}/bio-resources/preview')
def preview_resource(project_id:str,request:ResourceImportRequest,store:Store):return BioResourceService(store).preview_resource(project_id,request)


@router.post('/{project_id}/bio-resources')
def create_resource(project_id:str,request:ResourceImportRequest,store:Store,idempotency_key:Key,response:Response):
    value,response.status_code=BioResourceService(store).create(project_id,request,idempotency_key)
    return value


@router.post('/{project_id}/bio-resources/{root_id}/versions')
def version_resource(project_id:str,root_id:str,request:ResourceImportRequest,store:Store,idempotency_key:Key,response:Response):
    value,response.status_code=BioResourceService(store).create(project_id,request,idempotency_key,root_id)
    return value


@router.get('/{project_id}/bio-resources')
def resources(project_id:str,store:Store,page:Page=1,page_size:PageSize=20):return BioResourceService(store).list(project_id,page,page_size)


@router.get('/{project_id}/bio-resources/{version_id}')
def resource(project_id:str,version_id:str,store:Store):return BioResourceService(store).get(project_id,version_id)


def download(member,content):
    media={'json':'application/json','tsv':'text/tab-separated-values; charset=utf-8','csv':'text/csv; charset=utf-8',
        'png':'image/png','tiff':'image/tiff','pdf':'application/pdf','svg':'image/svg+xml','txt':'text/plain; charset=utf-8'}
    return Response(content,media_type=media.get(member['format'],'application/octet-stream'),headers={
        'Content-Disposition':"attachment; filename*=UTF-8''"+quote(member['key']+'.'+member['format'],safe=''),'X-Content-Type-Options':'nosniff'})


@router.get('/{project_id}/bio-resources/{version_id}/members/{member_id}/download')
def download_resource(project_id:str,version_id:str,member_id:str,store:Store):
    return download(*BioResourceService(store).member(project_id,version_id,member_id))


@router.get('/{project_id}/bio-insight-results/{version_id}')
def result(project_id:str,version_id:str,store:Store):return BioInsightResultService(store).get(project_id,version_id)


@router.get('/{project_id}/bio-insight-results/{version_id}/figures')
def report_figures(project_id:str,version_id:str,store:Store):
    from app.adapters.single_cell_insight_report import list_report_figures
    return list_report_figures(store,project_id,version_id)


@router.get('/{project_id}/bio-insight-results/{version_id}/report.docx')
def insight_word_report(project_id:str,version_id:str,store:Store,figure_version_ids:Annotated[list[str]|None,Query(max_length=10)]=None,language:Annotated[Literal['zh-CN','en']|None,Query()]=None):
    from app.domain.bio_insights.bulk_results import is_reviewed_bulk

    results = BioInsightResultService(store)
    with results.store.connection() as db:
        result = results.require(db, 'bio_insight_result_versions', project_id, version_id)
        plan = results.require(db, 'bio_insight_plan_versions', project_id, result['plan_version_id'])
    config = plan['config_json']
    if is_reviewed_bulk({'kind': result['kind'], 'plan_config': config}):
        comparison_id, attached = version_id, list(figure_version_ids or [])
    elif result['kind'] in ('ora', 'gsea_prerank') and config.get('bulk_enrichment'):
        sources = config['result_source_ids'] if result['kind'] == 'ora' else [config['result_source_id']]
        if len(sources) != 1:
            raise invalid('bio_insight_source_conflict', 409)
        comparison_id, attached = sources[0], [version_id, *(figure_version_ids or [])]
    else:
        comparison_id, attached = None, []
    if comparison_id:
        from app.api.bulk_workflow import heavy_slot, resolve_delivery, prepared_artifact, artifact_response
        from app.domain.bio_insights.bulk_delivery_contracts import BulkDeliveryRequest, BulkDownloadRequest

        request = BulkDeliveryRequest(comparison_version_id=comparison_id, result_version_ids=attached,
                                      language='en' if (language or config.get('output_language')) == 'en' else 'zh')
        with heavy_slot(store, project_id):
            _, facts = resolve_delivery(project_id, store, request)
            frozen = BulkDownloadRequest(**request.model_dump(), facts_digest=facts['facts_digest'])
            _, entry = prepared_artifact(project_id, store, frozen, 'word')
            return artifact_response(entry, 'word')

    from app.adapters.single_cell_insight_report import download_single_cell_insight_report
    return Response(download_single_cell_insight_report(store,project_id,version_id,figure_version_ids,language),
        media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        headers={'Content-Disposition':'attachment; filename="single-cell-donor-analysis.docx"','X-Content-Type-Options':'nosniff'})


@router.get('/{project_id}/bio-insight-results/{version_id}/members/{member_id}/download')
def download_result(project_id:str,version_id:str,member_id:str,store:Store):return download(*BioInsightResultService(store).member(project_id,version_id,member_id))


@router.get('/{project_id}/bio-insight-results/{version_id}/tables/{key}')
def result_table(project_id:str,version_id:str,key:str,store:Store,page:Page=1,page_size:PageSize=50,search:Annotated[str|None,Query(max_length=200)]=None):
    return BioInsightResultService(store).table(project_id,version_id,key,page,page_size,search)


@router.get('/{project_id}/bio-insight-results/{version_id}/bulk-comparisons')
def bulk_comparisons(
    project_id: str, version_id: str, store: Store,
    contrast_id: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    subset: Literal['all', 'deg', 'up', 'down'] = 'all',
    q_column: BulkQColumn = 'q_within_contrast',
    q_threshold: Annotated[float, Query(ge=0, le=1)] = 0.05,
    minimum_absolute_effect: Annotated[float, Query(ge=0, le=1_000_000)] = 1.0,
    page: Page = 1, page_size: PageSize = 50,
    search: Annotated[str | None, Query(max_length=200)] = None,
):
    return BioInsightResultService(store).bulk_comparisons(
        project_id, version_id, contrast_id=contrast_id, subset=subset, q_column=q_column, q_threshold=q_threshold,
        minimum_absolute_effect=minimum_absolute_effect, page=page, page_size=page_size, search=search,
    )


def reproduction_download(store,project,identifier,resource=False):
    from fastapi.responses import StreamingResponse
    from app.domain.bio_insights.reproducibility import BioInsightReproductionService
    package=BioInsightReproductionService(store).export(project,identifier,resource=resource)
    def chunks():
        try:
            while content:=package['file'].read(1024**2):yield content
        finally:package['file'].close()
    return StreamingResponse(chunks(),media_type='application/zip',headers={
        'Content-Disposition':"attachment; filename*=UTF-8''"+quote(package['filename'],safe=''),
        'X-Reproducibility-Manifest-SHA256':package['manifest_sha256'],
        'X-Analysis-Inputs-Self-Contained':'true' if package['analysis_inputs_self_contained'] else 'false',
        'X-Content-Type-Options':'nosniff'})


@router.get('/{project_id}/bio-insight-results/{version_id}/reproducibility-package')
def result_reproduction_package(project_id:str,version_id:str,store:Store):return reproduction_download(store,project_id,version_id)


@router.get('/{project_id}/bio-resources/{version_id}/reproducibility-package')
def resource_reproduction_package(project_id:str,version_id:str,store:Store):return reproduction_download(store,project_id,version_id,True)


@router.get('/{project_id}/bio-insight-results/{version_id}/impact')
def result_impact(project_id:str,version_id:str,store:Store):
    service=BioInsightResultService(store)
    from app.domain.research_results.source_changes import dependency_impact
    with service.store.connection() as db:
        row=service.require(db,'bio_insight_result_versions',project_id,version_id)
        return dict(source_kind='bio_insight_result_version',source_id=row['id'],**dependency_impact(db,project_id,service.store.user_id,'bio_insight_result_version',row['id']))


@router.get('/{project_id}/bio-resources/{version_id}/impact')
def resource_impact(project_id:str,version_id:str,store:Store):
    service=BioResourceService(store)
    from app.domain.research_results.source_changes import dependency_impact
    with service.store.connection() as db:
        row=service.require(db,'bio_resource_versions',project_id,version_id)
        newer=db.execute('SELECT id,version FROM bio_resource_versions WHERE root_id=%s AND project_id=%s AND user_id=%s AND version>%s ORDER BY version DESC LIMIT 1',(row['root_id'],project_id,service.store.user_id,row['version'])).fetchone()
        return dict(source_kind='bio_resource_version',source_id=row['id'],newer_version_id=newer['id'] if newer else None,newer_revision=newer['version'] if newer else None,**dependency_impact(db,project_id,service.store.user_id,'bio_resource_version',row['id']))
