"""Typed historical asset references. Never infer ownership by walking filenames.

All queries use existing SQL source relations. JSON is interpreted only at the
specific descriptor fields written by those producers; arbitrary embedded keys
are not recursively treated as assets. Only governance rows may be updated.
"""
import json
import re
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from app.core.exceptions import StorageError
from . import service as s


def mapping(value):
    if isinstance(value,str):value=json.loads(value)
    if not isinstance(value,dict):raise s.invalid()
    return value


def descriptor(value,*,key=None):
    value=mapping(value)
    result={name:value[name] for name in ('size_bytes','sha256')}
    result['object_key']=value['object_key'] if key is None else key
    if (type(result['size_bytes']) is not int or not 0<=result['size_bytes']<=2**63-1
            or not isinstance(result['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',result['sha256'])
            or not isinstance(result['object_key'],str)):
        raise s.invalid()
    return result


def _fixed(prefix,identifier,suffix):
    # The path comes from the original producer's typed ID contract, not a scan.
    # legacy_import._asset_reference has always accepted safe non-UUID IDs.
    if not isinstance(identifier,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',identifier):raise s.invalid()
    return prefix+'/'+identifier+suffix


def _metadata(row,column,prefix,suffix):
    value=mapping(row[column])
    if value.get('id',row['id'])!=row['id']:raise s.invalid()
    return descriptor(value,key=_fixed(prefix,row['id'],suffix))


def _rows(db,table,joins,where=''):
    return db.execute('SELECT to_jsonb(a) AS record,p.id AS project_id,p.owner_id FROM '+table+
        ' a '+joins+' JOIN projects p ON p.id=f.project_id '+where)


def references(db,root,failed,coverage):
    """Yield (scope, kind, exact descriptor); report per-family malformed evidence."""
    def emit(rows,kind,extract):
        coverage[kind]=dict(rows=0,references=0,errors=0)
        for scoped in rows:
            coverage[kind]['rows']+=1
            try:
                row=scoped['record']
                # Where tables carry their own user/project, independently check
                # it against the joined source. Never give another user's scope.
                if row.get('project_id',scoped['project_id'])!=scoped['project_id']:raise s.invalid()
                if row.get('user_id',scoped['owner_id'])!=scoped['owner_id']:raise s.invalid()
                for obj in extract(row):
                    obj=descriptor(obj)
                    # Validate lexical keys even when a missing path cannot be read.
                    key=obj['object_key']
                    if key.startswith('/') or any(p in ('','.','..') or ':' in p or '\\' in p for p in key.split('/')):raise s.invalid()
                    coverage[kind]['references']+=1
                    yield dict(project_id=scoped['project_id'],owner_id=scoped['owner_id'],kind=kind,**obj)
            except (StorageError,KeyError,TypeError,ValueError,OSError):
                coverage[kind]['errors']+=1;failed(kind)

    originals=_rows(db,'files','JOIN files f ON f.id=a.id')
    yield from emit(originals,'original',lambda r: [] if r['storage_backend'] not in (None,'local') else
        [descriptor(r,key=r['object_key'] or _fixed('files',r['id'],'.'+r['file_type']))])
    for table,kind in (('dataset_versions','dataset'),('prepared_dataset_versions','prepared_dataset'),('ocr_review_versions','ocr_review')):
        yield from emit(_rows(db,table,'JOIN files f ON f.id=a.file_id'),kind,lambda r:[r])

    def documents(row):
        value=mapping(row['result_json'])
        # Excel parse snapshots are SQL only and have no filesystem descriptor.
        if 'object' in value:
            yield value['object']
            for image in value['images']:yield image
    yield from emit(_rows(db,'file_parse_results','JOIN files f ON f.id=a.file_id',
        'WHERE a.result_json IS NOT NULL'),'document',documents)

    for table,kind in (('prepared_dataset_derivations','quality_manifest'),('prepared_dataset_derivations_v3','derivation_manifest')):
        yield from emit(_rows(db,table,'JOIN prepared_dataset_versions v ON v.id=a.prepared_dataset_id JOIN files f ON f.id=v.file_id'),
            kind,lambda r:[dict(object_key=r['manifest_object_key'],sha256=r['manifest_sha256'],size_bytes=r['manifest_size_bytes'])])

    def checkpoint(row):
        value=mapping(row['state_json']).get('candidate')
        if value is None:return
        obj=descriptor(value);yield obj
        if row['task_type']=='prepare_dataset' and row['workflow_version'] in ('dataset_preparation_v2','dataset_preparation_v3'):
            # Old checkpoints retain only the prepared descriptor. Its verified
            # typed immutable object is the evidence for its child manifest.
            from app.adapters.prepared_dataset_objects import PreparedDatasetObjects
            s._key(root,Path(root)/obj['object_key'])
            _,prepared=PreparedDatasetObjects(root).read(value)
            if prepared.schema_version not in (2,3):raise s.invalid()
            yield prepared.manifest.model_dump()
    rows=db.execute('''SELECT to_jsonb(a)||jsonb_build_object('task_type',t.task_type,'workflow_version',t.workflow_version) AS record,
        p.id AS project_id,p.owner_id FROM task_checkpoints a JOIN tasks t ON t.id=a.task_id
        JOIN projects p ON p.id=t.project_id AND p.owner_id=t.user_id
        WHERE t.task_type IN ('prepare_dataset','review_ocr')''')
    yield from emit(rows,'checkpoint_candidate',checkpoint)

    for table,column,suffix,kind in (('figures','figure_json','.png','figure'),('reports','report_json','.docx','report')):
        yield from emit(_rows(db,table,'JOIN analysis_runs v ON v.id=a.analysis_run_id JOIN files f ON f.id=v.file_id'),kind,
            lambda r,c=column,p=table,x=suffix:[_metadata(r,c,p,x)])
    collection=db.execute('''SELECT to_jsonb(a) AS record,p.id AS project_id,p.owner_id FROM collection_reports a
        JOIN report_collection_versions v ON v.id=a.version_id JOIN report_collections c ON c.id=v.collection_id
        JOIN projects p ON p.id=c.project_id AND p.owner_id=c.created_by''')
    yield from emit(collection,'collection_report',lambda r:[_metadata(r,'report_json','collection_reports','.docx')])
    manuscript=db.execute('''SELECT to_jsonb(a) AS record,p.id AS project_id,p.owner_id FROM manuscript_exports a
        JOIN manuscript_versions v ON v.id=a.version_id JOIN projects p ON p.id=v.project_id AND p.owner_id=v.user_id
        WHERE a.metadata_json IS NOT NULL''')
    yield from emit(manuscript,'manuscript_export',lambda r:[_metadata(r,'metadata_json','manuscript_exports','.docx')])
    language=db.execute('''SELECT to_jsonb(a) AS record,p.id AS project_id,p.owner_id FROM manuscript_figure_language_versions a
        JOIN projects p ON p.id=a.project_id AND p.owner_id=a.user_id''')
    yield from emit(language,'figure_language',lambda r:[_metadata(r,'snapshot_json','manuscript_figure_language_versions','.png')])

    def school_language(row):
        from app.domain.literature.service import digest
        from app.domain.manuscript_writing.language_service import artifact_sha
        from app.domain.manuscript_writing.school_render_cache import read,descriptors
        candidate=mapping(row['candidate_json']);proof=candidate['writing_provenance']['school_final_render']
        if digest(candidate)!=row['candidate_sha256'] or digest(row['inventory_json'])!=row['inventory_sha256'] or artifact_sha(row)!=row['artifact_sha256']:raise s.invalid()
        read(root,row['user_id'],row['project_id'],proof)
        return descriptors(proof,row['user_id'],row['project_id'])
    reviewed_school=db.execute('''SELECT to_jsonb(a) AS record,p.id AS project_id,p.owner_id FROM manuscript_writing_language_reviews a
        JOIN projects p ON p.id=a.project_id AND p.owner_id=a.user_id
        WHERE a.candidate_json->'writing_provenance' ? 'school_final_render' ''')
    yield from emit(reviewed_school,'school_language_artifact',school_language)

    def export(row,column,prefix):
        value=mapping(row[column]);name=value['object_name']
        if not isinstance(name,str) or '/' in name or '\\' in name:raise s.invalid()
        return [descriptor(value,key=prefix+'/'+name)]
    for table,column in (('pdf_exports','metadata_json'),('layout_exports','metadata_json'),('review_document_exports','artifact_json')):
        rows=db.execute('SELECT to_jsonb(a) AS record,p.id AS project_id,p.owner_id FROM '+table+
            ' a JOIN tasks t ON t.id=a.task_id JOIN projects p ON p.id=t.project_id AND p.owner_id=t.user_id WHERE a.'+column+' IS NOT NULL')
        yield from emit(rows,table,lambda r,c=column,p=table:export(r,c,p))

    literature=db.execute('''SELECT to_jsonb(a) AS record,p.id AS project_id,p.owner_id FROM literature_fetch_receipts a
        JOIN projects p ON p.id=a.project_id AND p.owner_id=a.user_id WHERE a.status='succeeded' ''')
    yield from emit(literature,'literature',lambda r:[r])
    pmc=db.execute('''SELECT to_jsonb(a) AS record,p.id AS project_id,p.owner_id FROM literature_pmc_receipts a
        JOIN projects p ON p.id=a.project_id AND p.owner_id=a.user_id''')
    yield from emit(pmc,'literature_pmc',lambda r:[v['object'] for v in mapping(r['snapshot_json'])['responses'] if v['object'] is not None])

    def figure_candidate(row):
        value=mapping(row['figure_candidate'])
        if row['task_type']=='boxplot':
            # Reuse the original typed path validator, including task-derived UUID.
            from app.adapters.task_execution_store import TaskExecutionStore
            from types import SimpleNamespace
            adapter=SimpleNamespace(assets=SimpleNamespace(directory=Path(root),figures_dir=Path(root)/'figures'))
            paths=TaskExecutionStore._figure_candidate_paths(adapter,row,value);figure=value['figure']
        else:
            if value['id']!=str(uuid5(NAMESPACE_URL,'paperassist:figure:'+row['id'])):raise s.invalid()
            figure=value;paths=[Path(root)/_fixed('figures',figure['id'],'.png'),Path(root)/_fixed('task-staging',figure['id'],'.candidate')]
        # Active v2 stages are resolved by their ledger, never promoted here.
        existing=[]
        for path in paths:
            s._key(root,path)
            if path.exists():existing.append(path)
        for path in existing or paths[:1]:yield descriptor(figure,key=path.relative_to(root).as_posix())
    tasks=db.execute('''SELECT to_jsonb(a) AS record,p.id AS project_id,p.owner_id FROM tasks a
        JOIN projects p ON p.id=a.project_id AND p.owner_id=a.user_id
        WHERE a.task_type IN ('boxplot','figure_workbench') AND a.figure_candidate IS NOT NULL''')
    yield from emit(tasks,'figure_candidate',figure_candidate)
