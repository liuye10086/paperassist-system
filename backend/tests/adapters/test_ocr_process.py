from copy import deepcopy
import sys

import pytest

from app.core.exceptions import StorageError
from app.domain.documents.ocr_contracts import OCR_SETTINGS


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def test_windows_fails_closed():
    from app.adapters.ocr_process import parse_ocr_isolated
    if sys.platform == 'linux':
        pytest.skip('Windows-only check')
    with pytest.raises(StorageError) as error:
        parse_ocr_isolated(b'x', 'x.png', 'png', [1], deepcopy(OCR_SETTINGS))
    assert error.value.code == 'parse_environment_unavailable'


@pytest.mark.parametrize('reply,code', [
    ({'error': {'code': 'parse_resource_limit'}}, 'parse_resource_limit'),
    ({'error': {'code': 'parse_process_failed'}}, 'parse_process_failed'),
    ({'error': {'code': 'parse_environment_unavailable'}}, 'parse_environment_unavailable'),
    ({'error': {'code': 'unknown'}}, 'parse_output_invalid'),
    ({'result': {}}, 'parse_output_invalid'),
])
def test_strict_error_protocol_and_ocr_budget(monkeypatch, reply, code):
    from app.adapters import ocr_process as process
    monkeypatch.setattr(process.sys, 'platform', 'linux')
    calls = []
    callback = lambda _: None
    def run(command, payload, **kwargs):
        calls.append(kwargs)
        return reply
    monkeypatch.setattr(process, '_run_child', run)
    with pytest.raises(StorageError) as error:
        process.parse_ocr_isolated(b'x', 'x.png', 'png', [1], deepcopy(OCR_SETTINGS), on_started=callback)
    assert error.value.code == code
    assert calls[0]['timeout_seconds'] == 180
    assert calls[0]['max_output_bytes'] == 33554432
    assert calls[0]['on_started'] is callback


@pytest.fixture(scope='module')
def valid_result():
    from pathlib import Path
    from app.adapters.ocr_parser import parse_ocr
    source = Path(__file__).parents[1] / 'fixtures/ocr/printed-zh-en.png'
    return parse_ocr(source.read_bytes(), 'x.png', 'png', [1], deepcopy(OCR_SETTINGS)).model_dump()


@pytest.mark.parametrize('mutation', ['filename', 'selected_pages', 'counts', 'source_page', 'affine', 'hash', 'payload', 'extra', 'boolean_rotation', 'boolean_schema'])
def test_rejects_forged_child_output(monkeypatch, valid_result, mutation):
    from app.adapters import ocr_process as process
    value = deepcopy(valid_result)
    document = value['document']
    if mutation == 'filename': document['filename'] = 'other.png'
    elif mutation == 'selected_pages': document['selected_pages'] = [2]
    elif mutation == 'counts': document['counts']['text_blocks'] = 0
    elif mutation == 'source_page': document['pages'][0]['text_blocks'][0]['source']['page_number'] = 2
    elif mutation == 'affine': document['pages'][0]['pixel_to_source'] = [0.] * 6
    elif mutation == 'hash': document['images'][0]['sha256'] = '0' * 64
    elif mutation == 'payload': value['image_payloads'][document['images'][0]['id']] = 'not base64!'
    elif mutation == 'extra': document['internal'] = 'unexpected'
    elif mutation == 'boolean_rotation': document['pages'][0]['rotation'] = False
    elif mutation == 'boolean_schema': document['schema_version'] = True
    monkeypatch.setattr(process.sys, 'platform', 'linux')
    monkeypatch.setattr(process, '_run_child', lambda *args, **kwargs: {'result': value})
    with pytest.raises(StorageError) as error:
        process.parse_ocr_isolated(b'x', 'x.png', 'png', [1], deepcopy(OCR_SETTINGS))
    assert error.value.code == 'parse_output_invalid'


def test_accepts_complete_valid_child_result(monkeypatch, valid_result):
    from app.adapters import ocr_process as process
    monkeypatch.setattr(process.sys, 'platform', 'linux')
    monkeypatch.setattr(process, '_run_child', lambda *args, **kwargs: {'result': deepcopy(valid_result)})
    result = process.parse_ocr_isolated(b'x', 'x.png', 'png', [1], deepcopy(OCR_SETTINGS))
    assert result.model_dump() == valid_result


@pytest.mark.skipif(sys.platform != 'linux', reason='Requires real Linux Landlock/seccomp sandbox')
@pytest.mark.parametrize('kind', ['png', 'jpeg', 'pdf'])
def test_real_linux_sandbox_recognizes_three_formats(kind):
    from io import BytesIO
    from pathlib import Path
    from PIL import Image
    from app.adapters.ocr_process import parse_ocr_isolated
    directory = Path(__file__).parents[1] / 'fixtures/ocr'
    pages = [1]
    if kind == 'pdf':
        content = (directory / 'mixed-three-pages.pdf').read_bytes()
        pages = [2, 3]
    elif kind == 'jpeg':
        with Image.open(directory / 'printed-zh-en.png') as image:
            rotated = image.transpose(Image.Transpose.ROTATE_90)
            exif = Image.Exif(); exif[274] = 6
            output = BytesIO(); rotated.save(output, format='JPEG', quality=90, exif=exif)
            content = output.getvalue()
    else:
        content = (directory / 'printed-zh-en.png').read_bytes()
    result = parse_ocr_isolated(content, 'fixture.' + kind, kind, pages, deepcopy(OCR_SETTINGS))
    text = '\n'.join(block.text for block in result.document.pages[0].text_blocks)
    assert '1.20 mg/L' in text and '12.50%' in text and '0012' in text
    assert result.document.selected_pages == pages
    if kind == 'pdf':
        assert result.document.pages[1].text_status == 'no_text'
    if kind == 'jpeg':
        assert result.document.pages[0].rotation == 90
