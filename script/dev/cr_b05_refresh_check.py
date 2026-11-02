"""Apply the unpublished 0062 comparison CHECK addition to the verified B05 clone."""
import hashlib
import importlib.util
import json
from datetime import datetime,timezone
from pathlib import Path
import cr_b05_runner as control


def run():
    state=control.read_state()
    if state.get('clone_status')!='verified' or state.get('migration_head')!='0062_bio_tabular_assays':
        raise ValueError('Verified B05 clone at 0062 required')
    if control.port_open(state):raise ValueError('Apply the unpublished CHECK before starting B05 services')
    control.configure(state)
    path=control.ROOT/'backend/alembic/versions/0062_bio_tabular_assays.py'
    spec=importlib.util.spec_from_file_location('b05_migration',path)
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    changes=[item for item in migration.CHANGES if item[:3]==('tasks','b04_tasks_snapshot_check','b04_tasks_snapshot_check')]
    if len(changes)!=1:raise ValueError('Expected one exact comparison CHECK addition')
    _,name,_,old_sql,new_sql=changes[0]
    expected=old_sql.replace("workflow_version=task_type||'_v1'", "(workflow_version=task_type||'_v1' OR (task_type='bio_comparison' AND workflow_version='bio_comparison_v2'))")
    if new_sql!=expected:raise ValueError('Unexpected migration expansion; inspect before applying')
    from app.db.database import get_migration_database_config,get_engine
    engine=get_engine(get_migration_database_config())
    quote=engine.dialect.identifier_preparer.quote_identifier
    relation=quote(state['schema'])+'.'+quote('tasks')
    receipt=control.RUNTIME/'comparison-check-upgrade.json'
    def definition(db,schema):
        return db.exec_driver_sql('SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname=%s AND c.conname=%s',(schema,name)).scalar_one()
    def tasks_digest(db,schema):
        values=db.exec_driver_sql('SELECT row_to_json(t)::text FROM '+quote(schema)+'.tasks t ORDER BY id').scalars().all()
        return hashlib.sha256('\n'.join(values).encode()).hexdigest()
    with engine.begin() as db:
        if db.exec_driver_sql('SELECT current_database()').scalar_one()!='paperassist_system_test':raise ValueError('Test database required')
        head=db.exec_driver_sql('SELECT version_num FROM '+quote(state['schema'])+'.alembic_version').scalar_one()
        if head!=migration.revision:raise ValueError('B05 schema revision changed')
        source_def=definition(db,state['source_schema']);target_def=definition(db,state['schema'])
        if receipt.exists():
            saved=json.loads(receipt.read_text(encoding='utf-8'))
            if saved['schema']==state['schema'] and saved['after_definition']==target_def and saved['source_definition']==source_def:return saved
            raise ValueError('Existing receipt differs; preserved for inspection')
        if source_def!=target_def:raise ValueError('Target CHECK has diverged from its accepted B04 source')
        before={schema:tasks_digest(db,schema) for schema in (state['schema'],state['source_schema'])}
        db.exec_driver_sql('ALTER TABLE '+relation+' DROP CONSTRAINT '+quote(name))
        db.exec_driver_sql('ALTER TABLE '+relation+' ADD CONSTRAINT '+quote(name)+' CHECK ('+new_sql+')')
        after=definition(db,state['schema'])
        if before!={schema:tasks_digest(db,schema) for schema in before} or definition(db,state['source_schema'])!=source_def:
            raise ValueError('Task rows or source CHECK changed')
    result=dict(schema=state['schema'],source_schema=state['source_schema'],constraint=name,before_definition=target_def,
        after_definition=after,source_definition=source_def,task_rows_preserved=True,task_row_digests=before,
        migration_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),applied_at=datetime.now(timezone.utc).isoformat())
    control.worker_stack.private_write(receipt,json.dumps(result,ensure_ascii=False,indent=2))
    return result


if __name__=='__main__':
    result=run()
    print(json.dumps({k:result[k] for k in ('schema','constraint','task_rows_preserved')}))
