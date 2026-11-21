"""Fixed old-parent revisions with immutable plan and explicit batch adoption."""
from copy import deepcopy
from uuid import uuid4
from psycopg.types.json import Jsonb
from app.adapters.task_store import source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_preparation.service import require_key
from app.domain.literature.service import digest
from app.domain.manuscripts.service import ManuscriptService
from app.domain.manuscripts.sources import require_visible_snapshot
from app.domain.journals.service import now
from .service import ReviewRoundService
from .planning import invalid
from .revision_contracts import CANDIDATE_SCHEMA_VERSION,WORKFLOW,RevisionInputVersion,RevisionPreview
from .grounded import evidence_for,locations_for,grounded_plans,apply_operations
from .writing import prepare_revision_layout, retain_school_layout
from app.domain.admin_configuration.rule_consumption import rules,round_version,inherit_task

GENERAL_WORD_NOTICE = '本次修订稿使用通用 Word 版式，期刊格式需按新稿重新核对。'


def revision_request_body(request):
    body=request.model_dump(mode='json')
    # Only this new optional field is canonicalized; sealed old fields stay exact.
    if not body.get('figure_adoption_ids'):body.pop('figure_adoption_ids',None)
    return body


def input_version(task):
    snap=task['input_snapshot']
    if task['task_type']!='review_revision' or task['workflow_version']!=WORKFLOW or digest(snap)!=task['input_digest'] or snap.get('project_id')!=task['project_id'] or snap.get('real_model_calls') is not False or snap.get('real_network_calls') is not False:raise source_conflict()
    return RevisionInputVersion(revision_id=snap['id'],round_id=snap['round_id'],base_version_id=snap['manuscript']['version_id']).model_dump()


