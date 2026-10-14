"""Bounded pipe transport to a secret-free Linux Excel child process."""
import json
import os
from pathlib import Path
import selectors
import signal
import struct
import subprocess
import sys
import time

from app.adapters.excel import WorkbookPreview
from app.core.config import ExcelSettings
from app.core.exceptions import StorageError

PARSER_VERSION = 'openpyxl-3.1.5-preview-v1'
PROCESS_SETTINGS = {'timeout_seconds': 60, 'cpu_seconds': 30,
                    'memory_bytes': 536870912, 'max_output_bytes': 4194304}
_MESSAGES = {
    'parse_timeout': 'Excel 解析超时，请重试或缩小工作簿。',
    'parse_resource_limit': 'Excel 解析达到资源限制，请重试或缩小工作簿。',
    'parse_process_failed': 'Excel 解析进程中断，请重试。',
    'parse_environment_unavailable': '当前 Worker 不支持安全 Excel 解析，请检查 Linux 隔离能力。',
    'parse_output_invalid': 'Excel 解析输出超过限制或格式无效，请缩小工作簿后重试。',
    'invalid_workbook': '文件不是有效的无宏 .xlsx 工作簿，可能损坏或加密，请另存为 .xlsx。',
    'workbook_too_large': '工作簿超过解析规模限制，请拆分文件后重试。',
    'parse_failed': 'Excel 解析失败，请用 Excel 打开并另存为 .xlsx 后重试。',
    'file_too_large': '上传文件超过大小限制，请缩小文件后重试。',
    'empty_file': '上传的文件为空，请选择包含内容的 .xlsx 文件。',
}


def _error(code):
    return StorageError(code, _MESSAGES[code])


def _terminate(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def _run_child(command, payload, *, timeout_seconds, max_output_bytes, on_started=None):
    """Internal transport also exercised with trusted synthetic fault children."""
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, env={}, cwd='/', close_fds=True,
                               start_new_session=True, bufsize=0)
    output = bytearray()
    position = 0
    ready = False
    deadline = time.monotonic() + timeout_seconds
    try:
        if on_started is not None:
            on_started(process.pid)
        with selectors.DefaultSelector() as selector:
            os.set_blocking(process.stdout.fileno(), False)
            os.set_blocking(process.stdin.fileno(), False)
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _error('parse_timeout')
                for key, events in selector.select(min(remaining, 0.1)):
                    if key.fileobj is process.stdout:
                        data = os.read(process.stdout.fileno(), min(65536, max_output_bytes + 7 - len(output)))
                        if not data:
                            selector.unregister(process.stdout)
                            if not process.stdin.closed:
                                if process.stdin in [key.fileobj for key in selector.get_map().values()]:
                                    selector.unregister(process.stdin)
                                process.stdin.close()
                            continue
                        output.extend(data)
                        if not ready and output.startswith(b'READY\n'):
                            del output[:6]
                            ready = True
                            selector.register(process.stdin, selectors.EVENT_WRITE)
                        if len(output) > max_output_bytes:
                            raise _error('parse_output_invalid')
                    else:
                        try:
                            position += os.write(process.stdin.fileno(), payload[position:position + 65536])
                        except BrokenPipeError:
                            selector.unregister(process.stdin)
                            process.stdin.close()
                            continue
                        if position == len(payload):
                            selector.unregister(process.stdin)
                            process.stdin.close()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _error('parse_timeout')
            try:
                returncode = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                raise _error('parse_timeout') from None
        if returncode:
            raise _error('parse_resource_limit' if returncode in (-signal.SIGXCPU, -signal.SIGKILL) else 'parse_process_failed')
        try:
            value = json.loads(output, object_pairs_hook=_strict_object,
                               parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (ValueError, UnicodeError):
            raise _error('parse_output_invalid') from None
        if not ready and value not in (
                {'error': {'code': 'parse_environment_unavailable'}},
                {'error': {'code': 'parse_resource_limit'}}):
            raise _error('parse_output_invalid')
        return value
    finally:
        _terminate(process)
        process.stdout.close()
        if not process.stdin.closed:
            process.stdin.close()


def parse_excel_isolated(content: bytes, filename: str, settings: dict, *, on_started=None) -> WorkbookPreview:
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
    command = [sys.executable, '-I', '-B', str(Path(__file__).with_name('excel_process_child.py')), str(os.getpid())]
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
    if set(result) == {'preview'}:
        try:
            preview = WorkbookPreview.model_validate(result['preview'])
            if preview.filename != filename or preview.model_dump() != result['preview']:
                raise ValueError()
            return preview
        except Exception:
            pass
    raise _error('parse_output_invalid')
