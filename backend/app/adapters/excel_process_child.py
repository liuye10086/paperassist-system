"""Trusted bootstrap; the first untrusted byte is read only after sandbox entry."""
import os

# openpyxl imports NumPy when available in the OCR Worker. Constrain native
# pools before importing any dependency; the sandbox permits only one thread.
for _key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
             'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'BLIS_NUM_THREADS'):
    os.environ[_key] = '1'

import json
from pathlib import Path
import struct
import sys
import codecs

# -I ignores PYTHONPATH and user site packages; trust only this adapter's tree.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.adapters.excel import parse_workbook
from app.adapters.excel_sandbox import SandboxUnavailable, enter_sandbox
from app.core.config import ExcelSettings
from app.core.errors import error_detail  # preload lazy parse_workbook error dependency
from fastapi import HTTPException
import openpyxl

# ZIP's legacy filename codec is lazy; preload before all filesystem access ends.
for _encoding in ('cp437', 'utf-8', 'utf-8-sig', 'utf-16', 'utf-16-le', 'utf-16-be'):
    codecs.lookup(_encoding)


def emit(value):
    sys.stdout.buffer.write(json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8'))
    sys.stdout.buffer.flush()


def main():
    try:
        if openpyxl.__version__ != '3.1.5':
            raise SandboxUnavailable()
        enter_sandbox(cpu_seconds=30, memory_bytes=536870912, parent_pid=int(sys.argv[1]))
    except Exception:
        emit({'error': {'code': 'parse_environment_unavailable'}})
        return
    sys.stdout.buffer.write(b'READY\n')
    sys.stdout.buffer.flush()
    try:
        raw = sys.stdin.buffer.read(4)
        if len(raw) != 4:
            raise ValueError()
        length = struct.unpack('!I', raw)[0]
        if not 0 < length <= 65536:
            raise ValueError()
        metadata = json.loads(sys.stdin.buffer.read(length))
        settings = ExcelSettings.model_validate(metadata['excel'])
        size = metadata['size']
        if type(size) is not int or not 0 < size <= min(settings.max_upload_bytes, 10 * 1024 * 1024):
            raise ValueError()
        content = sys.stdin.buffer.read(size + 1)
        if len(content) != size:
            raise ValueError()
        preview = parse_workbook(content, metadata['filename'], settings)
        emit({'preview': preview.model_dump()})
    except HTTPException as exc:
        code = exc.detail.get('code') if isinstance(exc.detail, dict) else None
        emit({'error': {'code': code if code in {'invalid_workbook', 'workbook_too_large', 'parse_failed'} else 'parse_failed'}})
    except MemoryError:
        emit({'error': {'code': 'parse_resource_limit'}})
    except Exception:
        emit({'error': {'code': 'parse_process_failed'}})


if __name__ == '__main__':
    main()
