import json
from fastapi.testclient import TestClient
from app.main import app
from app.db.database import get_database_config
from tests.api.test_admin_operations import accounts, admin, login


def test_recovery_summary_requires_admin_and_never_exposes_receipt_secrets(admin, accounts, monkeypatch, tmp_path):
    path = tmp_path / 'recovery.json'
    monkeypatch.setenv('PAPERASSIST_RECOVERY_STATUS_FILE', str(path))
    response = admin.get('/api/v1/admin/storage/recovery')
    assert response.status_code == 200
    assert response.json()['status'] == 'unavailable'
    from app.maintenance.backup_manifest import result_summary
    receipt = result_summary(get_database_config().schema)
    receipt['password'] = 'private-source-password'
    path.write_text(json.dumps(receipt))
    response = admin.get('/api/v1/admin/storage/recovery')
    assert response.json()['status'] == 'available'
    assert 'private-source-password' not in response.text
    with TestClient(app) as client:
        assert client.get('/api/v1/admin/storage/recovery').status_code == 401
        login(client, accounts[2])
        assert client.get('/api/v1/admin/storage/recovery').status_code == 403
