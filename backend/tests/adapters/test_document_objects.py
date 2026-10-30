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

def test_reused_document_image_binding_and_actual_bytes_are_checked(tmp_path):
    from copy import deepcopy
    from tests.helpers.document_samples import document_bytes
    store=DocumentObjects(tmp_path);result=parse_docx(document_bytes(),'paper.docx',DOCX_SETTINGS)
    manifest=store.save(str(uuid4()),result)
    _,document=store.read(manifest);image=manifest['images'][0]
    assert store._image_from_document(manifest,image['id'],document)==store.image(manifest,image['id'])
    for change in ('kind','sha256','size_bytes','mime','duplicate'):
        changed=deepcopy(manifest)
        if change=='kind':changed['kind']='pdf_document'
        elif change=='duplicate':changed['images'].append(deepcopy(image))
        elif change=='sha256':changed['images'][0]['sha256']='a'*64
        elif change=='size_bytes':changed['images'][0]['size_bytes']+=1
        else:changed['images'][0]['mime']='image/jpeg'
        with pytest.raises(StorageError):store._image_from_document(changed,image['id'],document)
    with pytest.raises(StorageError) as missing:store._image_from_document(manifest,'missing',document)
    assert missing.value.status==404
    path=tmp_path/image['object_key'];path.write_bytes(b'bad')
    with pytest.raises(StorageError):store._image_from_document(manifest,image['id'],document)
    with pytest.raises(StorageError):store.image(manifest,image['id'])
    path.unlink()
    with pytest.raises(StorageError) as deleted:store._image_from_document(manifest,image['id'],document)
    assert deleted.value.status==410
