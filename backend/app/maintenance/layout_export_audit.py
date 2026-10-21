"""Read-only validation of owner, typed DOCX, frozen input, task and output binding."""
from app.domain.layout_exports.service import LayoutExportService
from app.domain.report_collections.service import scoped_store

def audit_layout_exports(db):
    rows=db.execute('SELECT * FROM layout_exports').fetchall();invalid=0
    for row in rows:
        try:
            svc=LayoutExportService(scoped_store(row['user_id'],db.config))
            svc.row(db,row['project_id'],row['id']);task=svc.verify(db,row);svc.view(db,row)
            svc.verify_source(db,row)
            if task['status']=='succeeded': svc.download(row['project_id'],row['id'])
            attempts=db.execute('SELECT * FROM task_attempts WHERE task_id=%s ORDER BY attempt_no',(task['id'],)).fetchall()
            if [a['attempt_no'] for a in attempts]!=list(range(1,task['current_attempt']+1)): raise ValueError('Attempt gap')
            if task['status']=='running' and (not attempts or attempts[-1]['status']!='running' or not attempts[-1]['lease_owner']): raise ValueError('Lease mismatch')
        except Exception: invalid+=1
    orphan=db.execute("SELECT count(*) AS n FROM tasks t LEFT JOIN layout_exports e ON e.task_id=t.id WHERE t.task_type='layout_docx' AND e.id IS NULL").fetchone()['n']
    return [dict(table='layout_exports',column='owner_frozen_source_task_output_and_history',rows=len(rows),invalid=invalid),dict(table='tasks',column='layout_docx_binding',rows=len(rows)+orphan,invalid=orphan)]
