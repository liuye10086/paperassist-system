"""Preload dependencies before entering the fail-closed Linux sandbox."""
import codecs
import json
import os
from pathlib import Path
import struct
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from app.adapters.docx_parser import parse_docx
from app.adapters.excel_sandbox import enter_sandbox
from app.core.exceptions import StorageError
from app.domain.documents.contracts import DocxSettings
import lxml.etree
for encoding in ('cp437','utf-8','utf-16','utf-16-le','utf-16-be'):codecs.lookup(encoding)
def emit(value):
    sys.stdout.buffer.write(json.dumps(value,ensure_ascii=False,allow_nan=False).encode());sys.stdout.buffer.flush()
def main():
    try:enter_sandbox(cpu_seconds=30,memory_bytes=536870912,parent_pid=int(sys.argv[1]))
    except Exception:emit({'error':{'code':'parse_environment_unavailable'}});return
    sys.stdout.buffer.write(b'READY\n');sys.stdout.buffer.flush()
    try:
        raw=sys.stdin.buffer.read(4)
        if len(raw)!=4:raise ValueError()
        length=struct.unpack('!I',raw)[0]
        if not 0<length<=65536:raise ValueError()
        metadata=json.loads(sys.stdin.buffer.read(length));size=metadata['size'];limits=DocxSettings.model_validate(metadata['settings']['docx'])
        if type(size) is not int or not 0<size<=limits.max_upload_bytes:raise ValueError()
        content=sys.stdin.buffer.read(size+1)
        if len(content)!=size:raise ValueError()
        emit({'result':parse_docx(content,metadata['filename'],metadata['settings']).model_dump()})
    except StorageError as exc:emit({'error':{'code':exc.code}})
    except MemoryError:emit({'error':{'code':'parse_resource_limit'}})
    except Exception:emit({'error':{'code':'parse_process_failed'}})
if __name__=='__main__':main()
