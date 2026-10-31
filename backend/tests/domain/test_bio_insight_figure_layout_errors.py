"""The fixed renderer's actionable layout error survives the public boundary."""
import sys

import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def test_layout_size_error_reaches_public_parent_response(tmp_path, monkeypatch):
    from app.adapters import bio_insights_process, excel_process
    from app.adapters.bio_insights_engine import transport
    from app.core.errors import error_detail
    from app.core.exceptions import StorageError

    code = 'bio_insights_figure_layout_too_small'
    monkeypatch.setattr(bio_insights_process.sys, 'platform', 'linux')
    monkeypatch.setattr(bio_insights_process, 'INTERPRETER', sys.executable)
    monkeypatch.setattr(bio_insights_process, 'runtime_identity', lambda: {'available': True})
    monkeypatch.setattr(bio_insights_process, 'input_records', lambda payload: [])
    monkeypatch.setattr(transport, 'project_transport_payload', lambda payload: payload)
    monkeypatch.setattr(excel_process, '_run_child', lambda *args, **kwargs: {'error': {'code': code}})
    with pytest.raises(StorageError) as exc:
        bio_insights_process.execute_bio_insights({'kind': 'bio_insight_figure'}, tmp_path)
    assert exc.value.code == code
    assert error_detail(exc.value.code, str(exc.value))['code'] == code
