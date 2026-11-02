"""Shared isolated preparation; source data and accepted schemas stay unchanged."""
import json
from pathlib import Path
from uuid import uuid4


def prepare(control, accepted_batch, accepted_scope, accepted_head):
    accepted_path = control.ROOT / 'script/.runtime' / accepted_batch
    accepted = json.loads((accepted_path / 'user-acceptance.json').read_text(encoding='utf-8'))
    if accepted['user_acceptance'] != 'accepted' or accepted['scope'] != accepted_scope:
        raise ValueError('Expected accepted source subpackage baseline')
    source = json.loads((accepted_path / 'state.json').read_text(encoding='utf-8'))
    resuming = control.STATE.exists()
    if resuming:
        state = control.read_state()
        if state.get('preparation_kind') != 'fresh_schema' or state['source_schema'] != source['schema']:
            raise ValueError('Existing preparation has a different identity')
        if state.get('clone_status') == 'verified':
            return state
        if state.get('clone_status') != 'preparing':
            raise ValueError('Incomplete preparation has an unexpected status')
    else:
        state = control.new_state('pa_test_' + uuid4().hex, source['schema'])
        state['preparation_kind'] = 'fresh_schema'
    control.RUNTIME.mkdir(exist_ok=True)
    directory = Path(state['assets']).parent
    directory.mkdir(parents=True, exist_ok=resuming)
    control.worker_stack.protect_directory(directory)
    control.worker_stack.private_write(control.STATE, json.dumps(state, indent=2))
    for key in ('assets', 'staging', 'research_staging', 'bio_staging'):
        Path(state[key]).mkdir(exist_ok=resuming)
    control.configure(state)
    from app.db.database import get_migration_database_config, get_engine, migrate_database, database_connection
    config = get_migration_database_config()
    engine = get_engine(config)
    with engine.begin() as db:
        if db.exec_driver_sql('SELECT current_database()').scalar_one() != 'paperassist_system_test':
            raise ValueError('Only the isolated test database is allowed')
        old_head = db.exec_driver_sql('SELECT version_num FROM ' + engine.dialect.identifier_preparer.quote(source['schema']) + '.alembic_version').scalar_one()
        if old_head != accepted_head:
            raise ValueError('Accepted source schema revision changed')
        if resuming:
            count = db.exec_driver_sql('SELECT count(*) FROM information_schema.tables WHERE table_schema=%s', (state['schema'],)).scalar_one()
            if count:
                raise ValueError('Only an empty schema from a rolled-back migration can resume automatically')
        else:
            db.exec_driver_sql('CREATE SCHEMA ' + engine.dialect.identifier_preparer.quote(state['schema']))
    migrate_database(config)
    from app.domain.storage_governance.deletion import register_new_test_schema
    register_new_test_schema(state['schema'])
    # Reuse the already authorized local test login; create identities only in the new schema.
    credentials = json.loads((Path(source['assets']).parent / 'credentials.json').read_text(encoding='utf-8'))
    from app.auth.service import create_user
    for name, role in (('review', 'user'), ('other', 'user'), ('admin', 'admin')):
        original = credentials[name]
        user = create_user(original['email'], original['password'], role=role)
        credentials[name] = {**original, 'id': user['id']}
    control.worker_stack.private_write(directory / 'credentials.json', json.dumps(credentials, indent=2))
    with database_connection() as db:
        head = db.execute('SELECT version_num FROM alembic_version').fetchone()['version_num']
    state.update(clone_status='verified', status='ready', migration_head=head,
                 source_projects_copied=False, source_assets_copied=False)
    control.worker_stack.private_write(control.STATE, json.dumps(state, indent=2))
    control.worker_stack.private_write(control.RUNTIME / 'preparation.json', json.dumps(dict(
        schema=state['schema'], source_schema=source['schema'], source_head=old_head, head=head,
        preparation_kind='fresh_schema', source_mutated=False, old_assets_copied=False,
        explanation='Reuse code and frozen evidence; new examples use new projects without copying accepted large assets.'), indent=2))
    return state
