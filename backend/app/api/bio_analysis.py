"""Owner-scoped spatial analysis routes; all writes have stable request identity."""
from typing import Annotated,Literal
from urllib.parse import quote
from fastapi import APIRouter,Query,Response
from pydantic import BeforeValidator
from app.api.bio_datasets import Store,Key,Page
from app.api.tasks import decimal_query_integer
from app.adapters.bio_analysis_store import BioAnalysisStore
from app.adapters.bio_annotation_store import BioAnnotationStore
from app.adapters.bio_figure_store import BioFigureStore
from app.domain.bioinformatics.analysis_service import BioAnalysisService
from app.domain.bioinformatics.analysis_contracts import (BioObservationMapRequest,BioObservationMapPreviewRequest,BioAnalysisSetupRequest,
    BioAnalysisRunRequest,BioAnalysisConfirmRequest,BioAnnotationRequest,BioFigureRequest)
router=APIRouter(prefix='/api/v1/projects',tags=['空间转录组分析'])
Size=Annotated[int,Query(ge=1,le=100),BeforeValidator(decimal_query_integer)]


def download(pair):
    item,content=pair
    media={'png':'image/png','pdf':'application/pdf','tsv':'text/tab-separated-values','json':'application/json','txt':'text/plain','py':'text/plain','h5ad':'application/octet-stream','npy':'application/octet-stream'}.get(item['format'],'application/octet-stream')
    return Response(content,media_type=media,headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(item['filename'],safe=''),'ETag':'"'+item['sha256']+'"','X-Content-Type-Options':'nosniff'})

@router.get('/{project_id}/bio-analysis-capabilities')
def capabilities(project_id:str,store:Store,dataset_id:str,version_id:str):return BioAnalysisStore(store).capabilities(project_id,dataset_id,version_id)
@router.post('/{project_id}/bio-observation-map-table-previews')
def map_preview(project_id:str,request:BioObservationMapPreviewRequest,store:Store):return BioAnalysisStore(store).preview_mapping(project_id,request)
@router.post('/{project_id}/bio-observation-maps',status_code=201)
def create_map(project_id:str,request:BioObservationMapRequest,store:Store,idempotency_key:Key):return BioAnalysisStore(store).save_mapping(project_id,request,idempotency_key)
@router.post('/{project_id}/bio-observation-maps/{set_id}/versions',status_code=201)
def map_version(project_id:str,set_id:str,request:BioObservationMapRequest,store:Store,idempotency_key:Key):return BioAnalysisStore(store).save_mapping(project_id,request,idempotency_key,set_id)
@router.get('/{project_id}/bio-observation-maps/{set_id}/versions/{version_id}')
def mapping(project_id:str,set_id:str,version_id:str,store:Store,page:Page=1,page_size:Size=50):return BioAnalysisStore(store).mapping(project_id,set_id,version_id,page,page_size)
@router.post('/{project_id}/bio-analysis-setups',status_code=201)
def create_setup(project_id:str,request:BioAnalysisSetupRequest,store:Store,idempotency_key:Key):return BioAnalysisStore(store).save_recipe(project_id,request,idempotency_key)
@router.post('/{project_id}/bio-analysis-setups/{setup_id}/recipes',status_code=201)
def create_recipe(project_id:str,setup_id:str,request:BioAnalysisSetupRequest,store:Store,idempotency_key:Key):return BioAnalysisStore(store).save_recipe(project_id,request,idempotency_key,setup_id)
@router.get('/{project_id}/bio-analysis-setups/{setup_id}')
def setup(project_id:str,setup_id:str,store:Store):return BioAnalysisStore(store).setup(project_id,setup_id)
@router.get('/{project_id}/bio-analysis-setups/{setup_id}/recipes/{version_id}')
def recipe(project_id:str,setup_id:str,version_id:str,store:Store):return BioAnalysisStore(store).recipe(project_id,setup_id,version_id)
@router.post('/{project_id}/bio-analysis-runs',status_code=202)
def create_run(project_id:str,request:BioAnalysisRunRequest,store:Store,idempotency_key:Key):return BioAnalysisService(store).create(project_id,request,idempotency_key)
@router.get('/{project_id}/bio-analysis-runs')
def runs(project_id:str,store:Store,page:Page=1,page_size:Size=50):return BioAnalysisService(store).list_runs(project_id,page,page_size)
@router.get('/{project_id}/bio-analysis-runs/{run_id}')
def run(project_id:str,run_id:str,store:Store):return BioAnalysisService(store).get(project_id,run_id)
@router.post('/{project_id}/bio-analysis-runs/{run_id}/confirm',status_code=202)
def confirm(project_id:str,run_id:str,request:BioAnalysisConfirmRequest,store:Store,idempotency_key:Key):return BioAnalysisService(store).confirm(project_id,run_id,request,idempotency_key)
@router.get('/{project_id}/bio-analysis-runs/{run_id}/qc-members/{member_id}/download')
def qc_member(project_id:str,run_id:str,member_id:str,store:Store):return download(BioAnalysisService(store).qc_member(project_id,run_id,member_id))
@router.get('/{project_id}/bio-processed-datasets/{version_id}')
def processed(project_id:str,version_id:str,store:Store):return BioAnalysisStore(store).processed(project_id,version_id)
@router.get('/{project_id}/bio-processed-datasets/{version_id}/tables/{key}')
def table(project_id:str,version_id:str,key:str,store:Store,page:Page=1,page_size:Size=50,
    query:Annotated[str|None,Query(max_length=200)]=None,cluster:Annotated[str|None,Query(max_length=100)]=None,
    sort_by:Annotated[str|None,Query(max_length=100)]=None,order:Literal['asc','desc']='asc'):
    return BioAnalysisStore(store).table(project_id,version_id,key,page,page_size,query,cluster,sort_by,order)
