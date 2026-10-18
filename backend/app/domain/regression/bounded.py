"""Fixed kernels in a Linux sandbox with one shared business-node deadline."""
from collections import OrderedDict
from copy import deepcopy
import hashlib
import json
import math
import subprocess  # compatibility for callers asserting the old file runner is unused
import sys
import threading
import time

from app.domain.regression.common import NumericError, payload
from app.domain.fixed_statistics_contract import (CONTRACT_VERSION, EXECUTION_KINDS, ERROR_MESSAGES, PROJECTION_REASONS,
    validate_request, MAX_INPUT_BYTES as _MAX_INPUT_BYTES, MAX_OUTPUT_BYTES as _MAX_OUTPUT_BYTES)
from app.domain.fixed_statistics_runtime import remaining_seconds, record_execution
from app.domain.regression.runner import validate_method
from app.adapters.fixed_statistics_process import run_statistics_isolated, MEMORY_BYTES, SANDBOX_VERSION

_CACHE = OrderedDict()
_CACHE_BYTES = 0
_CACHE_LOCK = threading.RLock()
_MAX_CACHE_ITEMS = 8
_MAX_CACHE_BYTES = 16 * 1024 * 1024
_KERNEL_ID = CONTRACT_VERSION + ':' + SANDBOX_VERSION
_EXECUTION = threading.local()


