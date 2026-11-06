"""Resolve cloud tasks' local outputs without inventing local FASTQ inputs."""
from app.core.exceptions import StorageError
from app.domain.bioinformatics.contracts import digest


def governed_file_ids(db, task):
    row = db.execute('SELECT * FROM bio_cloud_runs WHERE task_id=%s',(task['id'],)).fetchone()
    if (row is None or row['project_id']!=task['project_id']
            or row['snapshot_json']!=task['input_snapshot']
            or digest(task['input_snapshot'])!=task['input_digest']
            or task['workflow_version']!='bio_cloud_run_v1'):
        raise StorageError('storage_deletion_scope_unknown','无法核对云任务的文件范围。',409)
    return [r['file_id'] for r in db.execute('SELECT file_id FROM bio_cloud_outputs WHERE run_id=%s AND project_id=%s',(row['id'],row['project_id']))]


def output_links(db, file):
    return [dict(r) for r in db.execute('''SELECT o.*,r.task_id FROM bio_cloud_outputs o
        JOIN bio_cloud_runs r ON r.id=o.run_id AND r.project_id=o.project_id
        WHERE o.file_id=%s''',(file['id'],))]


def valid_output(db, task, file, links):
    try:
        return (file['id'] in governed_file_ids(db,task)
                and all(r['sha256']==file['sha256'] and r['size_bytes']==file['size_bytes']
                        and r['project_id']==file['project_id'] for r in links if r['task_id']==task['id']))
    except StorageError:
        return False
