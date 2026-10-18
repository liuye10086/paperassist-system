"""Linux numerical child using the shared bounded READY pipe transport."""
import os
from pathlib import Path
import sys
from app.adapters.excel_process import _run_child
from app.core.exceptions import StorageError
from app.domain.regression.common import NumericError
from app.domain.fixed_statistics_contract import MAX_OUTPUT_BYTES

MEMORY_BYTES = 1024 ** 3
CPU_SECONDS = 30
SANDBOX_VERSION = 'fixed_statistics_linux_v1_as1073741824_cpu30_wall30'


def run_statistics_isolated(encoded, *, timeout_seconds):
    if sys.platform != 'linux':
        raise NumericError('numeric_environment_unavailable', '当前 Worker 不支持安全固定统计，请检查 Linux 隔离能力。')
    command = [sys.executable, '-I', '-B', str(Path(__file__).with_name('fixed_statistics_runner.py')), str(os.getpid())]
    try:
        message = _run_child(command, encoded, timeout_seconds=min(30., timeout_seconds), max_output_bytes=MAX_OUTPUT_BYTES)
    except StorageError as exc:
        # SIGKILL is ambiguous: never claim an OOM without evidence.
        code = {'parse_timeout': 'numeric_timeout', 'parse_resource_limit': 'numeric_process_terminated',
                'parse_output_invalid': 'numeric_output_invalid'}.get(exc.code, 'numeric_failure')
        raise NumericError(code, '固定统计达到超时。' if code == 'numeric_timeout' else '固定统计进程中断或输出无效，未发布结果。') from None
    except OSError:
        raise NumericError('numeric_failure', '固定统计子进程无法启动。') from None
    if message == {'error': {'code': 'parse_environment_unavailable'}}:
        raise NumericError('numeric_environment_unavailable', '当前 Worker 不支持安全固定统计，请检查 Linux 隔离能力。')
    return message
