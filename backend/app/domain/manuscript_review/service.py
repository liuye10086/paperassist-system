"""Persist deterministic local review candidates and publish explicitly through existing tasks."""
from copy import deepcopy
from datetime import datetime
from uuid import uuid4
from psycopg.types.json import Jsonb
from app.adapters.task_store import source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_preparation.service import require_key
from app.domain.literature.service import digest
from app.domain.manuscripts.service import ManuscriptService,now
from app.domain.manuscripts.sources import read_source
from app.domain.manuscripts.school_binding import current_changes as school_changes
from .contracts import ReviewRequest,RULES_VERSION
from .composition import compose
from .facts import extract_facts,relationships
from .checks import check_snapshot
from .writing_context import load_writing_context,has_review_edits,V2_WORKFLOW_MESSAGE


def invalid(message): return StorageError('manuscript_review_input_invalid',message,422)


class ReviewService:
    def __init__(self,assets):
        self.assets=assets;self.manuscripts=ManuscriptService(assets);self.store=self.manuscripts.store

    def source_state(self,db,project,base,selected=()):
        """Capture observable source state, including versions not selected yet."""
        previous_review=base.get('review') or (base.get('review_history') or [{}])[-1].get('review',{})
        sources=list({s['id']:s for s in [*base['sources'],*previous_review.get('selected_sources',[]),*selected]}.values())
        combined={**base,'sources':list({s['id']:s for s in sources}.values())}
        changed=self.manuscripts.source_changes(project,combined)
        configurations=[];observations=[]
        for source in sources:
            selection={k:source[k] for k in ('kind','id','file_id','role')}
            try: observations.append(dict(id=source['id'],sha256=digest(read_source(self.manuscripts,project,selection))))
            except StorageError as exc:
                if exc.code in ('storage_unavailable','database_configuration'): raise
                observations.append(dict(id=source['id'],unavailable=exc.code))
            reasons=[]
            if source['kind']=='analysis_run':
                newer=db.execute('SELECT n.id,n.setup_revision FROM analysis_runs n JOIN analysis_runs b ON b.id=%s WHERE n.file_id=b.file_id AND n.completed_at>b.completed_at ORDER BY n.completed_at,n.id',(source['id'],)).fetchall()
                setup=db.execute('SELECT revision FROM analysis_setups WHERE file_id=%s',(source['file_id'],)).fetchone()
                configurations.append(dict(id=source['id'],setup_revision=setup['revision'] if setup else None,newer=[dict(r) for r in newer]))
                if newer: reasons.append('newer_analysis_run')
            elif source['kind']=='figure':
                config=db.execute('SELECT v.configuration_id,v.revision,c.current_revision FROM figures f JOIN figure_config_versions v ON v.id=f.figure_config_version_id JOIN figure_configurations c ON c.id=v.configuration_id WHERE f.id=%s',(source['id'],)).fetchone()
                if config:
                    configurations.append(dict(id=source['id'],**dict(config)))
                    if config['revision']!=config['current_revision']: reasons.append('figure_configuration_changed')
            elif source['kind'] in ('document_version','ocr_review_version','external_evidence_version'):
                table={'document_version':'file_parse_results','ocr_review_version':'ocr_review_versions','external_evidence_version':'external_evidence_versions'}[source['kind']]
                versions=db.execute('SELECT id,version FROM '+table+' WHERE file_id=%s ORDER BY version,id',(source['file_id'],)).fetchall()
                configurations.append(dict(id=source['id'],available_versions=[dict(v) for v in versions]))
            if reasons:
                existing=next((c for c in changed if c['id']==source['id']),None)
                if existing: existing['reasons']+=reasons
                else: changed.append(dict(kind=source['kind'],id=source['id'],reasons=reasons))
        citation=base.get('citation_snapshot');citation_changes=[]
        if citation:
            citations=self.manuscripts.citations
            root=db.execute('SELECT revision FROM literature_citation_drafts WHERE id=%s',(citation['draft_id'],)).fetchone()
            support=[]
            for paragraph in citation['paragraphs']:
                for fragment in paragraph['fragments']:
                    if fragment['kind']!='claim': continue
                    for bound in fragment['bindings']:
                        claim,_=citations.evidence.claim_row(db,project,fragment['claim_id'],fragment['claim_revision'])
                        latest=citations.latest_review(db,project,fragment['claim_id'],fragment['claim_revision'],bound['project_reference_id'])
                        versions=citations.rows(db,'literature_citation_metadata_versions',project,' AND project_reference_id=%s',(bound['project_reference_id'],))
                        reference=citations.literature.require_reference(db,project,bound['project_reference_id'])
                        current=citations.literature.reference_view(db,reference)['source']
                        support.append(dict(claim_id=fragment['claim_id'],claim_revision=claim['revision'],review_id=latest['id'] if latest else None,metadata_versions=sorted(v['id'] for v in versions),receipt_id=current['receipt_id']))
            citation_changes=citations.current_changes(db,project,citation)
            configurations.append(dict(id=citation['draft_id'],draft_revision=root['revision'] if root else None,support=support))
        return dict(changes=changed,observations=observations,configurations=configurations,citation_integrity_changes=citation_changes)

    def context(self,project,identity,revision=None):
        with self.store.connection() as db:
            root=self.manuscripts.root(db,project,identity)
            version=self.manuscripts.version(db,project,identity,revision or root['current_revision'])
            base=version['snapshot_json'];state=self.source_state(db,project,base)
            writing_context=load_writing_context(self.manuscripts,db,project,identity,base)
        previous=base.get('review') or (base.get('review_history') or [{}])[-1].get('review',{})
        return dict(base_revision=version['revision'],base_version_id=version['id'],rules_version=RULES_VERSION,facts=extract_facts(base),relationships=relationships(base,previous.get('relationships',{}).get('associations',[])),issues=check_snapshot(base,previous.get('metadata',[]),writing_context=writing_context)+[dict(id='material:'+i['id'],category='material',severity='human_review',location=i['id'],message=i['message'],actual=i.get('values',[]),expected='targeted material correction',source_evidence=[],rules_version=RULES_VERSION) for i in base['issues']],current_changes=state['changes'],source_candidates=self.manuscripts.candidates(project),real_calls_enabled=False)

    def row(self,db,project,identity,review_id):
        self.manuscripts.root(db,project,identity)
        row=db.execute('SELECT * FROM manuscript_reviews WHERE id=%s AND manuscript_id=%s AND project_id=%s AND user_id=%s',(review_id,identity,project,self.store.user_id)).fetchone()
        if not row: raise StorageError('manuscript_review_not_found','资料评审不存在。',404)
        self.validate_row(db,row)
        return row

    def validate_row(self,db,row):
        try:
            frozen=row['input_snapshot']
            if (type(frozen.get('schema_version')) is not int or frozen['schema_version']!=1
                or set(frozen)-{'writing_check_version'}!={'schema_version','review_id','project_id','manuscript_id','base_version_id','base_snapshot','input','selected_sources','source_state','rules_version','created_by','created_at'}):
                raise ValueError('Invalid frozen review schema')
            if 'writing_check_version' in frozen and (type(frozen['writing_check_version']) is not int or frozen['writing_check_version'] not in (1,2)):
                raise ValueError('Invalid writing compatibility version')
            if row['published_revision'] is not None and row['published_revision']!=row['request_json']['base_revision']+1: raise ValueError('Review revision does not precede publication')
            if (digest(frozen)!=row['input_digest'] or digest(row['request_json'])!=row['request_digest']
                or digest(row['candidate_json'])!=row['candidate_sha256'] or digest(row['report_json'])!=row['report_sha256']
                or row['rules_version']!=RULES_VERSION or frozen['rules_version']!=RULES_VERSION
                or frozen['input']!=row['request_json'] or frozen['review_id']!=row['id']
                or frozen['project_id']!=row['project_id'] or frozen['manuscript_id']!=row['manuscript_id']
                or frozen['created_by']!=row['user_id'] or frozen['base_version_id']!=row['base_version_id']
                or datetime.fromisoformat(frozen['created_at'])!=row['created_at']): raise ValueError('Review input drift')
            base=self.manuscripts.version(db,row['project_id'],row['manuscript_id'],row['request_json']['base_revision'])
            if base['id']!=row['base_version_id'] or base['snapshot_json']!=frozen['base_snapshot']: raise ValueError('Review base drift')
            # Historical reports retain their original deterministic rules.
            # Only new v2-based reviews freeze this explicit compatibility flag.
            writing_context=None
            if frozen.get('writing_check_version') in (1,2):
                writing_context=load_writing_context(self.manuscripts,db,row['project_id'],row['manuscript_id'],frozen['base_snapshot'],check_version=frozen['writing_check_version'])
                if writing_context is None: raise ValueError('Writing authority is missing')
            candidate,report=compose(frozen,writing_context=writing_context)
            if candidate!=row['candidate_json'] or report!=row['report_json']: raise ValueError('Review candidate/report drift')
            if row['published_revision']:
                published=db.execute('SELECT * FROM manuscript_versions WHERE manuscript_id=%s AND revision=%s',(row['manuscript_id'],row['published_revision'])).fetchone()
                if (not published or published['snapshot_json']!=candidate or published['parent_version_id']!=base['id']
                    or published['project_id']!=row['project_id'] or published['user_id']!=row['user_id']
                    or row['published_revision']!=row['request_json']['base_revision']+1): raise ValueError('Review publication drift')
        except (ValueError,KeyError,TypeError) as exc: raise source_conflict() from exc

    def view(self,row):
        return dict(id=row['id'],project_id=row['project_id'],manuscript_id=row['manuscript_id'],base_revision=row['request_json']['base_revision'],base_version_id=row['base_version_id'],status='published' if row['published_revision'] else 'candidate',input=row['request_json'],input_sha256=row['input_digest'],rules_version=row['rules_version'],created_by=row['user_id'],created_at=row['created_at'].isoformat(),candidate=row['candidate_json'],report=row['report_json'],published_revision=row['published_revision'],real_calls_enabled=False)

    def get(self,project,identity,review_id):
        with self.store.connection() as db: return self.view(self.row(db,project,identity,review_id))

    def list(self,project,identity):
        with self.store.connection() as db:
            self.manuscripts.root(db,project,identity)
            rows=db.execute('SELECT id FROM manuscript_reviews WHERE manuscript_id=%s AND project_id=%s AND user_id=%s ORDER BY created_at DESC,id',(identity,project,self.store.user_id)).fetchall()
            return dict(items=[self.view(self.row(db,project,identity,r['id'])) for r in rows])

    def create(self,project,identity,request,key):
        require_key(key);request=ReviewRequest.model_validate(request) if isinstance(request,dict) else request
        body=request.model_dump(mode='json')
        with self.store.connection(write=True) as db:
            self.manuscripts.root(db,project,identity)
            db.execute('SELECT id FROM projects WHERE id=%s FOR UPDATE',(project,)).fetchone()
            root=self.manuscripts.root(db,project,identity)
            replay=db.execute('SELECT id,request_digest FROM manuscript_reviews WHERE manuscript_id=%s AND idempotency_key=%s',(identity,key)).fetchone()
            if replay:
                if replay['request_digest']!=digest(body): raise StorageError('task_idempotency_conflict','请求标识已用于不同评审输入。',409)
                return self.view(self.row(db,project,identity,replay['id'])),200
            version=self.manuscripts.version(db,project,identity,request.base_revision)
            if root['current_revision']!=request.base_revision or self.store.require_task(db,version['task_id'])['status']!='succeeded':
                raise StorageError('manuscript_revision_conflict','请选择当前已发布基础版本。',409)
            if version['snapshot_json'].get('writing_provenance',{}).get('schema_version')==2 and has_review_edits(body):
                raise StorageError('manuscript_review_v2_workflow_required',V2_WORKFLOW_MESSAGE,422)
            if school_changes(self.manuscripts,project,version['snapshot_json']): raise source_conflict()
            template_files={x['file_id'] for x in version['snapshot_json'].get('thesis_context',{}).get('source_files',[]) if x['role'] in ('template','supplement')}
            if any(s.file_id in template_files for s in request.selected_sources): raise invalid('学校模板不能作为新增研究资料。')
            selected=[read_source(self.manuscripts,project,s) for s in request.selected_sources]
            old_sources=[*version['snapshot_json']['sources'],*version['snapshot_json'].get('review',{}).get('selected_sources',[])]
            if {s['id'] for s in selected}&{s['id'] for s in old_sources}: raise invalid('新资料必须与冻结基础资料具有不同标识。')
            identity_review=str(uuid4());timestamp=now()
            frozen=dict(schema_version=1,review_id=identity_review,project_id=project,manuscript_id=identity,base_version_id=version['id'],base_snapshot=version['snapshot_json'],input=body,selected_sources=selected,source_state=self.source_state(db,project,version['snapshot_json'],selected),rules_version=RULES_VERSION,created_by=self.store.user_id,created_at=timestamp.isoformat())
            writing_context=load_writing_context(self.manuscripts,db,project,identity,version['snapshot_json'])
            if writing_context is not None: frozen['writing_check_version']=writing_context.check_version
            try: candidate,report=compose(frozen,writing_context=writing_context)
            except (ValueError,KeyError,TypeError) as exc: raise invalid(str(exc)) from exc
            db.execute('''INSERT INTO manuscript_reviews(id,project_id,user_id,manuscript_id,base_version_id,idempotency_key,request_json,request_digest,input_snapshot,input_digest,candidate_json,candidate_sha256,report_json,report_sha256,rules_version,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',(identity_review,project,self.store.user_id,identity,version['id'],key,Jsonb(body),digest(body),Jsonb(frozen),digest(frozen),Jsonb(candidate),digest(candidate),Jsonb(report),digest(report),RULES_VERSION,timestamp,timestamp))
            return self.view(self.row(db,project,identity,identity_review)),201

    def assert_source_state(self,db,row):
        frozen=row['input_snapshot']
        if school_changes(self.manuscripts,row['project_id'],frozen['base_snapshot']): raise source_conflict()
        if self.source_state(db,row['project_id'],frozen['base_snapshot'],frozen['selected_sources'])!=frozen['source_state']: raise source_conflict()

    def publish(self,project,identity,review_id,expected_revision,key):
        require_key(key)
        with self.store.connection(write=True) as db:
            self.manuscripts.root(db,project,identity)
            db.execute('SELECT id FROM projects WHERE id=%s FOR UPDATE',(project,)).fetchone()
            row=self.row(db,project,identity,review_id)
            if row['input_snapshot']['base_snapshot'].get('writing_provenance',{}).get('schema_version')==2:
                raise StorageError('manuscript_review_v2_workflow_required',V2_WORKFLOW_MESSAGE,409)
            if row['published_revision']:
                if row['publish_key']!=key or expected_revision!=row['request_json']['base_revision']: raise StorageError('task_idempotency_conflict','候选已由不同发布请求处理。',409)
                status=200
            else:
                root=self.manuscripts.root(db,project,identity)
                if expected_revision!=row['request_json']['base_revision'] or root['current_revision']!=expected_revision:
                    raise StorageError('manuscript_revision_conflict','基础版本已有变化。',409)
                self.assert_source_state(db,row)
                if not row['report_json']['can_publish']: raise StorageError('manuscript_review_blocked','一致性检查存在不可豁免的来源、数值或引用问题。',409)
                base=self.manuscripts.version(db,project,identity,expected_revision);revision=expected_revision+1
                candidate=row['candidate_json'];version_id=str(uuid4());timestamp=now()
                body=deepcopy(base['request_json']);body['expected_revision']=expected_revision
                task_snapshot=dict(project_id=project,manuscript_id=identity,manuscript_version_id=version_id,revision=revision,output_language=candidate['output_language'],workflow_version=base['snapshot_json']['workflow_version'],snapshot_sha256=digest(candidate))
                producer=self.manuscripts.task(db,project,'manuscript_draft',task_snapshot,'manuscript:'+version_id,validated_sources=candidate['sources'])
                db.execute('''INSERT INTO manuscript_versions(id,project_id,user_id,idempotency_key,request_json,request_digest,manuscript_id,revision,parent_version_id,task_id,snapshot_json,snapshot_sha256,created_at,school_confirmation_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',(version_id,project,self.store.user_id,'review:'+review_id,Jsonb(body),digest(body),identity,revision,base['id'],producer['id'],Jsonb(candidate),digest(candidate),timestamp,base.get('school_confirmation_id')))
                for table in ('manuscript_sources','manuscript_citations'):
                    for original in db.execute('SELECT * FROM '+table+' WHERE version_id=%s',(base['id'],)).fetchall():
                        fields=dict(original);fields.update(id=str(uuid4()),version_id=version_id)
                        fields={k:Jsonb(v) if isinstance(v,(dict,list)) else v for k,v in fields.items()}
                        db.execute('INSERT INTO '+table+'('+','.join(fields)+') VALUES ('+','.join(['%s']*len(fields))+')',tuple(fields.values()))
                db.execute('UPDATE manuscripts SET current_revision=%s,updated_at=%s WHERE id=%s',(revision,timestamp,identity))
                db.execute('UPDATE manuscript_reviews SET published_revision=%s,publish_key=%s,updated_at=%s WHERE id=%s',(revision,key,timestamp,review_id));status=201
        return self.manuscripts.get(project,identity),status


def validate_review_version(manuscripts,db,version):
    provenance=version['snapshot_json']['review_provenance']
    service=ReviewService(manuscripts.assets)
    review=service.row(db,version['project_id'],version['manuscript_id'],provenance.get('review_id'))
    if (review['published_revision']!=version['revision'] or review['candidate_json']!=version['snapshot_json']
        or review['base_version_id']!=version['parent_version_id'] or not review['report_json']['can_publish']): raise source_conflict()
