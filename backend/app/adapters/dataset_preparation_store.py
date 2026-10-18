"""Fenced local preparation nodes; each human wait commits and ends its lease."""
import json
from datetime import timezone
from psycopg.types.json import Jsonb

from app.adapters.task_store import TaskStore, DatasetTaskAssets, source_conflict
from app.domain.dataset_preparation.service import (DatasetPreparationService, validate_snapshot,
    preparation_input_version, candidate_id, latest_checkpoint, append_checkpoint, require_approval)
from app.domain.tasks.waits import persist_wait


class DatasetPreparationStore:
    def __init__(self,repository):
        self.repository = repository

    def service(self,task):
        model = DatasetPreparationService
        if task['workflow_version'] == 'dataset_preparation_v3':
            from app.domain.dataset_preparation.derivation_service import DerivationPreparationService
            model = DerivationPreparationService
        if task['workflow_version'] == 'dataset_preparation_v2':
            from app.domain.dataset_preparation.quality_service import QualityPreparationService
            model = QualityPreparationService
        return model(DatasetTaskAssets(task['user_id'],self.repository.config,self.repository.assets.directory))

    def load(self,lease):
        with self.repository.connection() as db:
            task = self.repository.require_lease(db,lease)
            self.repository.require_owner(db,task)
            validate_snapshot(task)
            checkpoint = latest_checkpoint(db,task)
        service = self.service(task)
        _,sheet = service.require_raw(preparation_input_version(task)['source'],task['project_id'])
        return task,checkpoint,sheet

    def wait(self,lease,checkpoint,obj):
        # Content is durable before its DB reference; a rollback leaves a safe,
        # content-addressed orphan for the next attempt to reuse.
        with self.repository.connection() as db:
            task = self.repository.require_lease(db,lease)
        service = self.service(task)
        content = json.dumps(obj.model_dump(mode='json'),ensure_ascii=False,sort_keys=True,
            separators=(',',':'),allow_nan=False).encode('utf-8')
        reference = dict(id=candidate_id(task['id']),**service.objects.save(candidate_id(task['id']),content))
        with self.repository.connection(write=True) as db:
            task = self.repository.require_lease(db,lease)
            self.repository.require_owner(db,task)
            current = latest_checkpoint(db,task)
            state = dict(current['state_json'])
            if (current['id'] != checkpoint['id'] or current['next_node'] != 'prepare_preview'
                    or (obj.base_source if obj.schema_version in (2,3) else obj.parent_source).model_dump(mode='json') != state['input_version']['source']
                    or obj.recipe.model_dump(mode='json') != state['recipe']):
                raise source_conflict()
            previous_revision = task['revision']
            task.update(status='waiting_confirmation',phase='plan',revision=previous_revision+1,
                updated_at=max(self.repository.now(db),task['updated_at']),reason_code='confirmation_required',error_code=None)
            state['candidate'] = reference
            append_checkpoint(db,task,'await_confirmation','await_confirmation',state,current)
            TaskStore.finish_attempt(db,task)
            TaskStore.update_task(db,task,previous_revision)
            TaskStore.append_event(db,task,'waiting')
            persist_wait(db,task)
            return TaskStore.public_task(task)

    def publish(self,lease,checkpoint):
        with self.repository.connection() as db:
            task = self.repository.require_lease(db,lease)
        service = self.service(task)
        _,obj = service.read_candidate(task,checkpoint)
        if obj is None:
            raise source_conflict()
        with self.repository.connection(write=True) as db:
            task = self.repository.require_lease(db,lease)
            self.repository.require_owner(db,task)
            current = latest_checkpoint(db,task)
            state = dict(current['state_json'])
            snapshot = validate_snapshot(task)
            if current['id'] != checkpoint['id'] or current['next_node'] != 'publish':
                raise source_conflict()
            require_approval(db,task,state)
            # Verify the exact accepted object inside the publication transaction.
            service.read_candidate(task,current)
            if obj.schema_version in (2,3):
                service.verify_publication(task,current)
            root_source = snapshot.get('root_source',snapshot['source'])
            # All v1/v2 publishers serialize allocation under the unchanged raw root.
            root = db.execute('SELECT id FROM dataset_versions WHERE id=%s FOR UPDATE',(root_source['dataset_id'],)).fetchone()
            if not root:
                raise source_conflict()
            if obj.schema_version in (2,3):
                if obj.sheet.row_count == 0:
                    from app.core.exceptions import StorageError
                    raise StorageError('preparation_invalid','不能发布保留记录为零的质量版本。',422)
                base = db.execute('''SELECT p.*,t.project_id FROM prepared_dataset_versions p JOIN tasks t ON t.id=p.task_id WHERE p.id=%s''',
                    (snapshot['source']['dataset_id'],)).fetchone()
                if (not base or base['created_by']!=task['user_id'] or base['project_id']!=task['project_id']
                        or base['file_id']!=root_source['file_id'] or base['parent_dataset_id']!=root_source['dataset_id']):
                    raise source_conflict()
            existing = db.execute('SELECT * FROM prepared_dataset_versions WHERE task_id=%s',(task['id'],)).fetchone()
            if existing:
                raise source_conflict()  # Publication and done are one transaction.
            version = db.execute('SELECT COALESCE(max(version),0)+1 AS n FROM prepared_dataset_versions WHERE parent_dataset_id=%s',
                (root_source['dataset_id'],)).fetchone()['n']
            candidate = state['candidate']
            now = max(self.repository.now(db),task['updated_at'])
            db.execute('''INSERT INTO prepared_dataset_versions
                (id,file_id,parent_dataset_id,task_id,decision_id,version,created_by,created_at,object_key,sha256,size_bytes,recipe_json,summary_json)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (candidate['id'],root_source['file_id'],root_source['dataset_id'],task['id'],
                 state['decision_id'],version,task['user_id'],now,candidate['object_key'],candidate['sha256'],candidate['size_bytes'],
                 Jsonb(obj.recipe.model_dump(mode='json')),Jsonb(obj.summary.model_dump(mode='json'))))
            if obj.schema_version == 2:
                manifest = obj.manifest
                db.execute('''INSERT INTO prepared_dataset_derivations
                    (prepared_dataset_id,base_prepared_dataset_id,object_schema_version,transform_version,workflow_version,rules_version,
                     manifest_object_key,manifest_sha256,manifest_size_bytes,manifest_entry_count)
                    VALUES (%s,%s,2,'excel_prepare_v2','dataset_preparation_v2','quality_rules_v1',%s,%s,%s,%s)''',
                    (candidate['id'],snapshot['source']['dataset_id'],manifest.object_key,manifest.sha256,manifest.size_bytes,manifest.entry_count))
            if obj.schema_version == 3:
                manifest=obj.manifest
                db.execute('''INSERT INTO prepared_dataset_derivations_v3
                    (prepared_dataset_id,base_prepared_dataset_id,operation,object_schema_version,transform_version,workflow_version,rules_version,
                     manifest_object_key,manifest_sha256,manifest_size_bytes,manifest_entry_count)
                    VALUES (%s,%s,%s,3,'excel_prepare_v3','dataset_preparation_v3',%s,%s,%s,%s,%s)''',
                    (candidate['id'],snapshot['source']['dataset_id'],obj.operation,
                     'population_filter_rules_v1' if obj.operation=='population_filter' else 'quality_rules_v1',
                     manifest.object_key,manifest.sha256,manifest.size_bytes,manifest.entry_count))
            state['result_id'] = candidate['id']
            task.update(phase='verify',updated_at=now)
            published = append_checkpoint(db,task,'publish','done',state,current)
            append_checkpoint(db,task,'done','done',state,published)
            db.execute('UPDATE projects SET updated_at=GREATEST(updated_at,%s) WHERE id=%s',
                (now.astimezone(timezone.utc).isoformat(),task['project_id']))
            self.repository.require_lease(db,lease)
            self.repository._finish(db,task,'succeeded',None)
            return TaskStore.public_task(task)
