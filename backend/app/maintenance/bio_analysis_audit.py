"""Read-only integrity audit of processed manifests, tasks and annotations."""
import json
import sys
from app.adapters.bio_analysis_store import BioAnalysisStore
from app.adapters.bio_annotation_store import BioAnnotationStore
from app.adapters.bio_figure_store import BioFigureStore
from app.adapters.task_store import DatasetTaskAssets
from app.core.config import get_data_dir
from app.maintenance.bio_task_source_audit import audit_bio_task_sources


def audit_bio_analysis(db,limit=200,directory=None):
    if type(limit) is not int or not 1<=limit<=1000:raise ValueError('Invalid audit limit')
    directory=directory or get_data_dir();checks=[]
    checks.extend(audit_bio_task_sources(db,limit))
    for table in ('bio_processed_dataset_versions','bio_observation_map_versions','bio_annotation_versions','bio_figure_versions'):
        rows=db.execute(f'SELECT * FROM {table} ORDER BY id LIMIT %s',(limit,)).fetchall();invalid=0
        for row in rows:
            try:
                assets=DatasetTaskAssets(row['created_by'],db.config,directory)
                if table=='bio_processed_dataset_versions':
                    store=BioAnalysisStore(assets);_,_,members=store.processed_record(db,row['project_id'],row['id'])
                    for member in members:store.objects.read(member)
                    task=db.execute('SELECT * FROM tasks WHERE id=%s',(row['task_id'],)).fetchone()
                    run=db.execute('SELECT * FROM bio_analysis_runs WHERE id=%s',(row['run_id'],)).fetchone()
                    if not task or task['status']!='succeeded' or task['result_bio_processed_dataset_version_id']!=row['id'] or not run or run['processed_dataset_version_id']!=row['id']:raise ValueError('Publication pointer mismatch')
                elif table=='bio_observation_map_versions':BioAnalysisStore(assets).mapping(row['project_id'],row['set_id'],row['id'])
                elif table=='bio_annotation_versions':BioAnnotationStore(assets).get(row['project_id'],row['set_id'],row['id'])
                else:
                    view=BioFigureStore(assets).get(row['project_id'],row['id'])
                    if row['manifest_object_id']:
                        for member in view['members']:BioFigureStore(assets).member(row['project_id'],row['id'],member['id'])
            except Exception:invalid+=1
        total=db.execute(f'SELECT count(*) AS n FROM {table}').fetchone()['n']
        checks.append(dict(table=table,column='frozen_scope_objects_publication',rows=len(rows),total=total,truncated=total>len(rows),invalid=invalid))
    evidence=db.execute('''SELECT count(*) AS n FROM bio_annotation_evidence e JOIN bio_annotation_versions v ON v.id=e.annotation_version_id
        LEFT JOIN bio_analysis_artifacts a ON a.id=e.analysis_artifact_id WHERE e.project_id<>v.project_id
        OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(v.labels_json) l WHERE l->>'id'=e.label_id)
        OR (e.kind='marker' AND (a.processed_dataset_version_id IS DISTINCT FROM v.processed_dataset_version_id OR a.role<>'marker_table'))''').fetchone()['n']
    checks.append(dict(table='bio_annotation_evidence',column='normalized_sources',invalid=evidence))
    return checks


def main():
    from app.db.database import database_connection
    try:
        with database_connection() as db:checks=audit_bio_analysis(db)
        ok=not any(c['invalid'] for c in checks);print(json.dumps(dict(ok=ok,read_only=True,data_checks=checks),ensure_ascii=False));return 0 if ok else 1
    except Exception:
        print('生信处理版本审计失败，请检查固定来源和受控对象。',file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
