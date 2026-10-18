"""Read-only audit of free statistics snapshots and exact task/result receipt bindings."""
from app.core.exceptions import StorageError
from app.adapters.storage import ProjectStore
from app.domain.statistics_execution.service import require_snapshot, digest
from app.domain.statistics_execution.verification import validate_statistics_receipt


def audit_statistics_execution(db):
    rows=db.execute("SELECT * FROM tasks WHERE task_type='statistics_compute'").fetchall()
    invalid=0
    for task in rows:
        try:
            snapshot=require_snapshot(task)
            file=db.execute('SELECT f.*,p.owner_id FROM files f JOIN projects p ON p.id=f.project_id WHERE f.id=%s',(snapshot['file']['id'],)).fetchone()
            if (not file or file['project_id']!=task['project_id'] or file['owner_id']!=task['user_id']
                    or file['sha256']!=snapshot['file']['sha256'] or snapshot['setup']['file_id']!=file['id']):
                raise ValueError('Statistics file identity differs')
            source=snapshot['setup'].get('source')
            if source:
                from app.domain.file_lifecycle.research_references import require_prepared_source
                require_prepared_source(db,source,task['project_id'],task['user_id'])
                reference=snapshot['setup']['analysis_plan']
                plan=db.execute('SELECT * FROM confirmed_analysis_plans WHERE id=%s',(reference['plan_id'],)).fetchone()
                if not plan or plan['sha256']!=reference['sha256'] or snapshot['plan']['sha256']!=plan['sha256']:
                    raise ValueError('Statistics confirmed plan differs')
            receipt=task['execution_receipt']
            if receipt is not None: validate_statistics_receipt(receipt)
            if task['status']=='succeeded':
                run=db.execute('SELECT * FROM analysis_runs WHERE id=%s',(task['result_analysis_run_id'],)).fetchone()
                result=ProjectStore.analysis_run_value(run) if run else None
                if (not result or receipt is None or receipt['status']!='succeeded' or receipt['result_sha256']!=digest(result)
                        or result['file_id']!=file['id'] or result.get('source')!=source
                        or result['setup_revision']!=snapshot['setup']['revision'] or result['selection']!=snapshot['setup']['selection']):
                    raise ValueError('Statistics result receipt differs')
            elif task['result_analysis_run_id'] is not None:
                raise ValueError('Unfinished task published a result')
        except (StorageError,KeyError,TypeError,ValueError): invalid+=1
    return [dict(table='tasks',column='statistics_execution',rows=len(rows),invalid=invalid)]
