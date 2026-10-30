"""Publish an exact reviewed candidate with all admission checks under one lock."""
from copy import deepcopy
from uuid import uuid4
from psycopg.types.json import Jsonb
from app.adapters.task_store import source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_preparation.service import require_key
from app.domain.literature.service import digest
from app.domain.manuscripts.service import now

def publish(service,project,identity,request_id,request,key):
    from . import live_review
    require_key(key);reviews=live_review.LiveReviewService(service.assets)
    with service.store.connection(write=True) as db:
        reviews.citations.evidence.lock(db,project)
        row,task=reviews.raw(db,project,identity,request_id)
        review=reviews.row(db,project,identity,request_id,request.review_id)
        if review['review_sha256']!=request.review_sha256 or request.expected_revision!=row['request_json']['base_revision']: raise source_conflict()
        if not row['published_revision']: reviews.assert_current(db,project,identity,request_id,review)
        candidate=live_review.require_language_review(db,reviews,project,review,request,for_admission=not row['published_revision']) or deepcopy(review['reviewed_candidate_json'])
        if row['published_revision']:
            version=service.manuscripts.version(db,project,identity,row['published_revision'])
            if row['publish_key']!=key or version['snapshot_json']!=candidate:
                raise StorageError('task_idempotency_conflict','发布标识或审后版本不匹配。',409)
            status=200
        else:
            base=service.manuscripts.version(db,project,identity,request.expected_revision)
            if candidate.get('thesis_context'):
                from .school_live import validate_preservation
                from .authorization import LiveWritingService
                bundle=LiveWritingService(service.assets).bundle(db,project,task['input_snapshot']['execution']['bundle_id'])
                validate_preservation(candidate,base['snapshot_json'],bundle)
                if candidate.get('school_content_report',{}).get('can_publish') is not True:raise StorageError('manuscript_review_blocked','学校内容检查存在必须修正的问题。',409)
            version_id=str(uuid4());timestamp=now();revision=request.expected_revision+1
            body=deepcopy(base['request_json']);body.update(expected_revision=request.expected_revision,title=candidate['title'],output_language=candidate['output_language'])
            citation=candidate['citation_snapshot']
            body['citation_draft']=dict(id=citation['draft_id'],revision=citation['revision']) if citation else None
            snapshot=dict(project_id=project,manuscript_id=identity,manuscript_version_id=version_id,revision=revision,
                output_language=candidate['output_language'],workflow_version=candidate['workflow_version'],snapshot_sha256=digest(candidate))
            producer=service.manuscripts.task(db,project,'manuscript_draft',snapshot,'manuscript:'+version_id,validated_sources=candidate['sources'])
            if candidate.get('thesis_context'):
                from app.domain.admin_configuration.rule_consumption import inherit_task
                inherit_task(db,producer,confirmation_id=base['school_confirmation_id'])
            db.execute('''INSERT INTO manuscript_versions(id,project_id,user_id,idempotency_key,request_json,request_digest,manuscript_id,revision,parent_version_id,task_id,snapshot_json,snapshot_sha256,created_at,school_confirmation_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',(version_id,project,service.store.user_id,'writing:'+request_id,Jsonb(body),digest(body),identity,revision,base['id'],producer['id'],Jsonb(candidate),digest(candidate),timestamp,base.get('school_confirmation_id')))
            for original in db.execute('SELECT * FROM manuscript_sources WHERE version_id=%s',(base['id'],)).fetchall():
                fields=dict(original);fields.update(id=str(uuid4()),version_id=version_id)
                fields={k:Jsonb(v) if isinstance(v,(dict,list)) else v for k,v in fields.items()}
                db.execute('INSERT INTO manuscript_sources('+','.join(fields)+') VALUES ('+','.join(['%s']*len(fields))+')',tuple(fields.values()))
            if citation:
                for paragraph in citation['paragraphs']:
                    for fragment in paragraph['fragments']:
                        if fragment['kind']!='claim': continue
                        for binding in fragment['bindings']:
                            db.execute('''INSERT INTO manuscript_citations(id,version_id,citation_version_id,paragraph_id,claim_id,claim_revision,review_id,metadata_version_id,project_reference_id,binding_json)
                                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',(str(uuid4()),version_id,citation['version_id'],'literature:'+paragraph['id'],fragment['claim_id'],fragment['claim_revision'],binding['review_id'],binding['metadata_version_id'],binding['project_reference_id'],Jsonb(binding)))
            db.execute('UPDATE manuscripts SET current_revision=%s,title=%s,updated_at=%s WHERE id=%s',(revision,candidate['title'],timestamp,identity))
            db.execute('UPDATE manuscript_writing_requests SET published_revision=%s,publish_key=%s,updated_at=%s WHERE task_id=%s',(revision,key,timestamp,request_id));status=201
    return service.manuscripts.get(project,identity),status

def validate_published(service,db,version,writing):
    from .live_review import LiveReviewService
    candidate=version['snapshot_json'];provenance=candidate['writing_provenance']
    reviews=LiveReviewService(service.assets)
    row=reviews.row(db,version['project_id'],version['manuscript_id'],writing['task_id'],provenance.get('review_id'))
    if (writing['published_revision']!=version['revision'] or writing['base_version_id']!=version['parent_version_id']
        or row['candidate_sha256']!=writing['candidate_sha256']): raise source_conflict()
    # Historical reads verify frozen artifacts, never rewrite history after a later negative review.
    reviews.validate_frozen(db,version['project_id'],version['manuscript_id'],writing['task_id'],row)

    if provenance.get('language_review_id'):
        from .language_service import LanguageReviewService
        language=LanguageReviewService(service.assets).language_row(db,version['project_id'],version['manuscript_id'],writing['task_id'],provenance['language_review_id'])
        if language['candidate_json']!=candidate or language['review_id']!=row['id']: raise source_conflict()
    elif row['reviewed_candidate_json']!=candidate: raise source_conflict()
