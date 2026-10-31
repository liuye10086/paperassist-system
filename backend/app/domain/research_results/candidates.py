"""Fenced candidate generation and separately idempotent manuscript publication."""
from copy import deepcopy
from app.domain.source_byte_verification import VerificationPhase, require_phase, phase_guard
from uuid import uuid4
from psycopg.types.json import Jsonb
from app.adapters.research_results_store import ResearchResultsStore,base,insert,identity,now,invalid
from app.domain.bioinformatics.contracts import digest,canonical
from app.domain.bioinformatics.service import require_key,append_checkpoint
from app.domain.manuscripts.research_sources import read,_read_in_phase,bind,file_ids,KINDS
from app.domain.manuscripts.service import ManuscriptService
from app.domain.manuscripts.delivery_context import resolve_document_context
from .handoff import ResearchHandoffService
from .task_contracts import input_version
from .fact_draft import compose


class ResearchCandidateService(ResearchResultsStore):
    table='research_manuscript_candidates'

    def create(self,project,request,key):
        require_key(key);body=request.model_dump(mode='json');hashed=digest(body);identifier=identity(project,'candidate',key)
        with self.store.connection(write=True) as db:
            self.lock(db,project,'candidate:'+key)
            replay=db.execute('SELECT * FROM research_manuscript_candidates WHERE project_id=%s AND user_id=%s AND request_key=%s',(project,self.store.user_id,key)).fetchone()
            if replay:
                if replay['request_digest']!=hashed:raise invalid('research_idempotency_conflict')
                status=200
            else:
                payload=ResearchHandoffService(self.assets).freeze(db,project,request);moment=now();task_id=identity(project,'candidate-task',key)
                snapshot=dict(schema_version=1,kind='research_fact_draft',workflow_version='research_results_methods_v1',project_id=project,
                    candidate_id=identifier,request=body,payload=payload,source_file_ids=file_ids(payload['sources']),
                    output_language=payload['output_language'],real_model_calls=False,real_network_calls=False)
                if len(canonical(snapshot))>4*1024*1024:raise invalid('research_source_limit_exceeded',422)
                task=dict(id=task_id,project_id=project,user_id=self.store.user_id,task_type='research_fact_draft',idempotency_key='research_fact_draft:'+task_id,
                    input_digest=digest(snapshot),input_snapshot=snapshot,workflow_version='research_results_methods_v1',status='queued',phase='compute',revision=1,current_attempt=0,reason_code=None,created_at=moment,updated_at=moment)
                self.store.insert_task(db,task,validated_file_ids=snapshot['source_file_ids'])
                insert(db,self.table,{**base(identifier,project,self.store.user_id),'delivery_id':request.delivery_id,'manuscript_id':request.manuscript_id,
                    'base_version_id':request.base_version_id,'expected_revision':request.expected_revision,'task_id':task_id,
                    'scope_json':dict(sections=request.sections,writing_scope='results_methods'),'candidate_json':None,'candidate_sha256':None,
                    'published_version_id':None,'publish_key':None,'request_key':key,'request_digest':hashed})
                append_checkpoint(db,task,'check','check',dict(input_version=input_version(task),stage='candidate'))
                self.store.append_event(db,task,'created');self.store.enqueue(db,task);status=201
        return self.get(project,identifier),status

    def require_sources(self,db,task,*,progress=None):
        with VerificationPhase(db,self.assets,task['project_id']) as phase:
            return self._require_sources_in_phase(db,task,phase=phase,progress=progress)

    @phase_guard
    def _require_sources_in_phase(self,db,task,*,phase,progress=None):
        require_phase(phase,db,self.assets,task['project_id'])
        input_version(task);snap=task['input_snapshot'];row=self.require(db,self.table,task['project_id'],snap['candidate_id'])
        if row['task_id']!=task['id'] or row['request_digest']!=digest(snap['request']):raise invalid()
        payload=snap['payload'];request=snap['request']
        if any(row[k]!=request[k] for k in ('delivery_id','manuscript_id','base_version_id','expected_revision')):raise invalid()
        if row['scope_json']!=dict(sections=request['sections'],writing_scope='results_methods'):raise invalid()
        resolve_document_context(db,task['project_id'],task['user_id'],delivery_id=row['delivery_id'],manuscript_id=row['manuscript_id'],active=False)
        service=ManuscriptService(self.assets)
        for source in payload['sources']:
            if progress is not None:progress()
            if source['kind'] in KINDS:
                if _read_in_phase(service,task['project_id'],source,db,phase=phase,progress=progress)!=source:raise invalid()
            else:
                from app.domain.manuscripts.sources import read_source
                if read_source(service,task['project_id'],{k:source[k] for k in ('kind','id','file_id','role')})!=source:raise invalid()
            if progress is not None:progress()
        if row['base_version_id']:
            version=service.version(db,task['project_id'],row['manuscript_id'],row['expected_revision'])
            if version['id']!=row['base_version_id'] or version['snapshot_json']!=payload['base_snapshot']:raise invalid()
        elif payload['base_snapshot'] is not None:raise invalid()
        return payload

    def get(self,project,identifier):
        with self.store.connection() as db:
            row=self.require(db,self.table,project,identifier);task=self.store.require_task(db,row['task_id']);payload=self.require_sources(db,task)
            if row['candidate_json'] is not None and (digest(row['candidate_json'])!=row['candidate_sha256'] or row['candidate_json']!=compose(payload) or task['status']!='succeeded'):raise invalid()
            return {k:row[k] for k in ('id','delivery_id','manuscript_id','base_version_id','expected_revision','task_id','published_version_id')} | dict(
                task=self.store.public_task(task),candidate=row['candidate_json'],candidate_sha256=row['candidate_sha256'],scope=row['scope_json'])

    def publish(self,db,task,checkpoint,moment,prepared,*,progress):
        from app.domain.bioinformatics.analysis_service import finish
        candidate=compose(self.require_sources(db,task,progress=progress));identifier=task['input_snapshot']['candidate_id']
        if prepared['manifest'].get('candidate_sha256')!=digest(candidate):raise invalid()
        members=prepared['members']
        if len(members)!=1 or members[0]['sha256']!=digest(candidate) or members[0]['key']!='candidate':raise invalid()
        from app.adapters.research_objects import ResearchObjects
        if ResearchObjects(self.assets.directory).read(members[0])!=canonical(candidate):raise invalid()
        changed=db.execute('UPDATE research_manuscript_candidates SET candidate_json=%s,candidate_sha256=%s WHERE id=%s AND candidate_json IS NULL',(Jsonb(candidate),digest(candidate),identifier))
        if changed.rowcount!=1:raise invalid()
        progress();return finish(db,task,checkpoint,moment,'result_research_candidate_id',identifier)

    def publish_manuscript(self,project,identifier,request,key):
        require_key(key)
        if request.candidate_id!=identifier:raise invalid('research_revision_conflict')
        with self.store.connection(write=True) as db:
            self.lock(db,project,'manuscript-publish:'+key)
            row=self.require(db,self.table,project,identifier)
            db.execute('SELECT id FROM research_manuscript_candidates WHERE id=%s FOR UPDATE',(identifier,)).fetchone()
            row=self.require(db,self.table,project,identifier)
            if row['expected_revision']!=request.expected_revision:raise invalid('research_revision_conflict')
            if row['published_version_id']:
                if row['publish_key']!=key:raise invalid('research_idempotency_conflict')
                version=db.execute('SELECT * FROM manuscript_versions WHERE id=%s',(row['published_version_id'],)).fetchone();status=200
            else:
                other=db.execute('SELECT id FROM research_manuscript_candidates WHERE project_id=%s AND user_id=%s AND publish_key=%s',(project,self.store.user_id,key)).fetchone()
                if other:raise invalid('research_idempotency_conflict')
                task=self.store.require_task(db,row['task_id']);payload=self.require_sources(db,task);candidate=compose(payload)
                if task['status']!='succeeded' or row['candidate_json']!=candidate or row['candidate_sha256']!=digest(candidate):raise invalid('research_source_incomplete',422)
                context=resolve_document_context(db,project,self.store.user_id,delivery_id=row['delivery_id'],manuscript_id=row['manuscript_id'])
                service=ManuscriptService(self.assets);root_id=row['manuscript_id'] or identity(project,'research-manuscript',identifier)
                if row['manuscript_id']:
                    db.execute('SELECT id FROM manuscripts WHERE id=%s FOR UPDATE',(root_id,)).fetchone()
                    if service.root(db,project,root_id)['current_revision']!=row['expected_revision']:raise invalid('research_revision_conflict')
                if candidate.get('thesis_context'):
                    from app.domain.manuscripts.school_binding import current_changes
                    if current_changes(service,project,candidate):raise invalid()
                moment=now();revision=row['expected_revision']+1;version_id=identity(project,'research-manuscript-version',identifier)
                body=dict(schema_version=2,kind='research_results_methods',candidate_id=identifier,delivery_id=row['delivery_id'],expected_revision=row['expected_revision'],
                    title=candidate['title'],output_language=candidate['output_language'],thesis=payload['thesis'])
                if not row['manuscript_id']:
                    db.execute('INSERT INTO manuscripts(id,project_id,user_id,idempotency_key,request_json,request_digest,delivery_id,document_kind,current_revision,title,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                        (root_id,project,self.store.user_id,'research:'+identifier,Jsonb(body),digest(body),row['delivery_id'],context['document_kind'],revision,candidate['title'],moment,moment))
                # The finished deterministic task is the producer; publication itself is atomic.
                fields=dict(id=version_id,project_id=project,user_id=self.store.user_id,idempotency_key='research:'+identifier,request_json=Jsonb(body),request_digest=digest(body),
                    manuscript_id=root_id,revision=revision,parent_version_id=row['base_version_id'],task_id=row['task_id'],snapshot_json=Jsonb(candidate),snapshot_sha256=digest(candidate),created_at=moment,
                    school_confirmation_id=(candidate.get('thesis_context') or {}).get('confirmation_id'))
                db.execute('INSERT INTO manuscript_versions('+','.join(fields)+') VALUES ('+','.join(['%s']*len(fields))+')',tuple(fields.values()))
                for source in candidate['sources']:
                    if source['kind'] in KINDS:bind(db,project,self.store.user_id,version_id,source)
                if row['base_version_id']:
                    for table in ('manuscript_sources','manuscript_citations'):
                        for old in db.execute('SELECT * FROM '+table+' WHERE version_id=%s',(row['base_version_id'],)).fetchall():
                            values=dict(old);values.update(id=str(uuid4()),version_id=version_id)
                            db.execute('INSERT INTO '+table+'('+','.join(values)+') VALUES ('+','.join(['%s']*len(values))+')',tuple(Jsonb(v) if isinstance(v,(dict,list)) else v for v in values.values()))
                    db.execute('UPDATE manuscripts SET current_revision=%s,title=%s,updated_at=%s WHERE id=%s',(revision,candidate['title'],moment,root_id))
                db.execute('UPDATE research_manuscript_candidates SET published_version_id=%s,publish_key=%s WHERE id=%s',(version_id,key,identifier))
                version=dict(fields);status=201
            return dict(manuscript_id=version['manuscript_id'],version_id=version['id'],revision=version['revision'],candidate_id=identifier),status
