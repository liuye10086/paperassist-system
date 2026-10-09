"""Public read projection never exposes administrator evidence."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.database import database_connection
from tests.integration.test_model_usage import context, request  # noqa: F401
from tests.integration.test_model_reconciliation import plot, reconciliation, evidence


@pytest.mark.parametrize('scope', ['projects', 'tasks'])
def test_actual_summary_covers_other_pages_and_redacts_evidence(context, scope):
    service, saved = plot(context)
    recon = reconciliation(context)
    recon.reconcile(saved['id'], {**evidence('tool', 600), 'operator': 'private-admin', 'evidence_reference': 'restricted:private-secret'})
    service.reserve_call(request(context[3], call_key='unobserved'))
    with TestClient(app) as client:
        client.headers.update({'X-PaperAssist-Client': 'web', 'Origin': 'http://testserver'})
        assert client.post('/api/v1/auth/login', json={'email': 'model-test@local.test', 'password': 'safe-test-password-2026'}).status_code == 200
        key = context[2] if scope == 'projects' else context[3]
        response = client.get(f'/api/v1/{scope}/{key}/model-usage?page_size=1')
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['reconciliation'] == dict(actual_micro_usd=600, reconciled_count=0, partial_count=1, pending_count=1)
        assert body['estimated_micro_usd'] == 1010 and body['accounted_micro_usd'] == 1010
        assert body['items'][0]['reconciliation']['actual_micro_usd'] is None
        for marker in ['private-', 'restricted:', 'evidence_', 'provider_object_id', 'response-test', 'cntr_test', 'b' * 64]:
            assert marker not in response.text
        partial = client.get(f'/api/v1/{scope}/{key}/model-usage?page_size=1&page=2').json()['items'][0]['reconciliation']
        assert partial['status'] == 'partial' and partial['actual_micro_usd'] == 600
        assert partial['reconciled_at'] is not None
    with database_connection() as db:
        assert db.execute("SELECT count(*) AS n FROM usage_events WHERE event_type='reconciliation'").fetchone()['n'] == 1
