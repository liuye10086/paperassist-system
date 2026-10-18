"""Trusted bootstrap. No input is read until imports and sandbox entry finish."""
import os
for _key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
             'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'BLIS_NUM_THREADS'):
    os.environ[_key] = '1'

import codecs
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.adapters.excel_sandbox import enter_sandbox
from app.domain.regression.runner import compute_request, preload_kernels
from app.domain.fixed_statistics_contract import MAX_INPUT_BYTES, MAX_OUTPUT_BYTES, ERROR_MESSAGES, PROJECTION_REASONS
from app.domain.fixed_statistics_metrics import measure_process


def emit(value):
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    if len(encoded) > MAX_OUTPUT_BYTES:
        encoded = json.dumps({'status': 'error', 'code': 'numeric_output_limit',
                              'message': ERROR_MESSAGES['numeric_output_limit'], 'measurement': measure_process()}).encode('utf-8')
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def prepare_runtime():
    if sys.platform != 'linux':
        raise RuntimeError('Linux required')
    # Bind before native-library initialization; no scheduler/BLAS pool can use
    # more than this one allowed logical CPU.
    os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    preload_kernels()
    for encoding in ('utf-8', 'ascii', 'latin-1', 'unicode_escape'):
        codecs.lookup(encoding)


def main():
    try:
        prepare_runtime()
        enter_sandbox(cpu_seconds=30, memory_bytes=1024 ** 3, parent_pid=int(sys.argv[1]))
    except Exception:
        emit({'error': {'code': 'parse_environment_unavailable'}})
        return
    sys.stdout.buffer.write(b'READY\n')
    sys.stdout.buffer.flush()
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            from app.domain.regression.common import NumericError
            raise NumericError('numeric_input_bytes_limit', ERROR_MESSAGES['numeric_input_bytes_limit'])
        result = compute_request(json.loads(raw))
        message = {'status': 'ok', 'result': result}
    except Exception as exc:
        code = getattr(exc, 'code', None)
        if code not in ERROR_MESSAGES:
            code = 'numeric_failure'
        message = {'status': 'error', 'code': code, 'message': ERROR_MESSAGES[code]}
        if code == 'figure_projection_invalid':
            reason = getattr(exc, 'reason', None)
            message['reason'] = reason if reason in PROJECTION_REASONS else 'invalid_rule'
    message['measurement'] = measure_process()
    emit(message)


if __name__ == '__main__':
    main()
