"""Clone a stopped B02 acceptance baseline into a newly owned B03 schema.

Source schema is read-only. Failures retain the new schema, receipts and bytes.
This command never removes a schema, container, volume or asset.
"""
import json
import os
from pathlib import Path
import re
import shutil
import sys
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[2]
RUNTIME=ROOT/'script/.runtime/client-requirements-b03'
SOURCE=ROOT/'script/.runtime/client-requirements-b02/state.json'
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'script'),str(ROOT/'script/dev')]
from cr_b03_preservation import asset_inventory,compare_assets,database_snapshot,compare_business


def validate_source(state):
    expected=ROOT/'script/.runtime/client-requirements-b02/acceptance'/state['schema']/'assets'
    if not re.fullmatch(r'pa_test_[a-f0-9]{32}',state['schema']) or state['status']!='accepted_stopped':
        raise ValueError('Only a stopped, accepted B02 test schema may be cloned')
    if Path(state['assets']).absolute()!=expected.absolute():raise ValueError('Unexpected source asset directory')


def write(path,value):
    from worker_stack import private_write
    private_write(path,json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def prepare():
    source=json.loads(SOURCE.read_text(encoding='utf-8-sig'));validate_source(source)
    state_path=RUNTIME/'state.json'
    if state_path.exists():
        existing=json.loads(state_path.read_text(encoding='utf-8-sig'))
        if existing.get('clone_status')=='verified':return existing
        raise ValueError('An incomplete preparation is retained; inspect it before creating another')
    source_inventory=asset_inventory(source['assets'])
    identifier='pa_test_'+uuid4().hex
    directory=RUNTIME/'acceptance'/identifier
    directory.mkdir(parents=True,exist_ok=False)
    from worker_stack import protect_directory
    protect_directory(directory)
    state=dict(schema=identifier,source_schema=source['schema'],workspace=str(ROOT),
        assets=str(directory/'assets'),staging=str(directory/'staging'),bind_host='127.0.0.83',port=18083,
        url='http://127.0.0.83:18083',stack_project='pa-test-'+identifier[8:],status='preparing',
        clone_status='preparing',public_database_modified=False,real_model_calls=0)
    write(state_path,state)
    os.environ.update(PAPERASSIST_ENV='test',PAPERASSIST_DB_SCHEMA=identifier,PAPERASSIST_DATA_DIR=state['assets'])
    from app.db.database import get_migration_database_config,get_engine,migration_connection,alembic_config,migrate_database
    from alembic import command
    config=get_migration_database_config();engine=get_engine(config)
    quote=engine.dialect.identifier_preparer.quote_identifier
    source_schema=quote(source['schema']);target_schema=quote(identifier)
    before=database_snapshot(engine,source['schema'])
    write(RUNTIME/'b02-database-before.json',before)
    with engine.begin() as db:
        if db.exec_driver_sql('SELECT current_database()').scalar_one()!='paperassist_system_test':raise ValueError('Expected test database')
        source_head=db.exec_driver_sql('SELECT version_num FROM '+source_schema+'.alembic_version').scalar_one()
        if source_head!='0059_bio_spatial_analysis':raise ValueError('B02 schema head changed')
        active=db.exec_driver_sql("SELECT count(*) FROM "+source_schema+".tasks WHERE status IN ('queued','running','submitting')").scalar_one()
        if active:raise ValueError('B02 has unfinished tasks; do not copy executable old work')
        db.exec_driver_sql('CREATE SCHEMA '+target_schema)
    with migration_connection(write=True) as db:
        cfg=alembic_config();cfg.attributes.update(connection=db.raw_connection,database_config=config)
        command.upgrade(cfg,'0059_bio_spatial_analysis')
    # Only the exact schema created above is changed. Source relations appear
    # exclusively on the SELECT side of the copy statements.
    with engine.begin() as db:
        db.exec_driver_sql("SELECT set_config('search_path',%s,true)",(identifier,))
        foreign=db.exec_driver_sql("SELECT c.conrelid::regclass::text,c.conname,pg_get_constraintdef(c.oid) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname=%s AND c.contype='f' ORDER BY c.conname",(identifier,)).all()
        for relation,name,definition in foreign:
            db.exec_driver_sql('ALTER TABLE '+relation+' DROP CONSTRAINT '+quote(name))
        for table,old in before.items():
            relation=target_schema+'.'+quote(table)
            db.exec_driver_sql('ALTER TABLE '+relation+' DISABLE TRIGGER USER')
            db.exec_driver_sql('DELETE FROM '+relation)
            columns=','.join(map(quote,old['columns']))
            db.exec_driver_sql('INSERT INTO '+relation+'('+columns+') OVERRIDING SYSTEM VALUE SELECT '+columns+' FROM '+source_schema+'.'+quote(table))
            db.exec_driver_sql('ALTER TABLE '+relation+' ENABLE TRIGGER USER')
        for relation,name,definition in foreign:
            db.exec_driver_sql('ALTER TABLE '+relation+' ADD CONSTRAINT '+quote(name)+' '+definition)
        sequences=db.exec_driver_sql("SELECT table_name,column_name FROM information_schema.columns WHERE table_schema=%s AND (is_identity='YES' OR column_default LIKE 'nextval%%')",(identifier,)).all()
        for table,column in sequences:
            relation=target_schema+'.'+quote(table)
            sequence=db.exec_driver_sql('SELECT pg_get_serial_sequence(%s,%s)',(relation,column)).scalar_one()
            maximum=db.exec_driver_sql('SELECT max('+quote(column)+') FROM '+relation).scalar_one()
            if maximum is not None:db.exec_driver_sql('SELECT setval(%s,%s,true)',(sequence,maximum))
    copied=database_snapshot(engine,identifier)
    if compare_business(before,copied):raise ValueError('Cloned old columns differ')
    shutil.copytree(source['assets'],state['assets'],copy_function=shutil.copy2)
    assets=compare_assets(source_inventory,asset_inventory(state['assets']))
    if not assets['preserved'] or assets['added']:raise ValueError('Asset copy differs')
    credentials=Path(source['assets']).parent/'credentials.json'
    write(directory/'credentials.json',json.loads(credentials.read_text(encoding='utf-8-sig')))
    migrate_database(config)
    migrated=database_snapshot(engine,identifier,before)
    expected={k:v for k,v in before.items() if k!='alembic_version'}
    failures=compare_business(expected,migrated)
    source_after=database_snapshot(engine,source['schema'],before)
    unchanged=compare_business(before,source_after)
    write(RUNTIME/'clone-verification.json',dict(source_schema=source['schema'],target_schema=identifier,
        original_table_count=len(before),original_rows=sum(v['count'] for v in before.values()),
        migrated_old_column_differences=failures,source_differences=unchanged,assets=assets,
        asset_count=len(source_inventory),asset_bytes=sum(v['size'] for v in source_inventory.values()),
        expected_schema_change='0059_bio_spatial_analysis -> 0060_research_results_bridge',
        public_database_modified=False,source_services_started=False))
    if failures or unchanged:raise ValueError('Preservation verification failed; retained for inspection')
    state.update(clone_status='verified',status='ready',migration_head='0060_research_results_bridge')
    write(state_path,state)
    return state


if __name__=='__main__':
    result=prepare()
    print(json.dumps({k:result[k] for k in ('schema','clone_status','status')},ensure_ascii=False))
