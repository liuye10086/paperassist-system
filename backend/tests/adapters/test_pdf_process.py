import sys
import pytest
from tests.helpers.pdf_samples import pdf_bytes,TEXT
from app.core.exceptions import StorageError
@pytest.fixture(autouse=True)
def postgres_schema():yield None

def test_non_linux_fails_closed():
    if sys.platform=='linux':pytest.skip('Windows guard')
    from app.adapters.pdf_process import parse_pdf_isolated
    from app.domain.documents.pdf_contracts import PDF_SETTINGS
    with pytest.raises(StorageError) as exc:parse_pdf_isolated(pdf_bytes([TEXT]),'a.pdf',PDF_SETTINGS)
    assert exc.value.code=='parse_environment_unavailable'

def test_transport_contract(monkeypatch):
    import app.adapters.pdf_process as process
    from app.adapters.pdf_parser import parse_pdf
    from app.domain.documents.pdf_contracts import PDF_SETTINGS
    content=pdf_bytes([TEXT]);result=parse_pdf(content,'a.pdf',PDF_SETTINGS)
    monkeypatch.setattr(process.sys,'platform','linux')
    def child(command,payload,**kwargs):
        assert kwargs['max_output_bytes']==8388608
        assert payload.endswith(content)
        assert command[2]=='-B'
        return {'result':result.model_dump()}
    monkeypatch.setattr(process,'_run_child',child)
    assert process.parse_pdf_isolated(content,'a.pdf',PDF_SETTINGS)==result

def test_transport_rejects_wrong_filename(monkeypatch):
    import app.adapters.pdf_process as process
    from app.adapters.pdf_parser import parse_pdf
    from app.domain.documents.pdf_contracts import PDF_SETTINGS
    content=pdf_bytes([TEXT]);result=parse_pdf(content,'wrong.pdf',PDF_SETTINGS)
    monkeypatch.setattr(process.sys,'platform','linux')
    monkeypatch.setattr(process,'_run_child',lambda *a,**kw:{'result':result.model_dump()})
    with pytest.raises(StorageError) as exc:process.parse_pdf_isolated(content,'a.pdf',PDF_SETTINGS)
    assert exc.value.code=='parse_output_invalid'

def test_transport_rejects_nonfinite_geometry(monkeypatch):
    import app.adapters.pdf_process as process
    from app.adapters.pdf_parser import parse_pdf
    from app.domain.documents.pdf_contracts import PDF_SETTINGS
    content=pdf_bytes([TEXT]);value=parse_pdf(content,'a.pdf',PDF_SETTINGS).model_dump()
    value['document']['pages'][0]['width']=float('inf')
    monkeypatch.setattr(process.sys,'platform','linux')
    monkeypatch.setattr(process,'_run_child',lambda *a,**kw:{'result':value})
    with pytest.raises(StorageError) as exc:process.parse_pdf_isolated(content,'a.pdf',PDF_SETTINGS)
    assert exc.value.code=='parse_output_invalid'