class RevisionService(ReviewRoundService):
    def fixed_context(self,db,project,identity,*,display=False):
        row=self.round_row(db,project,identity);base=self.fixed(db,row);state,events=self.state(db,row)
        version=round_version(db,identity);policy=rules(version,'review') if version else None
        if not events:raise invalid('请先等待轮次计划保存。',409)
        current=ManuscriptService(self.assets).root(db,project,base['manuscript_id'])['current_revision']
        context=dict(round_id=identity,plan_revision=events[-1]['revision'],manuscript={k:row['snapshot_json']['manuscript'][k] for k in ('id','revision','version_id')},expected_current_revision=current,project_type=row['snapshot_json']['project_type'],output_language=base['snapshot_json']['output_language'],locations=locations_for(base['snapshot_json'],numbered=display),evidence=evidence_for(base['snapshot_json'],state['materials']),grounded_plans=grounded_plans(base['snapshot_json'],state['items'],state['materials']),constraints=row['snapshot_json']['constraints'])
        from app.domain.manuscript_writing.context import literature_paragraphs
        context['citation_candidates']=[{k:p[k] for k in ('id','text','citations')} for p in literature_paragraphs(base['snapshot_json'])]
        from .science import ScienceService
        from .science_candidates import apply_analysis_sources
        from app.domain.manuscript_review.facts import extract_facts
        science=ScienceService(self.assets)
        adopted=[] if self.assets.customer else db.execute('SELECT * FROM review_analysis_adoptions WHERE round_id=%s ORDER BY created_at,id',(identity,)).fetchall()
        context['analysis_adoptions']=[science.adoption_view(science.validate_adoption(db,r)) for r in adopted]
        figures=[] if self.assets.customer else db.execute('SELECT * FROM review_figure_adoptions WHERE round_id=%s ORDER BY created_at,id',(identity,)).fetchall()
        context['figure_adoptions']=[science.figure_adoption_view(science.validate_figure_adoption(db,r)) for r in figures]
        current_items={i['id']:i for i in state['items']}
        selected=[r for r in adopted if r['item_id'] in current_items]
        augmented,_,_=apply_analysis_sources(base['snapshot_json'],selected)
        from .figure_candidates import apply_figure_sources
        current_figures=[r for r in figures if r['item_id'] in current_items and r['snapshot_json']['item_revision']==current_items[r['item_id']]['revision']]
        augmented=deepcopy(augmented)
        for adopted in current_figures:
            for source in (adopted['snapshot_json']['analysis_source'],adopted['snapshot_json']['source']):
                previous=next((s for s in augmented['sources'] if s['id']==source['id']),None)
                if previous is not None and previous!=source:raise source_conflict()
                if previous is None:augmented['sources'].append(deepcopy(source))
            source=adopted['snapshot_json']['source']
            if not any(loc['id']==source['id'] for loc in context['locations']):
                old=next(loc for loc in context['locations'] if loc['kind']=='figure' and loc['id']==adopted['snapshot_json']['supersedes_figure_id'])
                context['locations'].append(dict(old,id=source['id'],text=source['content']['caption']))
        new_ids={r['snapshot_json']['source']['id'] for r in selected}
        context['analysis_facts']=[f for f in extract_facts(augmented) if f['source_id'] in new_ids]
        context['analysis_impacts']=[dict(adoption_id=r['id'],impact=r['snapshot_json']['impact'],pending=r['snapshot_json']['pending']) for r in selected]
        context['evidence']=evidence_for(augmented,state['materials'])
        planning_items=deepcopy(analysis_items(state['items'],selected))
        for adopted in selected:
            item=next(i for i in planning_items if i['id']==adopted['item_id'])
            source_id=adopted['snapshot_json']['source']['id']
            if source_id not in item['evidence_ids']:item['evidence_ids'].append(source_id)
        context['grounded_plans']=grounded_plans(augmented,planning_items,state['materials'],rules=policy,with_locations=display)
        return row,base,state,context
    def revision_context(self,project,identity):
        with self.store.connection() as db:return self.fixed_context(db,project,identity,display=self.assets.customer)[3]
    def calculate(self,db,project,identity,request,*,candidate_schema_version=CANDIDATE_SCHEMA_VERSION):
        row,base,state,context=self.fixed_context(db,project,identity)
        if request.plan_revision!=context['plan_revision']:raise StorageError('task_revision_conflict','本轮计划或决定已变化，请刷新具体候选。',409)
        if request.expected_current_revision!=context['expected_current_revision']:raise StorageError('manuscript_revision_conflict','当前稿件版本已变化，请刷新。',409)
        from app.domain.manuscript_review.writing_context import load_writing_context
        from app.domain.manuscript_review.checks import check_snapshot
        ms=ManuscriptService(self.assets);authority=load_writing_context(ms,db,project,base['manuscript_id'],base['snapshot_json'],check_version=2)
        target_id=row['snapshot_json']['constraints']['journal_target_id'];target=self.target_row(db,project,target_id)['snapshot_json'] if target_id else None
        from .science import ScienceService
        from .science_candidates import apply_analysis_sources,analysis_consistency_issues,science_unexecuted
        adoptions=ScienceService(self.assets).selected_adoptions(db,project,identity,request.analysis_adoption_ids,request.plan_revision,require_current=True)
        augmented,authority,table_changes=apply_analysis_sources(base['snapshot_json'],adoptions,authority)
        from .figure_candidates import apply_figure_sources,figure_consistency_issues
        figures=ScienceService(self.assets).selected_figure_adoptions(db,project,identity,request.figure_adoption_ids,request.plan_revision,require_current=True)
        augmented,authority,figure_changes=apply_figure_sources(augmented,figures,adoptions,authority)
        active_items=analysis_items(state['items'],adoptions)
        candidate,changes,unexecuted,strict,issues=apply_operations(augmented,active_items,state['materials'],request.operations,writing_context=authority,target=target,fixed_safety=round_version(db,identity) is not None,candidate_schema_version=candidate_schema_version)
        changes=table_changes+figure_changes+changes
        explicitly_changed={c['item_id'] for c in figure_changes}
        unexecuted=[u for u in unexecuted if not (u['item_id'] in explicitly_changed and u['reason']=='本次未选择具体修改。')]
        unexecuted+=science_unexecuted(state['items'],adoptions,figures,candidate)
        issues+=analysis_consistency_issues(candidate,adoptions)
        issues+=figure_consistency_issues(candidate,figures)
        general_word = candidate_schema_version >= 3 and prepare_revision_layout(candidate)
        previous=base['snapshot_json'].get('review') or (base['snapshot_json'].get('review_history') or [{}])[-1].get('review',{})
        issues+=check_snapshot(candidate,metadata=previous.get('metadata',[]),strict_locations=strict,writing_context=authority)
        for check in issues:
            if check['location'] in strict and check['category'] in ('unit','terminology'):check['severity']='error'
        constraints=[]
        if target:
            from app.domain.journals.format_rules import check_format
            report=check_format(candidate,target['selected_requirements'],target['conflicts'],public_issues=issues,warnings=target['warnings'])
            constraints=[dict(i,severity='error' if i['key']=='public_consistency' else 'info' if i['status']=='pass' else 'human_review',message=i['reason']) for i in report['items']]
        elif context['project_type']=='sci':constraints=[dict(severity='human_review',message='期刊规范待核：本轮未固定可用期刊指南。')]
        elif candidate.get('thesis_context'):
            constraints=candidate['school_content_report']['issues']
        if general_word:
            constraints.append(dict(severity='info',message=GENERAL_WORD_NOTICE))
        preview=dict(round_id=identity,plan_revision=request.plan_revision,manuscript=context['manuscript'],expected_current_revision=request.expected_current_revision,actual_changes=changes,unexecuted=unexecuted,public_issues=issues,constraint_issues=constraints,can_adopt=bool(changes) and not any(i['severity']=='error' for i in [*issues,*constraints]),synthetic=bool(row['snapshot_json']['synthetic'] or state.get('synthetic')))
        preview['preview_sha256']=digest(preview)
        return row,base,state,candidate,preview
    def preview_revision(self,project,identity,request):
        with self.store.connection() as db:
            self.round_row(db,project,identity)
            self.require_customer_material_selection(request)
            return self.calculate(db,project,identity,request)[4]

    def require_customer_material_selection(self, request):
        if self.assets.customer and (request.analysis_adoption_ids or request.figure_adoption_ids):
            raise StorageError('customer_operation_forbidden','请将已发布的分析交付作为返修材料上传后选择。',403)

    def revision_row(self,db,project,identity):
        self.project(db,project)
        row=db.execute('SELECT * FROM review_revision_runs WHERE id=%s AND project_id=%s AND user_id=%s',(identity,project,self.store.user_id)).fetchone()
        if not row:raise StorageError('not_found','实际修改批次不存在。',404)
        self.validate(db,row);task=self.store.require_task(db,row['task_id']);input_version(task)
        snap=row['snapshot_json']
        parent=self.round_row(db,project,row['round_id'])['snapshot_json']
        manuscript=parent['manuscript']
        if (task['input_snapshot']!=snap or snap['round_id']!=row['round_id'] or snap['project_type']!=parent['project_type']
            or snap['manuscript']!={k:manuscript[k] for k in ('id','revision','version_id')}
            or snap['base_sha256']!=manuscript['sha256'] or row['manuscript_id']!=manuscript['id']
            or row['manuscript_version_id']!=manuscript['version_id']):
            raise source_conflict()
        if row['result_json'] is not None:
            require_visible_snapshot(self.assets,db,project,row['result_json'])
        return row

    def output(self,db,row):
        """Check the immutable child identity without recursively validating itself."""
        value=row['result_json']['output']
        version=db.execute('''SELECT * FROM manuscript_versions WHERE id=%s AND manuscript_id=%s
            AND project_id=%s AND user_id=%s''',(row['output_version_id'],row['manuscript_id'],row['project_id'],row['user_id'])).fetchone()
        if (not version or value!=dict(manuscript_id=version['manuscript_id'],version_id=version['id'],
                revision=version['revision'],parent_version_id=version['parent_version_id'],task_id=version['task_id'])
            or version['parent_version_id']!=row['manuscript_version_id']
            or digest(version['snapshot_json'])!=version['snapshot_sha256']):
            raise source_conflict()
        producer=self.store.require_task(db,version['task_id'])
        if (producer['task_type']!='manuscript_draft' or producer['project_id']!=row['project_id']
            or producer['input_snapshot'].get('manuscript_version_id')!=version['id']
            or producer['input_snapshot'].get('snapshot_sha256')!=version['snapshot_sha256']):
            raise source_conflict()
        require_visible_snapshot(self.assets,db,row['project_id'],version['snapshot_json'])
        return version,producer

    def view_revision(self,db,row):
        check=db.execute("SELECT state_json FROM task_checkpoints WHERE task_id=%s AND node='check' ORDER BY seq DESC LIMIT 1",(row['task_id'],)).fetchone()
        result=deepcopy(row['result_json']);output_status=None
        if result:
            _,producer=self.output(db,row);output_status='published' if producer['status']=='succeeded' else 'pending'
            if output_status!='published':
                for item in result['items']:
                    if item['status']=='completed':item.update(status='executing',uncompleted_reason='公共新稿生产任务尚未成功。')
        return dict(id=row['id'],round_id=row['round_id'],input_snapshot=row['snapshot_json'],task=self.store.public_task(self.store.require_task(db,row['task_id'])),result=result,validation=check['state_json'] if check else None,output_status=output_status,created_at=row['created_at'])
    def get_revision(self,project,identity):
        with self.store.connection() as db:return self.view_revision(db,self.revision_row(db,project,identity))
    def revisions(self,project,round_id):
        with self.store.connection() as db:
            self.round_row(db,project,round_id)
            rows=db.execute('SELECT id FROM review_revision_runs WHERE round_id=%s ORDER BY created_at DESC,id',(round_id,)).fetchall()
            return dict(items=list(self.visible_records(rows,lambda item:self.view_revision(db,self.revision_row(db,project,item['id'])))))
    def adopt(self,project,identity,request,key):
        require_key(key);body=revision_request_body(request)
        with self.store.connection(write=True) as db:
            self.project(db,project,True)
            old=db.execute('SELECT * FROM review_revision_runs WHERE project_id=%s AND user_id=%s AND idempotency_key=%s',(project,self.store.user_id,key)).fetchone()
            if old:
                if old['request_digest']!=digest(body) or old['round_id']!=identity:raise StorageError('task_idempotency_conflict','标识已用于其他修改输入。',409)
                return self.view_revision(db,self.revision_row(db,project,old['id'])),200
            self.round_row(db,project,identity)
            self.require_customer_material_selection(request)
            row,base,state,candidate,preview=self.calculate(db,project,identity,request)
            if preview['preview_sha256']!=request.preview_sha256:raise invalid('差异预览已变化，请重新查看。',409)
            if not preview['can_adopt']:raise invalid('没有有效实际差异或公共检查存在硬错误，不能采用。',409)
            identity=str(uuid4());timestamp=now();snap=dict(id=identity,kind='review_revision',project_id=project,round_id=row['id'],workflow_version=WORKFLOW,project_type=row['snapshot_json']['project_type'],sources=[{k:v[k] for k in ('id','role','label')} for v in row['snapshot_json']['sources']],output_language=base['snapshot_json']['output_language'],manuscript=preview['manuscript'],base_sha256=base['snapshot_sha256'],plan_revision=request.plan_revision,plan_state=state,operations=body['operations'],expected_current_revision=request.expected_current_revision,preview=preview,synthetic=preview['synthetic'],real_model_calls=False,real_network_calls=False)
            if request.analysis_adoption_ids:snap['analysis_adoption_ids']=list(request.analysis_adoption_ids)
            if request.figure_adoption_ids:snap['figure_adoption_ids']=list(request.figure_adoption_ids)
            snap['candidate_schema_version']=CANDIDATE_SCHEMA_VERSION
            task=dict(id=str(uuid4()),project_id=project,user_id=self.store.user_id,task_type='review_revision',idempotency_key='review-revision:'+identity,input_digest=digest(snap),input_snapshot=snap,workflow_version=WORKFLOW,status='queued',phase='verify',revision=1,current_attempt=0,reason_code=None,created_at=timestamp,updated_at=timestamp)
            self.store.insert_task(db,task);self.store.append_event(db,task,'created');self.store.enqueue(db,task)
            inherit_task(db,task,round_id=row['id'])
            self.insert(db,'review_revision_runs',project,key,body,snap,round_id=row['id'],task_id=task['id'],manuscript_id=base['manuscript_id'],manuscript_version_id=base['id'])
            return self.view_revision(db,self.revision_row(db,project,identity)),202
    def compute(self,db,row):
        request=RevisionPreview.model_validate({k:row['request_json'][k] for k in RevisionPreview.model_fields if k in row['request_json']})
        version=row['snapshot_json'].get('candidate_schema_version',1)
        _,base,state,candidate,preview=self.calculate(db,row['project_id'],row['round_id'],request,candidate_schema_version=version)
        if preview!=row['snapshot_json']['preview'] or state!=row['snapshot_json']['plan_state'] or base['snapshot_sha256']!=row['snapshot_json']['base_sha256']:raise source_conflict()
        if version==2:
            retain_school_layout(candidate)
        candidate['review_revision_provenance']=dict(revision_id=row['id'],round_id=row['round_id'],base_version_id=base['id'],input_sha256=row['snapshot_sha256'],synthetic=preview['synthetic'])
        items=deepcopy(state['items'])
        for item in items:
            actual=[c for c in preview['actual_changes'] if c['item_id']==item['id']]
            item['actual_changes']=actual
            skipped=[u for u in preview['unexecuted'] if u['item_id']==item['id']]
            if actual and not skipped:item.update(status='completed',uncompleted_reason='',completion=dict(revision_id=row['id'],public_check_version=3))
            elif skipped:
                statuses={u['status'] for u in skipped}
                status=next((s for s in ('waiting_material','waiting_confirmation','not_adopted') if s in statuses),'pending')
                item.update(status=status,uncompleted_reason='；'.join(dict.fromkeys(u['reason'] for u in skipped)))
        result=dict(actual_changes=preview['actual_changes'],unexecuted=preview['unexecuted'],public_issues=preview['public_issues'],constraint_issues=preview['constraint_issues'],public_check_version=3,items=items,synthetic=preview['synthetic'])
        return base,candidate,result


