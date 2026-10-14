import copy
import pytest
from app.core.exceptions import StorageError
from tests.helpers.pdf_samples import pdf_bytes, TEXT, TABLE

@pytest.fixture(autouse=True)
def postgres_schema():
    yield None

def parse(data, settings=None):
    from app.adapters.pdf_parser import parse_pdf
    from app.domain.documents.pdf_contracts import PDF_SETTINGS
    return parse_pdf(data,'sample.pdf',settings or PDF_SETTINGS).document

def test_text_regions_and_mixed_blank_pages():
    content=pdf_bytes([TEXT,b''])
    doc=parse(content)
    assert doc.pages[0].text_blocks[0].text=='001.20 kg'
    assert doc.pages[0].text_blocks[0].source.bbox[0]==20
    assert doc.pages[1].text_status=='no_extractable_text'
    assert doc.counts.pages_without_text==1
    assert content==pdf_bytes([TEXT,b''])

def test_bordered_table_and_empty_cells():
    table=parse(pdf_bytes([TABLE])).pages[0].tables[0]
    assert table.candidate and table.rows==2 and table.columns==2
    assert table.cells[0].text=='A'
    assert table.cells[1].text==''
    assert table.cells[1].bbox is not None

def test_rotation_and_geometry_order_candidate():
    page=parse(pdf_bytes([TEXT],rotation=90)).pages[0]
    assert page.rotation==90 and page.bbox==[0.,0.,400.,300.]
    assert any(w.code=='reading_order_candidate' for w in page.warnings)

@pytest.mark.parametrize('data,code',[(b'garbage','invalid_document'),(b'','empty_file'),(pdf_bytes([TEXT],encrypted=True),'encrypted_document'),(pdf_bytes([b'']*101),'document_too_large')])
def test_rejections(data,code):
    with pytest.raises(StorageError) as exc:parse(data)
    assert exc.value.code==code

def test_json_limit_fails_without_truncation():
    from app.domain.documents.pdf_contracts import PDF_SETTINGS
    settings=copy.deepcopy(PDF_SETTINGS);settings['pdf']['max_json_bytes']=50
    with pytest.raises(StorageError) as exc:parse(pdf_bytes([TEXT]),settings)
    assert exc.value.code=='document_too_large'

def test_chinese_cid_mapping():
    from tests.helpers.pdf_samples import chinese_pdf
    assert parse(chinese_pdf()).pages[0].text_blocks[0].text=='中文'

def test_columns_use_geometric_candidate_order():
    stream=b'BT /F1 12 Tf 180 350 Td (right) Tj ET BT /F1 12 Tf 20 350 Td (left) Tj ET BT /F1 12 Tf 20 320 Td (next) Tj ET'
    page=parse(pdf_bytes([stream])).pages[0]
    assert page.text_blocks[0].text=='left right'
    assert page.text_blocks[1].text=='next'

def test_merged_covered_cell_stays_null():
    stream=TABLE.replace(b'120 200 m 120 280 l S',b'120 200 m 120 240 l S')
    table=parse(pdf_bytes([stream])).pages[0].tables[0]
    assert table.cells[0].text=='A'
    assert table.cells[1].text is None and table.cells[1].bbox is None

def test_undecoded_characters_are_explicit():
    data=pdf_bytes([TEXT]).replace(b'/BaseFont /Helvetica',b'/BaseFont /UnknownFont').replace(b'(001.20 kg)',b'<81>')
    page=parse(data).pages[0]
    assert any(w.code=='undecoded_characters' for w in page.warnings)

def test_real_cid_tables_rotation_fixture():
    from pathlib import Path
    content=(Path(__file__).parents[1]/'fixtures/pdf/text-tables-cid.pdf').read_bytes()
    doc=parse(content)
    assert len(doc.pages)==3
    assert '合成研究资料' in '\n'.join(t.text for t in doc.pages[0].text_blocks)
    assert doc.pages[0].tables
    assert doc.pages[2].rotation==90

def test_real_image_and_blank_pages_fixture():
    from pathlib import Path
    content=(Path(__file__).parents[1]/'fixtures/pdf/mixed-image-blank.pdf').read_bytes()
    doc=parse(content)
    assert doc.pages[0].text_status=='text'
    assert [p.text_status for p in doc.pages[1:]]==['no_extractable_text']*2
    assert all('扫描' not in w.message for p in doc.pages[1:] for w in p.warnings)

def test_real_empty_password_encryption_rejected():
    from pathlib import Path
    content=(Path(__file__).parents[1]/'fixtures/pdf/encrypted.pdf').read_bytes()
    with pytest.raises(StorageError) as exc:parse(content)
    assert exc.value.code=='encrypted_document'
