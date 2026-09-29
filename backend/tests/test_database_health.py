"""Readiness must reflect the actual PostgreSQL schema, not just HTTP liveness."""

import pytest
from fastapi.testclient import TestClient

from app.database import database_connection
from app.main import app
from app.storage import StorageError


def remove_migration_version():
    with database_connection(write=True) as db:
        db.execute('DROP TABLE alembic_version')


def test_health_rejects_unmigrated_postgresql_schema():
    remove_migration_version()
    response = TestClient(app).get('/api/v1/health')
    assert response.status_code == 503
    assert response.json()['detail']['code'] == 'storage_version'


def test_startup_rejects_unmigrated_postgresql_schema():
    remove_migration_version()
    with pytest.raises(StorageError) as caught:
        with TestClient(app):
            pass
    assert caught.value.code == 'storage_version'


def test_ready_health_preserves_existing_api_contract():
    with TestClient(app) as client:
        response = client.get('/api/v1/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok', 'service': 'paperassist-system'}
