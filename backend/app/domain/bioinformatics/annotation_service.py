"""Queued SingleR suggestions, published separately from human label sets."""
import csv
import io
import json
from app.adapters.bio_annotation_store import BioAnnotationStore
from app.adapters.bio_analysis_store import identity,base_row,insert,scoped_object,object_by_key,error,now
from app.domain.bioinformatics.analysis_service import engine_member,latest_checkpoint
from app.domain.bioinformatics.contracts import digest,canonical,conflict
from app.domain.bioinformatics.service import require_key,append_checkpoint
from .annotation_contracts import BioAnnotationSnapshot,validate_snapshot,input_version
from .single_cell_resources import SingleCellRAnalysisLimits


def candidate_annotations(rows):
    names=sorted({r['candidate_label'] for r in rows if r['candidate_label'] not in ('','unknown')})
    labels=[dict(id='candidate-'+digest(name)[:20],name=name,status='proposed',note='SingleR machine suggestion; requires human review.',cluster_ids=[],cell_ids=[]) for name in names]
    lookup={l['name']:l['id'] for l in labels};assignments=[]
    for row in rows:
        candidate=row['candidate_label'];pruned=row['pruned_label']
        status='unknown' if candidate not in lookup else 'uncertain' if pruned=='unknown' else 'proposed'
        assignments.append(dict(barcode=row['barcode'],label_id=lookup.get(candidate),status=status,region_ids=[],candidate_label=candidate,
            pruned_label=pruned,delta_next=float(row['delta_next']),delta_median=float(row['delta_median'])))
    return labels,assignments


def reference_catalog():
    from app.adapters.single_cell_r.annotation import reference_catalog as catalog
    return catalog()