@router.get('/{project_id}/bio-processed-datasets/{version_id}/coordinates')
def coordinates(project_id:str,version_id:str,store:Store):return BioAnalysisStore(store).coordinates(project_id,version_id)
@router.get('/{project_id}/bio-processed-datasets/{version_id}/matrix-preview')
def matrix(project_id:str,version_id:str,store:Store,layer:Literal['counts','normalized','log1p']='log1p',features_page:Page=1,observations_page:Page=1):return BioAnalysisStore(store).matrix_preview(project_id,version_id,layer,features_page,observations_page)
@router.get('/{project_id}/bio-processed-datasets/{version_id}/members/{member_id}/download')
def processed_member(project_id:str,version_id:str,member_id:str,store:Store):return download(BioAnalysisStore(store).member(project_id,version_id,member_id))
@router.post('/{project_id}/bio-annotation-sets',status_code=201)
def create_annotation(project_id:str,request:BioAnnotationRequest,store:Store,idempotency_key:Key):return BioAnnotationStore(store).save(project_id,request,idempotency_key)
@router.post('/{project_id}/bio-annotation-sets/{set_id}/versions',status_code=201)
def annotation_version(project_id:str,set_id:str,request:BioAnnotationRequest,store:Store,idempotency_key:Key):return BioAnnotationStore(store).save(project_id,request,idempotency_key,set_id)
@router.get('/{project_id}/bio-annotation-sets/{set_id}/versions/{version_id}')
def annotation(project_id:str,set_id:str,version_id:str,store:Store):return BioAnnotationStore(store).get(project_id,set_id,version_id)
@router.post('/{project_id}/bio-figures',status_code=202)
def create_figure(project_id:str,request:BioFigureRequest,store:Store,idempotency_key:Key):return BioFigureStore(store).create(project_id,request,idempotency_key)
@router.post('/{project_id}/bio-figures/{root_id}/versions',status_code=202)
def figure_version(project_id:str,root_id:str,request:BioFigureRequest,store:Store,idempotency_key:Key):return BioFigureStore(store).create(project_id,request,idempotency_key,root_id)
@router.get('/{project_id}/bio-figures/{figure_id}')
def figure(project_id:str,figure_id:str,store:Store):return BioFigureStore(store).get(project_id,figure_id)
@router.get('/{project_id}/bio-figures/{figure_id}/members/{member_id}/download')
def figure_member(project_id:str,figure_id:str,member_id:str,store:Store):return download(BioFigureStore(store).member(project_id,figure_id,member_id))
@router.get('/{project_id}/bio-requests/{request_key}')
def lookup(project_id:str,request_key:str,store:Store,kind:Literal['map','recipe','run','confirmation','annotation','figure','import','import_confirmation']):return BioAnalysisStore(store).request(project_id,request_key,kind)
