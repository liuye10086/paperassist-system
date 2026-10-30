"""File-bound intake/bio references, retaining multi-file import identities."""
from app.core.exceptions import StorageError
from app.domain.bioinformatics.contracts import validate_snapshot

GROUPS=('research_material_refs','bio_datasets','bio_imports','bio_dataset_versions','bio_dataset_members')


def valid_task(db,task,file):
    try:
        snapshot=validate_snapshot(task)
        row=db.execute('SELECT * FROM bio_imports WHERE id=%s AND project_id=%s AND task_id=%s',
                       (snapshot['import_id'],file['project_id'],task['id'])).fetchone()
        if not row or row['dataset_id']!=snapshot['dataset_id'] or task['project_id']!=file['project_id']:
            return False
        frozen=[dict(r) for r in db.execute('SELECT * FROM bio_import_files WHERE import_id=%s',(row['id'],))]
        by_id={r['file_id']:r for r in frozen}
        if set(by_id)!={f['id'] for f in snapshot['files']}:
            return False
        for source in snapshot['files']:
            linked=by_id[source['id']]
            if linked['project_id']!=file['project_id'] or linked['source_sha256']!=source['sha256'] or linked['source_size_bytes']!=source['size_bytes']:
                return False
            current=db.execute('SELECT sha256,size_bytes FROM files WHERE id=%s AND project_id=%s',(source['id'],file['project_id'])).fetchone()
            if not current or current['sha256']!=source['sha256'] or current['size_bytes']!=source['size_bytes']:
                return False
        return True
    except (StorageError,KeyError,ValueError,TypeError):
        return False


def read_groups(db,file,user_id):
    imports=[dict(row) for row in db.execute('''SELECT i.* FROM bio_imports i JOIN bio_import_files f
        ON f.import_id=i.id WHERE f.file_id=%s''',(file['id'],))]
    import_ids=[r['id'] for r in imports]
    versions=[dict(row) for row in db.execute('SELECT * FROM bio_dataset_versions WHERE import_id=ANY(%s)',(import_ids,))]
    version_ids=[r['id'] for r in versions]
    groups={
        'bio_imports':imports,
        'bio_dataset_versions':versions,
        'bio_datasets':[dict(row) for row in db.execute('SELECT * FROM bio_datasets WHERE id=ANY(%s)',([r['dataset_id'] for r in imports],))],
        'bio_dataset_members':[dict(row) for row in db.execute('SELECT * FROM bio_dataset_members WHERE source_file_id=%s',(file['id'],))],
        'research_material_refs':[dict(row) for row in db.execute('''SELECT * FROM research_material_refs
            WHERE file_id=%s OR bio_dataset_version_id=ANY(%s)''',(file['id'],version_ids))],
    }
    owner=db.execute('SELECT owner_id FROM projects WHERE id=%s',(file['project_id'],)).fetchone()
    valid_owner=bool(owner and owner['owner_id']==user_id)
    tasks={r['id']:dict(r) for r in db.execute('SELECT * FROM tasks WHERE id=ANY(%s)',([r['task_id'] for r in imports],))}
    for name,rows in groups.items():
        for row in rows:
            row['_integrity_valid']=valid_owner and row['project_id']==file['project_id']
            if name=='bio_imports':
                task=tasks.get(row['task_id'])
                row['_integrity_valid'] &= bool(task and task['user_id']==user_id and valid_task(db,task,file))
            if name=='research_material_refs':
                table,column=('research_requirement_versions','requirement_version_id') if row['requirement_version_id'] else ('research_design_versions','design_version_id')
                source=db.execute(f'SELECT project_id,created_by FROM {table} WHERE id=%s',(row[column],)).fetchone()
                row['_integrity_valid'] &= bool(source and source['project_id']==file['project_id'] and source['created_by']==user_id)
    return groups
