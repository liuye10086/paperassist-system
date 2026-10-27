"""Process-scoped socket guard; no business app, database or external connection."""
from pathlib import Path
import subprocess
import sys
import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def test_blocking_portal_initializes_and_external_socket_is_rejected():
    # A fresh child contains the permanent audit hook. On Windows the same
    # blocking portal used by TestClient creates a loopback TCP socketpair.
    program = r'''
import json
import socket
from anyio.from_thread import start_blocking_portal
from app.maintenance.recovery_http import install_network_guard
from app.maintenance.recovery_drill import DrillError
observations = install_network_guard(51473)
with start_blocking_portal() as portal:
    assert portal.call(lambda: 'portal-ready') == 'portal-ready'
assert observations['blocked_connections'] == 0
with socket.socket() as connection:
    try:
        connection.connect(('192.0.2.1', 443))
    except DrillError as exc:
        assert str(exc) == 'network_connection_forbidden'
    else:
        raise AssertionError('External socket was not rejected before connection')
assert observations['blocked_connections'] == 1
print(json.dumps(dict(portal_initialized=True, external_rejected=True)))
'''
    result = subprocess.run([sys.executable, '-B', '-c', program],
                            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert '"external_rejected": true' in result.stdout
