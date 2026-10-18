"""Explicit v4 multi-file proofs; legacy single-file readers remain strict."""
from app.core.exceptions import StorageError
from app.domain.file_lifecycle.contracts import digest


def require_prepared_source(db,source,project,user):
    from app.domain.dataset_preparation.quality_service import audit_published
    row=db.execute('SELECT * FROM prepared_dataset_versions WHERE id=%s',(source['dataset_id'],)).fetchone()
    task=db.execute('SELECT * FROM tasks WHERE id=%s',(row['task_id'],)).fetchone() if row else None
    file=db.execute('SELECT * FROM files WHERE id=%s AND project_id=%s',(source['file_id'],project)).fetchone()
    if (not row or not task or not file or row['file_id']!=source['file_id'] or row['created_by']!=user
            or task['user_id']!=user or task['project_id']!=project):
        raise ValueError('Research computational source scope differs')
    if task['workflow_version']=='dataset_preparation_v3':
        from app.domain.dataset_preparation.derivation_service import audit_published
    validated=audit_published(db,task,row)
    if task['workflow_version']=='dataset_preparation_v1':
        from app.domain.analysis_sources import prepared_dataset_source
        from app.domain.dataset_preparation.service import validate_snapshot
        validated=prepared_dataset_source(row,validate_snapshot(task)['source'])
    if validated!=source:
        raise ValueError('Research computational source differs')


def require_research_material(db,task,snapshot):
    from app.domain.external_evidence.service import validate_evidence_row
    owner=db.execute('SELECT owner_id FROM projects WHERE id=%s',(task['project_id'],)).fetchone()
    if not owner or owner['owner_id']!=task['user_id']:raise ValueError('Research owner differs')
    for evidence in snapshot['evidence_versions']:
        row=db.execute('SELECT * FROM external_evidence_versions WHERE id=%s',(evidence['id'],)).fetchone()
        if (not row or row['project_id']!=task['project_id'] or row['user_id']!=task['user_id']
                or validate_evidence_row(db,row)!=evidence):
            raise ValueError('Frozen research material differs')
    if snapshot['source'] is not None:
        require_prepared_source(db,snapshot['source'],task['project_id'],task['user_id'])


def research_proofs(db,tasks,user,project):
    """Prove exact snapshots/content before permitting any multi-file projection."""
    proofs={}
    for task in tasks:
        if task['user_id']!=user or task['project_id']!=project:continue
        try:
            if task['workflow_version'] in ('analysis_plan_v4','analysis_plan_v5'):
                from app.domain.analysis_plan.service import validate_snapshot,latest_checkpoint,validate_published
                snapshot=validate_snapshot(task)
                require_research_material(db,task,snapshot)
                latest_checkpoint(db,task)
                proofs[digest(snapshot)]=snapshot
                row=db.execute('SELECT * FROM confirmed_analysis_plans WHERE task_id=%s',(task['id'],)).fetchone()
                if row:
                    content=validate_published(db,task,row)
                    proofs[digest(content)]=content
                    proofs[digest(row['plan_json'])]=row['plan_json']
            elif task['workflow_version'] in ('analysis_recommendation_v4','analysis_recommendation_v5'):
                from app.domain.analysis_recommendation.service import validate_snapshot
                snapshot=validate_snapshot(task)
                require_prepared_source(db,snapshot['source'],project,user)
                proofs[digest(snapshot)]=snapshot
        except (StorageError,KeyError,TypeError,ValueError):
            continue
    return proofs


def scoped_snapshot(value,file_id,proofs):
    """Collapse only exactly proved contracts, retaining every local dependency."""
    if isinstance(value,dict):
        if digest(value) in proofs:
            source=value.get('source')
            local=dict(source=source) if source and source['file_id']==file_id else {}
            local['evidence']=[dict(evidence_version_id=e['id']) for e in value.get('evidence_versions',[]) if e['file_id']==file_id]
            return local
        return {k:scoped_snapshot(v,file_id,proofs) for k,v in value.items()}
    if isinstance(value,list):return [scoped_snapshot(v,file_id,proofs) for v in value]
    return value


def valid_evidence(db,row,file,user):
    from app.domain.external_evidence.service import validate_evidence_row
    try:
        validate_evidence_row(db,row)
        return row['file_id']==file['id'] and row['project_id']==file['project_id'] and row['user_id']==user
    except (StorageError,KeyError,TypeError,ValueError):return False
