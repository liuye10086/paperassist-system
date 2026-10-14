"""Structure protocol over the existing bounded, secret-free Linux transport."""
import json
import os
from pathlib import Path
import struct
import sys
from app.adapters.excel_process import PROCESS_SETTINGS, _MESSAGES, _error, _run_child
from app.core.config import ExcelSettings
from app.domain.datasets.contracts import ExcelStructure, STRUCTURE_PARSER_VERSION

PARSER_VERSION = STRUCTURE_PARSER_VERSION

def parse_excel_structure_isolated(content: bytes, filename: str, settings: dict, *, on_started=None) -> ExcelStructure:
    if sys.platform != 'linux':
        raise _error('parse_environment_unavailable')
    try:
        if (type(settings) is not dict or set(settings) != {'excel', 'process'}
                or settings['process'] != PROCESS_SETTINGS or type(settings['excel']) is not dict
                or any(type(value) is not int for value in settings['process'].values())
                or set(settings['excel']) != set(ExcelSettings.model_fields)):
            raise ValueError()
        excel = ExcelSettings.model_validate(settings['excel'])
        defaults = ExcelSettings()
        if any(type(settings['excel'][key]) is not int or settings['excel'][key] > getattr(defaults, key)
               for key in ExcelSettings.model_fields):
            raise ValueError()
        if type(content) is not bytes or type(filename) is not str or not filename or len(filename) > 1024:
            raise ValueError()
    except Exception:
        raise _error('parse_environment_unavailable') from None
    if not content:
        raise _error('empty_file')
    if len(content) > excel.max_upload_bytes:
        raise _error('file_too_large')
    header = json.dumps({'filename': filename, 'excel': excel.model_dump(), 'size': len(content)},
                        ensure_ascii=False, allow_nan=False).encode('utf-8')
    payload = struct.pack('!I', len(header)) + header + content
    command = [sys.executable, '-I', '-B', str(Path(__file__).with_name('excel_structure_child.py')), str(os.getpid())]
    try:
        result = _run_child(command, payload, timeout_seconds=60, max_output_bytes=4194304, on_started=on_started)
    except OSError:
        raise _error('parse_process_failed') from None
    if type(result) is not dict:
        raise _error('parse_output_invalid')
    if set(result) == {'error'} and type(result['error']) is dict and set(result['error']) == {'code'}:
        code = result['error']['code']
        if type(code) is str and code in _MESSAGES:
            raise _error(code)
    if set(result) == {'structure'}:
        try:
            preview = ExcelStructure.model_validate(result['structure'])
            if preview.filename != filename or preview.model_dump() != result['structure']:
                raise ValueError()
            if (len(preview.sheets) > excel.max_sheets
                    or sum(s.row_count*s.column_count for s in preview.sheets) > excel.max_cells
                    or any(s.row_count > excel.max_rows or s.column_count > excel.max_columns for s in preview.sheets)):
                raise ValueError()
            return preview
        except Exception:
            pass
    raise _error('parse_output_invalid')