def _finite_number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _compute_uncached(task_type, rows, selection, timeout_seconds=30):
    validate_request(task_type, rows, payload(selection))
    validate_method(task_type, payload(selection))
    if not _finite_number(timeout_seconds) or not 0 < timeout_seconds <= 30:
        raise NumericError('numeric_timeout_invalid', '固定统计超时配置无效。')
    try:
        encoded = json.dumps(dict(task_type=task_type, rows=rows, selection=payload(selection)),
            allow_nan=False, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    except (ValueError, TypeError) as exc:
        raise NumericError('numeric_invalid_input', 'Noncanonical statistics input.') from exc
    if len(encoded) > _MAX_INPUT_BYTES:
        raise NumericError('numeric_input_bytes_limit', '固定统计输入超过8 MiB。')
    message = run_statistics_isolated(encoded, timeout_seconds=timeout_seconds)
    if len(json.dumps(message, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')) > _MAX_OUTPUT_BYTES:
        raise NumericError('numeric_output_limit', '固定统计输出超过16 MiB。')
    if type(message) is not dict:
        raise NumericError('numeric_output_invalid', '固定统计输出无效。')
    measurement = message.pop('measurement', None)
    if (type(measurement) is not dict or set(measurement) != {'cpu_seconds', 'peak_rss_bytes'}
        or measurement['cpu_seconds'] is not None and (not _finite_number(measurement['cpu_seconds']) or measurement['cpu_seconds'] < 0)
        or measurement['peak_rss_bytes'] is not None and (type(measurement['peak_rss_bytes']) is not int or measurement['peak_rss_bytes'] <= 0)):
        raise NumericError('numeric_output_invalid', '固定统计进程测量记录无效。')
    _EXECUTION.measurement = measurement
    if message.get('status') == 'error' and set(message) == {'status', 'code', 'message', 'reason'} and message.get('code') == 'figure_projection_invalid':
        if type(message['reason']) is not str or message['reason'] not in PROJECTION_REASONS or type(message['message']) is not str:
            raise NumericError('numeric_output_invalid', '固定投影错误响应无效。')
        error = NumericError('figure_projection_invalid', ERROR_MESSAGES['figure_projection_invalid'])
        error.reason = message['reason']
        raise error
    if message.get('status') == 'error' and set(message) == {'status', 'code', 'message'}:
        code = message['code']
        if type(code) is not str or code not in ERROR_MESSAGES or type(message['message']) is not str:
            raise NumericError('numeric_output_invalid', '固定统计错误响应无效。')
        raise NumericError(code, ERROR_MESSAGES[code])
    if message.get('status') != 'ok' or set(message) != {'status', 'result'} or type(message['result']) is not dict:
        raise NumericError('numeric_output_invalid', '固定统计输出无效。')
    return message['result']


def last_execution_receipt():
    return deepcopy(getattr(_EXECUTION, 'receipt', None))


def _record(started, input_bytes, output_bytes, timeout_seconds, cache_hit, error_code=None):
    measurement = {} if cache_hit else getattr(_EXECUTION, 'measurement', {})
    receipt = dict(contract_version=CONTRACT_VERSION, sandbox_version=SANDBOX_VERSION,
        input_bytes=input_bytes, output_bytes=output_bytes, timeout_seconds=timeout_seconds,
        elapsed_seconds=time.monotonic()-started, cache_hit=cache_hit,
        stdout_policy='bounded_protocol', stderr_policy='discard', input_policy='frozen_projection',
        output_policy='bounded_pipe', memory_hard_limit=MEMORY_BYTES,
        isolation='linux_landlock_seccomp', cpu_hard_limit_seconds=30, cpu_affinity_count=1,
        child_cpu_seconds=measurement.get('cpu_seconds'), child_peak_rss_bytes=measurement.get('peak_rss_bytes'),
        error_code=error_code)
    _EXECUTION.receipt = receipt
    record_execution(receipt)


def clear_compute_cache():
    global _CACHE_BYTES
    with _CACHE_LOCK:
        _CACHE.clear()
        _CACHE_BYTES = 0


def compute_bounded(task_type, rows, selection, timeout_seconds=30, *, cache_identity=None):
    global _CACHE_BYTES
    started = time.monotonic()
    _EXECUTION.receipt = None
    _EXECUTION.measurement = {}
    if not _finite_number(timeout_seconds) or not 0 < timeout_seconds <= 30:
        raise NumericError('numeric_timeout_invalid', '固定统计超时配置无效。')
    # The absolute deadline includes validation, serialization, cache/lock waits,
    # child imports, computation and result copying; cache hits cannot bypass it.
    deadline = started + min(timeout_seconds, remaining_seconds())
    canonical = b''
    output_size = None
    cache_hit = False
    locked = False
    try:
        if deadline <= time.monotonic():
            raise NumericError('numeric_timeout', '固定统计节点超过硬超时。')
        if sys.platform != 'linux':
            raise NumericError('numeric_environment_unavailable', '当前 Worker 不支持安全固定统计，请检查 Linux 隔离能力。')
        if type(task_type) is not str or task_type not in EXECUTION_KINDS:
            raise NumericError('numeric_invalid_input', '未知统计类型。')
        selected = payload(selection)
        validate_request(task_type, rows, selected)
        validate_method(task_type, selected)
        try:
            canonical = json.dumps(dict(kernel=_KERNEL_ID, task_type=task_type, rows=rows,
                selection=selected, cache_identity=cache_identity), sort_keys=True,
                separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
        except (TypeError, ValueError, RecursionError) as exc:
            raise NumericError('numeric_invalid_input', 'Noncanonical statistics input.') from exc
        if len(canonical) > _MAX_INPUT_BYTES:
            raise NumericError('numeric_input_bytes_limit', '固定统计输入超过8 MiB。')
        key = hashlib.sha256(canonical).digest()
        remaining = max(0., deadline-time.monotonic())
        if remaining <= 0 or not _CACHE_LOCK.acquire(timeout=remaining):
            raise NumericError('numeric_timeout', '固定统计等待超过硬超时。')
        locked = True
        if time.monotonic() >= deadline:
            raise NumericError('numeric_timeout', '固定统计阶段超过硬超时。')
        if timeout_seconds == 30 and key in _CACHE:
            result, size = _CACHE.pop(key)
            _CACHE[key] = (result, size)
            cache_hit = True
        else:
            result = _compute_uncached(task_type, rows, selected, deadline-time.monotonic())
        try:
            encoded = json.dumps(result, allow_nan=False, separators=(',', ':')).encode('utf-8')
        except (TypeError, ValueError, RecursionError) as exc:
            raise NumericError('numeric_output_invalid', '固定统计输出无效。') from exc
        output_size = len(encoded)
        if output_size > _MAX_OUTPUT_BYTES:
            raise NumericError('numeric_output_limit', '固定统计输出超过16 MiB。')
        result_copy = deepcopy(result)
        if time.monotonic() >= deadline:
            raise NumericError('numeric_timeout', '固定统计阶段超过硬超时。')
        size = output_size + len(canonical)
        if not cache_hit and timeout_seconds == 30 and size <= _MAX_CACHE_BYTES:
            while _CACHE and (len(_CACHE) >= _MAX_CACHE_ITEMS or _CACHE_BYTES+size > _MAX_CACHE_BYTES):
                _, (_, old_size) = _CACHE.popitem(last=False)
                _CACHE_BYTES -= old_size
            _CACHE[key] = (deepcopy(result), size)
            _CACHE_BYTES += size
        _record(started, len(canonical), output_size, timeout_seconds, cache_hit)
        return result_copy
    except NumericError as exc:
        _record(started, len(canonical), output_size, timeout_seconds, cache_hit, exc.code)
        raise
    finally:
        if locked:
            _CACHE_LOCK.release()
