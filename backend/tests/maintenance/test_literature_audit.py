"""Read-only audit detects provenance/decision mismatches in isolated fixtures."""
from psycopg.types.json import Jsonb
from app.db.database import database_connection
from app.maintenance.database_audit import audit_database
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_literature import project,create
from tests.helpers.literature import SyntheticNcbi
from tests.integration.test_literature_workflow import execute


def test_audit_verifies_literature_content_against_the_saved_response(client):
    task = create(client,project(client)).json()
    assert execute(task,SyntheticNcbi(2))['status'] == 'succeeded'
    with database_connection() as db:
        assert audit_database(db)['ok']
    with database_connection(write=True) as db:
        hit = db.execute('SELECT * FROM literature_search_hits LIMIT 1').fetchone()
        db.execute('UPDATE literature_search_hits SET record_json=%s WHERE id=%s',
            (Jsonb({**hit['record_json'],'title':'Unsupported changed title'}),hit['id']))
    with database_connection() as db:
        result = audit_database(db)
        assert not result['ok']
        assert any(c['table']=='literature_search_hits' and c['invalid'] for c in result['data_checks'])
