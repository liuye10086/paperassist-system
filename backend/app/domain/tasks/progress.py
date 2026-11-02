"""Bounded public stages from existing task attempts and checkpoints only."""
from app.core.exceptions import StorageError
from app.domain.research_results.task_contracts import input_version

STAGES=frozenset(('frozen_inputs','source_verification','organizing_existing_members','writing_package','publishing','published','organizing_report_inputs','rendering_report_and_package','render_and_package_complete'))
COUNTS=('completed_members','total_members','table_count','figure_count')


def public_progress(db,task):
    if task['task_type'] not in ('delivery_package','research_report'):
        raise StorageError('task_transition_invalid','此任务没有这类阶段进度。',409)
    input_version(task)
    observed=db.execute('SELECT clock_timestamp() AS time').fetchone()['time']
    number=task['current_attempt']
    attempt=db.execute('SELECT started_at,finished_at,status FROM task_attempts WHERE task_id=%s AND attempt_no=%s',(task['id'],number)).fetchone() if number else None
    start=attempt['started_at'] if attempt else task['created_at']
    finish=attempt['finished_at'] if attempt else task['updated_at'] if task['status'] in ('succeeded','failed','cancelled') else None
    # Failed/retried attempts stop at their own recorded end, not the time of a later queue update.
    boundary=finish or observed
    rows=db.execute("""SELECT seq,created_at,state_json->>'stage' AS stage,
        state_json->'completed_members' AS completed_members,state_json->'total_members' AS total_members,
        state_json->'table_count' AS table_count,state_json->'figure_count' AS figure_count
        FROM task_checkpoints WHERE task_id=%s AND created_at>=%s AND created_at<=%s
        ORDER BY seq DESC LIMIT 64""",(task['id'],start,boundary)).fetchall()
    phases=[]
    for row in reversed(rows):
        stage=row['stage']
        if not number and stage=='report':stage='frozen_inputs'
        if stage not in STAGES:continue
        counts={key:row[key] for key in COUNTS if type(row[key]) is int and 0<=row[key]<=2147483647}
        if phases and phases[-1]['stage']==stage:phases[-1]['counts']=counts
        else:phases.append(dict(stage=stage,started=row['created_at'],counts=counts))
    if not phases:return None
    history=[]
    for index,phase in enumerate(phases):
        end=phases[index+1]['started'] if index+1<len(phases) else finish
        # Input freezing is already complete before the first execution attempt.
        if not number:end=phase['started']
        elapsed=max(0.0,((end or observed)-phase['started']).total_seconds())
        history.append(dict(stage=phase['stage'],started_at=phase['started'].isoformat(),ended_at=end.isoformat() if end else None,elapsed_seconds=round(elapsed,6)))
    last=history[-1]
    return dict(stage=last['stage'],attempt_no=number,stage_started_at=last['started_at'],stage_ended_at=last['ended_at'],stage_elapsed_seconds=last['elapsed_seconds'],observed_at=observed.isoformat(),stages=history,**phases[-1]['counts'])


def task_progress(store,identifier):
    with store.connection() as db:
        task=store.require_task(db,identifier)
        result=dict(task_id=task['id'],project_id=task['project_id'],task_type=task['task_type'],status=task['status'],progress=public_progress(db,task))
        if task['task_type']=='delivery_package':
            result.update(delivery_id=task['input_snapshot']['delivery_id'],snapshot_id=task['input_snapshot']['snapshot_id'])
        return result
