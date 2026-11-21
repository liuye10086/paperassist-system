import pytest
from alembic import command

from app.db.database import alembic_config, database_connection
from tests.db.test_task_schema import NOW, seed_owner


@pytest.mark.initial_revision('0073_analysis_request_receipts')
def test_request_identity_survives_refused_downgrade(postgres_migration_config):
    with database_connection(write=True) as db:
        seed_owner(db)
        db.execute('''INSERT INTO analysis_request_receipts
            (id,user_id,project_id,kind,request_key,request_digest,target_id,created_at)
            VALUES ('receipt','u','p','research_report','request',%s,'report',%s)''', ('a' * 64, NOW))
        before = dict(db.execute('SELECT * FROM analysis_request_receipts').fetchone())
    settings = alembic_config()
    settings.attributes['database_config'] = postgres_migration_config
    with pytest.raises(RuntimeError, match='Request identities are retained'):
        command.downgrade(settings, '0072_single_cell_annotations')
    with database_connection() as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()['version_num'] == '0073_analysis_request_receipts'
        assert dict(db.execute('SELECT * FROM analysis_request_receipts').fetchone()) == before


@pytest.mark.initial_revision('0075_account_roles')
@pytest.mark.parametrize('role,active,review_status', [(None, False, 'pending'), ('customer', True, 'approved')])
def test_account_review_survives_refused_downgrade(postgres_migration_config, role, active, review_status):
    with database_connection(write=True) as db:
        db.execute('''INSERT INTO users(id,email,password_hash,role,active,created_at,updated_at,review_status)
            VALUES ('account','review@example.invalid','synthetic',%s,%s,1,1,%s)''', (role, active, review_status))
        before = dict(db.execute('SELECT * FROM users').fetchone())
    settings = alembic_config()
    settings.attributes['database_config'] = postgres_migration_config
    with pytest.raises(RuntimeError, match='Account roles or review records require schema 0075'):
        command.downgrade(settings, '0074_tabular_import_file_limit')
    with database_connection() as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()['version_num'] == '0075_account_roles'
        assert dict(db.execute('SELECT * FROM users').fetchone()) == before
