import pytest
from app.adapters.docx_process import parse_docx_isolated
from app.adapters.docx_parser import DOCX_SETTINGS
from app.core.exceptions import StorageError
@pytest.fixture(autouse=True)
def postgres_schema():yield None

def test_non_linux_fails_closed(monkeypatch):
    monkeypatch.setattr('sys.platform','win32')
    with pytest.raises(StorageError) as e:parse_docx_isolated(b'bad','x.docx',DOCX_SETTINGS)
    assert e.value.code=='parse_environment_unavailable'

@pytest.mark.skipif(__import__('sys').platform!='linux',reason='Real sandbox requires Linux')
def test_real_linux_process():
    from tests.adapters.test_docx_parser import sample
    result=parse_docx_isolated(sample(),'测试.docx',DOCX_SETTINGS)
    assert [b.kind for b in result.document.blocks]==['paragraph','table','paragraph']
