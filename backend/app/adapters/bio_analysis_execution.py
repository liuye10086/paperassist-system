"""Fenced, admitted output manifests with byte-exact durable retry staging."""
import copy
import hashlib
import os
import re
from pathlib import Path
from uuid import UUID,uuid5
from app.adapters.task_store import TaskStore,DatasetTaskAssets
from app.adapters.bio_objects import BioAnalysisObjects,BioFigureObjects
from app.domain.bioinformatics.contracts import canonical,conflict
from app.domain.bioinformatics.analysis_service import BioAnalysisService,latest_checkpoint
from app.domain.bioinformatics.service import append_checkpoint
from app.domain.storage_governance.deterministic import explicit_retry,authorize_rebuild
from app.domain.storage_governance.bio_manifest import admit_bio_manifest,settle_bio_manifest
from app.domain.tasks.waits import persist_wait
from app.core.config import local_config


def build_candidate(task,result,objects,stage):
    snapshot=task['input_snapshot'];identifier=snapshot.get('run_id') or snapshot['figure_version_id'];namespace=UUID(identifier)
    members=[];leaves=[];keys=set();total=0
    for output in result['outputs']:
        key=output['key'];path=Path(output['path']);size=output['size_bytes']
        if (not re.fullmatch('[A-Za-z0-9_-]{1,100}',key) or key in keys or path.is_symlink() or not path.is_file()
            or type(size) is not int or not 0<size<=268435456 or path.stat().st_size!=size):raise conflict('bio_output_invalid')
        value=hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
        if value.hexdigest()!=output['sha256']:raise conflict('bio_output_invalid')
        total+=size
        if len(members)>=256 or total>536870912:raise conflict('bio_resource_exceeded')
        member={k:output[k] for k in ('key','role','format','sha256','size_bytes')}
        if key in ('markers','markers_top'):member['role']='marker_table'
        elif member['role']=='marker_table':raise conflict('bio_output_invalid')
        member.update(id=str(uuid5(namespace,stage+':'+key)),object_key=f'{objects.prefix}/{identifier}/{output["sha256"]}.bin')
        objects.path(member['object_key']);members.append(member);leaves.append(dict(path=str(path),record={k:member[k] for k in ('object_key','sha256','size_bytes')}));keys.add(key)
    manifest=copy.deepcopy(result['manifest']);manifest['members']=[{k:v for k,v in m.items() if k!='object_key'} for m in members]
    if result.get('resources'):manifest['parent_resources']=result['resources']
    candidate=dict(schema_version=1,run_id=snapshot.get('run_id'),figure_version_id=snapshot.get('figure_version_id'),input_sha256=task['input_digest'],
        stage=stage,manifest=manifest,members=members,summary=result.get('summary',{}),checks=result.get('checks',{}),
        effective_params=result.get('effective_params',{}),steps=result.get('steps',[]))
    return candidate,leaves


