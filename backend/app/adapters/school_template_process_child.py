"""Preload, enter the existing sandbox, then read untrusted template bytes."""
import codecs
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.adapters.school_template_parser import inspect_school_template
from app.adapters.excel_sandbox import enter_sandbox
from app.core.exceptions import StorageError

for encoding in ('cp437', 'utf-8', 'utf-16', 'utf-16-le', 'utf-16-be'):
    codecs.lookup(encoding)


def emit(value):
    sys.stdout.buffer.write(json.dumps(value, ensure_ascii=False, allow_nan=False).encode())
    sys.stdout.buffer.flush()


def main():
    try:
        enter_sandbox(cpu_seconds=30, memory_bytes=536870912, parent_pid=int(sys.argv[1]))
    except Exception:
        emit({'error': {'code': 'parse_environment_unavailable'}})
        return
    sys.stdout.buffer.write(b'READY\n'); sys.stdout.buffer.flush()
    try:
        raw = sys.stdin.buffer.read(4)
        if len(raw) != 4:
            raise ValueError()
        length = struct.unpack('!I', raw)[0]
        if not 0 < length <= 65536:
            raise ValueError()
        header = json.loads(sys.stdin.buffer.read(length))
        size = header['size']
        if type(size) is not int or not 0 < size <= 10485760:
            raise ValueError()
        content = sys.stdin.buffer.read(size + 1)
        if len(content) != size:
            raise ValueError()
        emit({'result': inspect_school_template(content, header['filename'])})
    except StorageError as exc:
        emit({'error': {'code': exc.code}})
    except MemoryError:
        emit({'error': {'code': 'parse_resource_limit'}})
    except Exception:
        emit({'error': {'code': 'parse_process_failed'}})


if __name__ == '__main__':
    main()
