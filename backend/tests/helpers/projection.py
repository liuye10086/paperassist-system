"""Drive the actual free queued projection worker; never replace its calculation."""
from app.domain.figure_workbench.projection_execution import run_projection_task

def check_projection(store,*args):
    value=store.check(*args)
    if value.get('task') and value['task']['status']=='queued':
        task=run_projection_task(value['task']['id'],value['task']['revision'])
        assert task and task['status']=='waiting_confirmation',task
        value=store.check(*args)
    return value

def confirm_projection(store,*args):
    value=store.confirm(*args)
    if 'task' in value:
        task=run_projection_task(value['task']['id'],value['task']['revision'])
        assert task and task['status']=='succeeded',task
        project,file,run,version,_request=args
        with store.tasks.connection() as db:
            row=store._version(db,project,file,run,version)
            value=store._projection(db,row)
        assert value is not None
    return value
