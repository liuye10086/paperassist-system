from copy import deepcopy
from io import BytesIO

import pytest
from PIL import Image

from app.core.exceptions import StorageError
from app.domain.documents.ocr_contracts import OCR_SETTINGS


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def image_bytes(fmt='PNG', size=(240, 160), exif=None):
    output = BytesIO()
    Image.new('RGB', size, 'white').save(output, format=fmt, **({'exif': exif} if exif else {}))
    return output.getvalue()


@pytest.mark.parametrize('pages', [[], [0], [1, 1], [True], list(range(1, 12)), [2]])
def test_invalid_image_page_selection(pages):
    from app.adapters.ocr_parser import parse_ocr
    with pytest.raises(StorageError) as error:
        parse_ocr(image_bytes(), 'x.png', 'png', pages, deepcopy(OCR_SETTINGS))
    assert error.value.code == 'invalid_document'


@pytest.mark.parametrize('field', ['threads', 'sha256'])
def test_frozen_models_cannot_change(field):
    from app.adapters.ocr_parser import validate_inputs
    settings = deepcopy(OCR_SETTINGS)
    settings['models'][field] = 2 if field == 'threads' else {}
    with pytest.raises(StorageError) as error:
        validate_inputs(image_bytes(), 'x.png', 'png', [1], settings)
    assert error.value.code == 'parse_environment_unavailable'


def test_blank_image_is_valid_empty_result():
    from app.adapters.ocr_parser import parse_ocr
    result = parse_ocr(image_bytes(), 'blank.png', 'png', [1], deepcopy(OCR_SETTINGS))
    assert result.document.pages[0].text_status == 'no_text'
    assert result.document.counts.text_blocks == 0
    assert result.document.images[0].mime == 'image/jpeg'
    assert set(result.image_payloads) == {result.document.pages[0].preview_image_id}


def test_image_pixel_limit_before_ocr():
    from app.adapters.ocr_parser import parse_ocr
    settings = deepcopy(OCR_SETTINGS)
    settings['ocr']['max_image_pixels'] = 100
    with pytest.raises(StorageError) as error:
        parse_ocr(image_bytes(), 'x.png', 'png', [1], settings)
    assert error.value.code == 'document_too_large'


def test_static_format_and_bytes_must_match():
    from app.adapters.ocr_parser import parse_ocr
    with pytest.raises(StorageError) as error:
        parse_ocr(image_bytes('JPEG'), 'x.png', 'png', [1], deepcopy(OCR_SETTINGS))
    assert error.value.code == 'invalid_document'


def test_exif_orientation_and_original_transform():
    from app.adapters.ocr_parser import parse_ocr
    exif = Image.Exif(); exif[274] = 6
    result = parse_ocr(image_bytes('JPEG', (240, 160), exif), 'x.jpeg', 'jpeg', [1], deepcopy(OCR_SETTINGS))
    page = result.document.pages[0]
    assert (page.width, page.height, page.rotation) == (160, 240, 90)
    assert page.pixel_to_source == [0., 1., 0., -1., 0., 160.]
    assert page.source_width == 240.


def test_json_and_preview_limits_are_enforced():
    from app.adapters.ocr_parser import parse_ocr
    for field in ('max_json_bytes', 'max_image_bytes'):
        settings = deepcopy(OCR_SETTINGS)
        settings['ocr'][field] = 1
        with pytest.raises(StorageError) as error:
            parse_ocr(image_bytes(), 'x.png', 'png', [1], settings)
        assert error.value.code == 'document_too_large'


def test_real_model_recognizes_known_synthetic_text():
    from pathlib import Path
    from app.adapters.ocr_parser import parse_ocr
    result = parse_ocr((Path(__file__).parents[1] / 'fixtures/ocr/printed-zh-en.png').read_bytes(),
                       'printed-zh-en.png', 'png', [1], deepcopy(OCR_SETTINGS))
    text = '\n'.join(block.text for block in result.document.pages[0].text_blocks)
    assert '12.50%' in text and '1.20 mg/L' in text and '研究' in text
    assert all(block.review_status == 'unreviewed' for block in result.document.pages[0].text_blocks)


