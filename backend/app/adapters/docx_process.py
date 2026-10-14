"""Word-only bounded process transport, sharing the existing Linux sandbox."""
import json
import os
from pathlib import Path
import struct
import sys
from app.adapters.excel_process import _run_child
from app.adapters.document_objects import validate_result
from app.core.exceptions import StorageError
from app.domain.documents.contracts import *

def parse_docx_isolated(content,filename,settings,*,on_started=None):
    if sys.platform!='linux':raise StorageError('parse_environment_unavailable','当前 Worker 不支持安全 Word 解析。')
    try:
        if type(settings) is not dict or set(settings)!={'docx','process'} or settings['process']!=PROCESS_SETTINGS:raise ValueError()
        limits=DocxSettings.model_validate(settings['docx'])
        if set(settings['docx'])!=set(DocxSettings.model_fields) or type(content) is not bytes or type(filename) is not str or not 0<len(filename)<=1024:raise ValueError()
    except Exception:raise StorageError('parse_environment_unavailable','Word 解析设置无效。') from None
    if not content:raise StorageError('empty_file','上传的文件为空。',422)
    if len(content)>limits.max_upload_bytes:raise StorageError('file_too_large','上传文件超过大小限制。',422)
    header=json.dumps(dict(filename=filename,settings=settings,size=len(content)),ensure_ascii=False).encode()
    payload=struct.pack('!I',len(header))+header+content
    try:value=_run_child([sys.executable,'-I','-B',str(Path(__file__).with_name('docx_process_child.py')),str(os.getpid())],payload,timeout_seconds=60,max_output_bytes=33554432,on_started=on_started)
    except StorageError as exc:raise StorageError(exc.code,'Word 解析进程失败或达到资源限制。') from exc
    except OSError as exc:raise StorageError('parse_process_failed','Word 解析进程启动失败。') from exc
    codes={'invalid_document','document_too_large','file_too_large','empty_file','parse_environment_unavailable','parse_resource_limit','parse_process_failed'}
    if type(value) is dict and set(value)=={'error'} and type(value['error']) is dict and set(value['error'])=={'code'} and value['error']['code'] in codes:
        raise StorageError(value['error']['code'],'Word 解析失败，请检查文档格式和大小。')
    try:
        if type(value) is not dict or set(value)!={'result'}:raise ValueError()
        result,_=validate_result(value['result'])
        if result.document.filename!=filename or result.document.parser_version!=PARSER_VERSION or result.model_dump()!=value['result']:raise ValueError()
        return result
    except Exception:raise StorageError('parse_output_invalid','Word 解析输出无效。') from None
