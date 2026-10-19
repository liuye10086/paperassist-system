"""SQL NULL pairing and auditing of an isolated legacy anomalous row."""
import pytest
from sqlalchemy.exc import IntegrityError
from psycopg.types.json import Jsonb

from app.db.database import database_connection, migration_connection
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_literature import project
from tests.integration.test_literature_assistance import create, budgets, SyntheticProvider


def unknown_submission(client):
    from app.domain.literature_assistance.execution import run_assistance_task
    task = create(client, project(client))
    budgets(client, task)
    provider = SyntheticProvider(unknown=True)
    waiting = run_assistance_task(task['id'], task['revision'], provider_factory=lambda: provider)
    assert waiting['reason_code'] == 'submission_unknown'
    with database_connection() as db:
        call = db.execute('SELECT id FROM model_calls WHERE task_id=%s', (task['id'],)).fetchone()
    return task['id'], call['id']


@pytest.mark.parametrize('case', ['sql_null_with_call','object_without_call','json_null_with_call','array_with_call'])
def test_result_and_model_call_invalid_pairs_are_rejected(client, case):
    task_id, call_id = unknown_submission(client)
    result = None if case=='sql_null_with_call' else Jsonb({} if case=='object_without_call' else None if case=='json_null_with_call' else [])
    paired_call = None if case=='object_without_call' else call_id
    with pytest.raises(IntegrityError):
        with database_connection(write=True) as db:
            db.execute('''UPDATE literature_assistance_requests SET result_json=%s,model_call_id=%s
                WHERE task_id=%s''', (result, paired_call, task_id))


def test_audit_rejects_legacy_sql_null_result_with_model_call(client, postgres_schema):
    from app.maintenance.literature_assistance_audit import audit_literature_assistance
    task_id, call_id = unknown_submission(client)
    with database_connection() as db:
        assert audit_literature_assistance(db)[0]['invalid'] == 0
    # Emulate the old CHECK's permitted anomaly only in this disposable schema.
    assert postgres_schema.environment == 'test'
    assert postgres_schema.schema.startswith('pa_test_')
    with migration_connection(write=True) as db:
        db.execute('ALTER TABLE literature_assistance_requests DROP CONSTRAINT literature_assistance_requests_result_check')
    with database_connection(write=True) as db:
        db.execute('''UPDATE literature_assistance_requests SET result_json=NULL,model_call_id=%s
            WHERE task_id=%s''', (call_id, task_id))
    with database_connection() as db:
        assert audit_literature_assistance(db)[0]['invalid'] == 1
