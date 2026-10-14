import pytest
from tests.helpers.evidence_samples import evidence_pdf

@pytest.fixture(autouse=True)
def postgres_schema(): yield None

def test_pdf_v2_has_real_embedded_image_geometry_and_legacy_is_unchanged(tmp_path):
    from app.adapters.pdf_parser import parse_pdf
    from app.domain.documents.pdf_contracts import PDF_SETTINGS
    from app.adapters.document_objects import DocumentObjects
    from uuid import uuid4
    content=evidence_pdf()
    current=parse_pdf(content,'evidence.pdf',PDF_SETTINGS)
    assert current.document.parser_version=='pdfplumber-0.11.10-evidence-v2'
    assert current.document.counts.embedded_images==1
    image=current.document.pages[0].embedded_images[0]
    assert image.source.page_number==1 and image.source.bbox==[20.,40.,140.,100.]
    assert image.pixel_width==1 and image.pixel_height==1
    store=DocumentObjects(tmp_path)
    manifest=store.save(str(uuid4()),current)
    assert manifest['images']==[]
    assert store.read(manifest)[1]==current.document
    legacy=parse_pdf(content,'evidence.pdf',PDF_SETTINGS,parser_version='pdfplumber-0.11.10-text-v1')
    assert 'embedded_images' not in legacy.document.pages[0].model_dump()
    assert 'embedded_images' not in legacy.document.counts.model_dump()
    assert store.read(store.save(str(uuid4()),legacy))[1]==legacy.document

def test_image_only_pdf_does_not_generate_scientific_text():
    from app.adapters.pdf_parser import parse_pdf
    from app.domain.documents.pdf_contracts import PDF_SETTINGS
    doc=parse_pdf(evidence_pdf(image_only=True),'image.pdf',PDF_SETTINGS).document
    assert doc.pages[0].text_blocks==[] and doc.counts.embedded_images==1

@pytest.mark.parametrize('tamper',['count','page','bbox'])
def test_pdf_v2_rejects_inconsistent_image_source_contract(tamper):
    from app.adapters.pdf_parser import parse_pdf
    from app.domain.documents.pdf_contracts import PDF_SETTINGS,PdfParseResult
    from pydantic import ValidationError
    value=parse_pdf(evidence_pdf(),'source.pdf',PDF_SETTINGS).model_dump()
    if tamper=='count':value['document']['counts']['embedded_images']=0
    if tamper=='page':value['document']['pages'][0]['embedded_images'][0]['source']['page_number']=2
    if tamper=='bbox':value['document']['pages'][0]['embedded_images'][0]['source']['bbox']=[140.,40.,20.,100.]
    with pytest.raises(ValidationError):PdfParseResult.model_validate(value)

def test_pdf_v2_image_location_limit_is_global_and_never_truncates():
    from app.adapters.pdf_parser import parse_pdf
    from app.domain.documents.pdf_contracts import PDF_SETTINGS
    from app.core.exceptions import StorageError
    doc=parse_pdf(evidence_pdf(image_only=True,image_count=100),'hundred.pdf',PDF_SETTINGS).document
    assert doc.counts.embedded_images==100
    with pytest.raises(StorageError) as error:parse_pdf(evidence_pdf(image_only=True,image_count=101),'overflow.pdf',PDF_SETTINGS)
    assert error.value.code=='document_too_large'
