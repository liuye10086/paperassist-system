"""PDF transport sharing the existing bounded Linux child runner."""
import json
import os
from pathlib import Path
import struct
import sys
from app.adapters.excel_process import _run_child
from app.adapters.pdf_parser import validate_inputs
from app.core.exceptions import StorageError
from app.domain.documents.pdf_contracts import PARSER_VERSION, PdfParseResult

def parse_pdf_isolated(content,filename,settings,*,on_started=None,parser_version=PARSER_VERSION):
    if sys.platform!='linux':raise StorageError('parse_environment_unavailable','当前Worker不支持安全PDF解析。')
    limits=validate_inputs(content,filename,settings)
    header=json.dumps(dict(filename=filename,settings=settings,size=len(content),parser_version=parser_version),ensure_ascii=False,allow_nan=False).encode('utf-8')
    payload=struct.pack('!I',len(header))+header+content
    try:
        value=_run_child([sys.executable,'-I','-B',str(Path(__file__).with_name('pdf_process_child.py')),str(os.getpid())],payload,timeout_seconds=60,max_output_bytes=8388608,on_started=on_started)
    except StorageError as exc:raise StorageError(exc.code,'PDF解析进程失败或达到资源限制。') from exc
    except OSError as exc:raise StorageError('parse_process_failed','PDF解析进程启动失败。') from exc
    codes={'invalid_document','encrypted_document','document_too_large','file_too_large','empty_file','parse_environment_unavailable','parse_resource_limit','parse_process_failed'}
    if type(value) is dict and set(value)=={'error'} and type(value['error']) is dict and set(value['error'])=={'code'} and type(value['error']['code']) is str and value['error']['code'] in codes:
        raise StorageError(value['error']['code'],'PDF解析失败，请核对格式和大小。')
    try:
        if type(value) is not dict or set(value)!={'result'}:raise ValueError()
        result=PdfParseResult.model_validate(value['result'])
        if result.document.filename!=filename or result.document.parser_version!=parser_version or result.model_dump()!=value['result']:raise ValueError()
        if len(result.document.model_dump_json().encode('utf-8'))>limits.max_json_bytes:raise ValueError()
        return result
    except Exception:raise StorageError('parse_output_invalid','PDF解析输出无效。') from None
