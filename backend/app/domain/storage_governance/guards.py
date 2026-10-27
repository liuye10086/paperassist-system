"""Writer-only deletion barriers. Ordinary readers never call these guards."""
from app.core.exceptions import StorageError


def pending(code='storage_deletion_pending'):
    return StorageError(code,'该资料范围已进入受控处置，不能新增任务、引用或产物。',409)


def require_scope_open(db,project_id,*,file_ids=(),task=None,object_key=None,validated_file_ids=None):
    operations=list(db.execute("SELECT id,file_id,scope_kind,state FROM storage_deletion_operations WHERE project_id=%s AND state<>'preview'",(project_id,)))
    if any(o['scope_kind']=='project' or o['state'] in ('running','partial_failed') for o in operations):
        raise pending()
    blocked={o['file_id'] for o in operations if o['scope_kind']=='file' and db.execute(
        "SELECT 1 FROM storage_deletion_items WHERE operation_id=%s AND state='deleted'",(o['id'],)).fetchone()}
    if blocked:
        sources=set(file_ids)
        resolved=validated_file_ids is not None
        if resolved:sources.update(validated_file_ids)
        if task is not None:
            from app.domain.file_lifecycle.references import file_ids as snapshot_files
            sources.update(snapshot_files(task['input_snapshot']))
            if not sources and not resolved:
                from app.domain.file_lifecycle.manuscript_task_sources import TYPES,task_material
                if task['task_type'] in TYPES and task['task_type']!='literature_search':
                    try:
                        material=task_material(db,task,task['user_id'],project_id)
                        sources.update(snapshot_files(material))
                        # Unsupported PDF source families deliberately return
                        # the same unexpanded snapshot; it is not a resolution.
                        resolved=bool(sources) or material is not task['input_snapshot']
                    except (StorageError,KeyError,TypeError,ValueError):
                        raise pending('storage_deletion_scope_unknown') from None
            if not sources and not resolved and task['task_type'] not in ('literature_search','literature_assistance'):
                raise pending('storage_deletion_scope_unknown')
        if blocked & sources:raise pending()
    if object_key is not None and db.execute('''SELECT 1 FROM storage_deletion_items i
        JOIN storage_objects s ON s.id=i.object_id WHERE s.object_key=%s AND s.namespace='local:assets-v1'
        AND i.state<>'retained' ''',(object_key,)).fetchone():raise pending()


def require_task_open(db,task,*,validated_file_ids=None):
    require_scope_open(db,task['project_id'],task=task,validated_file_ids=validated_file_ids)


def disposed_identity(db,key,size,digest):
    return bool(db.execute('''SELECT 1 FROM storage_objects s JOIN storage_deletion_items i ON i.object_id=s.id
        WHERE s.namespace='local:assets-v1' AND s.object_key=%s AND s.size_bytes=%s AND s.sha256=%s
        AND s.state='deleted' AND i.state='deleted' AND i.disposed_at IS NOT NULL''',(key,size,digest)).fetchone())
