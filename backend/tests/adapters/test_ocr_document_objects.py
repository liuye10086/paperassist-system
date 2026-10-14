"""Independent OCR object provenance tests without loading the OCR engine."""
from uuid import uuid4
import pytest
from app.adapters.document_objects import DocumentObjects
from app.maintenance.document_source_audit import validate_manifest
from app.core.exceptions import StorageError
from tests.helpers.ocr_samples import ocr_result


@pytest.fixture(autouse=True)
def postgres_schema():yield


def test_ocr_preview_and_json_are_immutable_and_hash_checked(tmp_path):
    from app.domain.documents.ocr_contracts import OCR_SETTINGS
    store=DocumentObjects(tmp_path);identifier=str(uuid4())
    result=ocr_result(b'original','scan.png','png',[1],OCR_SETTINGS)
    manifest=store.save(identifier,result)
    assert store.save(identifier,result)==manifest
    assert store.read(manifest)[1]==result.document
    validate_manifest(manifest,identifier)
    raw,mime=store.image(manifest,'page-1')
    assert mime=='image/jpeg' and raw.startswith(b'\xff\xd8\xff')
    (tmp_path/manifest['images'][0]['object_key']).write_bytes(b'changed')
    with pytest.raises(StorageError):store.image(manifest,'page-1')


def test_ocr_manifest_page_count_must_match_preview_count(tmp_path):
    from app.domain.documents.ocr_contracts import OCR_SETTINGS
    identifier=str(uuid4())
    manifest=DocumentObjects(tmp_path).save(identifier,ocr_result(b'original','scan.png','png',[1],OCR_SETTINGS))
    manifest['summary']['counts']['pages']=2
    with pytest.raises(StorageError):validate_manifest(manifest,identifier)
