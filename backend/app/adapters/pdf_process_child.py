"""Preload PDF dependencies and bundled CMaps before receiving user bytes."""
import codecs
import json
import os
from pathlib import Path
import struct
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from app.adapters.pdf_parser import parse_pdf
from app.adapters.excel_sandbox import enter_sandbox
from app.core.exceptions import StorageError
from app.domain.documents.pdf_contracts import PdfSettings

def preload():
    import pdfminer.cmapdb
    from pdfminer.cmapdb import CMapDB
    # CMaps are finite package resources, not names derived from document input.
    for path in sorted(Path(pdfminer.cmapdb.__file__).with_name('cmap').glob('*.json.gz')):
        name=path.name[:-8]
        if name.startswith('to-unicode-'):
            CMapDB.get_unicode_map(name[len('to-unicode-'):])
        else:CMapDB.get_cmap(name)
    for encoding in ('utf-8','utf-16','utf-16-be','utf-16-le','latin-1','cp1252','ascii'):
        codecs.lookup(encoding)
    # Force lazy cryptography/Rust providers and algorithms to load before isolation.
    from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
    Cipher(algorithms.AES(b'0'*16),modes.CBC(b'0'*16)).decryptor().update(b'0'*16)
    from cryptography.hazmat.decrepit.ciphers.algorithms import ARC4
    Cipher(ARC4(b'0'*16),mode=None).decryptor().update(b'0'*16)

def emit(value):
    sys.stdout.buffer.write(json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8'));sys.stdout.buffer.flush()

def main():
    try:
        preload()
        enter_sandbox(cpu_seconds=30,memory_bytes=536870912,parent_pid=int(sys.argv[1]))
    except Exception:emit({'error':{'code':'parse_environment_unavailable'}});return
    sys.stdout.buffer.write(b'READY\n');sys.stdout.buffer.flush()
    try:
        raw=sys.stdin.buffer.read(4)
        if len(raw)!=4:raise ValueError()
        length=struct.unpack('!I',raw)[0]
        if not 0<length<=65536:raise ValueError()
        metadata=json.loads(sys.stdin.buffer.read(length));size=metadata['size'];limits=PdfSettings.model_validate(metadata['settings']['pdf'])
        if type(size) is not int or not 0<size<=limits.max_upload_bytes:raise ValueError()
        content=sys.stdin.buffer.read(size+1)
        if len(content)!=size:raise ValueError()
        emit({'result':parse_pdf(content,metadata['filename'],metadata['settings'],parser_version=metadata['parser_version']).model_dump()})
    except StorageError as exc:emit({'error':{'code':exc.code}})
    except MemoryError:emit({'error':{'code':'parse_resource_limit'}})
    except Exception:emit({'error':{'code':'parse_process_failed'}})
if __name__=='__main__':main()
