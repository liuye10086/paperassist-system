import pytest
from uuid import uuid4
from app.adapters.document_objects import DocumentObjects
from app.adapters.docx_parser import parse_docx, DOCX_SETTINGS
from tests.adapters.test_docx_parser import sample
from app.core.exceptions import StorageError
@pytest.fixture(autouse=True)
def postgres_schema():yield None

def test_save_read_immutable_and_tamper(tmp_path):
    store=DocumentObjects(tmp_path); result=parse_docx(sample(),'x.docx',DOCX_SETTINGS); identifier=str(uuid4())
    manifest=store.save(identifier,result)
    assert store.save(identifier,result)==manifest
    raw, document=store.read(manifest)
    assert document==result.document
    (tmp_path/manifest['object']['object_key']).write_bytes(b'bad')
    with pytest.raises(StorageError):store.read(manifest)

def test_bad_payload_never_publishes_manifest(tmp_path):
    store=DocumentObjects(tmp_path); result=parse_docx(sample(),'x.docx',DOCX_SETTINGS)
    result.image_payloads={'fake':'AAAA'}
    with pytest.raises(StorageError):store.save(str(uuid4()),result)
    assert not list(tmp_path.rglob('*.json'))
