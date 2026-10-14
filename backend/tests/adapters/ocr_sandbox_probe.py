"""Real fixed-model preload plus original sandbox; no relaxation or test switches."""
import os
for _key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
             'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'BLIS_NUM_THREADS'):
    os.environ[_key] = '1'
import json
from pathlib import Path
import resource
import socket
import sys
import threading
import time

from app.adapters.ocr_runtime import get_runtime
from app.adapters.excel_sandbox import enter_sandbox
from app.domain.documents.ocr_contracts import PROCESS_SETTINGS

start = time.monotonic()
get_runtime()
threads = len(os.listdir('/proc/self/task'))
assert threads == 1
status = Path('/proc/self/status').read_text()
enter_sandbox(cpu_seconds=PROCESS_SETTINGS['cpu_seconds'], memory_bytes=PROCESS_SETTINGS['memory_bytes'],
              parent_pid=os.getppid())
denied = []
operations = {
    'read': lambda: Path('/etc/passwd').read_bytes(),
    'write': lambda: Path('/tmp/ocr-forbidden').write_bytes(b'forbidden'),
    'network': lambda: socket.socket(),
    'fork': lambda: os.fork(),
    'exec': lambda: os.execv('/bin/true', ['true']),
    'proc_environment': lambda: Path('/proc/1/environ').read_bytes(),
}
for name, operation in operations.items():
    try:
        operation()
    except PermissionError:
        denied.append(name)
assert denied == list(operations)
try:
    threading.Thread(target=lambda: None).start()
except RuntimeError:
    denied.append('thread')
assert 'thread' in denied
try:
    bytearray(PROCESS_SETTINGS['memory_bytes'])
except MemoryError:
    denied.append('memory_over_budget')
assert 'memory_over_budget' in denied
print(json.dumps(dict(denied=denied, threads_before_sandbox=threads, preload_seconds=time.monotonic()-start,
                     limits={str(key):resource.getrlimit(key) for key in (resource.RLIMIT_CPU,resource.RLIMIT_AS,
                             resource.RLIMIT_NOFILE,resource.RLIMIT_FSIZE)}, status_before_sandbox=status)))
