"""Preload verified CPU models/plugins, then sandbox, READY, then user bytes."""
import os

# _run_child starts with env={}; set native thread limits before any native import.
for _key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
             'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'BLIS_NUM_THREADS'):
    os.environ[_key] = '1'
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.adapters.ocr_parser import parse_ocr
from app.adapters.ocr_runtime import get_runtime
from app.adapters.excel_sandbox import enter_sandbox
from app.core.exceptions import StorageError
from app.domain.documents.ocr_contracts import PROCESS_SETTINGS, OcrSettings


def emit(value):
    sys.stdout.buffer.write(json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8'))
    sys.stdout.buffer.flush()


def main():
    try:
        import resource
        # Trusted preload must also fit the total OCR resource budget.
        for key, value in [(resource.RLIMIT_CPU, PROCESS_SETTINGS['cpu_seconds']),
                           (resource.RLIMIT_AS, PROCESS_SETTINGS['memory_bytes'])]:
            resource.setrlimit(key, (value, value))
        get_runtime()
        enter_sandbox(cpu_seconds=PROCESS_SETTINGS['cpu_seconds'], memory_bytes=PROCESS_SETTINGS['memory_bytes'],
                      parent_pid=int(sys.argv[1]))
    except MemoryError:
        emit({'error': {'code': 'parse_resource_limit'}}); return
    except Exception:
        emit({'error': {'code': 'parse_environment_unavailable'}}); return
    sys.stdout.buffer.write(b'READY\n'); sys.stdout.buffer.flush()
    try:
        raw = sys.stdin.buffer.read(4)
        if len(raw) != 4:
            raise ValueError()
        length = struct.unpack('!I', raw)[0]
        if not 0 < length <= 65536:
            raise ValueError()
        metadata = json.loads(sys.stdin.buffer.read(length))
        if type(metadata) is not dict or set(metadata) != {'filename', 'file_type', 'page_numbers', 'settings', 'size'}:
            raise ValueError()
        size = metadata['size']
        limits = OcrSettings.model_validate(metadata['settings']['ocr'])
        if type(size) is not int or not 0 < size <= limits.max_upload_bytes:
            raise ValueError()
        content = sys.stdin.buffer.read(size + 1)
        if len(content) != size:
            raise ValueError()
        result = parse_ocr(content, metadata['filename'], metadata['file_type'], metadata['page_numbers'], metadata['settings'])
        emit({'result': result.model_dump()})
    except StorageError as exc:
        emit({'error': {'code': exc.code}})
    except MemoryError:
        emit({'error': {'code': 'parse_resource_limit'}})
    except Exception:
        emit({'error': {'code': 'parse_process_failed'}})


if __name__ == '__main__':
    main()
