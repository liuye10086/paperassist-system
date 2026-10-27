"""0050 upgrade rehearsal is confined to the fixture's new random test schema."""
from alembic import command

from app.db.database import alembic_config,migration_connection


def test_0051_preserves_existing_users_and_adds_default_revision(postgres_schema,postgres_migration_config):
    settings=alembic_config()
    settings.attributes['database_config']=postgres_migration_config
    with migration_connection(write=True) as db:
        settings.attributes['connection']=db.raw_connection
        command.downgrade(settings,'0050_review_round_returns')
        db.execute("""INSERT INTO users(id,email,password_hash,role,active,created_at,updated_at)
            VALUES('legacy-account','legacy@example.test','unchanged-hash','user',true,10,20)""")
        before=dict(db.execute('SELECT * FROM users').fetchone())
        command.upgrade(settings,'head')
        after=dict(db.execute('SELECT * FROM users').fetchone())
        assert after.pop('admin_revision')==1
        assert after==before
        assert db.execute('SELECT count(*) AS n FROM admin_audit_events').fetchone()['n']==0
        assert db.execute('SELECT count(*) AS n FROM operational_collection').fetchone()['n']==1
