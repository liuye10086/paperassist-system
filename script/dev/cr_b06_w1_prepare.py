"""Clone the accepted B04 source once for W1 using the established copy protocol."""
import json
from pathlib import Path
import shutil
from uuid import uuid4
import cr_b06_w1_runner as control
from cr_b05_clone import validate_source
from cr_b03_preservation import asset_inventory, compare_assets, database_snapshot, compare_business


def prepare():
    source = json.loads((control.ROOT / 'script/.runtime/client-requirements-b04/state.json').read_text(encoding='utf-8-sig'))
    validate_source(source)
    if control.STATE.exists():
        existing = control.read_state()
        if existing['clone_status'] == 'verified':
            return existing
        raise ValueError('Incomplete W1 preparation retained; inspect rather than create another copy')
    if control.port_open(source):
        raise ValueError('Accepted B04 API must remain stopped')
    if shutil.disk_usage(control.DATA_ROOT.anchor).free < 12 * 1024 ** 3:
        raise ValueError('Insufficient free disk for an isolated copy')
    state = control.new_state('pa_test_' + uuid4().hex, source['schema'])
    directory = Path(state['assets']).parent
    directory.mkdir(parents=True, exist_ok=False)
    control.worker_stack.protect_directory(directory)
    control.save(control.STATE, state)
    control.configure(state)
    from app.db.database import get_migration_database_config, get_engine, migration_connection, alembic_config, migrate_database
    from alembic import command
    config = get_migration_database_config(); engine = get_engine(config)
    quote = engine.dialect.identifier_preparer.quote_identifier
    source_schema, target_schema = quote(source['schema']), quote(state['schema'])
    before = database_snapshot(engine, source['schema'])
    control.save(control.RUNTIME / 'b04-database-before.json', before)
    with engine.begin() as db:
        if db.exec_driver_sql('SELECT current_database()').scalar_one() != 'paperassist_system_test':
            raise ValueError('Only the isolated test database is allowed')
        source_head = db.exec_driver_sql('SELECT version_num FROM ' + source_schema + '.alembic_version').scalar_one()
        if source_head != '0061_bio_insights':
            raise ValueError('Accepted B04 migration changed')
        active = db.exec_driver_sql("SELECT count(*) FROM " + source_schema + ".tasks WHERE status IN ('queued','running','submitting')").scalar_one()
        if active:
            raise ValueError('Source contains executable unfinished tasks')
        db.exec_driver_sql('CREATE SCHEMA ' + target_schema)
    with migration_connection(write=True) as db:
        cfg = alembic_config(); cfg.attributes.update(connection=db.raw_connection, database_config=config)
        command.upgrade(cfg, source_head)
    # Same exact-target copy protocol as cr_b05_clone; accepted source is SELECT-only.
    with engine.begin() as db:
        db.exec_driver_sql("SELECT set_config('search_path',%s,true)", (state['schema'],))
        foreign = db.exec_driver_sql("SELECT c.conrelid::regclass::text,c.conname,pg_get_constraintdef(c.oid) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname=%s AND c.contype='f' ORDER BY c.conname", (state['schema'],)).all()
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
        sequences = db.exec_driver_sql("SELECT table_name,column_name FROM information_schema.columns WHERE table_schema=%s AND (is_identity='YES' OR column_default LIKE 'nextval%%')", (state['schema'],)).all()
        for table, column in sequences:
            relation = target_schema + '.' + quote(table)
            sequence = db.exec_driver_sql('SELECT pg_get_serial_sequence(%s,%s)', (relation, column)).scalar_one()
            maximum = db.exec_driver_sql('SELECT max(' + quote(column) + ') FROM ' + relation).scalar_one()
            if maximum is not None:
                db.exec_driver_sql('SELECT setval(%s,%s,true)', (sequence, maximum))
    copied = database_snapshot(engine, state['schema'])
    if compare_business(before, copied):
        raise ValueError('Copied original columns differ; inspect retained target')
    inventory = asset_inventory(source['assets'])
    control.save(control.RUNTIME / 'b04-assets-before.json', inventory)
    shutil.copytree(source['assets'], state['assets'], copy_function=shutil.copy2)
    assets = compare_assets(inventory, asset_inventory(state['assets']))
    if not assets['preserved'] or assets['added']:
        raise ValueError('Copied assets differ; inspect retained target')
    credentials = Path(source['assets']).parent / 'credentials.json'
    control.save(directory / 'credentials.json', json.loads(credentials.read_text(encoding='utf-8-sig')))
    for key in ('staging', 'research_staging', 'bio_staging'):
        Path(state[key]).mkdir(exist_ok=False)
    migrate_database(config)
    migrated = database_snapshot(engine, state['schema'], before)
    old_columns = {k: v for k, v in before.items() if k != 'alembic_version'}
    differences = compare_business(old_columns, migrated)
    source_differences = compare_business(before, database_snapshot(engine, source['schema'], before))
    with engine.connect() as db:
        head = db.exec_driver_sql('SELECT version_num FROM ' + target_schema + '.alembic_version').scalar_one()
    control.save(control.RUNTIME / 'clone-verification.json', dict(source_schema=source['schema'], target_schema=state['schema'],
        source_head=source_head, target_head=head, original_tables=len(before), original_rows=sum(v['count'] for v in before.values()),
        source_differences=source_differences, migrated_old_column_differences=differences, assets=assets,
        asset_count=len(inventory), asset_bytes=sum(v['size'] for v in inventory.values()), source_services_started=False))
    if differences or source_differences:
        raise ValueError('Preservation check failed; target retained')
    state.update(clone_status='verified', status='ready', migration_head=head)
    control.save(control.STATE, state)
    return state