class BioAnnotationService(BioAnnotationStore):
    def _reference(self,reference_id):
        reference=next((r for r in reference_catalog() if r['reference_id']==reference_id),None)
        if not reference or not reference.get('available'):raise error('bio_environment_unavailable')
        return {k:v for k,v in reference.items() if k not in ('available','reason')}

    def create(self,project,request,key):
        from .single_cell_settings import runtime_identity
        require_key(key);sha=digest(request.model_dump(mode='json'));identifier=identity(project,'annotation-run',key)
        with self.store.connection() as db:
            self.store.require_project(db,project)
            replay=db.execute('SELECT * FROM tasks WHERE id=%s AND project_id=%s',(identifier,project)).fetchone()
            if replay:
                if replay['user_id']!=self.store.user_id or replay['input_snapshot'].get('request_digest')!=sha:raise error('task_idempotency_conflict')
                return self.get_run(project,identifier)
            _,manifest,_=self._parent(db,project,request.parent_processed_source)
        runtime=runtime_identity()
        if not runtime['available']:raise error('bio_environment_unavailable')
        reference=self._reference(request.reference_id)
        value=BioAnnotationSnapshot(schema_version=1,kind='bio_annotation',workflow_version='bio_annotation_v1',project_id=project,run_id=identifier,name=request.name,
            parent_processed_source=request.parent_processed_source,reference=reference,seed=request.seed,request_digest=sha,
            engine_version=runtime['engine_version'],environment_digest=runtime['environment_digest'],code_digest=runtime['code_digest'],
            output_language=manifest.get('params',{}).get('output_language','en'),limits=SingleCellRAnalysisLimits()).model_dump(mode='json')
        with self.store.connection(write=True) as db:
            self.store.require_project(db,project)
            from app.adapters.bio_analysis_store import lock
            lock(db,project,'annotation-run:'+key)
            replay=db.execute('SELECT * FROM tasks WHERE id=%s AND project_id=%s',(identifier,project)).fetchone()
            if replay:
                if replay['input_snapshot'].get('request_digest')!=sha:raise error('task_idempotency_conflict')
            else:
                self._parent(db,project,request.parent_processed_source)
                moment=now();task=dict(id=identifier,project_id=project,user_id=self.store.user_id,task_type='bio_annotation',idempotency_key='bio_annotation:'+identifier,
                    input_digest=digest(value),input_snapshot=value,workflow_version='bio_annotation_v1',status='queued',phase='compute',revision=1,current_attempt=0,
                    reason_code=None,created_at=moment,updated_at=moment)
                self.store.insert_task(db,task,validated_file_ids=request.parent_processed_source.raw_source.source_file_ids)
                append_checkpoint(db,task,'check','check',dict(input_version=input_version(task),stage='annotation',candidate=None,decision_id=None,result_id=None))
                self.store.append_event(db,task,'created');self.store.enqueue(db,task)
        return self.get_run(project,identifier)

    def _parent(self,db,project,parent):
        if hasattr(parent,'model_dump'):parent=parent.model_dump(mode='json')
        row,manifest,members=self.processed_record(db,project,parent['processed_dataset_version_id'])
        if parent['project_id']!=project or self.processed_source(row,manifest)!=parent or manifest.get('assay')!='single_cell':raise conflict('bio_input_integrity_changed')
        _,raw,_=self.raw(db,project,parent['raw_source'])
        samples=raw.get('samples',[])
        if not samples or any(s.get('species_taxon_id')!=9606 for s in samples):raise error('bio_annotation_invalid',422)
        return row,manifest,members

    def require_sources(self,db,task,*,runtime=True):
        from .single_cell_settings import runtime_identity
        value=validate_snapshot(task);project=task['project_id'];self.store.require_project(db,project)
        if task['user_id']!=self.store.user_id:raise conflict('bio_input_integrity_changed')
        if runtime:
            environment=runtime_identity()
            if not environment['available']:raise error('bio_environment_unavailable')
            if any(value[k]!=environment[k] for k in ('engine_version','environment_digest','code_digest')):raise conflict('bio_input_integrity_changed')
            if value['reference']!=self._reference(value['reference']['reference_id']):raise conflict('bio_input_integrity_changed')
        _,manifest,members=self._parent(db,project,value['parent_processed_source'])
        _,raw,raw_members=self.raw(db,project,value['parent_processed_source']['raw_source'])
        return dict(raw=dict(manifest=raw,members={m['key']:engine_member(m,self.raw_store.objects.path(m['object_key'])) for m in raw_members}),
            processed=dict(manifest=manifest,members={m['key']:engine_member(m,self.objects.path(m['object_key'])) for m in members}),
            config=dict(reference_id=value['reference']['reference_id'],seed=value['seed'],species='Homo sapiens',gene_id_type='ensembl_gene_id',label_level='main'),reference=value['reference'],
            identity=dict(processed_source=value['parent_processed_source'],raw_source=value['parent_processed_source']['raw_source'],
                environment_digest=value['environment_digest'],code_digest=value['code_digest'],output_language=value['output_language']))

    def get_run(self,project,identifier):
        with self.store.connection() as db:
            self.store.require_project(db,project);task=self.store.require_task(db,identifier)
            if task['project_id']!=project or task['task_type']!='bio_annotation':raise error('bio_annotation_not_found',404)
            value=validate_snapshot(task);cp=latest_checkpoint(db,task);result_id=cp['state_json'].get('result_id')
        return dict(id=identifier,name=value['name'],parent_processed_source=value['parent_processed_source'],reference_id=value['reference']['reference_id'],
            task=self.store.public_task(task),result=dict(set_id=result_id,version_id=result_id) if result_id else None)

    def list_runs(self,project,identifier):
        with self.store.connection() as db:
            self.processed_record(db,project,identifier)
            rows=db.execute("""SELECT id FROM tasks WHERE project_id=%s AND user_id=%s AND task_type='bio_annotation'
                AND input_snapshot #>> '{parent_processed_source,processed_dataset_version_id}'=%s ORDER BY created_at DESC,id LIMIT 100""",
                (project,self.store.user_id,identifier)).fetchall()
        return dict(items=[self.get_run(project,r['id']) for r in rows])

    def request_receipt(self,project,key):
        require_key(key);identifier=identity(project,'annotation-run',key)
        with self.store.connection() as db:
            self.store.require_project(db,project)
            task=db.execute("SELECT * FROM tasks WHERE id=%s AND project_id=%s AND user_id=%s AND task_type='bio_annotation'",
                (identifier,project,self.store.user_id)).fetchone()
            if not task:raise error('bio_request_not_found',404)
            value=validate_snapshot(task)
        return dict(kind='annotation_run',id=identifier,root_id=None,request_digest=value['request_digest'],task_id=identifier)

    def publish(self,db,task,checkpoint,moment,prepared,*,progress=None):
        self.require_sources(db,task);value=validate_snapshot(task)
        if prepared['stage']!='annotation' or prepared['input_sha256']!=task['input_digest']:raise conflict('bio_input_integrity_changed')
        namespace=value['run_id'];candidate=next((m for m in prepared['members'] if m['key']=='annotation_candidates'),None)
        if not candidate:raise conflict('bio_output_invalid')
        rows=list(csv.DictReader(io.StringIO(self.annotation_objects.read(candidate).decode('utf-8')),delimiter='\t'))
        labels,assignments=candidate_annotations(rows)
        if len(labels)>100:raise error('bio_resource_exceeded')
        # These documents were admitted with the same aggregate output manifest.
        geometry=next(m for m in prepared['members'] if m['key']=='annotation_geometry')
        assigned=next(m for m in prepared['members'] if m['key']=='annotation_assignments')
        geometry_obj=object_by_key(db,task['project_id'],task['user_id'],geometry);assignments_obj=object_by_key(db,task['project_id'],task['user_id'],assigned)
        parent=value['parent_processed_source'];checks=dict(assigned=sum(r['status']=='proposed' for r in assignments),
            uncertain=sum(r['status']=='uncertain' for r in assignments),unknown=sum(r['status']=='unknown' for r in assignments),ambiguous=0,
            coordinate_space='cell',biological_validation=False,candidate_only=True)
        insert(db,'bio_annotation_sets',{**base_row(namespace,task['project_id'],task['user_id']),'name':value['name'],'revision':1,'current_version_id':None,'updated_at':moment,
            'raw_dataset_version_id':parent['raw_source']['dataset_version_id'],'processed_dataset_version_id':parent['processed_dataset_version_id']})
        insert(db,'bio_annotation_versions',{**base_row(namespace,task['project_id'],task['user_id']),'set_id':namespace,'version':1,'parent_id':None,
            'raw_dataset_version_id':parent['raw_source']['dataset_version_id'],'processed_dataset_version_id':parent['processed_dataset_version_id'],
            'geometry_object_id':geometry_obj['id'],'geometry_sha256':geometry['sha256'],'assignments_object_id':assignments_obj['id'],'assignments_sha256':assigned['sha256'],
            'labels_json':labels,'checks_json':checks,'request_key':'SingleR:'+namespace,'request_digest':value['request_digest']})
        db.execute('UPDATE bio_annotation_sets SET current_version_id=%s WHERE id=%s',(namespace,namespace))
        from app.adapters.task_store import TaskStore
        previous=task['revision'];task.update(status='succeeded',phase='verify',revision=previous+1,updated_at=moment,reason_code=None,error_code=None)
        append_checkpoint(db,task,'done','done',{**checkpoint['state_json'],'result_id':namespace},checkpoint)
        TaskStore.finish_attempt(db,task);TaskStore.update_task(db,task,previous);TaskStore.append_event(db,task,'succeeded')
        return TaskStore.public_task(task)


def source_current(db,task):
    try:
        from app.domain.bioinformatics.analysis_service import service_for
        service=service_for(db,task)
        BioAnnotationService(service.assets).require_sources(db,task,runtime=False)
        return True
    except Exception:return False


def recovery_actions(db,task):
    if task['status']=='failed' and task.get('error_code') in {'storage_unavailable','task_worker_interrupted','storage_quota_exceeded','storage_disk_insufficient','storage_accounting_unknown','bio_environment_unavailable'} and source_current(db,task):return ['retry']
    return []


def retry_in_transaction(store,db,task,expected_revision):
    if task['revision']!=expected_revision or 'retry' not in recovery_actions(db,task):raise error('task_transition_invalid')
    from app.adapters.task_store import TaskStore
    previous=task['revision'];task.update(status='queued',revision=previous+1,updated_at=now(),reason_code='retry_requested',error_code=None)
    TaskStore.update_task(db,task,previous);task['_retry_reason']='manual_retry';TaskStore.append_event(db,task,'requeued');TaskStore.enqueue(db,task)
    return TaskStore.public_task(task)
