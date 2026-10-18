"""Background reconciliation for persisted local-only collection export intents."""
from pathlib import Path
from app.adapters.storage import ProjectStore, _storage_connection
from app.adapters.file_objects import LocalFileObjects
from app.core.config import get_data_dir
from app.db.database import get_database_config
from app.core.exceptions import StorageError


def scoped_store(owner_id,config=None,directory=None):
    # Construct the existing asset reader without a second default-config connection.
    store=ProjectStore.__new__(ProjectStore)
    store.owner_id=owner_id; store.db_config=config or get_database_config()
    store.directory=Path(directory if directory is not None else get_data_dir())
    store.objects=LocalFileObjects(store.directory)
    store.files_dir=store.directory/'files'; store.figures_dir=store.directory/'figures'
    return store


def advance_pending(*,config=None,directory=None,limit=20):
    from app.adapters.collection_store import CollectionStore
    config=config or get_database_config()
    if type(limit) is not int or not 1<=limit<=100: raise ValueError('Invalid scan bound')
    with _storage_connection(config=config) as db:
        rows=db.execute('''SELECT q.id,c.project_id,c.created_by FROM report_build_requests q
            JOIN report_collection_versions v ON v.id=q.version_id JOIN report_collections c ON c.id=v.collection_id
            WHERE q.status='waiting' ORDER BY q.updated_at,q.id LIMIT %s''',(limit,)).fetchall()
    advanced=0
    for row in rows:
        repository=CollectionStore(scoped_store(row['created_by'],config,directory))
        try:
            repository.advance(row['project_id'],row['id']); advanced+=1
        except StorageError as exc:
            if exc.code in ('storage_unavailable','database_configuration'): continue
            with repository.store.connection(write=True) as db:
                db.execute("UPDATE report_build_requests SET status='blocked',error_code=%s,updated_at=clock_timestamp() WHERE id=%s AND status='waiting'",(exc.code,row['id']))
    return advanced


def collection_task_source(task_store,db,task,*,directory=None):
    from app.adapters.collection_store import CollectionStore
    repository=CollectionStore(scoped_store(task['user_id'],task_store.config,directory))
    snapshot=repository.verify_task_snapshot(db,task)
    source=snapshot['sources'][0]
    file=db.execute('SELECT filename FROM files WHERE id=%s AND project_id=%s',(source['file_id'],task['project_id'])).fetchone()
    if not file: raise StorageError('collection_source_conflict','集合来源文件不存在。',409)
    return {'file_id':source['file_id'],'filename':file['filename'],'analysis_run_id':None,'is_current':True,'dataset_source':source}


def collection_task_artifact(task_store,db,task,*,directory=None):
    from app.adapters.collection_store import CollectionStore
    repository=CollectionStore(scoped_store(task['user_id'],task_store.config,directory))
    row=db.execute('''SELECT r.report_json,v.collection_id FROM collection_reports r JOIN report_build_requests q ON q.id=r.build_request_id
        JOIN report_collection_versions v ON v.id=r.version_id WHERE q.task_id=%s''',(task['id'],)).fetchone()
    if not row: return None
    metadata,_=repository.download(task['project_id'],row['collection_id'],row['report_json']['id'])
    return {'filename':metadata['filename'],'download_url':f"/api/v1/projects/{task['project_id']}/report-collections/{row['collection_id']}/reports/{metadata['id']}/download"}


def input_version(task):
    from app.domain.tasks.contracts import CollectionInputVersion
    snapshot=task['input_snapshot']
    return CollectionInputVersion(kind='report_collection',collection_version_id=snapshot['collection_version_id'],
        export_revision=snapshot['export_revision'],output_language=snapshot['language'],workflow_version='collection_word_report_v1').model_dump()
