"""Real short children exercise startup errors without loading native models."""
from copy import deepcopy
import sys

import pytest

from app.adapters.excel_process import _run_child
from app.core.exceptions import StorageError
from app.domain.documents.ocr_contracts import OCR_SETTINGS

pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='Requires Linux pipe transport')


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def _startup_command(reply):
    # Check the actual pipe after emitting the error: any bytes or EOF before
    # child exit mean the parent interacted with stdin without receiving READY.
    source = (
        'import json, select, sys\n'
        f'print(json.dumps({reply!r}), flush=True)\n'
        'assert not select.select([sys.stdin], [], [], 0.2)[0]\n'
    )
    return [sys.executable, '-I', '-B', '-c', source]


@pytest.mark.parametrize('code', ['parse_environment_unavailable', 'parse_resource_limit'])
def test_known_startup_errors_return_without_sending_payload(code):
    reply = {'error': {'code': code}}
    assert _run_child(_startup_command(reply), b'user-document-must-not-arrive',
                      timeout_seconds=3, max_output_bytes=1024) == reply


@pytest.mark.parametrize('reply', [
    {'error': {'code': 'unknown'}},
    {'error': {'code': 'parse_process_failed'}},
    {'error': {'code': 'parse_resource_limit', 'extra': True}},
])
def test_unknown_startup_errors_are_rejected_without_sending_payload(reply):
    with pytest.raises(StorageError) as error:
        _run_child(_startup_command(reply), b'user-document-must-not-arrive',
                   timeout_seconds=3, max_output_bytes=1024)
    assert error.value.code == 'parse_output_invalid'


def test_ocr_startup_resource_error_reaches_caller(monkeypatch):
    from app.adapters import ocr_process

    command = _startup_command({'error': {'code': 'parse_resource_limit'}})

    def run_short_child(_command, payload, **kwargs):
        return _run_child(command, payload, **kwargs)

    monkeypatch.setattr(ocr_process, '_run_child', run_short_child)
    with pytest.raises(StorageError) as error:
        ocr_process.parse_ocr_isolated(b'user-document-must-not-arrive', 'x.png', 'png', [1],
                                       deepcopy(OCR_SETTINGS))
    assert error.value.code == 'parse_resource_limit'
