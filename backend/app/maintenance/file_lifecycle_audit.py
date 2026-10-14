"""Verify frozen receipts against their own digest, identities and policy.

Never compare a historical assessment with today's dependency graph: a changed
graph is expected, and must not retroactively alter the original decision.
"""
from copy import deepcopy
from app.domain.file_lifecycle.contracts import POLICY_VERSION, digest
from app.db.file_lifecycle_schema import SCOPE_FUNCTION_BODY


def valid_snapshot(row, snapshot, action):
    frozen = deepcopy(snapshot)
    assessment = frozen['assessment']
    revision = assessment.pop('assessment_revision')
    return (digest(frozen) == revision == row['assessment_revision']
            and assessment['file_id'] == row['file_id'] == frozen['file']['id']
            and frozen['file']['project_id'] == row['project_id']
            and assessment['action'] == action
            and assessment['policy_version'] == row['policy_version'] == POLICY_VERSION
            and assessment['automatic_deletion'] is False
            and assessment['physical_deletion_available'] is False
            and assessment['operation_preserves_history'] is True)


def audit_file_lifecycle(db):
    checks = []
    for table, field, actor, action in (
            ('file_deletion_requests','assessment_json','requested_by','delete'),
            ('file_reparse_assessments','snapshot_json','actor_id','reparse')):
        rows = db.execute(f'SELECT * FROM {table}').fetchall()
        invalid = 0
        for row in rows:
            try:
                file = db.execute('SELECT f.project_id,p.owner_id FROM files f JOIN projects p ON p.id=f.project_id WHERE f.id=%s',(row['file_id'],)).fetchone()
                valid = file and file['project_id']==row['project_id'] and file['owner_id']==row[actor]
                valid = valid and valid_snapshot(row,row[field],action)
                if action=='delete':
                    valid = valid and row['status']==row[field]['assessment']['deletion_status'] and row['resolved_at']==row['created_at']
                    valid = valid and row['request_digest']==digest(dict(expected_assessment_revision=row['assessment_revision'],reason=row['reason']))
                else:
                    task = db.execute('SELECT project_id,user_id,task_type,input_snapshot FROM tasks WHERE id=%s',(row['task_id'],)).fetchone()
                    valid = valid and task and task['project_id']==row['project_id'] and task['user_id']==row[actor]
                    valid = valid and task['task_type'] in ('parse_file','extract_dataset') and task['input_snapshot']['file']['id']==row['file_id']
                if not valid:
                    invalid += 1
            except (KeyError,ValueError,TypeError):
                invalid += 1
        checks.append(dict(table=table,column='lifecycle_integrity',rows=len(rows),invalid=invalid))
    for table in ('file_deletion_requests','file_reparse_assessments'):
        present = db.execute('''SELECT p.prosrc FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_proc p ON p.oid=t.tgfoid
            WHERE n.nspname=current_schema() AND p.pronamespace=n.oid
            AND p.proname='enforce_file_lifecycle_scope' AND NOT p.prosecdef
            AND c.relname=%s AND t.tgname=%s AND t.tgenabled='O' AND NOT t.tgisinternal
            AND t.tgtype=31 AND t.tgqual IS NULL''',
            (table,table+'_scope')).fetchone()
        valid = present and ' '.join(present['prosrc'].split())==' '.join(SCOPE_FUNCTION_BODY.split())
        checks.append(dict(table=table,column='lifecycle_scope_trigger',rows=1,invalid=0 if valid else 1))
    return checks
