"""Frozen delivery facts and existing fenced packaging tasks."""
from uuid import uuid4
import json
from psycopg.types.json import Jsonb
from app.adapters.research_intake_store import latest_confirmed_requirement
from app.adapters.research_results_store import ResearchResultsStore,identity,now,invalid
from app.domain.bioinformatics.contracts import digest
from app.core.exceptions import StorageError
from app.domain.research_intake.service import request_key
from app.domain.bioinformatics.service import append_checkpoint
from .contracts import SnapshotWrite,Selection,AcceptanceWrite
from .sources import resolve_members,require_document_delivery


def insert(db,table,value):
    if table not in ('delivery_snapshots','delivery_acceptance_events'):raise ValueError()
    db.execute('INSERT INTO '+table+'('+','.join(value)+') VALUES('+','.join(['%s']*len(value))+')',tuple(Jsonb(v) if isinstance(v,(dict,list)) else v for v in value.values()))


def normalized(value):return json.loads(json.dumps(value,default=lambda x:x.isoformat()))


def analysis_member_supported(kind, format):
    """Keep system-generated reconstruction data out of customer releases."""
    formats = {
        'research_report_member': ('docx', 'xlsx'),
        'research_figure_member': ('png', 'tiff', 'jpg', 'jpeg', 'svg'),
    }
    return kind == 'file' or format in formats.get(kind, ())


