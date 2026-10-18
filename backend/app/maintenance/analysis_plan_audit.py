"""Read-only database plan lineage audit; readers separately verify asset bytes."""
from app.core.exceptions import StorageError
from app.domain.analysis_sources import prepared_dataset_source
from app.domain.analysis_plan.service import (validate_snapshot,plan_input_version,latest_checkpoint,
    read_decision,validate_published,validate_checkpoint)
from app.domain.analysis_plan.context import validate_result_context, plan_selection_check
from app.domain.analysis_plan.references import PlanReference
from app.domain.dataset_preparation.service import validate_snapshot as preparation_snapshot
from app.maintenance.dataset_source_audit import object_json


def audit_analysis_plans(db):
    checks=[]
    tasks={r['id']:r for r in db.execute("SELECT * FROM tasks WHERE task_type='analysis_plan'")}
    invalid=0
    for task in tasks.values():
        try:
            snapshot=validate_snapshot(task)
            if task['workflow_version'] in ('analysis_plan_v4','analysis_plan_v5'):
                from app.domain.external_evidence.service import validate_evidence_row
                owner=db.execute('SELECT owner_id FROM projects WHERE id=%s',(task['project_id'],)).fetchone()
                if not owner or owner['owner_id']!=task['user_id']:
                    raise ValueError('Requirement owner differs')
                for evidence in snapshot['evidence_versions']:
                    saved=db.execute('SELECT * FROM external_evidence_versions WHERE id=%s',(evidence['id'],)).fetchone()
                    if (not saved or saved['project_id']!=task['project_id'] or saved['user_id']!=task['user_id']
                            or validate_evidence_row(db,saved)!=evidence):
                        raise ValueError('Requirement material differs')
                if snapshot['source'] is None:
                    continue
            row=db.execute('SELECT * FROM prepared_dataset_versions WHERE id=%s',(snapshot['source']['dataset_id'],)).fetchone()
            parent=db.execute('SELECT * FROM tasks WHERE id=%s',(row['task_id'],)).fetchone()
            owner=db.execute('SELECT owner_id FROM projects WHERE id=%s',(task['project_id'],)).fetchone()
            file=db.execute('SELECT filename FROM files WHERE id=%s',(row['file_id'],)).fetchone()
            if parent['workflow_version']=='dataset_preparation_v3':
                from app.domain.dataset_preparation.derivation_service import audit_published
                prepared_source=audit_published(db,parent,row)
            elif parent['workflow_version']=='dataset_preparation_v2':
                from app.domain.dataset_preparation.quality_service import audit_published
                prepared_source=audit_published(db,parent,row)
            else:
                prepared_source=prepared_dataset_source(row,preparation_snapshot(parent)['source'])
            if (parent['status']!='succeeded' or row['created_by']!=task['user_id'] or owner['owner_id']!=task['user_id']
                    or parent['project_id']!=task['project_id'] or row['file_id']!=snapshot['source']['file_id']
                    or prepared_source!=snapshot['source']
                    or file['filename']!=snapshot['filename']):
                raise ValueError('Prepared plan parent differs')
        except (StorageError,KeyError,ValueError,TypeError): invalid+=1
    checks.append(dict(table='tasks',column='analysis_plan_source',rows=len(tasks),invalid=invalid))
    rows=db.execute("SELECT c.* FROM task_checkpoints c JOIN tasks t ON t.id=c.task_id WHERE t.task_type='analysis_plan'").fetchall()
    invalid=0
    for row in rows:
        try:
            validate_checkpoint(db,tasks[row['task_id']],row)
        except (StorageError,KeyError,ValueError,TypeError): invalid+=1
    for task in tasks.values():
        try: latest_checkpoint(db,task)
        except (StorageError,KeyError,ValueError,TypeError): invalid+=1
    checks.append(dict(table='task_checkpoints',column='analysis_plan_source',rows=len(rows),invalid=invalid))
    rows=db.execute('SELECT * FROM analysis_plan_decisions').fetchall();invalid=0
    for row in rows:
        try:
            task=tasks[row['task_id']]
            if task['workflow_version'] in ('analysis_plan_v4','analysis_plan_v5') and row['response_json'].get('completion_type')=='continued_as_plan':
                checkpoint=latest_checkpoint(db,task)
                if checkpoint['state_json']['decision_id']!=row['id']:
                    raise ValueError('Continuation decision differs')
            else:
                read_decision(db,task,row['id'])
        except (StorageError,KeyError,ValueError,TypeError): invalid+=1
    checks.append(dict(table='analysis_plan_decisions',column='analysis_plan_source',rows=len(rows),invalid=invalid))
    rows=db.execute('SELECT * FROM confirmed_analysis_plans').fetchall();invalid=0;plans={};identities={}
    for row in rows:
        identities[row['file_id'],row['setup_revision']]=row['id']
        try: plans[row['id']]=validate_published(db,tasks[row['task_id']],row)
        except (StorageError,KeyError,ValueError,TypeError): invalid+=1
    checks.append(dict(table='confirmed_analysis_plans',column='analysis_plan_source',rows=len(rows),invalid=invalid))
    for table,column,revision in (('analysis_setups','setup_json','revision'),('analysis_runs','result_json','setup_revision')):
        count=invalid=0
        for row in db.execute('SELECT * FROM '+table):
            value=object_json(row[column]);identity=identities.get((row['file_id'],row[revision]))
            has_context='schema_version' in value or 'analysis_context' in value
            if not identity and 'analysis_plan' not in value and not has_context: continue
            count+=1
            try:
                reference=PlanReference.model_validate(value['analysis_plan'],strict=True).model_dump(mode='json')
                plan=plans[identity]
                if (reference!=dict(plan_id=plan['id'],sha256=plan['sha256'],resolutions=plan['resolutions'])
                        or value.get(revision)!=plan['setup_revision'] or value.get('source')!=plan['source']
                        or value.get('selection')!=plan['selection'] or value.get('check')!=plan_selection_check(plan)):
                    raise ValueError('Consumer reference differs')
                validate_result_context(value,plan)
            except (StorageError,KeyError,ValueError,TypeError): invalid+=1
        checks.append(dict(table=table,column='analysis_plan_reference',rows=count,invalid=invalid))
    return checks