class BioAnalysisExecution:
    def __init__(self,repository):self.repository=repository
    def service(self,task):return BioAnalysisService(DatasetTaskAssets(task['user_id'],self.repository.config,self.repository.assets.directory))
    def objects(self,task):return (BioFigureObjects if task['task_type']=='bio_figure' else BioAnalysisObjects)(self.repository.assets.directory)

    @staticmethod
    def renew_lease(db,lease):
        """Renew only a still-valid fenced lease, using the held writer connection."""
        from app.adapters.bio_lease import renew_bio_lease
        renew_bio_lease(db,lease)

    def load(self,lease):
        with self.repository.connection() as db:
            task=self.repository.require_lease(db,lease);self.repository.require_owner(db,task)
            cp=latest_checkpoint(db,task);payload=self.service(task).require_sources(db,task)
            return task,cp,payload

    def wait(self,lease,checkpoint,result):return self._prepare(lease,checkpoint,result,'qc')
    def publish_result(self,lease,checkpoint,result):
        return self._prepare(lease,checkpoint,result,checkpoint['state_json']['stage'])

    def _prepare(self,lease,checkpoint,result,stage):
        with self.repository.connection() as db:
            task=self.repository.require_lease(db,lease);self.repository.require_owner(db,task)
            current=latest_checkpoint(db,task)
            if current['id']!=checkpoint['id'] or current['next_node']!='check' or current['state_json']['stage']!=stage:raise conflict('bio_input_integrity_changed')
            self.service(task).require_sources(db,task)
        objects=self.objects(task);prepared,leaves=build_candidate(task,result,objects,stage)
        identifier=task['input_snapshot'].get('run_id') or task['input_snapshot']['figure_version_id']
        content=canonical(prepared['manifest']);manifest_ref=objects.describe(identifier,content,json=True);prepared['manifest_ref']=manifest_ref
        candidate_content=canonical(prepared);candidate_ref=objects.describe(identifier,candidate_content,json=True)
        unique={leaf['record']['object_key']:leaf for leaf in leaves}
        kind='bio_figure' if task['task_type']=='bio_figure' else 'bio_analysis';prefix=kind+':'+identifier+':'+stage+':'
        entries=[(kind,prefix+'leaf:'+leaf['record']['sha256'],leaf['record']) for leaf in unique.values()]
        entries.extend([(kind,prefix+'manifest',manifest_ref),(kind,prefix+'candidate',candidate_ref)])
        with self.repository.connection(write=True) as db:
            task=self.repository.require_lease(db,lease);self.repository.require_owner(db,task);current=latest_checkpoint(db,task)
            progress=lambda:self.renew_lease(db,lease)
            progress()
            if current['id']!=checkpoint['id']:raise conflict('bio_input_integrity_changed')
            self.service(task).require_sources(db,task)
            rows=admit_bio_manifest(db,self.repository.assets.directory,task,entries,progress=progress)
            state={**current['state_json'],'prepared':prepared,'prepared_leaves':list(unique.values()),'prepared_reservations':[dict(r) for r in rows],
                'prepared_candidate_ref':candidate_ref}
            # Only stable scalar reservation identity is serialized, never datetime.
            state['prepared_reservations']=[{k:r[k] for k in ('id','namespace','project_id','owner_id','task_id','kind','operation_key','object_key','size_bytes','sha256')} for r in rows]
            cp=append_checkpoint(db,task,'publish','publish',state,current)
            progress()
        return self.publish_existing(lease,cp)

    def _staging_path(self,task,path):
        configured=os.environ.get('PAPERASSIST_BIO_STAGING_DIR') or local_config().get('PAPERASSIST_BIO_STAGING_DIR')
        if not configured:raise conflict('bio_environment_unavailable')
        root=Path(configured).resolve();candidate=Path(path)
        if not candidate.is_absolute() or not candidate.resolve().is_relative_to(root/task['id']):raise conflict('bio_output_invalid')
        for part in [candidate,*candidate.parents]:
            if part.is_symlink() or getattr(part,'is_junction',lambda:False)():raise conflict('bio_output_invalid')
        return candidate

    def publish_existing(self,lease,checkpoint):
        with self.repository.connection(write=True) as db:
            task=self.repository.require_lease(db,lease);self.repository.require_owner(db,task);current=latest_checkpoint(db,task)
            progress=lambda:self.renew_lease(db,lease)
            progress()
            if current['id']!=checkpoint['id'] or current['next_node']!='publish':raise conflict('bio_input_integrity_changed')
            service=self.service(task);service.require_sources(db,task);state=current['state_json'];prepared=state.get('prepared')
            if not prepared or prepared['input_sha256']!=task['input_digest']:raise conflict('bio_input_integrity_changed')
            if explicit_retry(db,task):
                identifier=task['input_snapshot'].get('run_id') or task['input_snapshot']['figure_version_id'];kind='bio_figure' if task['task_type']=='bio_figure' else 'bio_analysis'
                authorize_rebuild(db,self.repository.assets.directory,task,allowed={kind:(self.objects(task).prefix,identifier,re.escape(kind+':'+identifier+':')+r'(?:qc|compute|figure):(?:leaf:[0-9a-f]{64}|manifest|candidate)')},progress=progress)
            progress()
        objects=self.objects(task)
        for leaf in state['prepared_leaves']:
            record=leaf['record']
            if objects.path(record['object_key']).exists():objects.read(record)
            else:objects.write(record,self._staging_path(task,leaf['path']).read_bytes())
        objects.write(prepared['manifest_ref'],canonical(prepared['manifest']))
        objects.write(state['prepared_candidate_ref'],canonical(prepared))
        with self.repository.connection(write=True) as db:
            task=self.repository.require_lease(db,lease);self.repository.require_owner(db,task);current=latest_checkpoint(db,task)
            progress=lambda:self.renew_lease(db,lease)
            progress()
            if current['id']!=checkpoint['id']:raise conflict('bio_input_integrity_changed')
            service=self.service(task);service.require_sources(db,task)
            settle_bio_manifest(db,self.repository.assets.directory,task,state['prepared_reservations'],progress=progress)
            progress()
            moment=max(self.repository.now(db),task['updated_at'])
            if prepared['stage']=='qc':
                previous=task['revision'];task.update(status='waiting_confirmation',phase='plan',revision=previous+1,updated_at=moment,reason_code='confirmation_required',error_code=None)
                clean={k:v for k,v in state.items() if not k.startswith('prepared')};clean.update(candidate=state['prepared_candidate_ref'],stage='qc')
                append_checkpoint(db,task,'await_confirmation','await_confirmation',clean,current)
                TaskStore.finish_attempt(db,task);TaskStore.update_task(db,task,previous);TaskStore.append_event(db,task,'waiting');persist_wait(db,task)
                return TaskStore.public_task(task)
            return service.publish(db,task,current,moment,prepared,progress=progress)
