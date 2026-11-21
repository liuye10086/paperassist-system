"""0090 adds material submissions; downgrade refuses to discard them."""

import pytest
from alembic import command

from app.db.database import SCHEMA_HEAD, alembic_config, migration_connection


def status_check(db):
    return db.execute('''SELECT pg_get_constraintdef(oid) AS definition FROM pg_constraint
        WHERE conname='customer_progress_status' AND conrelid='customer_requirement_progress'::regclass''').fetchone()['definition']


def test_downgrade_refuses_submission_history_and_restores_previous_status_check(postgres_migration_config):
    settings = alembic_config()
    settings.attributes['database_config'] = postgres_migration_config
    with migration_connection(write=True) as db:
        settings.attributes['connection'] = db.raw_connection
        assert SCHEMA_HEAD == '0090_material_submissions' and 'materials_submitted' in status_check(db)
        db.execute('''INSERT INTO users (id,email,password_hash,role,active,created_at,updated_at)
            VALUES ('submission-customer','submission@schema.test','unused','customer',true,1,1)''')
        db.execute('''INSERT INTO projects (id,owner_id,name,research_topic,project_type,created_at,updated_at)
            VALUES ('submission-project','submission-customer','Materials','Synthetic study','research',
                    '2026-11-01T00:00:00Z','2026-11-01T00:00:00Z')''')
        db.execute('''INSERT INTO research_intakes (project_id,owner_id,created_at,updated_at)
            VALUES ('submission-project','submission-customer',now(),now())''')
        db.execute('''INSERT INTO research_requirement_versions (id,project_id,version,operation,content_json,
            sha256,request_key,request_digest,created_by,created_at)
            VALUES ('submission-requirement','submission-project',1,'confirm','{"schema_version":1}',
                    %s,'submission-submit',%s,'submission-customer',now())''', ('a' * 64, 'b' * 64))
        db.execute('''INSERT INTO customer_requirement_progress (requirement_version_id,project_id,status)
            VALUES ('submission-requirement','submission-project','materials_submitted')''')
        with pytest.raises(RuntimeError, match='material submissions'):
            command.downgrade(settings, '0089_paper_worksheets')

        db.execute("UPDATE customer_requirement_progress SET status='analyzing'")
        db.execute('''INSERT INTO customer_material_submissions (id,project_id,requirement_version_id,user_id,request_key)
            VALUES ('submission','submission-project','submission-requirement','submission-customer','submission-key')''')
        with pytest.raises(RuntimeError, match='material submissions'):
            command.downgrade(settings, '0089_paper_worksheets')

        db.execute('DELETE FROM customer_material_submissions')
        command.downgrade(settings, '0089_paper_worksheets')
        assert 'materials_submitted' not in status_check(db)
        assert db.execute("SELECT to_regclass('customer_material_submissions') AS t").fetchone()['t'] is None
        command.upgrade(settings, 'head')
        assert 'materials_submitted' in status_check(db)
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()['version_num'] == SCHEMA_HEAD