def retry_in_transaction(store,db,task,expected_revision):
    if task['task_type']!='review_revision' or task['status']!='failed' or task['revision']!=expected_revision or task.get('error_code') not in ('storage_unavailable','task_worker_interrupted'):raise invalid('只能重试当前失败的实际修改任务。',409)
    from .access import review_task_assets
    service=RevisionService(review_task_assets(db,task,store.config));row=service.revision_row(db,task['project_id'],input_version(task)['revision_id'])
    if row['result_json'] is not None:raise source_conflict()
    task.update(status='queued',revision=expected_revision+1,reason_code='retry_requested',error_code=None,updated_at=max(now(),task['updated_at']),_retry_reason='manual_retry')
    store.update_task(db,task,expected_revision);store.append_event(db,task,'requeued');store.enqueue(db,task)
    return store.public_task(task)


def validate_revised_version(manuscripts,db,version):
    service=RevisionService(manuscripts.assets);provenance=version['snapshot_json']['review_revision_provenance']
    row=service.revision_row(db,version['project_id'],provenance.get('revision_id'));result=row['result_json'];frozen=row['snapshot_json']
    if not result or row['output_version_id']!=version['id'] or provenance['input_sha256']!=row['snapshot_sha256'] or any(i['severity']=='error' for i in result['public_issues']):raise source_conflict()
    base=service.manuscript_row(db,version['project_id'],version['manuscript_id'],frozen['manuscript']['revision'])
    from app.domain.manuscript_review.writing_context import load_writing_context
    authority=load_writing_context(manuscripts,db,version['project_id'],version['manuscript_id'],base['snapshot_json'],check_version=2)
    target_id=service.round_row(db,version['project_id'],row['round_id'])['snapshot_json']['constraints']['journal_target_id'];target=service.target_row(db,version['project_id'],target_id)['snapshot_json'] if target_id else None
    from .science import ScienceService
    from .science_candidates import apply_analysis_sources,analysis_consistency_issues
    adoptions=ScienceService(manuscripts.assets).selected_adoptions(db,version['project_id'],row['round_id'],frozen.get('analysis_adoption_ids',[]))
    augmented,authority,table_changes=apply_analysis_sources(base['snapshot_json'],adoptions,authority)
    from .figure_candidates import apply_figure_sources,figure_consistency_issues
    figures=ScienceService(manuscripts.assets).selected_figure_adoptions(db,version['project_id'],row['round_id'],frozen.get('figure_adoption_ids',[]))
    augmented,authority,figure_changes=apply_figure_sources(augmented,figures,adoptions,authority)
    candidate_version=frozen.get('candidate_schema_version',1)
    expected,changes,_,_,_=apply_operations(augmented,analysis_items(frozen['plan_state']['items'],adoptions),frozen['plan_state']['materials'],frozen['operations'],writing_context=authority,target=target,
                                            fixed_safety=candidate_version >= 2 and round_version(db,row['round_id']) is not None,candidate_schema_version=candidate_version)
    changes=table_changes+figure_changes+changes
    if any(i['severity']=='error' for i in analysis_consistency_issues(expected,adoptions)):raise source_conflict()
    if any(i['severity']=='error' for i in figure_consistency_issues(expected,figures)):raise source_conflict()
    if candidate_version>=3:
        prepare_revision_layout(expected)
    elif candidate_version==2:
        retain_school_layout(expected)
    expected['review_revision_provenance']=dict(revision_id=row['id'],round_id=row['round_id'],base_version_id=base['id'],input_sha256=row['snapshot_sha256'],synthetic=frozen['synthetic'])
    if expected!=version['snapshot_json'] or changes!=result['actual_changes'] or base['id']!=version['parent_version_id'] or result['output']!=dict(manuscript_id=version['manuscript_id'],version_id=version['id'],revision=version['revision'],parent_version_id=version['parent_version_id'],task_id=version['task_id']):raise source_conflict()


