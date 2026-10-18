"""Fenced plan check/wait and atomic approved-plan/setup publication."""
from psycopg.types.json import Jsonb
from datetime import timezone
from app.adapters.task_store import TaskStore,DatasetTaskAssets,source_conflict
from app.adapters.storage import ProjectStore
from app.domain.dataset_preparation.service import append_checkpoint,request_digest
from app.domain.analysis_plan.service import (AnalysisPlanService,latest_checkpoint,validate_snapshot,require_approval,plan_id,published_content)
from app.domain.tasks.waits import persist_wait


class AnalysisPlanStore:
    def __init__(self,repository):
        self.repository=repository

    def service(self,task):
        return AnalysisPlanService(DatasetTaskAssets(task['user_id'],self.repository.config,self.repository.assets.directory))

    def load(self,lease):
        with self.repository.connection() as db:
            task=self.repository.require_lease(db,lease);self.repository.require_owner(db,task)
            checkpoint=latest_checkpoint(db,task)
        sheet=self.service(task).require_check(task,checkpoint['state_json'])
        return task,checkpoint,sheet

    def wait(self,lease,checkpoint,check):
        with self.repository.connection(write=True) as db:
            task=self.repository.require_lease(db,lease);self.repository.require_owner(db,task)
            current=latest_checkpoint(db,task)
            if current['id']!=checkpoint['id'] or current['next_node']!='check': raise source_conflict()
            state=dict(current['state_json']);state['check']=check
            self.service(task).require_check(task,state)
            previous=task['revision']
            needs_input=bool(check.get('research_missing'))
            node='await_input' if needs_input else 'await_confirmation'
            task.update(status='waiting_input' if needs_input else 'waiting_confirmation',phase='plan',revision=previous+1,
                updated_at=max(self.repository.now(db),task['updated_at']),reason_code='input_required' if needs_input else 'confirmation_required',error_code=None)
            append_checkpoint(db,task,node,node,state,current)
            TaskStore.finish_attempt(db,task);TaskStore.update_task(db,task,previous)
            TaskStore.append_event(db,task,'waiting');persist_wait(db,task)
            return TaskStore.public_task(task)

    def publish(self,lease,checkpoint):
        with self.repository.connection(write=True) as db:
            task=self.repository.require_lease(db,lease);self.repository.require_owner(db,task)
            current=latest_checkpoint(db,task);state=dict(current['state_json']);snapshot=validate_snapshot(task)
            if current['id']!=checkpoint['id'] or current['next_node']!='publish': raise source_conflict()
            require_approval(db,task,state)
            self.service(task).require_check(task,state)
            now=max(self.repository.now(db),task['updated_at']).astimezone(timezone.utc);id=plan_id(task['id'])
            content=published_content(task,snapshot,state,id,snapshot['expected_setup_revision']+1,now)
            digest=request_digest(content)
            setup=dict(file_id=content['file_id'],source_sha256=snapshot['source']['source_sha256'],status='configured',
                source=snapshot['source'],selection=state['selection'],check=(state['check']['data_check'] if snapshot['schema_version'] in (4,5) else state['check'])['selection_check'],
                analysis_plan=dict(plan_id=id,sha256=digest,resolutions=state['resolutions']))
            ProjectStore.save_analysis_setup_in_transaction(db,task['project_id'],content['file_id'],
                snapshot['expected_setup_revision'],setup,now)
            db.execute('''INSERT INTO confirmed_analysis_plans
                (id,file_id,task_id,decision_id,created_by,created_at,sha256,plan_json,setup_revision)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (id,content['file_id'],task['id'],state['decision_id'],task['user_id'],now,digest,Jsonb(content),content['setup_revision']))
            state['result_id']=id;task.update(phase='plan',updated_at=now)
            published=append_checkpoint(db,task,'publish','done',state,current)
            append_checkpoint(db,task,'done','done',state,published)
            self.repository.require_lease(db,lease)
            self.repository._finish(db,task,'succeeded',None)
            return TaskStore.public_task(task)
