"""Explicit previous round and selected public input; never substitute latest."""
from uuid import uuid4
from psycopg.types.json import Jsonb
from app.adapters.task_store import source_conflict
from app.core.exceptions import StorageError
from app.domain.journals.service import now
from app.domain.literature.service import digest


def prepare_continuation(service, db, project, request, base):
    if request.user_return_id and not request.previous_round_id:
        raise StorageError('review_continuation_invalid','选择回传稿须明确上一轮。',422)
    if not request.previous_round_id:
        return None
    previous=service.round_row(db,project,request.previous_round_id)
    if previous['snapshot_json']['manuscript']['id']!=base['manuscript_id']:
        raise StorageError('review_continuation_invalid','下一轮输入须属于上一轮的同一公共稿件。',422)
    if request.user_return_id:
        from .returns import ReviewReturnService
        returns=ReviewReturnService(service.assets)
        returned=returns.return_row(db,project,request.user_return_id)
        if returned['previous_round_id']!=previous['id']:
            raise StorageError('review_continuation_invalid','回传记录不属于明确选择的上一轮。',422)
        if returned['output_version_id']!=base['id']:
            raise StorageError('review_continuation_invalid','必须明确选择此回传实际产生且已发布的公共稿。',409)
        # The caller has already read base through the published-only reader.
    return dict(previous_round_id=previous['id'],user_return_id=request.user_return_id,
                input_manuscript=dict(id=base['manuscript_id'],revision=base['revision'],version_id=base['id']))


def save_continuation(service, db, row, relation):
    if relation is None:
        return
    fields=dict(id=str(uuid4()),project_id=row['project_id'],user_id=service.store.user_id,
                idempotency_key='round:'+row['id'],request_json=Jsonb(relation),request_digest=digest(relation),
                snapshot_json=Jsonb(relation),snapshot_sha256=digest(relation),created_at=now(),round_id=row['id'],
                previous_round_id=relation['previous_round_id'],user_return_id=relation['user_return_id'],
                manuscript_id=relation['input_manuscript']['id'],manuscript_version_id=relation['input_manuscript']['version_id'])
    db.execute('INSERT INTO review_round_continuations('+','.join(fields)+') VALUES ('+','.join(['%s']*len(fields))+')',tuple(fields.values()))


def round_continuation(service, db, row):
    expected=row['snapshot_json'].get('continuation')
    saved=db.execute('SELECT * FROM review_round_continuations WHERE round_id=%s',(row['id'],)).fetchone()
    if expected is None:
        if saved:
            raise source_conflict()
        return None
    if not saved:
        raise source_conflict()
    if digest(saved['request_json'])!=saved['request_digest'] or digest(saved['snapshot_json'])!=saved['snapshot_sha256']:
        raise source_conflict()
    if (saved['snapshot_json']!=expected or saved['request_json']!=expected
        or saved['previous_round_id']!=expected['previous_round_id'] or saved['user_return_id']!=expected['user_return_id']
        or saved['manuscript_id']!=expected['input_manuscript']['id'] or saved['manuscript_version_id']!=expected['input_manuscript']['version_id']):
        raise source_conflict()
    previous=service.round_row(db,row['project_id'],saved['previous_round_id'])
    m=row['snapshot_json']['manuscript']
    if (previous['round_number']>=row['round_number'] or previous['snapshot_json']['manuscript']['id']!=m['id']
        or expected['input_manuscript']!={k:m[k] for k in ('id','revision','version_id')}
        or previous['snapshot_json']['synthetic'] and not row['snapshot_json']['synthetic']):
        raise source_conflict()
    if saved['user_return_id']:
        from .returns import ReviewReturnService
        returned=ReviewReturnService(service.assets).return_row(db,row['project_id'],saved['user_return_id'])
        if returned['previous_round_id']!=previous['id'] or returned['output_version_id']!=m['version_id']:
            raise source_conflict()
    return expected


def continuation_context(assets, project, identity):
    from .service import ReviewRoundService
    from .returns import ReviewReturnService
    from .revisions import RevisionService
    rounds=ReviewRoundService(assets)
    returns=ReviewReturnService(assets)
    revisions=RevisionService(assets)
    with rounds.store.connection() as db:
        row=rounds.round_row(db,project,identity)
        m=row['snapshot_json']['manuscript']
        root=returns.manuscripts.root(db,project,m['id'])
        inputs=[]
        for version in db.execute("SELECT v.* FROM manuscript_versions v JOIN tasks t ON t.id=v.task_id WHERE v.manuscript_id=%s AND t.status='succeeded' ORDER BY v.revision DESC",(m['id'],)).fetchall():
            rounds.manuscript(db,project,m['id'],version['revision'])
            exports=[]
            for export in db.execute('SELECT id FROM manuscript_exports WHERE version_id=%s ORDER BY created_at DESC,id',(version['id'],)).fetchall():
                view=returns.manuscripts.export_view(db,version,export['id'])
                exports.append(dict(id=export['id'],status=view['status']))
            inputs.append(dict(id=m['id'],revision=version['revision'],version_id=version['id'],title=version['snapshot_json']['title'],exports=exports))
        successful=[]
        for run in db.execute('SELECT id FROM review_revision_runs WHERE round_id=%s AND output_version_id IS NOT NULL ORDER BY created_at DESC,id',(identity,)).fetchall():
            fixed=revisions.revision_row(db,project,run['id'])
            if rounds.store.require_task(db,fixed['task_id'])['status']=='succeeded':
                output=fixed['result_json']['output']
                if rounds.store.require_task(db,output['task_id'])['status']=='succeeded':
                    successful.append(dict(id=fixed['id'],output=output))
        returned=[returns.view_return(db,returns.return_row(db,project,r['id'])) for r in db.execute('SELECT id FROM review_round_user_returns WHERE previous_round_id=%s ORDER BY created_at DESC,id',(identity,)).fetchall()]
        return dict(previous_round_id=identity,manuscript_id=m['id'],expected_current_revision=root['current_revision'],eligible_inputs=inputs,successful_revisions=successful,returns=returned)