def revision_writing_context(manuscripts,db,project,identity,snapshot,*,check_version=2):
    """Public recheck of exact published local edits; original v2 rules stay strict."""
    from app.domain.manuscript_review.writing_context import load_writing_context,WritingCheckContext
    from app.domain.manuscript_writing.context import normalize_sections
    service=RevisionService(manuscripts.assets)
    row=service.revision_row(db,project,snapshot['review_revision_provenance']['revision_id'])
    result=row['result_json']
    if not result or result['output']['manuscript_id']!=identity:raise source_conflict()
    version,_=service.output(db,row)
    if version['snapshot_json']!=snapshot:raise source_conflict()
    base=service.manuscript_row(db,project,identity,row['snapshot_json']['manuscript']['revision'])
    authority=load_writing_context(manuscripts,db,project,identity,base['snapshot_json'],check_version=check_version)
    if authority is None:return None
    from .science import ScienceService
    from .science_candidates import apply_analysis_sources
    adoptions=ScienceService(manuscripts.assets).selected_adoptions(db,project,row['round_id'],row['snapshot_json'].get('analysis_adoption_ids',[]))
    _,authority,_=apply_analysis_sources(base['snapshot_json'],adoptions,authority)
    from .figure_candidates import apply_figure_sources
    figures=ScienceService(manuscripts.assets).selected_figure_adoptions(db,project,row['round_id'],row['snapshot_json'].get('figure_adoption_ids',[]))
    augmented,_,_=apply_analysis_sources(base['snapshot_json'],adoptions)
    _,authority,_=apply_figure_sources(augmented,figures,adoptions,authority)
    paragraphs=deepcopy(authority.paragraphs)
    for section in normalize_sections(snapshot):
        for paragraph in section['paragraphs']:
            previous=paragraphs.get(paragraph['id'])
            if not previous or previous['paragraph']!=paragraph:
                paragraphs[paragraph['id']]=dict(paragraph=deepcopy(paragraph),review_revision=True)
    return WritingCheckContext(paragraphs=paragraphs,sources=authority.sources,tables=authority.tables,check_version=check_version)


def analysis_items(items,adoptions):
    """Only a receipt-backed analysis need is fulfilled; materials/experiments stay."""
    if not adoptions:return items
    selected={(r['snapshot_json']['item_id'],r['snapshot_json']['item_revision']) for r in adoptions};items=deepcopy(items)
    for item in items:
        # A revised plan can request different analysis. Reusing an older receipt
        # must preserve its new needs until the user explicitly resolves them.
        if (item['id'],item['revision']) in selected:item['needs']=[n for n in item['needs'] if n['kind']!='analysis']
    return items
