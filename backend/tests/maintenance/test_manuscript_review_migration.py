"""0038 only adds review history; old bytes/columns/indexes remain unchanged."""
from tests.helpers.historical_migration import historical_workflow, assert_saved_history_blocks
import pytest
from alembic import command
from tests.api.test_manuscripts import client,setup,body
from tests.api.test_literature_evidence import post
from tests.maintenance.test_literature_evidence_migration import fingerprints
from app.db.database import alembic_config,get_migration_database_config,migration_connection,database_connection


def test_review_migration_preserves_old_rows_columns_indexes_and_empty_audit(client):
    path,_,_=setup(client)
    response = post(client,path,body(),'base')
    assert response.status_code == 201, response.text
    saved = response.json()
    with historical_workflow(get_migration_database_config(), '0037_manuscript_writing') as (db, cfg):
        assert db.execute("SELECT 1 FROM manuscripts WHERE id=%s", (saved['id'],)).fetchone()
        tables=[r['tablename'] for r in db.execute('SELECT tablename FROM pg_tables WHERE schemaname=current_schema()') if r['tablename']!='alembic_version']
        before=fingerprints(db,tables)
        columns=[dict(r) for r in db.execute("SELECT table_name,column_name,data_type,is_nullable,column_default FROM information_schema.columns WHERE table_schema=current_schema() ORDER BY table_name,ordinal_position")]
        indexes={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        command.upgrade(cfg,'0038_manuscript_review')
        assert fingerprints(db,tables)==before
        after=[dict(r) for r in db.execute("SELECT table_name,column_name,data_type,is_nullable,column_default FROM information_schema.columns WHERE table_schema=current_schema() AND table_name!='manuscript_reviews' ORDER BY table_name,ordinal_position")]
        assert after==columns
        new_indexes={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        assert all(new_indexes.get(k)==v for k,v in indexes.items())
    with database_connection() as db:
        from app.maintenance.database_audit import audit_database
        audit=audit_database(db)
        assert audit['ok'],audit['schema_issues'] or [c for c in audit['data_checks'] if c['invalid']]


def test_review_history_blocks_destructive_downgrade(client):
    from tests.api.test_manuscript_review import ready
    _,_,endpoint,_=ready(client)
    assert post(client,endpoint,dict(base_revision=1),'review').status_code==201
    assert_saved_history_blocks('0038_manuscript_review', 'Review history exists; refusing destructive downgrade.')

@pytest.mark.parametrize('column,value',[('published_revision',2),('publish_key','publish')])
def test_review_database_rejects_half_filled_publication_state(client,column,value):
    from sqlalchemy.exc import IntegrityError
    from tests.api.test_manuscript_review import ready
    _,_,endpoint,_=ready(client)
    review=post(client,endpoint,dict(base_revision=1),'r').json()
    with pytest.raises(IntegrityError):
        with database_connection(write=True) as db:
            db.execute('UPDATE manuscript_reviews SET '+column+'=%s WHERE id=%s',(value,review['id']))
