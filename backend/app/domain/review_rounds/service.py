"""Frozen scientific review inputs with explicit, versioned user planning."""
from copy import deepcopy
from uuid import uuid4
from psycopg.types.json import Jsonb
from app.adapters.task_store import TaskStore,source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_preparation.service import require_key
from app.domain.journals.format_service import FormatService
from app.domain.journals.service import now
from app.domain.journals.display import synthetic_input
from app.domain.literature.service import digest
from .contracts import WORKFLOW,ReviewInputVersion,ItemEdit
from .planning import invalid,propose,update_status
from .extraction import preview

def input_version(task):
    snap=task['input_snapshot']
    if task['task_type']!='review_round_plan' or task['workflow_version']!=WORKFLOW or digest(snap)!=task['input_digest'] or snap.get('project_id')!=task['project_id'] or snap.get('real_model_calls') is not False or snap.get('real_network_calls') is not False:raise source_conflict()
    return ReviewInputVersion(round_id=snap['id'],base_version_id=snap['manuscript']['version_id']).model_dump()

class ReviewRoundService(FormatService):
    def project(self,db,project,lock=False):
        row=self.store.require_project(db,project)
        if lock:db.execute('SELECT id FROM projects WHERE id=%s FOR UPDATE',(project,)).fetchone()
        return row
    def inputs(self,project):
        with self.store.connection() as db:
            p=self.project(db,project);manuscripts=[]
            for root in db.execute('SELECT * FROM manuscripts WHERE project_id=%s AND user_id=%s ORDER BY created_at DESC',(project,self.store.user_id)).fetchall():
                versions=db.execute("SELECT v.id,v.revision,t.status FROM manuscript_versions v JOIN tasks t ON t.id=v.task_id WHERE v.manuscript_id=%s AND t.status='succeeded' ORDER BY v.revision DESC",(root['id'],)).fetchall()
                manuscripts.append(dict(id=root['id'],title=root['title'],current_revision=root['current_revision'],versions=[dict(v,title=root['title'],status='published') for v in versions]))
            documents=db.execute("SELECT f.id AS file_id,f.filename,r.id AS document_version_id,r.version,t.input_snapshot->>'kind' AS kind FROM files f JOIN file_parse_results r ON r.file_id=f.id JOIN tasks t ON t.id=r.task_id WHERE f.project_id=%s AND t.user_id=%s AND t.status='succeeded' AND t.workflow_version IN ('docx_document_v1','pdf_document_v1') ORDER BY f.filename,r.version DESC",(project,self.store.user_id)).fetchall()
            targets=db.execute("SELECT id,snapshot_json FROM journal_targets WHERE project_id=%s AND user_id=%s",(project,self.store.user_id)).fetchall() if p['project_type']=='sci' else []
            confirmations=db.execute('SELECT id,snapshot_json FROM school_template_confirmations WHERE project_id=%s AND user_id=%s',(project,self.store.user_id)).fetchall() if p['project_type']=='thesis' else []
            return dict(project_type=p['project_type'],manuscripts=manuscripts,documents=[dict(d) for d in documents],journal_targets=[dict(id=r['id'],label=r['snapshot_json'].get('profile',{}).get('name') or '固定期刊目标') for r in targets],school_confirmations=[dict(id=r['id'],label='固定学校确认版本') for r in confirmations])
    def preview(self,project,source):
        with self.store.connection() as db:self.project(db,project)
        return preview(self,project,source)
    def round_row(self,db,project,identity,lock=False):
        self.project(db,project)
        row=db.execute('SELECT * FROM review_rounds WHERE id=%s AND project_id=%s AND user_id=%s'+(' FOR UPDATE' if lock else ''),(identity,project,self.store.user_id)).fetchone()
        if not row:raise StorageError('not_found','返修轮次不存在。',404)
        self.validate(row);task=self.store.require_task(db,row['task_id']);input_version(task)
        if task['input_snapshot']!=row['snapshot_json']:raise source_conflict()
        return row
    def events(self,db,row):
        rows=db.execute('SELECT * FROM review_round_events WHERE round_id=%s ORDER BY revision',(row['id'],)).fetchall()
        for event in rows:self.validate_event(event)
        return rows
    def validate_event(self,row):
        if digest(row['request_json'])!=row['request_digest'] or digest(row['snapshot_json'])!=row['snapshot_sha256']:raise source_conflict()
    def state(self,db,row):
        events=self.events(db,row)
        return deepcopy(events[-1]['snapshot_json']) if events else dict(items=[],materials=row['snapshot_json']['materials'],decisions=[]),events
    def view(self,db,row):
        state,events=self.state(db,row);snap=row['snapshot_json'];task=self.store.require_task(db,row['task_id'])
        from app.domain.tasks.waits import get_open_wait
        result=dict(id=row['id'],project_id=row['project_id'],title=snap['title'],project_type=snap['project_type'],round_number=row['round_number'],revision=events[-1]['revision'] if events else 1,synthetic=bool(snap['synthetic'] or state.get('synthetic')),manuscript={k:snap['manuscript'][k] for k in ('id','revision','version_id','title')},sources=snap['sources'],items=state['items'],materials=state['materials'],constraints=snap['constraints'],versions=[dict(id=e['id'],revision=e['revision'],created_at=e['created_at'],items=e['snapshot_json']['items']) for e in events if e['kind'] in ('initial','plans')],decisions=state['decisions'],task=self.store.public_task(task),wait=get_open_wait(db,task),created_at=row['created_at'],real_model_calls=False,real_network_calls=False)
        from .revisions import RevisionService
        revisions=RevisionService(self.assets)
        runs=[revisions.view_revision(db,revisions.revision_row(db,row['project_id'],r['id'])) for r in db.execute('SELECT id FROM review_revision_runs WHERE round_id=%s ORDER BY created_at DESC,id',(row['id'],)).fetchall()]
        result['actual_revisions']=runs
        latest=next((r for r in runs if r['result'] and r['input_snapshot']['plan_revision']==result['revision']),None)
        if latest:result['items']=latest['result']['items']
        result['documents']=[dict(r) for r in db.execute('SELECT id,revision_id,kind,version,language,confirmed_at FROM review_documents WHERE round_id=%s ORDER BY created_at DESC,id',(row['id'],)).fetchall()]
        from .lineage import round_continuation
        result['continuation']=round_continuation(self,db,row)
        result['next_round_ids']=[r['round_id'] for r in db.execute('SELECT round_id FROM review_round_continuations WHERE previous_round_id=%s ORDER BY created_at,id',(row['id'],)).fetchall()]
        return result
    def get(self,project,identity):
        with self.store.connection() as db:return self.view(db,self.round_row(db,project,identity))
    def listing(self,project):
        with self.store.connection() as db:
            self.project(db,project)
            return dict(items=[self.view(db,self.round_row(db,project,r['id'])) for r in db.execute('SELECT * FROM review_rounds WHERE project_id=%s AND user_id=%s ORDER BY round_number DESC',(project,self.store.user_id)).fetchall()])
    def append(self,db,row,revision,kind,key,body,state):
        db.execute('INSERT INTO review_round_events(id,round_id,project_id,user_id,revision,kind,idempotency_key,request_json,request_digest,snapshot_json,snapshot_sha256,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(str(uuid4()),row['id'],row['project_id'],self.store.user_id,revision,kind,key,Jsonb(body),digest(body),Jsonb(state),digest(state),now()))
    def fixed(self,db,row):
        snap=row['snapshot_json'];m=snap['manuscript'];base=self.manuscript(db,row['project_id'],m['id'],m['revision'])
        if base['id']!=m['version_id'] or base['snapshot_sha256']!=m['sha256']:raise source_conflict()
        for source in snap['sources']:
            if source['format']=='document':
                current=preview(self,row['project_id'],{k:source[k] for k in ('role','label','format','file_id','document_version_id','received_on')}|dict(segments=[{k:x[k] for k in ('start','end','original_number')} for x in source['segments']]))
                if not current['supported'] or current['original_text']!=source['original_text']:raise source_conflict()
        state,_=self.state(db,row)
        for material in state['materials']:
            if self.material(row['project_id'],{k:material[k] for k in ('kind','id','file_id')})!=material:raise source_conflict()
        return base
    def create(self,project,request,key):
        require_key(key);body=request.model_dump(mode='json')
        with self.store.connection(write=True) as db:
            p=self.project(db,project,True)
            old=db.execute('SELECT * FROM review_rounds WHERE project_id=%s AND user_id=%s AND idempotency_key=%s',(project,self.store.user_id,key)).fetchone()
            if old:
                if old['request_digest']!=digest(body):raise StorageError('task_idempotency_conflict','标识已用于不同输入。',409)
                return self.view(db,self.round_row(db,project,old['id'])),200
            if request.project_type!=p['project_type']:raise invalid('项目类型不一致。')
            m=request.manuscript;base=self.manuscript(db,project,m.id,m.revision)
            if base['id']!=m.version_id:raise source_conflict()
            from .lineage import prepare_continuation,save_continuation
            relation=prepare_continuation(self,db,project,request,base)
            target=None;school=None
            if p['project_type']=='thesis':
                if request.journal_target_id:raise invalid('学校返修不能选择期刊目标。')
                fixed=base['snapshot_json'].get('thesis_context') or {}
                expected=fixed.get('confirmation_id')
                if request.school_confirmation_id!=expected:raise invalid('学校约束必须与固定稿件确认版本一致。')
                if request.school_confirmation_id:
                    school=db.execute('SELECT * FROM school_template_confirmations WHERE id=%s AND project_id=%s AND user_id=%s',(request.school_confirmation_id,project,self.store.user_id)).fetchone()
                    if not school:raise StorageError('not_found','学校确认不存在。',404)
            else:
                if request.school_confirmation_id:raise invalid('SCI不能选择学校约束。')
                if request.journal_target_id:target=self.target_row(db,project,request.journal_target_id)['snapshot_json']
            allowed=('editor','reviewer') if p['project_type']=='sci' else ('advisor','evaluator','defense');sources=[]
            for source in request.sources:
                if source.role not in allowed:raise invalid('意见来源角色与项目类型不一致。')
                result=self.preview(project,source)
                if not result['supported']:raise invalid('意见文档不能完整提取：'+'；'.join(result['warnings']))
                sources.append(dict(id=str(uuid4()),**{k:v for k,v in source.model_dump().items() if k not in ('text','segments')},**result))
            materials=[self.material(project,m) for m in request.materials]
            identity=str(uuid4());timestamp=now();number=db.execute('SELECT COALESCE(MAX(round_number),0)+1 AS n FROM review_rounds WHERE project_id=%s',(project,)).fetchone()['n']
            synthetic=bool(request.synthetic or synthetic_input(base['snapshot_json']) or target and target.get('synthetic') or any(synthetic_input(x.get('content',{})) for x in materials))
            if relation:
                synthetic=bool(synthetic or self.round_row(db,project,relation['previous_round_id'])['snapshot_json']['synthetic'])
            snap=dict(id=identity,kind='review_round_plan',project_id=project,title=request.title,project_type=request.project_type,workflow_version=WORKFLOW,synthetic=synthetic,manuscript=dict(id=m.id,revision=m.revision,version_id=base['id'],title=base['snapshot_json']['title'],sha256=base['snapshot_sha256']),sources=sources,materials=materials,constraints=dict(school_confirmation_id=request.school_confirmation_id,journal_target_id=request.journal_target_id),real_model_calls=False,real_network_calls=False)
            snap['continuation']=relation
            task=dict(id=str(uuid4()),project_id=project,user_id=self.store.user_id,task_type='review_round_plan',idempotency_key='review-round:'+identity,input_digest=digest(snap),input_snapshot=snap,workflow_version=WORKFLOW,status='queued',phase='verify',revision=1,current_attempt=0,reason_code=None,created_at=timestamp,updated_at=timestamp)
            self.store.insert_task(db,task);self.store.append_event(db,task,'created');self.store.enqueue(db,task)
            db.execute('INSERT INTO review_rounds(id,project_id,user_id,task_id,round_number,idempotency_key,request_json,request_digest,snapshot_json,snapshot_sha256,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(identity,project,self.store.user_id,task['id'],number,key,Jsonb(body),digest(body),Jsonb(snap),digest(snap),timestamp))
            save_continuation(self,db,dict(id=identity,project_id=project),relation)
            return self.view(db,self.round_row(db,project,identity)),202
    def mutate(self,project,identity,request,key,kind):
        require_key(key);body=request.model_dump(mode='json')
        with self.store.connection(write=True) as db:
            row=self.round_row(db,project,identity,True);state,events=self.state(db,row)
            old=next((e for e in events if e['idempotency_key']==key),None)
            if old:
                if old['request_digest']!=digest(body) or old['kind']!=kind:raise StorageError('task_idempotency_conflict','标识已用于不同输入。',409)
                return self.view(db,row),200
            if not events:raise invalid('请等待初始计划保存。',409)
            if request.expected_revision!=events[-1]['revision']:raise StorageError('task_revision_conflict','返修计划已变化，请刷新。',409)
            task=self.store.require_task(db,row['task_id'])
            if task['status'] in ('running','queued'):raise invalid('请等待当前计划任务结束后保存。',409)
            base=self.fixed(db,row);items=state['items'];ids={i['id'] for i in items}
            if kind=='plans':
                edits=[i.model_dump() for i in request.items]
                if len(edits)!=len(items) or {i['id'] for i in edits}!=ids:raise invalid('必须一次保存所有原始意见，不能删除或替换原文。')
                materials=state['materials'] if request.materials is None else [self.material(project,m) for m in request.materials]
                from app.domain.manuscript_writing.context import normalize_sections
                sections=normalize_sections(base['snapshot_json']);valid={('section',s['id']) for s in sections}|{('paragraph',p['id']) for s in sections for p in s['paragraphs']}
                for group in base['snapshot_json'].get('results_groups',[]):
                    for name in ('figures','tables'):valid.update((name[:-1],v['id']) for v in group.get(name,[]))
                evidence={x['id'] for x in materials}|{x['id'] for x in base['snapshot_json'].get('sources',[])}
                frozen_risks={i['id']:i for i in events[0]['snapshot_json']['items']}
                changed_ids=set()
                for edit in edits:
                    original_risk=frozen_risks[edit['id']]
                    edit['flags']=list(dict.fromkeys(edit['flags']+original_risk['flags']))
                    edit['conflicting_item_ids']=list(dict.fromkeys(edit['conflicting_item_ids']+original_risk['conflicting_item_ids']))
                    if any((x['kind'],x['id']) not in valid for x in edit['locations']):raise invalid('位置不属于固定稿件。')
                    if not set(edit['evidence_ids'])<=evidence:raise invalid('证据不属于固定材料。')
                    if not set(edit['conflicting_item_ids'])<=ids-{edit['id']}:raise invalid('冲突意见必须属于本轮且不能指向自身。')
                    if edit['conflicting_item_ids'] and 'conflict' not in edit['flags']:raise invalid('关联冲突必须保留冲突标记。')
                    if edit['proposed_action']=='not_adopt' and not edit['not_adopt_reason'].strip():raise invalid('拟不采纳须填写理由。')
                    item=next(i for i in items if i['id']==edit['id']);changed=any(item[k]!=v for k,v in edit.items())
                    if changed:
                        changed_ids.add(item['id']);item.update(edit,revision=item['revision']+1,decision=None)
                for item in items:
                    if item['id'] not in changed_ids and set(item['conflicting_item_ids']) & changed_ids:item.update(revision=item['revision']+1,decision=None)
                state['materials']=materials;state['synthetic']=bool(state.get('synthetic') or any(synthetic_input(m.get('content',{})) for m in materials))
            else:
                if len({d.item_id for d in request.decisions})!=len(request.decisions):raise invalid('同一意见决定不能重复。')
                for choice in request.decisions:
                    if choice.item_id not in ids:raise invalid('决定不属于本轮意见。')
                    item=next(i for i in items if i['id']==choice.item_id)
                    if (item['flags'] or choice.action!='accept' or item['proposed_action']=='not_adopt') and not choice.reason.strip():raise invalid('重要决定须记录明确理由。')
                    if item['proposed_action']=='not_adopt' and choice.action=='accept':raise invalid('不采纳方案须显式选择不采纳。')
                    prior=item.get('decision')
                    if prior and prior['action']==choice.action and prior['reason']==choice.reason:continue
                    decision=dict(id=str(uuid4()),item_id=item['id'],item_revision=item['revision'],action=choice.action,reason=choice.reason,created_at=now().isoformat());item['decision']=decision;state['decisions'].append(decision)
            update_status(items);self.append(db,row,events[-1]['revision']+1,kind,key,body,state)
            needs=any(i['status']=='waiting_material' for i in items);confirmation=any(i['status']=='waiting_confirmation' for i in items)
            if task['status']=='succeeded' and (needs or confirmation):
                previous=task['revision'];task.update(status='waiting_input' if needs else 'waiting_confirmation',revision=previous+1,updated_at=max(now(),task['updated_at']),reason_code='input_required' if needs else 'confirmation_required',error_code=None)
                self.store.update_task(db,task,previous);self.store.append_event(db,task,'waiting')
                from app.domain.tasks.waits import persist_wait
                persist_wait(db,task)
            return self.view(db,row),201
