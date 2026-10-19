"""0031 -> 0032 preserves exact old rows, indexes and saved source bytes."""
from alembic import command
from alembic.script import ScriptDirectory
from app.db.database import alembic_config, migration_connection, get_migration_database_config, database_connection, verify_runtime_permissions
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_literature_citations import seeded
from tests.api.test_literature_evidence import claim
from tests.maintenance.test_literature_evidence_migration import fingerprints


def test_citation_upgrade_retains_existing_rows_indexes_and_sources(client):
    _,lit,_,refs=seeded(client)
    original_claim=claim(client,lit+'/evidence')
    source_url=refs[0]['source']['source_download_url'];source=client.get(source_url).content
    config=alembic_config()
    assert ScriptDirectory.from_config(config).get_heads()==['0034_literature_pmc']
    with migration_connection(write=True) as db:
        config.attributes.update(connection=db.raw_connection,database_config=get_migration_database_config())
        command.downgrade(config,'0031_literature_evidence')
        tables=[r['tablename'] for r in db.execute('SELECT tablename FROM pg_tables WHERE schemaname=current_schema()') if r['tablename']!='alembic_version']
        before=fingerprints(db,tables)
        indexes={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        command.upgrade(config,'0032_literature_citations')
        assert fingerprints(db,tables)==before
        after={r['indexname']:r['indexdef'] for r in db.execute('SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema()')}
        assert all(after.get(k)==v for k,v in indexes.items())
        command.upgrade(config,'head')
    with database_connection() as db:
        from app.maintenance.database_audit import audit_database
        verify_runtime_permissions(db.raw_connection,db.config)
        result=audit_database(db)
        assert result['ok'],dict(issues=result['schema_issues'],invalid=[c for c in result['data_checks'] if c['invalid']])
    assert client.get(lit+'/evidence/claims/'+original_claim['id']).json()==original_claim
    assert client.get(source_url).content==source


def test_readonly_citation_audit_detects_snapshot_drift(client):
    from tests.api.test_literature_citations import binding,paragraph,draft_body
    from tests.api.test_literature_evidence import post
    from psycopg.types.json import Jsonb
    from app.maintenance.literature_citation_audit import audit_literature_citations
    _,lit,task,refs=seeded(client)
    c,b,_,_=binding(client,lit,task,refs[0])
    first=post(client,lit+'/citations/drafts',draft_body(paragraph(c,b)),'sample')
    assert first.status_code==201,first.text
    with database_connection() as db:
        checks=audit_literature_citations(db)
        assert all(c['invalid']==0 for c in checks),checks
    with database_connection(write=True) as db:
        row=db.execute('SELECT * FROM literature_citation_versions').fetchone()
        changed={**row['snapshot_json'],'title':'Changed without provenance'}
        db.execute('UPDATE literature_citation_versions SET snapshot_json=%s WHERE id=%s',(Jsonb(changed),row['id']))
    with database_connection() as db:
        checks=audit_literature_citations(db)
        assert any(c['table']=='literature_citation_versions' and c['invalid'] for c in checks)
