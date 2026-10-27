"""Atomic all-sheet publication fenced by the active task lease."""
from datetime import timezone

import json
from uuid import UUID, uuid5
from psycopg.types.json import Jsonb
from app.adapters.dataset_objects import DatasetObjects, DatasetObject
from app.adapters.task_store import TaskStore, source_conflict
from app.core.exceptions import StorageError
from app.domain.datasets.contracts import ExcelStructure
from app.domain.datasets.snapshots import require_structure_source
from app.domain.storage_governance.service import publication, reconcile_intents, reserve, invalid

NAMESPACE = UUID('70e3e76d-c7d4-45bd-8eba-02b1b693171a')


class DatasetStore:
    def __init__(self, repository):
        self.repository = repository
        self.objects = DatasetObjects(repository.assets.directory)

    def load(self, lease):
        repo = self.repository
        with repo.connection() as db:
            task = repo.require_lease(db, lease)
            repo.require_owner(db,task)
            snapshot = require_structure_source(db,task)
        return snapshot,repo.assets.original(snapshot['file'])

    def complete(self, lease, snapshot, structure):
        repo = self.repository
        try:
            structure = ExcelStructure.model_validate(structure.model_dump() if isinstance(structure,ExcelStructure) else structure,strict=True)
            settings = snapshot['settings']['excel']
            if (structure.filename != snapshot['file']['filename'] or len(structure.sheets)>settings['max_sheets']
                    or any(sheet.row_count>settings['max_rows'] or sheet.column_count>settings['max_columns'] for sheet in structure.sheets)
                    or sum(sheet.row_count*sheet.column_count for sheet in structure.sheets)>settings['max_cells']):
                raise ValueError('Invalid structure boundary')
            encoded = json.dumps(structure.model_dump(),ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
            candidates = []
            for sheet in structure.sheets:
                obj = DatasetObject(schema_version=1,epoch=structure.epoch,sheet=sheet)
                content = json.dumps(obj.model_dump(),ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
                candidates.append((sheet,str(uuid5(NAMESPACE,lease.task_id+':'+str(sheet.index))),content))
            if max(len(encoded),sum(len(c[2]) for c in candidates))>snapshot['settings']['process']['max_output_bytes']:
                raise ValueError('Oversized full result')
        except (ValueError,TypeError,KeyError) as exc:
            raise StorageError('parse_output_invalid','完整结构结果无效或超过输出额度。',422) from exc
        with repo.connection(write=True) as db:
            task = repo.require_lease(db,lease)
            repo.require_owner(db,task)
            if require_structure_source(db,task)!=snapshot:
                raise source_conflict()
            repo.assets.original(snapshot['file'])
            version = db.execute('SELECT * FROM file_structure_versions WHERE id=%s',(snapshot['structure_id'],)).fetchone()
            if version['manifest_json'] is not None:
                raise source_conflict()
            # Admission covers the complete manifest before any object/intent
            # is written. The caller's writer holds the global admission lock.
            if reconcile_intents(db, repo.assets.directory):
                raise invalid()
            for _, identifier, content in candidates:
                descriptor = self.objects.describe(identifier, content)
                reserve(db, repo.assets.directory, task['project_id'], 'dataset:'+identifier,
                        self.objects.path(descriptor['object_key']), descriptor['size_bytes'],
                        sha256=descriptor['sha256'], kind='dataset', task_id=task['id'])
            now=repo.now(db)
            dataset_ids=[]
            for sheet,identifier,content in candidates:
                repo.require_lease(db,lease)
                descriptor = self.objects.describe(identifier, content)
                with publication(db, repo.assets.directory, task['project_id'], 'dataset:'+identifier,
                                 self.objects.path(descriptor['object_key']), content,
                                 kind='dataset', task_id=task['id']):
                    saved = self.objects.save(identifier,content)
                parent = db.execute('''SELECT id FROM dataset_versions WHERE file_id=%s AND sheet_index=%s AND version<%s
                    ORDER BY version DESC LIMIT 1''',(version['file_id'],sheet.index,version['version'])).fetchone()
                summary={**sheet.model_dump(exclude={'index','name','cells'}),'epoch':structure.epoch}
                db.execute('''INSERT INTO dataset_versions(id,file_id,structure_id,sheet_index,version,parent_id,created_at,
                    sheet_name,object_key,sha256,size_bytes,schema_version,summary_json) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s)''',
                    (identifier,version['file_id'],version['id'],sheet.index,version['version'],parent['id'] if parent else None,
                     now,sheet.name,saved['object_key'],saved['sha256'],saved['size_bytes'],Jsonb(summary)))
                dataset_ids.append(identifier)
            repo.require_lease(db,lease)
            manifest=dict(schema_version=1,epoch=structure.epoch,filename=structure.filename,dataset_ids=dataset_ids)
            changed=db.execute('UPDATE file_structure_versions SET completed_at=%s,manifest_json=%s WHERE id=%s AND manifest_json IS NULL',
                               (now,Jsonb(manifest),version['id']))
            if changed.rowcount!=1:
                raise source_conflict()
            repo._finish(db,task,'succeeded',None)
            db.execute('UPDATE projects SET updated_at=GREATEST(updated_at,%s) WHERE id=%s',(now.astimezone(timezone.utc).isoformat(),task['project_id']))
            return TaskStore.public_task(task)

    def fail(self,lease,code):
        return self.repository.fail(lease,code)
