"""Small caller-transaction helper. Never dispatches or modifies a target."""
from datetime import datetime,timezone
from uuid import uuid4

from app.core.exceptions import StorageError
from app.domain.bioinformatics.service import require_key


# Only these fixed SQL identifiers can enter a target query.
TARGETS={
    'bio_analysis_run':('bio_analysis_runs','created_by',('bio_analysis',)),
    'bio_insight_run':('bio_insight_runs','user_id',('bio_comparison','bio_result_import','bio_enrichment','bio_candidate','bio_insight_figure','bio_feature_extract','bio_integration')),
    'research_report':('research_report_versions','user_id',('research_report',)),
}


def _scope(db,user_id,project_id,kind,key):
    if kind not in TARGETS:raise ValueError('Unregistered analysis receipt kind')
    require_key(key)
    row=db.execute('SELECT p.id FROM projects p JOIN users u ON u.id=p.owner_id WHERE p.id=%s AND p.owner_id=%s AND u.active',(project_id,user_id)).fetchone()
    if not row:raise StorageError('project_not_found','项目不存在，请刷新项目列表。',404)


def target(db,*,user_id,project_id,kind,target_id):
    if kind not in TARGETS:raise ValueError('Unregistered analysis receipt kind')
    table,owner,types=TARGETS[kind]
    row=db.execute('SELECT r.* FROM '+table+' r JOIN tasks t ON t.id=r.task_id AND t.project_id=r.project_id WHERE r.id=%s AND r.project_id=%s AND r.'+owner+'=%s AND t.user_id=%s AND t.task_type=ANY(%s)',(target_id,project_id,user_id,user_id,list(types))).fetchone()
    if not row:raise StorageError('bio_input_integrity_changed','请求关联的来源或目标需要重新核对。',409)
    return dict(row)


def read_receipt(db,*,user_id,project_id,kind,key,request_digest=None):
    _scope(db,user_id,project_id,kind,key)
    row=db.execute('SELECT * FROM analysis_request_receipts WHERE user_id=%s AND project_id=%s AND kind=%s AND request_key=%s',(user_id,project_id,kind,key)).fetchone()
    if not row:return None
    if request_digest is not None and row['request_digest']!=request_digest:
        raise StorageError('task_idempotency_conflict','同一请求标识的内容不一致。',409)
    target(db,user_id=user_id,project_id=project_id,kind=kind,target_id=row['target_id'])
    return dict(row)


def bind_receipt(db,*,user_id,project_id,kind,key,request_digest,target_id):
    _scope(db,user_id,project_id,kind,key)
    target(db,user_id=user_id,project_id=project_id,kind=kind,target_id=target_id)
    db.execute('INSERT INTO analysis_request_receipts(id,user_id,project_id,kind,request_key,request_digest,target_id,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(user_id,project_id,kind,request_key) DO NOTHING',
        (str(uuid4()),user_id,project_id,kind,key,request_digest,target_id,datetime.now(timezone.utc)))
    row=read_receipt(db,user_id=user_id,project_id=project_id,kind=kind,key=key,request_digest=request_digest)
    if row['target_id']!=target_id:raise StorageError('task_idempotency_conflict','同一请求标识已关联其他结果。',409)
    return row
