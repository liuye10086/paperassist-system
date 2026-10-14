import sys
import pytest
from app.core.exceptions import StorageError


def test_windows_refuses_unrestricted_structure_process(monkeypatch):
    from app.adapters.excel_structure_process import parse_excel_structure_isolated
    monkeypatch.setattr(sys, 'platform', 'win32')
    with pytest.raises(StorageError) as exc:
        parse_excel_structure_isolated(b'xlsx', 'test.xlsx', {})
    assert exc.value.code == 'parse_environment_unavailable'


def test_structure_process_validates_child_identity(monkeypatch):
    import app.adapters.excel_structure_process as process
    from app.core.config import ExcelSettings
    monkeypatch.setattr(sys,'platform','linux')
    monkeypatch.setattr(process,'_run_child',lambda *args,**kwargs: {'structure':{'schema_version':True}})
    with pytest.raises(StorageError) as exc:
        process.parse_excel_structure_isolated(b'xlsx','test.xlsx',{'excel':ExcelSettings().model_dump(),'process':process.PROCESS_SETTINGS})
    assert exc.value.code=='parse_output_invalid'
