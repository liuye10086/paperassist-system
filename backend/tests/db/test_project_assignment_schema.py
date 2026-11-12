"""Upgrade an existing customer workspace with historical batches and progress."""

from alembic import command
from sqlalchemy import inspect

from app.db.database import SCHEMA_HEAD, alembic_config, migration_connection


def test_assignment_upgrade_preserves_existing_customer_uploads_and_progress(postgres_migration_config):
    settings = alembic_config()
    settings.attributes['database_config'] = postgres_migration_config
    with migration_connection(write=True) as db:
        settings.attributes['connection'] = db.raw_connection
        command.downgrade(settings, '0077_customer_workspace')
        previous = inspect(db.raw_connection)
        assert 'upload_actor_id' not in {c['name'] for c in previous.get_columns('file_upload_batches')}
        assert 'assignment_revision' not in {c['name'] for c in previous.get_columns('customer_requirement_progress')}

        db.execute('''INSERT INTO users (id,email,password_hash,role,active,created_at,updated_at)
            VALUES ('legacy-customer','legacy@assignments.test','unused','customer',true,1,1)''')
        db.execute('''INSERT INTO projects (id,owner_id,name,research_topic,project_type,created_at,updated_at)
            VALUES ('legacy-project','legacy-customer','Legacy materials','Synthetic study','research',
                    '2026-10-01T00:00:00Z','2026-10-01T00:00:00Z')''')
        db.execute('''INSERT INTO research_intakes (project_id,owner_id,created_at,updated_at)
            VALUES ('legacy-project','legacy-customer',now(),now())''')
        db.execute('''INSERT INTO research_requirement_versions (id,project_id,version,operation,content_json,
            sha256,request_key,request_digest,created_by,created_at)
            VALUES ('legacy-requirement','legacy-project',1,'confirm','{"schema_version":1}',
                    %s,'legacy-submit',%s,'legacy-customer',now())''', ('a' * 64, 'b' * 64))
        db.execute('''INSERT INTO customer_requirement_progress (requirement_version_id,project_id,status,note)
            VALUES ('legacy-requirement','legacy-project','needs_materials','Original request')''')
        db.execute('''INSERT INTO file_upload_batches (id,project_id,user_id,idempotency_key,request_digest,created_at)
            VALUES ('legacy-batch','legacy-project','legacy-customer','legacy-key',%s,now())''', ('c' * 64,))

        command.upgrade(settings, 'head')

        batch = db.execute("SELECT user_id,upload_actor_id,idempotency_key FROM file_upload_batches WHERE id='legacy-batch'").fetchone()
        assert dict(batch) == {'user_id': 'legacy-customer', 'upload_actor_id': 'legacy-customer', 'idempotency_key': 'legacy-key'}
        progress = db.execute('''SELECT status,note,assignment_revision FROM customer_requirement_progress
            WHERE requirement_version_id='legacy-requirement' ''').fetchone()
        assert dict(progress) == {'status': 'needs_materials', 'note': 'Original request', 'assignment_revision': None}
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()['version_num'] == SCHEMA_HEAD