def test_pdf_selection_preserves_physical_page_and_mapping():
    from pathlib import Path
    from app.adapters.ocr_parser import parse_ocr
    result = parse_ocr((Path(__file__).parents[1] / 'fixtures/ocr/mixed-three-pages.pdf').read_bytes(),
                       'mixed.pdf', 'pdf', [3, 2], deepcopy(OCR_SETTINGS))
    assert result.document.source_pages == 3
    assert result.document.selected_pages == [2, 3]
    assert [page.page_number for page in result.document.pages] == [2, 3]
    assert result.document.pages[1].text_status == 'no_text'
    block = result.document.pages[0].text_blocks[0]
    page = result.document.pages[0]
    a, b, c, d, e, f = page.pixel_to_source
    x, y = block.polygon[0]
    assert block.source.polygon[0] == [a*x+b*y+c, d*x+e*y+f]


def test_nonfinite_native_box_is_failure_not_valid_ocr():
    from types import SimpleNamespace
    from app.adapters.ocr_parser import _recognize_page
    from app.domain.documents.ocr_contracts import OcrSettings
    result = SimpleNamespace(txts=['text'], scores=[0.9],
                             boxes=[[[float('nan'), 0.], [20., 0.], [20., 10.], [0., 10.]]])
    image = Image.new('RGB', (240, 160), 'white')
    metadata = dict(rotation=0, source_width=240., source_height=160.,
                    source_coordinate_system='image_pixels_top_left', pixel_to_source=[1., 0., 0., 0., 1., 0.], transforms=[])
    with pytest.raises(StorageError) as error:
        _recognize_page(image, 1, metadata, lambda _: result, OcrSettings())
    assert error.value.code == 'parse_process_failed'


def test_low_score_is_preserved_as_unreviewed_with_hint():
    from types import SimpleNamespace
    from app.adapters.ocr_parser import _recognize_page
    from app.domain.documents.ocr_contracts import OcrSettings
    result = SimpleNamespace(txts=['blurred'], scores=[0.45], boxes=[[[0., 0.], [20., 0.], [20., 10.], [0., 10.]]])
    image = Image.new('RGB', (240, 160), 'white')
    metadata = dict(rotation=0, source_width=240., source_height=160.,
                    source_coordinate_system='image_pixels_top_left', pixel_to_source=[1., 0., 0., 0., 1., 0.], transforms=[])
    page, _, _ = _recognize_page(image, 1, metadata, lambda _: result, OcrSettings())
    assert page.text_blocks[0].score == 0.45
    assert page.text_blocks[0].review_status == 'unreviewed'
    assert page.warnings[0].code == 'low_confidence'


def test_animated_png_is_rejected():
    from app.adapters.ocr_parser import parse_ocr
    out = BytesIO()
    Image.new('RGB', (20, 20), 'white').save(out, format='PNG', save_all=True,
        append_images=[Image.new('RGB', (20, 20), 'black')], duration=100, loop=0)
    with pytest.raises(StorageError) as error:
        parse_ocr(out.getvalue(), 'animation.png', 'png', [1], deepcopy(OCR_SETTINGS))
    assert error.value.code == 'invalid_document'


def test_pdf_original_page_and_render_limits_before_ocr():
    import pypdfium2 as pdfium
    from app.adapters.ocr_parser import parse_ocr
    pdf = pdfium.PdfDocument.new()
    page = pdf.new_page(100, 100); page.close()
    out = BytesIO(); pdf.save(out); pdf.close()
    settings = deepcopy(OCR_SETTINGS); settings['ocr']['max_render_pixels'] = 100
    with pytest.raises(StorageError) as error:
        parse_ocr(out.getvalue(), 'x.pdf', 'pdf', [1], settings)
    assert error.value.code == 'document_too_large'
    with pytest.raises(StorageError) as error:
        parse_ocr(out.getvalue(), 'x.pdf', 'pdf', [2], deepcopy(OCR_SETTINGS))
    assert error.value.code == 'invalid_document'


@pytest.mark.parametrize('content,code', [(b'', 'empty_file'), (b'not pdf', 'invalid_document')])
def test_invalid_original_does_not_return_empty_result(content, code):
    from app.adapters.ocr_parser import parse_ocr
    with pytest.raises(StorageError) as error:
        parse_ocr(content, 'x.pdf', 'pdf', [1], deepcopy(OCR_SETTINGS))
    assert error.value.code == code