class DeliveryService(ResearchResultsStore):
    def scope(self,db,project,delivery):
        self.store.require_project(db,project)
        row=db.execute('SELECT * FROM research_deliveries WHERE id=%s AND project_id=%s',(delivery,project)).fetchone()
        if not row or (getattr(self.assets, 'assignment', None) is not None and row['kind'] != 'analysis'):
            raise invalid('research_source_not_found',404)
        return dict(row)

    def row(self,db,project,delivery,identifier):
        self.scope(db,project,delivery)
        row=db.execute('SELECT * FROM delivery_snapshots WHERE id=%s AND project_id=%s AND delivery_id=%s AND user_id=%s',(identifier,project,delivery,self.store.user_id)).fetchone()
        if not row:raise invalid('research_source_not_found',404)
        if digest(row['snapshot_json'])!=row['sha256']:raise invalid()
        return dict(row)

    def view(self,row):
        value=dict(row['snapshot_json'],sha256=row['sha256'])
        project=row['project_id'];delivery=row['delivery_id'];identifier=row['id']
        base=f'/api/v1/projects/{project}/deliveries/{delivery}/snapshots/{identifier}'
        value['members']=[dict(m,download_url=base+'/members/'+m['id']+'/download') for m in value['members']]
        return value

    def get(self,project,delivery,identifier):
        with self.store.connection() as db:return self.view(self.row(db,project,delivery,identifier))

    def listing(self,project,delivery,key=None):
        with self.store.connection() as db:
            self.scope(db,project,delivery)
            rows=db.execute('SELECT * FROM delivery_snapshots WHERE project_id=%s AND delivery_id=%s AND user_id=%s AND (%s::text IS NULL OR request_key=%s) ORDER BY revision DESC',(project,delivery,self.store.user_id,key,key)).fetchall()
            if key and not rows:raise invalid('research_source_not_found',404)
            return self.view(rows[0]) if key else dict(items=[self.view(row) for row in rows])

    def prepare_snapshot(self,db,project,delivery,request):
        registered=self.scope(db,project,delivery)
        assigned = getattr(self.assets, 'assignment', None) is not None
        if assigned:
            latest = latest_confirmed_requirement(db, project)
            if latest is None or latest['id'] != request.requirement_version_id:
                raise StorageError('research_revision_conflict', '交付需关联客户最新正式需求。', 409)
        requirement=db.execute('SELECT * FROM research_requirement_versions WHERE id=%s AND project_id=%s',(request.requirement_version_id,project)).fetchone()
        if not requirement or digest(requirement['content_json'])!=requirement['sha256']:raise invalid('research_source_not_found',404)
        if registered['kind'] not in requirement['content_json']['services']:raise invalid()
        parent=db.execute('SELECT * FROM delivery_snapshots WHERE delivery_id=%s ORDER BY revision DESC LIMIT 1',(delivery,)).fetchone()
        if (parent['revision'] if parent else 0)!=request.expected_revision or (parent['id'] if parent else None)!=request.parent_snapshot_id:raise invalid('research_revision_conflict')
        if (not parent and request.stage!='first') or (parent and request.stage=='first'):raise invalid('research_revision_conflict')
        round_binding=dict(status='not_applicable',reason=request.opinion_round)
        if bool(request.opinion_round_id)!=bool(request.opinion_round_event_id):raise invalid()
        if request.opinion_round_id:
            from app.domain.review_rounds.service import ReviewRoundService
            round_service=ReviewRoundService(self.assets)
            fixed=round_service.round_row(db,project,request.opinion_round_id)
            event=db.execute('SELECT * FROM review_round_events WHERE id=%s AND round_id=%s AND project_id=%s AND user_id=%s',(request.opinion_round_event_id,fixed['id'],project,self.store.user_id)).fetchone()
            if not event:raise invalid('research_source_not_found',404)
            round_service.validate_event(event)
            root=db.execute('SELECT * FROM manuscripts WHERE id=%s AND project_id=%s AND user_id=%s',(fixed['snapshot_json']['manuscript']['id'],project,self.store.user_id)).fetchone()
            if not root or root['delivery_id']!=delivery:raise invalid()
            selected_roots={m.manuscript_id for m in request.members if m.kind=='manuscript_export'}
            if selected_roots and selected_roots!={root['id']}:raise invalid()
            round_binding=dict(status='fixed_existing_event',round_id=fixed['id'],round_number=fixed['round_number'],round_sha256=fixed['snapshot_sha256'],event_id=event['id'],revision=event['revision'],event_sha256=event['snapshot_sha256'],manuscript=fixed['snapshot_json']['manuscript'])
        members,raws,files=resolve_members(self,db,project,registered,request.members,request.mode)
        if assigned and any(not analysis_member_supported(member['selection']['kind'], member['format']) for member in members):
            raise StorageError('research_source_unsupported', '请仅选择分析报告、图件或可交付的附件。', 422)
        formats={m['format'] for m in members};gaps=['required_format:'+x for x in sorted(set(request.required_formats)-formats)]
        quality=list(request.quality_items)
        for m in members:
            is_figure=bool(m['image']) and (m['format'] in ('png','tiff','jpg','jpeg','svg') or m['selection']['kind']=='research_figure_member' or m['selection'].get('figure_mapping') is not None)
            if is_figure:
                if m['image']['mapping_status']=='pending_verification':quality.append('figure_mapping:'+m['id'])
                for key in ('text_verification','font_verification','semantic_verification'):
                    if m['image'].get(key) in ('unknown','unverified','pending'):quality.append(key+':'+m['id'])
            if m['source_metadata'].get('scientific_binding_status')=='unverified':quality.append('source_alignment:'+m['id'])
            if m['source_metadata'].get('source_quality_unresolved'):quality.append('source_quality:'+m['id'])
            inherited=m['source_metadata'].get('presentation') or {}
            if inherited.get('quality',{}).get('real_compliance')=='pending':quality.append('source_quality:'+m['id'])
        old=parent['snapshot_json']['members'] if parent else [];oldmap={m['id']:m for m in old};newmap={m['id']:m for m in members}
        changes=dict(added=sorted(set(newmap)-set(oldmap)),removed=sorted(set(oldmap)-set(newmap)),replaced=[],reason=request.change_note)
        return dict(schema_version=1,project_id=project,delivery_id=delivery,delivery_kind=registered['kind'],revision=request.expected_revision+1,parent_snapshot_id=request.parent_snapshot_id,stage=request.stage,requirement_version_id=request.requirement_version_id,requirement_sha256=requirement['sha256'],mode=request.mode,required_formats=sorted(set(request.required_formats)),change_note=request.change_note,opinion_round=request.opinion_round,opinion_round_binding=round_binding,source_notices=[dict(member_id=m['id'],notices=m['source_metadata'].get('source_notices',[])) for m in members if m['source_metadata'].get('source_notices')],members=members,gaps=gaps,quality_items=sorted(set(quality)),completeness='missing_required' if gaps else 'quality_unresolved' if quality else 'complete',changes=changes,source_file_ids=files,acceptance='not_recorded'),raws

    def preview(self,project,delivery,request):
        with self.store.connection() as db:return self.prepare_snapshot(db,project,delivery,request)[0]

    def freeze(self,project,delivery,request,key):
        request_key(key);body=request.model_dump(mode='json');sha=digest(body)
        with self.store.connection(write=True) as db:
            self.scope(db,project,delivery);self.lock(db,project,'delivery:'+delivery)
            replay=db.execute('SELECT * FROM delivery_snapshots WHERE delivery_id=%s AND request_key=%s',(delivery,key)).fetchone()
            if replay:
                if replay['request_digest']!=sha:raise invalid('research_idempotency_conflict')
                return self.view(replay),200
            snapshot,_=self.prepare_snapshot(db,project,delivery,request);identifier=identity(project,'delivery-snapshot',delivery+':'+key);moment=now();snapshot.update(id=identifier,created_at=moment.isoformat())
            from app.domain.storage_governance.guards import require_scope_open
            require_scope_open(db,project,file_ids=snapshot['source_file_ids'])
            row=dict(id=identifier,project_id=project,delivery_id=delivery,user_id=self.store.user_id,revision=snapshot['revision'],parent_snapshot_id=request.parent_snapshot_id,requirement_version_id=request.requirement_version_id,stage=request.stage,request_key=key,request_digest=sha,snapshot_json=normalized(snapshot),sha256=digest(snapshot),created_at=moment)
            insert(db,'delivery_snapshots',row)
            return self.view(row),201

    def candidates(self,project,delivery):
        with self.store.connection() as db:
            self.scope(db,project,delivery);items=[]
            assigned = getattr(self.assets, 'assignment', None) is not None
            for family in ('report','figure'):
                kind = 'research_' + family + '_member'
                for row in db.execute('SELECT m.*,v.root_id,v.revision FROM research_'+family+'_members m JOIN research_'+family+'_versions v ON v.id=m.'+family+"_version_id JOIN tasks t ON t.id=v.task_id WHERE m.project_id=%s AND m.user_id=%s AND t.status='succeeded' ORDER BY v.created_at DESC,m.key",(project,self.store.user_id)):
                    if row['format']=='pdf' or (assigned and not analysis_member_supported(kind, row['format'])):continue
                    items.append(dict(selection=dict(kind=kind,version_id=row[family+'_version_id'],member_id=row['id']),label=f"{family} r{row['revision']} {row['key']}",format=row['format'],status='succeeded',sha256=row['sha256']))
            if not assigned:
                for row in db.execute("SELECT e.*,v.manuscript_id,v.snapshot_json FROM manuscript_exports e JOIN manuscript_versions v ON v.id=e.version_id JOIN manuscripts m ON m.id=v.manuscript_id JOIN tasks t ON t.id=e.task_id WHERE v.project_id=%s AND v.user_id=%s AND (m.delivery_id=%s OR m.delivery_id IS NULL) AND t.status='succeeded' ORDER BY e.created_at DESC",(project,self.store.user_id,delivery)):
                    try:require_document_delivery(self,db,project,delivery,row['manuscript_id'])
                    except StorageError as exc:
                        if exc.code not in ('research_source_conflict','research_writing_unavailable'):raise
                        continue
                    task=self.store.require_task(db,row['task_id']);binding=task['input_snapshot'].get('presentation',{}).get('binding',{})
                    items.append(dict(selection=dict(kind='manuscript_export',version_id=row['version_id'],manuscript_id=row['manuscript_id'],export_id=row['id']),label=(row['metadata_json'] or {}).get('filename') or row['id'],format='docx',status='succeeded',language=binding.get('language_view',row['snapshot_json']['output_language']),review_mode=binding.get('review_mode','identified'),presentation_id=binding.get('presentation_version_id')))
            for row in db.execute('SELECT * FROM files WHERE project_id=%s ORDER BY uploaded_at DESC,id',(project,)):
                items.append(dict(selection=dict(kind='file',file_id=row['id']),label=row['filename'],format=row['filename'].rsplit('.',1)[-1].lower(),status='existing_upload',blind_eligible=False))
            if assigned:
                latest = latest_confirmed_requirement(db, project)
                requirements = [dict(id=latest['id'], version=latest['version'], sha256=latest['sha256'])] if latest else []
                return dict(items=items, requirements=requirements, opinion_rounds=[])
            requirements=[dict(id=r['id'],version=r['version'],sha256=r['sha256']) for r in db.execute('SELECT id,version,sha256 FROM research_requirement_versions WHERE project_id=%s ORDER BY version DESC',(project,))]
            rounds=[]
            for round_row in db.execute("SELECT r.* FROM review_rounds r JOIN manuscripts m ON m.id=(r.snapshot_json->'manuscript'->>'id') WHERE r.project_id=%s AND r.user_id=%s AND m.delivery_id=%s ORDER BY r.round_number DESC",(project,self.store.user_id,delivery)):
                if digest(round_row['snapshot_json'])!=round_row['snapshot_sha256']:raise invalid()
                events=[]
                for event in db.execute('SELECT * FROM review_round_events WHERE round_id=%s AND project_id=%s AND user_id=%s ORDER BY revision DESC',(round_row['id'],project,self.store.user_id)):
                    if digest(event['snapshot_json'])!=event['snapshot_sha256']:raise invalid()
                    events.append(dict(id=event['id'],revision=event['revision'],kind=event['kind'],sha256=event['snapshot_sha256']))
                rounds.append(dict(id=round_row['id'],round_number=round_row['round_number'],label=round_row['snapshot_json']['title'],events=events))
            return dict(items=items,requirements=requirements,opinion_rounds=rounds)

    def member(self,project,delivery,identifier,member_id):
        with self.store.connection() as db:
            return self.member_bytes(db,self.row(db,project,delivery,identifier),member_id)

    def member_bytes(self,db,row,member_id):
        snapshot=row['snapshot_json'];member=next((m for m in snapshot['members'] if m['id']==member_id),None)
        if not member:raise invalid('research_source_not_found',404)
        project=row['project_id'];registered=self.scope(db,project,row['delivery_id'])
        current,raws,_=resolve_members(self,db,project,registered,[Selection.model_validate(member['selection'])],snapshot['mode'],frozen_members=[member])
        if current[0]!=member:raise invalid()
        return member,raws[0]

    def acceptance(self,project,delivery,identifier,request,key):
        request_key(key);hashed=digest(request.model_dump(mode='json'))
        with self.store.connection(write=True) as db:
            self.lock(db,project,'delivery-acceptance:'+identifier+':'+key)
            row=self.row(db,project,delivery,identifier)
            if request.snapshot_sha256!=row['sha256']:raise invalid()
            replay=db.execute('SELECT * FROM delivery_acceptance_events WHERE snapshot_id=%s AND request_key=%s',(identifier,key)).fetchone()
            if replay:
                if replay['request_digest']!=hashed:raise invalid('research_idempotency_conflict')
                return replay['event_json'],200
            if (request.kind=='correction')!=(request.corrects_event_id is not None):raise invalid()
            if request.corrects_event_id and not db.execute('SELECT 1 FROM delivery_acceptance_events WHERE id=%s AND snapshot_id=%s',(request.corrects_event_id,identifier)).fetchone():raise invalid('research_source_not_found',404)
            moment=now();event=dict(id=str(uuid4()),snapshot_id=identifier,actor_id=self.store.user_id,actor_kind='current_user',created_at=moment.isoformat(),**request.model_dump(mode='json'))
            insert(db,'delivery_acceptance_events',dict(id=event['id'],snapshot_id=identifier,delivery_id=delivery,project_id=project,user_id=self.store.user_id,snapshot_sha256=row['sha256'],request_key=key,request_digest=hashed,event_json=event,created_at=moment))
            return event,201

    def acceptances(self,project,delivery,identifier):
        with self.store.connection() as db:
            self.row(db,project,delivery,identifier)
            return dict(items=[r['event_json'] for r in db.execute('SELECT event_json FROM delivery_acceptance_events WHERE snapshot_id=%s ORDER BY created_at,id',(identifier,))])

    def package(self,project,delivery,identifier,key=None):
        with self.store.connection(write=key is not None) as db:
            row=self.row(db,project,delivery,identifier)
            if key is not None:request_key(key);self.lock(db,project,'delivery-package:'+identifier)
            existing=db.execute("SELECT * FROM tasks WHERE project_id=%s AND user_id=%s AND task_type='delivery_package' AND input_snapshot->>'snapshot_id'=%s ORDER BY created_at LIMIT 1",(project,self.store.user_id,identifier)).fetchone()
            status=200
            if key is not None:
                requested=self.store.find_request(db,project,'delivery_package','delivery-package:'+digest(key))
                if requested and requested['input_snapshot']['snapshot_id']!=identifier:raise invalid('research_idempotency_conflict')
            if not existing and key is not None:
                from app.domain.research_results.task_contracts import input_version
                snap=dict(schema_version=1,kind='delivery_package',workflow_version='delivery_package_v1',project_id=project,delivery_id=delivery,snapshot_id=identifier,snapshot_sha256=row['sha256'],source_file_ids=row['snapshot_json']['source_file_ids'],real_model_calls=False,real_network_calls=False,output_language='zh-CN')
                moment=now();task_id=identity(project,'delivery-package-task',identifier)
                existing=dict(id=task_id,project_id=project,user_id=self.store.user_id,task_type='delivery_package',idempotency_key='delivery-package:'+digest(key),input_snapshot=snap,input_digest=digest(snap),workflow_version='delivery_package_v1',status='queued',phase='export',revision=1,current_attempt=0,reason_code=None,created_at=moment,updated_at=moment)
                self.store.insert_task(db,existing,validated_file_ids=snap['source_file_ids']);append_checkpoint(db,existing,'check','check',dict(input_version=input_version(existing),stage='frozen_inputs',completed_members=0,total_members=len(row['snapshot_json']['members'])));self.store.append_event(db,existing,'created');self.store.enqueue(db,existing);status=201
            if not existing:return dict(task=None,task_id=None,download_url=None,progress=None),status
            from app.domain.tasks.progress import public_progress
            progress=public_progress(db,existing)
            return dict(task_id=existing['id'],task=self.store.public_task(existing),download_url=f'/api/v1/projects/{project}/deliveries/{delivery}/snapshots/{identifier}/download' if existing['status']=='succeeded' else None,progress=progress),status

    def require_sources(self,db,task,*,progress=None):
        from app.domain.research_results.task_contracts import input_version
        input_version(task);snap=task['input_snapshot'];row=self.row(db,task['project_id'],snap['delivery_id'],snap['snapshot_id'])
        if snap['snapshot_sha256']!=row['sha256']:raise invalid()
        raws = self.require_snapshot_sources(db, row, progress=progress)
        return dict(snapshot=self.view(row),raws=raws)

    def require_snapshot_sources(self, db, row, *, progress=None):
        snapshot = row['snapshot_json']
        project_id = row['project_id']
        registered = self.scope(db, project_id, row['delivery_id'])
        selections = [Selection.model_validate(member['selection']) for member in snapshot['members']]
        members, raws, files = resolve_members(self, db, project_id, registered, selections, snapshot['mode'],
                                               progress, frozen_members=snapshot['members'])
        if members != snapshot['members'] or files != snapshot['source_file_ids']:
            raise invalid()
        return raws

    def publish(self,db,task,checkpoint,moment,prepared,*,progress):
        if len(prepared['members'])!=1 or prepared['members'][0]['format']!='zip':raise invalid()
        progress();previous=task['revision'];task.update(status='succeeded',phase='verify',revision=previous+1,updated_at=moment,reason_code=None,error_code=None)
        append_checkpoint(db,task,'done','done',{**checkpoint['state_json'],'stage':'published','completed_members':checkpoint['state_json'].get('total_members',0),'result_id':task['input_snapshot']['snapshot_id']},checkpoint)
        self.store.finish_attempt(db,task);self.store.update_task(db,task,previous);self.store.append_event(db,task,'succeeded');return self.store.public_task(task)

    def download(self,project,delivery,identifier):
        with self.store.connection() as db:
            return self.package_bytes(db,self.row(db,project,delivery,identifier))

    def ready_package(self,db,row):
        return db.execute('''SELECT * FROM tasks WHERE project_id=%s AND user_id=%s AND task_type='delivery_package'
            AND input_snapshot->>'snapshot_id'=%s AND status='succeeded' ''',
            (row['project_id'],self.store.user_id,row['id'])).fetchone()

    def package_bytes(self,db,row):
        task=self.ready_package(db,row)
        if not task:raise invalid('research_source_incomplete',409)
        self.require_sources(db,task)
        cp=db.execute('SELECT * FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(task['id'],)).fetchone()
        member=cp['state_json']['prepared']['members'][0]
        from app.adapters.bio_analysis_store import object_by_key
        from app.adapters.research_objects import ResearchObjects
        obj=object_by_key(db,row['project_id'],self.store.user_id,member)
        raw=ResearchObjects(self.assets.directory).read(obj)
        from app.domain.research_results.report_package import verify_package
        verify_package(raw)
        return dict(filename='delivery-'+row['id']+'.zip',sha256=member['sha256'],size_bytes=member['size_bytes']),raw


def run_delivery_package_task(task_id,task_revision,**kwargs):
    from app.domain.research_results.execution import run_research_task
    return run_research_task(task_id,task_revision,task_type='delivery_package',**kwargs)
