"""Read-only input, suggestion, ownership and model receipt consistency audit."""
from app.domain.literature_assistance.service import require_snapshot, checkpoint
from app.domain.literature_assistance.contracts import validate_result
from app.domain.literature_assistance.execution import instructions_for
from app.domain.model_usage.gateway import input_digest


def audit_literature_assistance(db):
    rows = db.execute('SELECT * FROM literature_assistance_requests').fetchall()
    tasks = {r['id']:dict(r) for r in db.execute("SELECT * FROM tasks WHERE task_type='literature_assistance'")}
    owners = {r['id']:r['owner_id'] for r in db.execute('SELECT id,owner_id FROM projects')}
    invalid = len(set(tasks)-{r['task_id'] for r in rows})
    for row in rows:
        try:
            task = tasks[row['task_id']]
            snapshot = require_snapshot(task)
            saved = checkpoint(db,task)
            if (owners.get(row['project_id'])!=row['user_id'] or row['project_id']!=task['project_id']
                    or row['user_id']!=task['user_id'] or row['kind']!=snapshot['input']['kind']
                    or (row['result_json'] is None)!=(row['model_call_id'] is None)
                    or (task['status']=='succeeded')!=(row['result_json'] is not None)
                    or (task['status']=='succeeded')!=(saved['next_node']=='done')):
                raise ValueError()
            if row['result_json'] is not None:
                validate_result(row['result_json'],snapshot)
                call = db.execute('SELECT * FROM model_calls WHERE id=%s',(row['model_call_id'],)).fetchone()
                payload = dict(kind=snapshot['input']['kind'],output_language=snapshot['input']['output_language'],material=snapshot['material'])
                if (not call or call['task_id']!=task['id'] or call['user_id']!=task['user_id']
                        or call['project_id']!=task['project_id'] or call['status']!='completed'
                        or call['provider_response_id'] is None or call['call_key']!='literature-assistance-v1'
                        or call['input_digest']!=input_digest(instructions=instructions_for(snapshot),payload=payload)
                        or call['policy_snapshot']['prompt_version']!='literature_assistance_v1'
                        or call['policy_snapshot']['tools']):
                    raise ValueError()
        except Exception:
            invalid += 1
    return [dict(table='literature_assistance_requests',column='input_suggestion_and_receipt',rows=len(rows),invalid=invalid)]
