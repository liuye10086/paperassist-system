"""Bounded read-only checks of frozen sources, manifest bytes and storage scope."""
import json
import sys
from app.adapters.bio_objects import BioObjects
from app.adapters.file_objects import LocalFileObjects
from app.core.config import get_data_dir
from app.domain.bioinformatics.contracts import validate_snapshot, input_version


def scoped_object(db,identifier,project,owner):
    row=db.execute('''SELECT o.* FROM storage_objects o JOIN storage_references r ON r.object_id=o.id
        WHERE o.id=%s AND r.project_id=%s AND r.owner_id=%s AND r.kind='bio_dataset' AND o.state='present' ''',(identifier,project,owner)).fetchone()
    if not row:
        raise ValueError('Object not scoped')
    return dict(row)


def audit_bio_datasets(db,limit=200,directory=None):
    if type(limit) is not int or not 1<=limit<=1000:
        raise ValueError('Invalid audit limit')
    directory=directory if directory is not None else get_data_dir()
    objects=BioObjects(directory); originals=LocalFileObjects(directory); checks=[]
    imports=db.execute('SELECT * FROM bio_imports ORDER BY id LIMIT %s',(limit,)).fetchall();invalid=0
    for row in imports:
        try:
            task=db.execute('SELECT * FROM tasks WHERE id=%s',(row['task_id'],)).fetchone()
            if not task:
                raise ValueError('Task missing')
            snapshot=validate_snapshot(task)
            project=db.execute('SELECT owner_id FROM projects WHERE id=%s',(row['project_id'],)).fetchone()
            if (not project or project['owner_id']!=task['user_id'] or row['project_id']!=task['project_id']
                    or row['id']!=snapshot['import_id'] or row['dataset_id']!=snapshot['dataset_id']
                    or row['input_sha256']!=task['input_digest'] or row['settings_json']!=snapshot['settings']
                    or row['parser_version']!=snapshot['parser_version'] or row['expected_dataset_revision']!=snapshot['expected_dataset_revision']):
                raise ValueError('Frozen import mismatch')
            sources=db.execute('SELECT * FROM bio_import_files WHERE import_id=%s',(row['id'],)).fetchall()
            frozen={f['id']:f for f in snapshot['files']}
            if set(frozen)!={source['file_id'] for source in sources}:
                raise ValueError('Source membership differs')
            for source in sources:
                current=db.execute('SELECT * FROM files WHERE id=%s AND project_id=%s',(source['file_id'],row['project_id'])).fetchone()
                expected=frozen[source['file_id']]
                if (not current or current['sha256']!=source['source_sha256'] or current['size_bytes']!=source['source_size_bytes']
                        or any(current[k]!=expected[k] for k in ('id','filename','sha256','size_bytes','object_key','storage_backend'))
                        or source['declared_role']!=expected['role'] or current['parse_status']!='stored'):
                    raise ValueError('Source identity differs')
                originals.original(dict(current))
            checkpoint=db.execute('SELECT * FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(task['id'],)).fetchone()
            if not checkpoint or checkpoint['state_json'].get('input_version')!=input_version(task):
                raise ValueError('Checkpoint missing')
            candidate=checkpoint['state_json'].get('candidate')
            if bool(candidate)!=bool(row['candidate_object_id']):
                raise ValueError('Candidate pointer differs')
            if candidate:
                obj=scoped_object(db,row['candidate_object_id'],row['project_id'],task['user_id'])
                if any(obj[k]!=candidate[k] for k in ('object_key','sha256','size_bytes')):
                    raise ValueError('Candidate object differs')
                value=objects.read_json(obj)
                if value['import_id']!=row['id'] or value['input_sha256']!=row['input_sha256']:
                    raise ValueError('Candidate source differs')
                for member in value['members']:
                    objects.read(member)
        except Exception:
            invalid+=1
    total=db.execute('SELECT count(*) AS n FROM bio_imports').fetchone()['n']
    checks.append(dict(table='bio_imports',column='frozen_inputs_task_candidate',rows=len(imports),total=total,truncated=total>len(imports),invalid=invalid))
    versions=db.execute('SELECT * FROM bio_dataset_versions ORDER BY id LIMIT %s',(limit,)).fetchall();invalid=0
    for version in versions:
        try:
            project=db.execute('SELECT owner_id FROM projects WHERE id=%s',(version['project_id'],)).fetchone()
            task=db.execute('SELECT * FROM tasks WHERE id=%s',(version['task_id'],)).fetchone()
            root=db.execute('SELECT * FROM bio_datasets WHERE id=%s AND project_id=%s',(version['dataset_id'],version['project_id'])).fetchone()
            if (not root or not task or not project or project['owner_id']!=version['created_by'] or task['user_id']!=project['owner_id']
                    or task['status']!='succeeded' or task['result_bio_dataset_version_id']!=version['id']):
                raise ValueError('Version task/root mismatch')
            snapshot=validate_snapshot(task)
            if version['import_id']!=snapshot['import_id'] or version['dataset_id']!=snapshot['dataset_id']:
                raise ValueError('Version source mismatch')
            record=scoped_object(db,version['manifest_object_id'],version['project_id'],project['owner_id'])
            if record['sha256']!=version['manifest_sha256']:
                raise ValueError('Manifest hash differs')
            manifest=objects.read_json(record)
            if manifest['parser_version']!=version['parser_version']:
                raise ValueError('Manifest parser differs')
            frozen={m['id']:m for m in manifest['members']}
            members=db.execute('SELECT * FROM bio_dataset_members WHERE dataset_version_id=%s',(version['id'],)).fetchall()
            if set(frozen)!={m['id'] for m in members}:
                raise ValueError('Member membership differs')
            for member in members:
                expected=frozen[member['id']]
                if any(member[k]!=expected[k] for k in ('role','format','compression','verification_state','source_file_id','source_member_name','sha256','size_bytes')):
                    raise ValueError('Member identity differs')
                if not db.execute('SELECT file_id FROM bio_import_files WHERE import_id=%s AND file_id=%s',(version['import_id'],member['source_file_id'])).fetchone():
                    raise ValueError('Member is not an import source')
                record=scoped_object(db,member['object_id'],version['project_id'],project['owner_id'])
                if record['sha256']!=member['sha256'] or record['size_bytes']!=member['size_bytes']:
                    raise ValueError('Member object differs')
                objects.read(record)
            parent=db.execute('SELECT id FROM bio_dataset_versions WHERE dataset_id=%s AND version=%s',(version['dataset_id'],version['version']-1)).fetchone()
            if version['parent_id']!=(parent['id'] if parent else None):
                raise ValueError('Version parent differs')
        except Exception:
            invalid+=1
    total=db.execute('SELECT count(*) AS n FROM bio_dataset_versions').fetchone()['n']
    checks.append(dict(table='bio_dataset_versions',column='manifest_members_task',rows=len(versions),total=total,truncated=total>len(versions),invalid=invalid))
    roots=db.execute('SELECT * FROM bio_datasets ORDER BY id LIMIT %s',(limit,)).fetchall();invalid=0
    for row in roots:
        latest=db.execute('SELECT id FROM bio_dataset_versions WHERE dataset_id=%s ORDER BY version DESC LIMIT 1',(row['id'],)).fetchone()
        invalid+=row['current_version_id']!=(latest['id'] if latest else None)
    total=db.execute('SELECT count(*) AS n FROM bio_datasets').fetchone()['n']
    checks.append(dict(table='bio_datasets',column='current_version_pointer',rows=len(roots),total=total,truncated=total>len(roots),invalid=invalid))
    return checks


def main():
    from app.db.database import database_connection
    try:
        with database_connection() as db:
            checks=audit_bio_datasets(db)
        result={'ok':not any(x['invalid'] for x in checks),'data_checks':checks,'read_only':True}
        print(json.dumps(result,ensure_ascii=False))
        return 0 if result['ok'] else 1
    except Exception:
        print('生信数据审计失败，请检查数据库、受控原件和对象权限。',file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
