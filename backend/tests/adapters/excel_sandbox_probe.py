"""Security probe executes the exact production sandbox, without parser test switches."""
import ctypes
import errno
import json
import os
from pathlib import Path
import resource
import platform
import socket
import sys
import time

from app.adapters.excel_sandbox import enter_sandbox, SandboxUnavailable, _Filter, _Program

mode = sys.argv[1]
target_pid = os.getppid()
if mode == 'prlimit':
    syscall_lib = ctypes.CDLL(None, use_errno=True)
    syscall_lib.syscall.restype = ctypes.c_long
    prlimit_nr = 302 if platform.machine() == 'x86_64' else 261
if mode == 'missing_capability':
    # Stack a stricter filter on Docker's existing policy; do not relax anything.
    libc = ctypes.CDLL(None)
    instructions = (_Filter * 4)(_Filter(0x20, 0, 0, 0), _Filter(0x15, 0, 1, 444),
                                 _Filter(0x06, 0, 0, 0x00050001), _Filter(0x06, 0, 0, 0x7FFF0000))
    program = _Program(4, instructions)
    assert libc.prctl(38, 1, 0, 0, 0) == 0
    assert libc.prctl(22, 2, ctypes.byref(program), 0, 0) == 0
    try:
        enter_sandbox(cpu_seconds=30, memory_bytes=536870912, parent_pid=os.getppid())
    except SandboxUnavailable:
        print('fail_closed')
        sys.exit(0)
    sys.exit(1)
enter_sandbox(cpu_seconds=30 if mode == 'permissions' else 1,
              memory_bytes=536870912, parent_pid=os.getppid())
if mode == 'permissions':
    denied = []
    operations = {
        'read': lambda: Path(__file__).read_bytes(),
        'write': lambda: Path('/tmp/probe-write').write_bytes(b'forbidden'),
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
    print(json.dumps({'denied': denied, 'limits': [resource.getrlimit(key)[0] for key in
          [resource.RLIMIT_CPU, resource.RLIMIT_AS, resource.RLIMIT_NOFILE, resource.RLIMIT_FSIZE]]}))
elif mode == 'cpu':
    while True:
        pass
elif mode == 'memory':
    try:
        bytearray(600 * 1024 * 1024)
    except MemoryError:
        print('memory_denied')
elif mode == 'sleep':
    print(os.getpid(), flush=True)
    time.sleep(30)
elif mode == 'prlimit':
    denied = []
    def raw_prlimit(pid, new_limit):
        old_limit = (ctypes.c_uint64 * 2)()
        result = syscall_lib.syscall(ctypes.c_long(prlimit_nr), ctypes.c_uint64(pid),
                                     ctypes.c_long(resource.RLIMIT_NOFILE), ctypes.c_uint64(new_limit),
                                     ctypes.byref(old_limit))
        if result < 0:
            error = ctypes.get_errno()
            if error == errno.EPERM:
                raise PermissionError(error, 'denied')
            raise OSError(error, 'unexpected syscall failure')
        return list(old_limit)
    calls = {
        'parent_read': lambda: resource.prlimit(target_pid, resource.RLIMIT_NOFILE),
        'parent_write': lambda: resource.prlimit(target_pid, resource.RLIMIT_NOFILE, (32, 32)),
        'self_write': lambda: resource.prlimit(0, resource.RLIMIT_NOFILE, (32, 32)),
        'pid_high': lambda: raw_prlimit(1 << 32, 0),
        'new_limit_high': lambda: raw_prlimit(0, 1 << 32),
    }
    for name, operation in calls.items():
        try:
            operation()
        except PermissionError:
            denied.append(name)
    print(json.dumps({'denied': denied, 'self_read': resource.getrlimit(resource.RLIMIT_NOFILE),
                      'self_read_raw': raw_prlimit(0, 0)}))
