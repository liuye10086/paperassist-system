"""Bounded OCR transport using the existing secret-free Linux child runner."""
import base64
import hashlib
import json
import os
from pathlib import Path
import struct
import sys

from app.adapters.excel_process import _run_child
from app.adapters.ocr_parser import validate_inputs
from app.adapters.ocr_result_validation import validate_ocr_document
from app.core.exceptions import StorageError
from app.domain.documents.ocr_contracts import OcrParseResult, PARSER_VERSION, PROCESS_SETTINGS

ERROR_CODES = {'invalid_document', 'encrypted_document', 'document_too_large', 'file_too_large', 'empty_file',
               'parse_environment_unavailable', 'parse_resource_limit', 'parse_process_failed', 'parse_output_invalid', 'parse_timeout'}


def _validate_result(value, filename, file_type, page_numbers, limits):
    if type(value) is not dict or set(value) != {'result'}:
        raise ValueError()
    result = OcrParseResult.model_validate(value['result'])
    document = result.document
    if (result.model_dump() != value['result'] or document.filename != filename or document.parser_version != PARSER_VERSION
            or document.source_type != file_type or document.selected_pages != sorted(page_numbers)
            or [p.page_number for p in document.pages] != sorted(page_numbers)
            or document.source_pages < max(page_numbers) or document.source_pages > limits.max_pages
            or (file_type != 'pdf' and document.source_pages != 1)
            or len(document.model_dump_json().encode('utf-8')) > limits.max_json_bytes):
        raise ValueError()
    validate_ocr_document(document)
    if document.counts.text_blocks > limits.max_text_blocks:
        raise ValueError()
    image_ids = [image.id for image in document.images]
    if set(image_ids) != set(result.image_payloads):
        raise ValueError()
    total = 0
    for image in document.images:
        binary = base64.b64decode(result.image_payloads[image.id], validate=True)
        if (len(binary) != image.size_bytes or hashlib.sha256(binary).hexdigest() != image.sha256
                or image.mime != 'image/jpeg' or not image.inline_preview or not binary.startswith(b'\xff\xd8')):
            raise ValueError()
        total += len(binary)
    if total > limits.max_image_bytes:
        raise ValueError()
    for page in document.pages:
        if page.width*page.height > (limits.max_render_pixels if file_type == 'pdf' else limits.max_image_pixels):
            raise ValueError()
    return result


def parse_ocr_isolated(content, filename, file_type, page_numbers, settings, *, on_started=None) -> OcrParseResult:
    if sys.platform != 'linux':
        raise StorageError('parse_environment_unavailable', '当前Worker不支持安全OCR识别。')
    limits = validate_inputs(content, filename, file_type, page_numbers, settings)
    header = json.dumps(dict(filename=filename, file_type=file_type, page_numbers=page_numbers,
                             settings=settings, size=len(content)), ensure_ascii=False, allow_nan=False).encode('utf-8')
    payload = struct.pack('!I', len(header)) + header + content
    try:
        value = _run_child([sys.executable, '-I', '-B', str(Path(__file__).with_name('ocr_process_child.py')), str(os.getpid())],
                           payload, timeout_seconds=PROCESS_SETTINGS['timeout_seconds'],
                           max_output_bytes=PROCESS_SETTINGS['max_output_bytes'], on_started=on_started)
    except StorageError as exc:
        raise StorageError(exc.code, 'OCR识别进程失败或达到资源限制。') from exc
    except OSError as exc:
        raise StorageError('parse_process_failed', 'OCR识别进程启动失败。') from exc
    if (type(value) is dict and set(value) == {'error'} and type(value['error']) is dict
            and set(value['error']) == {'code'} and type(value['error']['code']) is str and value['error']['code'] in ERROR_CODES):
        raise StorageError(value['error']['code'], 'OCR识别失败，请核对文件与所选页。')
    try:
        return _validate_result(value, filename, file_type, page_numbers, limits)
    except Exception:
        raise StorageError('parse_output_invalid', 'OCR识别输出无效。') from None
