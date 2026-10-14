"""Read-only relational OCR review audit; asset bytes are checked by readers."""
from app.core.exceptions import StorageError
from app.domain.ocr_review.contracts import OcrReviewSummary, OcrReviewEdit, dump_edits
from app.domain.ocr_review.service import (validate_snapshot, review_input_version,
    OcrReviewState, OcrReviewDecisionRequest, candidate_id, request_digest,
    require_approval, latest_checkpoint, CandidateReference)


def validate_parent(db, task):
    from app.domain.file_parsing import require_parse_source
    from app.maintenance.document_source_audit import validate_manifest
    snapshot = validate_snapshot(task)
    source = snapshot['source']
    row = db.execute('''SELECT r.*,t.input_snapshot,t.workflow_version,t.project_id,t.user_id,t.task_type,t.status
        FROM file_parse_results r JOIN tasks t ON t.id=r.task_id WHERE r.id=%s''',(source['parse_id'],)).fetchone()
    if not row or row['workflow_version']!='ocr_document_v1' or row['status']!='succeeded':
        raise ValueError('Missing completed parent OCR')
    require_parse_source(db,dict(row,id=row['task_id']))
    validate_manifest(row['result_json'],row['id'])
    expected=dict(file_id=row['file_id'],parse_id=row['id'],parse_version=row['version'],
        source_sha256=row['source_sha256'],document_sha256=row['result_json']['object']['sha256'],
        parser_version=row['parser_version'],selected_pages=row['input_snapshot']['page_numbers'])
    owner=db.execute('SELECT owner_id FROM projects WHERE id=%s',(task['project_id'],)).fetchone()
    if (source!=expected or row['project_id']!=task['project_id'] or row['user_id']!=task['user_id']
            or not owner or owner['owner_id']!=task['user_id'] or snapshot['filename']!=row['input_snapshot']['file']['filename']):
        raise ValueError('Frozen review parent differs')
    return snapshot


def audit_ocr_reviews(db):
    checks=[]
    tasks={row['id']:row for row in db.execute("SELECT * FROM tasks WHERE task_type='review_ocr'")}
    invalid=0
    for task in tasks.values():
        try: validate_parent(db,task)
        except (StorageError,ValueError,TypeError,KeyError): invalid+=1
    checks.append(dict(table='tasks',column='ocr_review_source',rows=len(tasks),invalid=invalid))
    checkpoints=db.execute("SELECT c.* FROM task_checkpoints c JOIN tasks t ON t.id=c.task_id WHERE t.task_type='review_ocr' ORDER BY c.task_id,c.seq").fetchall()
    states={};previous={};invalid=0
    for row in checkpoints:
        try:
            task=tasks[row['task_id']]
            state=OcrReviewState.model_validate(row['state_json']).model_dump(mode='json')
            if state['input_version']!=review_input_version(task) or row['seq']!=previous.get(task['id'],0)+1:
                raise ValueError('Invalid checkpoint sequence or parent')
            previous[task['id']]=row['seq']
            candidate=state['candidate']
            if candidate and (candidate['id']!=candidate_id(task['id']) or candidate['object_key']!=f"ocr-reviews/{candidate['id']}/{candidate['sha256']}.json"):
                raise ValueError('Invalid candidate identity')
            if row['next_node'] in ('await_confirmation','publish','done') and not candidate:
                raise ValueError('Missing durable candidate')
            states[row['id']]=(row,state)
        except (StorageError,ValueError,TypeError,KeyError): invalid+=1
    checks.append(dict(table='task_checkpoints',column='ocr_review_source',rows=len(checkpoints),invalid=invalid))
    decisions=db.execute('SELECT * FROM ocr_review_decisions').fetchall();invalid=0
    for decision in decisions:
        try:
            task=tasks[decision['task_id']]
            request=OcrReviewDecisionRequest.model_validate(decision['request_json']).model_dump(mode='json')
            checkpoint,state=states[decision['checkpoint_id']]
            wait=db.execute('SELECT * FROM task_waits WHERE id=%s',(decision['wait_id'],)).fetchone()
            if (request['operation']!=decision['operation'] or request_digest(request)!=decision['request_digest']
                    or request['input_version']!=review_input_version(task)
                    or decision['user_id']!=task['user_id'] or decision['project_id']!=task['project_id']
                    or checkpoint['task_id']!=task['id'] or checkpoint['next_node']!='await_confirmation'
                    or request['checkpoint_id']!=checkpoint['id'] or request['wait_id']!=wait['id']
                    or wait['task_id']!=task['id'] or wait['user_id']!=task['user_id'] or wait['project_id']!=task['project_id']
                    or wait['kind']!='ocr_review_confirmation' or wait['input_version']!=request['input_version']
                    or wait['task_revision']!=request['expected_task_revision']
                    or wait['resolved_task_revision']!=request['expected_task_revision']+1
                    or wait['status']!=('resolved' if request['operation']=='approve' else 'superseded')
                    or decision['response_json']['id']!=task['id']
                    or decision['response_json']['revision']!=wait['resolved_task_revision']):
                raise ValueError('Invalid review decision chain')
        except (StorageError,ValueError,TypeError,KeyError): invalid+=1
    checks.append(dict(table='ocr_review_decisions',column='ocr_review_source',rows=len(decisions),invalid=invalid))
    versions=db.execute('SELECT * FROM ocr_review_versions').fetchall();invalid=0
    for row in versions:
        try:
            task=tasks[row['task_id']]
            snapshot=validate_parent(db,task)
            current=latest_checkpoint(db,task);state=current['state_json']
            require_approval(db,task,state)
            summary=OcrReviewSummary.model_validate(row['summary_json'])
            edits=[OcrReviewEdit.model_validate(e) for e in row['edits_json']]
            if (task['status']!='succeeded' or current['node']!='done' or current['next_node']!='done'
                    or row['id']!=candidate_id(task['id']) or row['id']!=state['result_id']
                    or row['file_id']!=snapshot['source']['file_id'] or row['parent_parse_id']!=snapshot['source']['parse_id']
                    or row['created_by']!=task['user_id'] or row['decision_id']!=state['decision_id']
                    or state['candidate']!={k:row[k] for k in CandidateReference.model_fields}
                    or dump_edits(edits)!=state['edits'] or len({e.block_id for e in edits})!=len(edits)
                    or summary.unreviewed_blocks or summary.reviewed_blocks!=len(edits)
                    or (summary.accepted_blocks,summary.corrected_blocks,summary.unreadable_blocks)!=tuple(sum(e.action==action for e in edits) for action in ('accept_original','replace_text','unreadable'))):
                raise ValueError('Invalid published review chain')
        except (StorageError,ValueError,TypeError,KeyError): invalid+=1
    checks.append(dict(table='ocr_review_versions',column='ocr_review_source',rows=len(versions),invalid=invalid))
    return checks
