"""SQL-only frozen bio task identities; no asset IO or current runtime lookup."""
from app.adapters.bio_analysis_store import scoped_object
from app.domain.bioinformatics.analysis_contracts import validate_snapshot,BioProcessedDatasetSourceV1
from app.domain.bioinformatics.analysis_service import latest_checkpoint
from app.domain.bioinformatics.contracts import canonical,digest,validate_snapshot as import_snapshot
from app.domain.bioinformatics.service import BioDatasetService


def validate_bio_task_source(db,task):
    snapshot=validate_snapshot(task);project=task['project_id'];owner=task['user_id']
    actual=db.execute('SELECT owner_id FROM projects WHERE id=%s',(project,)).fetchone()
    if not actual or actual['owner_id']!=owner:raise ValueError('Task owner differs')
    latest_checkpoint(db,task)
    def row(table,identifier):
        # Table names below are internal literals, never supplied by snapshots.
        value=db.execute('SELECT * FROM '+table+' WHERE id=%s AND project_id=%s',(identifier,project)).fetchone()
        if not value or value['created_by']!=owner:raise ValueError('Source scope differs')
        return value
    def object_hash(identifier,sha,size=None):
        value=scoped_object(db,project,owner,identifier)
        if value['sha256']!=sha or size is not None and value['size_bytes']!=size:raise ValueError('Object identity differs')
    if task['task_type']=='bio_analysis':
        raw_source=snapshot['raw_source']
        run=row('bio_analysis_runs',snapshot['run_id']);recipe=row('bio_analysis_recipe_versions',snapshot['recipe_version_id'])
        if (run['task_id']!=task['id'] or run['source_digest']!=task['input_digest']
            or run['recipe_version_id']!=recipe['id'] or run['raw_dataset_version_id']!=raw_source['dataset_version_id']
            or run['expected_setup_revision']!=snapshot['expected_setup_revision']
            or recipe['setup_id']!=snapshot['setup_id'] or recipe['params_json']!=snapshot['params']
            or recipe['raw_dataset_version_id']!=raw_source['dataset_version_id']
            or any(recipe[k]!=snapshot[k] for k in ('observation_map_version_id','design_version_id'))):
            raise ValueError('Frozen recipe/run differs')
        if run['execution_snapshot_sha256']!=task['input_digest']:raise ValueError('Execution snapshot differs')
        object_hash(run['execution_snapshot_object_id'],task['input_digest'],len(canonical(snapshot)))
        if snapshot['observation_map_version_id']:
            mapping=row('bio_observation_map_versions',snapshot['observation_map_version_id'])
            if mapping['raw_dataset_version_id']!=raw_source['dataset_version_id'] or mapping['design_version_id']!=snapshot['design_version_id']:
                raise ValueError('Mapping source differs')
            object_hash(mapping['mapping_object_id'],mapping['mapping_sha256'])
        if snapshot['design_version_id']:row('research_design_versions',snapshot['design_version_id'])
        if task['status']=='succeeded':
            published=row('bio_processed_dataset_versions',task['result_bio_processed_dataset_version_id'])
            if (published['task_id']!=task['id'] or published['run_id']!=run['id'] or run['processed_dataset_version_id']!=published['id']
                or published['raw_dataset_version_id']!=raw_source['dataset_version_id'] or published['recipe_version_id']!=recipe['id']
                or any(published[k]!=snapshot[k] for k in ('engine_version','environment_digest','code_digest'))):
                raise ValueError('Processed publication differs')
    else:
        source=snapshot['processed_source'];raw_source=source['raw_source']
        figure=row('bio_figure_versions',snapshot['figure_version_id'])
        processed=row('bio_processed_dataset_versions',source['processed_dataset_version_id'])
        parent=db.execute('SELECT * FROM tasks WHERE id=%s',(processed['task_id'],)).fetchone()
        if not parent or parent['task_type']!='bio_analysis' or parent['status']!='succeeded':raise ValueError('Processed producer differs')
        validate_bio_task_source(db,parent)
        expected=BioProcessedDatasetSourceV1(project_id=project,processed_dataset_version_id=processed['id'],
            analysis_run_id=processed['run_id'],raw_source=parent['input_snapshot']['raw_source'],recipe_version_id=processed['recipe_version_id'],
            manifest_sha256=processed['manifest_sha256'],engine_version=processed['engine_version'],environment_digest=processed['environment_digest']).model_dump(mode='json')
        if (source!=expected or figure['task_id']!=task['id'] or figure['processed_dataset_version_id']!=processed['id']
            or figure['config_json']!=snapshot['config'] or figure['config_sha256']!=digest(snapshot['config'])
            or figure['annotation_version_id']!=snapshot['annotation_version_id']):raise ValueError('Frozen figure source differs')
        object_hash(processed['manifest_object_id'],processed['manifest_sha256'])
        if snapshot['annotation_version_id']:
            annotation=row('bio_annotation_versions',snapshot['annotation_version_id'])
            if annotation['processed_dataset_version_id']!=processed['id'] or annotation['raw_dataset_version_id']!=raw_source['dataset_version_id']:
                raise ValueError('Annotation source differs')
            for key in ('geometry','assignments'):object_hash(annotation[key+'_object_id'],annotation[key+'_sha256'])
        if task['status']=='succeeded':
            if task['result_bio_figure_version_id']!=figure['id']:raise ValueError('Figure publication differs')
            object_hash(figure['manifest_object_id'],figure['manifest_sha256'])
    raw=row('bio_dataset_versions',raw_source['dataset_version_id'])
    producer=db.execute('SELECT * FROM tasks WHERE id=%s',(raw['task_id'],)).fetchone()
    if (not producer or producer['status']!='succeeded' or producer['project_id']!=project or producer['user_id']!=owner
        or producer['result_bio_dataset_version_id']!=raw['id']):raise ValueError('Raw producer differs')
    frozen=import_snapshot(producer)
    if raw['import_id']!=frozen['import_id'] or raw_source!=BioDatasetService.source(raw,[f['id'] for f in frozen['files']]):
        raise ValueError('Frozen raw source differs')
    object_hash(raw['manifest_object_id'],raw['manifest_sha256'])


def audit_bio_task_sources(db,limit=200):
    if type(limit) is not int or not 1<=limit<=1000:raise ValueError('Invalid audit limit')
    rows=db.execute("SELECT * FROM tasks WHERE task_type IN ('bio_analysis','bio_figure') ORDER BY id LIMIT %s",(limit,)).fetchall()
    invalid=0
    for task in rows:
        try:validate_bio_task_source(db,task)
        except Exception:invalid+=1
    total=db.execute("SELECT count(*) AS n FROM tasks WHERE task_type IN ('bio_analysis','bio_figure')").fetchone()['n']
    return [dict(table='tasks',column='bio_typed_sources',rows=len(rows),total=total,truncated=total>len(rows),invalid=invalid)]
