"""Copy accepted B04 to a new B05 test schema. Never deletes retained data."""
import json
from pathlib import Path
import re
import shutil
import socket
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / 'script/.runtime/client-requirements-b05'
SOURCE = ROOT / 'script/.runtime/client-requirements-b04/state.json'
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'script'), str(ROOT / 'script/dev')]
from cr_b03_preservation import asset_inventory, compare_assets, database_snapshot, compare_business
import cr_b05_runner as control


def validate_source(state):
    if (not re.fullmatch(r'pa_test_[a-f0-9]{32}', state.get('schema', ''))
            or state.get('status') != 'user_accepted_and_services_stopped'):
        raise ValueError('Only accepted, stopped B04 may seed B05')
    expected = ROOT / 'script/.runtime/client-requirements-b04/acceptance' / state['schema'] / 'assets'
    if (state.get('workspace') != str(ROOT) or state.get('assets') != str(expected)
            or state.get('migration_head') != '0061_bio_insights'
            or state.get('bind_host') != '127.0.0.84' or state.get('port') != 18084):
        raise ValueError('Unexpected source schema, directory or service identity')


def write(path, value):
    control.worker_stack.private_write(path, json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def prepare():
    source = json.loads(SOURCE.read_text(encoding='utf-8-sig'))
    validate_source(source)
    if control.STATE.exists():
        existing = control.read_state()
        if existing.get('clone_status') == 'verified':
            return existing
        raise ValueError('Incomplete preparation retained; inspect before creating another')
    with socket.socket() as connection:
        connection.settimeout(.2)
        if connection.connect_ex((source['bind_host'], source['port'])) == 0:
            raise ValueError('Accepted source API must remain stopped')
    stack = control.worker_stack.load(ROOT, test_id=source['schema'][8:])
    containers = control.worker_stack.owned_containers(stack)
    if len(containers) != 4 or any(c['status'] != 'exited' for c in containers):
        raise ValueError('Accepted source containers must remain stopped')
    if shutil.disk_usage(control.DATA_ROOT.anchor).free < 12 * 1024 ** 3:
        raise ValueError('B05 requires at least 12GiB additional free disk')
    source_inventory = asset_inventory(source['assets'])
    write(RUNTIME / 'b04-assets-before.json', {'source_assets': source['assets'], 'files': source_inventory})
    identifier = 'pa_test_' + uuid4().hex
    state = control.new_state(identifier, source['schema'])
    directory = Path(state['assets']).parent
    directory.mkdir(parents=True, exist_ok=False)
    control.worker_stack.protect_directory(directory)
    write(control.STATE, state)
    control.configure(state)
    from app.db.database import get_migration_database_config, get_engine, migration_connection, alembic_config, migrate_database
    from alembic import command
    config = get_migration_database_config()
    engine = get_engine(config)
    quote = engine.dialect.identifier_preparer.quote_identifier
    source_schema, target_schema = quote(source['schema']), quote(identifier)
    before = database_snapshot(engine, source['schema'])
    write(RUNTIME / 'b04-database-before.json', before)
    with engine.begin() as db:
        if db.exec_driver_sql('SELECT current_database()').scalar_one() != 'paperassist_system_test':
            raise ValueError('Expected isolated test database')
        source_head = db.exec_driver_sql('SELECT version_num FROM ' + source_schema + '.alembic_version').scalar_one()
        if source_head != '0061_bio_insights':
            raise ValueError('Accepted B04 schema revision changed')
        active = db.exec_driver_sql("SELECT count(*) FROM " + source_schema + ".tasks WHERE status IN ('queued','running','submitting')").scalar_one()
        if active:
            raise ValueError('B04 has unfinished executable tasks')
        db.exec_driver_sql('CREATE SCHEMA ' + target_schema)
    with migration_connection(write=True) as db:
        cfg = alembic_config()
        cfg.attributes.update(connection=db.raw_connection, database_config=config)
        command.upgrade(cfg, '0061_bio_insights')
    # Every mutation below targets only the exact newly generated target schema.
    # The accepted source is used exclusively in SELECT statements.
    with engine.begin() as db:
        db.exec_driver_sql("SELECT set_config('search_path',%s,true)", (identifier,))
        foreign = db.exec_driver_sql("SELECT c.conrelid::regclass::text,c.conname,pg_get_constraintdef(c.oid) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname=%s AND c.contype='f' ORDER BY c.conname", (identifier,)).all()
        for relation, name, definition in foreign:
            db.exec_driver_sql('ALTER TABLE ' + relation + ' DROP CONSTRAINT ' + quote(name))
        for table, old in before.items():
            relation = target_schema + '.' + quote(table)
            db.exec_driver_sql('ALTER TABLE ' + relation + ' DISABLE TRIGGER USER')
            db.exec_driver_sql('DELETE FROM ' + relation)
            columns = ','.join(map(quote, old['columns']))
            db.exec_driver_sql('INSERT INTO ' + relation + '(' + columns + ') OVERRIDING SYSTEM VALUE SELECT ' + columns + ' FROM ' + source_schema + '.' + quote(table))
            db.exec_driver_sql('ALTER TABLE ' + relation + ' ENABLE TRIGGER USER')
        for relation, name, definition in foreign:
            db.exec_driver_sql('ALTER TABLE ' + relation + ' ADD CONSTRAINT ' + quote(name) + ' ' + definition)
        sequences = db.exec_driver_sql("SELECT table_name,column_name FROM information_schema.columns WHERE table_schema=%s AND (is_identity='YES' OR column_default LIKE 'nextval%%')", (identifier,)).all()
        for table, column in sequences:
            relation = target_schema + '.' + quote(table)
            sequence = db.exec_driver_sql('SELECT pg_get_serial_sequence(%s,%s)', (relation, column)).scalar_one()
            maximum = db.exec_driver_sql('SELECT max(' + quote(column) + ') FROM ' + relation).scalar_one()
            if maximum is not None:
                db.exec_driver_sql('SELECT setval(%s,%s,true)', (sequence, maximum))
    copied = database_snapshot(engine, identifier)
    if compare_business(before, copied):
        raise ValueError('Cloned old columns differ; retained for inspection')
    shutil.copytree(source['assets'], state['assets'], copy_function=shutil.copy2)
    assets = compare_assets(source_inventory, asset_inventory(state['assets']))
    if not assets['preserved'] or assets['added']:
        raise ValueError('Asset copy differs; retained for inspection')
    credentials = Path(source['assets']).parent / 'credentials.json'
    write(directory / 'credentials.json', json.loads(credentials.read_text(encoding='utf-8-sig')))
    for key in ('staging', 'research_staging', 'bio_staging'):
        Path(state[key]).mkdir(exist_ok=False)
    migrate_database(config)
    migrated = database_snapshot(engine, identifier, before)
    old_columns = {k: v for k, v in before.items() if k != 'alembic_version'}
    failures = compare_business(old_columns, migrated)
    source_after = database_snapshot(engine, source['schema'], before)
    unchanged = compare_business(before, source_after)
    write(RUNTIME / 'clone-verification.json', dict(source_schema=source['schema'], target_schema=identifier,
        original_table_count=len(before), original_rows=sum(v['count'] for v in before.values()),
        migrated_old_column_differences=failures, source_differences=unchanged, assets=assets,
        asset_count=len(source_inventory), asset_bytes=sum(v['size'] for v in source_inventory.values()),
        expected_schema_change='0061_bio_insights -> 0062_bio_tabular_assays',
        public_database_modified=False, source_services_started=False,
        historical_failed_task_materials='Original B04 staging and logs retained in original runtime; not executed in B05'))
    if failures or unchanged:
        raise ValueError('Preservation verification failed; retained for inspection')
    state.update(clone_status='verified', status='ready', migration_head='0062_bio_tabular_assays')
    write(control.STATE, state)
    return state


if __name__ == '__main__':
    result = prepare()
    print(json.dumps({k: result[k] for k in ('schema', 'clone_status', 'status')}, ensure_ascii=False))
