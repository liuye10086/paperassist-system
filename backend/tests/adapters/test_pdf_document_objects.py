from uuid import uuid4
import pytest
from app.adapters.document_objects import DocumentObjects

@pytest.fixture(autouse=True)
def postgres_schema():
    yield None

def test_pdf_objects_round_trip_and_format_guard(tmp_path):
    result = {'document': {'schema_version': 1, 'kind': 'pdf_document', 'filename': 'x.pdf', 'parser_version': 'pdfplumber-0.11.10-text-v1', 'pages': [], 'warnings': [], 'counts': {'pages': 0, 'text_blocks': 0, 'tables': 0, 'cells': 0, 'pages_without_text': 0}}}
    store = DocumentObjects(tmp_path)
    manifest = store.save(str(uuid4()), result)
    assert manifest['kind'] == 'pdf_document'
    assert manifest['images'] == []
    raw, document = store.read(manifest)
    assert document.kind == 'pdf_document'
    assert store.save(manifest['object']['object_key'].split('/')[1], result) == manifest

def test_pdf_manifest_does_not_accept_word_image_records(tmp_path):
    from app.maintenance.document_source_audit import validate_manifest
    from app.core.exceptions import StorageError
    identifier=str(uuid4())
    result={'document':{'schema_version':1,'kind':'pdf_document','filename':'x.pdf','parser_version':'pdfplumber-0.11.10-text-v1','pages':[],'warnings':[],'counts':{'pages':0,'text_blocks':0,'tables':0,'cells':0,'pages_without_text':0}}}
    manifest=DocumentObjects(tmp_path).save(identifier,result)
    validate_manifest(manifest,identifier)
    manifest['images']=[{'id':'im','sha256':'a'*64,'object_key':f'documents/{identifier}/'+('a'*64)+'.bin','size_bytes':1,'inline_preview':False,'mime':'application/octet-stream','part':'x'}]
    with pytest.raises(StorageError):validate_manifest(manifest,identifier)
