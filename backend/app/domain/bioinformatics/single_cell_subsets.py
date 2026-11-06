"""Parent-frozen cell selections; reuse the existing direct analysis pipeline."""
import csv
import io
from app.adapters.bio_analysis_store import error
from .contracts import conflict,digest


def resolve_selection(rows,cluster_ids,cell_ids):
    retained=[r for r in rows if str(r.get('kept','')).lower()=='true']
    known={r['barcode'] for r in retained};clusters={r.get('cluster') for r in retained}
    if not (cluster_ids or cell_ids) or not set(cell_ids)<=known or not set(cluster_ids)<=clusters:
        raise error('bio_annotation_invalid',422)
    selected=[r['barcode'] for r in retained if r['barcode'] in set(cell_ids) or r.get('cluster') in set(cluster_ids)]
    if not selected or len(set(selected))!=len(selected):raise error('bio_annotation_invalid',422)
    return selected


def validate_parent(service,db,project,parent,cluster_ids,cell_ids):
    if hasattr(parent,'model_dump'):parent=parent.model_dump(mode='json')
    row,manifest,members=service.processed_record(db,project,parent['processed_dataset_version_id'])
    if parent['project_id']!=project or service.processed_source(row,manifest)!=parent or manifest.get('assay')!='single_cell':
        raise conflict('bio_input_integrity_changed')
    observations=next((m for m in members if m['key']=='observations'),None)
    if observations is None:raise conflict('bio_input_integrity_changed')
    rows=list(csv.DictReader(io.StringIO(service.objects.read(observations).decode('utf-8')),delimiter='\t'))
    return row,manifest,members,resolve_selection(rows,cluster_ids,cell_ids)


def start_subset(service,project,request,key):
    from .service import require_key
    from .single_cell_contracts import SingleCellAnalysisStartRequest,SingleCellSetupRequest
    from .analysis_contracts import BioAnalysisRunRequest
    require_key(key)
    request_sha=digest(request.model_dump(mode='json'))
    with service.store.connection() as db:
        service.store.require_project(db,project)
        replay=db.execute('SELECT * FROM bio_analysis_runs WHERE project_id=%s AND request_key=%s',(project,key)).fetchone()
        if replay:
            if replay['request_digest']!=request_sha:raise error('task_idempotency_conflict')
            return dict(id=replay['id'],task=service.store.public_task(service.store.require_task(db,replay['task_id'])),
                recipe_version_id=replay['recipe_version_id'],expected_setup_revision=replay['expected_setup_revision'])
        parent,_,_,selected=validate_parent(service,db,project,request.parent_processed_source,request.cluster_ids,request.cell_ids)
        parent_recipe=service.require(db,'bio_analysis_recipe_versions',project,parent['recipe_version_id'])
    params=request.params.model_copy(deep=True)
    params.cell_labels=[]
    params.doublet.enabled=False;params.doublet.exclude_predicted=False;params.decontx.enabled=False
    config=SingleCellAnalysisStartRequest(name=request.name,raw_source=request.parent_processed_source.raw_source,
        observation_map_version_id=request.observation_map_version_id or parent_recipe['observation_map_version_id'],
        design_version_id=request.design_version_id or parent_recipe['design_version_id'],params=params)
    recipe=service.save_recipe(project,SingleCellSetupRequest(**config.model_dump(),recipe_code='single_cell_explore_v1',expected_revision=0),
        'single-cell-subset-recipe:'+digest(key))
    selection=dict(parent_processed_source=request.parent_processed_source.model_dump(mode='json'),cluster_ids=request.cluster_ids,cell_ids=request.cell_ids,resolved_cell_ids=selected)
    return service.create(project,BioAnalysisRunRequest(raw_source=config.raw_source,recipe_version_id=recipe['id'],expected_setup_revision=recipe['revision']),
        key,execution_mode='direct',request_digest=request_sha,subset=selection)
