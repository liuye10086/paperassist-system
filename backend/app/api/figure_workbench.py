"""Free local configuration/confirmation and explicitly confirmed paid task requests."""
from fastapi import APIRouter,Response
from io import BytesIO
import json
from zipfile import ZipFile,ZIP_DEFLATED
from app.api.dependencies import Store
from app.adapters.figure_workbench_store import FigureWorkbenchStore,read_bundle
from app.domain.figure_workbench.contracts import SaveConfiguration,ConfirmProjection,GenerateFigure,ReuseExplanation
from app.domain.external_processing import digest
from app.adapters.task_store import source_conflict

router=APIRouter(prefix='/api/v1/projects/{project_id}/files/{file_id}/analysis-runs/{run_id}/figure-workbench',tags=['图表工作台'])

@router.get('')
def state(project_id:str,file_id:str,run_id:str,store:Store):return FigureWorkbenchStore(store).state(project_id,file_id,run_id)
@router.post('/configurations')
def save(project_id:str,file_id:str,run_id:str,request:SaveConfiguration,store:Store):return FigureWorkbenchStore(store).save(project_id,file_id,run_id,request)
@router.post('/versions/{version_id}/check')
def check(project_id:str,file_id:str,run_id:str,version_id:str,response:Response,store:Store):
    value=FigureWorkbenchStore(store).check(project_id,file_id,run_id,version_id)
    if value.get('task',{} ) and value['task']['status'] in ('queued','running'):response.status_code=202
    return value
@router.post('/versions/{version_id}/confirm')
def confirm(project_id:str,file_id:str,run_id:str,version_id:str,request:ConfirmProjection,response:Response,store:Store):
    value=FigureWorkbenchStore(store).confirm(project_id,file_id,run_id,version_id,request)
    if value.get('task'):response.status_code=202
    return value
@router.post('/versions/{version_id}/external-preview')
def preview(project_id:str,file_id:str,run_id:str,version_id:str,store:Store):return FigureWorkbenchStore(store).external_preview(project_id,file_id,run_id,version_id)
@router.post('/versions/{version_id}/generate',status_code=202)
def generate(project_id:str,file_id:str,run_id:str,version_id:str,request:GenerateFigure,store:Store):
    from app.domain.figure_workbench.tasks import submit
    return submit(FigureWorkbenchStore(store),project_id,file_id,run_id,version_id,request)

def bundle_for(store,project_id,file_id,run_id,figure_id):
    bundle=read_bundle(store,project_id,figure_id)
    if bundle['result']['file_id']!=file_id or bundle['result']['id']!=run_id:raise source_conflict()
    return bundle

@router.post('/figures/{figure_id}/explanation-preview')
def explanation_preview(project_id:str,file_id:str,run_id:str,figure_id:str,store:Store):
    from app.domain.figure_workbench.explanations import build_payload
    bundle=bundle_for(store,project_id,file_id,run_id,figure_id);payload=build_payload(bundle)
    return {'payload_sha256':digest(payload),'payload':payload,'requires_confirmation':True}
@router.post('/figures/{figure_id}/explanations',status_code=202)
def explain(project_id:str,file_id:str,run_id:str,figure_id:str,request:GenerateFigure,store:Store):
    from app.domain.figure_workbench.tasks import submit
    bundle=bundle_for(store,project_id,file_id,run_id,figure_id)
    return submit(FigureWorkbenchStore(store),project_id,file_id,run_id,bundle['figure']['figure_config_version_id'],request,figure_id=figure_id)
@router.post('/versions/{version_id}/reuse-explanation')
def reuse_explanation(project_id:str,file_id:str,run_id:str,version_id:str,request:ReuseExplanation,store:Store):
    from app.domain.figure_workbench.explanations import reuse,version_for,validate_saved
    workbench=FigureWorkbenchStore(store)
    with workbench.tasks.connection() as db:
        workbench._version(db,project_id,file_id,run_id,version_id)
        target=db.execute('SELECT id FROM figures WHERE figure_config_version_id=%s',(version_id,)).fetchone()
        previous=db.execute('SELECT figure_id FROM explanations WHERE id=%s',(request.source_explanation_id,)).fetchone()
    if not target or not previous:raise source_conflict()
    old=read_bundle(store,project_id,previous['figure_id'],request.source_explanation_id);new=bundle_for(store,project_id,file_id,run_id,target['id'])
    value=reuse(old,new,old['explanation'])
    version=value['engine']['id']
    with workbench.tasks.connection(write=True) as db:
        workbench._version(db,project_id,file_id,run_id,version_id,lock=True)
        existing=db.execute('SELECT explanation_json FROM explanations WHERE figure_id=%s AND engine_version=%s',(target['id'],version)).fetchone()
        if existing:return validate_saved(new,json.loads(existing['explanation_json']))
        db.execute('INSERT INTO explanations(id,analysis_run_id,figure_id,engine_version,explanation_json) VALUES (%s,%s,%s,%s,%s)',(value['id'],run_id,target['id'],version,json.dumps(value,ensure_ascii=False,allow_nan=False)))
    return value
@router.get('/figures/{figure_id}/png')
def png(project_id:str,file_id:str,run_id:str,figure_id:str,store:Store):
    bundle=bundle_for(store,project_id,file_id,run_id,figure_id)
    return Response(store.figure_png(bundle['figure']),media_type='image/png',headers={'Content-Disposition':f'attachment; filename="figure-{figure_id}.png"'})
@router.get('/figures/{figure_id}/package')
def package(project_id:str,file_id:str,run_id:str,figure_id:str,store:Store):
    bundle=bundle_for(store,project_id,file_id,run_id,figure_id);figure=bundle['figure'];buffer=BytesIO()
    with ZipFile(buffer,'w',ZIP_DEFLATED) as archive:
        archive.writestr('figure.png',store.figure_png(figure))
        description={'figure_number':1,'number_scope':'standalone_package','title':figure['title'],'caption':figure['caption'],'figure_id':figure['id'],'sha256':figure['sha256'],'source':figure['source'],'method':figure['method'],'configuration':bundle['configuration']['config'],'verification':figure['verification']}
        if 'presentation' in figure:description['presentation']=figure['presentation']
        archive.writestr('explanation.json',json.dumps(description,ensure_ascii=False,indent=2))
    return Response(buffer.getvalue(),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="figure-{figure_id}.zip"'})
