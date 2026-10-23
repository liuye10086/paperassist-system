"""School-template inspection through the existing secret-free Linux transport."""
import json
import os
from pathlib import Path
import struct
import sys

from app.adapters.excel_process import _run_child
from app.adapters.school_template_parser import PARSER_VERSION, MAX_RESULT_BYTES, RESULT_KEYS
from app.core.exceptions import StorageError


def inspect_school_template_isolated(content, filename):
    if sys.platform != 'linux':
        raise StorageError('parse_environment_unavailable', '学校模板解析需要现有Linux Worker。', 503)
    if not isinstance(content, bytes) or not content or len(content) > 10485760 or not isinstance(filename, str) or not 0 < len(filename) <= 255:
        raise StorageError('invalid_document', '模板为空或超过上传限制。', 422)
    header = json.dumps({'size': len(content), 'filename': filename}, ensure_ascii=False).encode()
    command = [sys.executable, '-I', '-B', str(Path(__file__).with_name('school_template_process_child.py')), str(os.getpid())]
    result = _run_child(command, struct.pack('!I', len(header)) + header + content,
                        timeout_seconds=60, max_output_bytes=MAX_RESULT_BYTES)
    if isinstance(result, dict) and set(result) == {'error'}:
        code = result['error'].get('code') if isinstance(result['error'], dict) else None
        if code in ('invalid_document', 'document_too_large', 'parse_output_invalid', 'parse_resource_limit',
                    'parse_environment_unavailable', 'parse_process_failed', 'file_too_large', 'empty_file'):
            raise StorageError(code, '模板解析失败或达到资源限制，请核对原件。', 422)
    value = result.get('result') if isinstance(result, dict) and set(result) == {'result'} else None
    if not isinstance(value, dict) or set(value) != RESULT_KEYS or value.get('parser_version') != PARSER_VERSION:
        raise StorageError('parse_output_invalid', '模板解析结果格式无效。', 422)
    if not isinstance(value['defaults'], dict) or any(not isinstance(value[k], list) for k in RESULT_KEYS - {'defaults', 'parser_version'}):
        raise StorageError('parse_output_invalid', '模板解析结果不完整。', 422)
    return value
