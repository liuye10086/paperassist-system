"""Linux-only, fail-closed sandbox. No filesystem access remains after entry.

Dependencies must be loaded before entry. Landlock ABI >= 3 is mandatory;
seccomp uses an architecture checked syscall allowlist, never a denylist.
"""
import ctypes
import os
import platform
import signal
import sys


class SandboxUnavailable(Exception):
    pass


class _Ruleset(ctypes.Structure):
    _fields_ = [('handled_access_fs', ctypes.c_uint64)]


class _Filter(ctypes.Structure):
    _fields_ = [('code', ctypes.c_ushort), ('jt', ctypes.c_ubyte),
                ('jf', ctypes.c_ubyte), ('k', ctypes.c_uint32)]


class _Program(ctypes.Structure):
    _fields_ = [('length', ctypes.c_ushort), ('filters', ctypes.POINTER(_Filter))]


def enter_sandbox(*, cpu_seconds: int, memory_bytes: int, parent_pid: int) -> None:
    if sys.platform != 'linux':
        raise SandboxUnavailable()
    import resource
    machine = platform.machine()
    # These lists only permit in-memory Python execution, metadata checks and
    # standard pipe I/O. All network/process/exec/io_uring/ptrace calls fail EPERM.
    if machine == 'x86_64':
        arch = 0xC000003E
        prlimit_number = 302
        allowed = [0, 1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
                   16, 17, 19, 20, 21, 23, 24, 25, 28, 32, 33, 35, 39,
                   60, 63, 72, 89, 96, 97, 98, 99, 102, 104, 107, 108,
                   110, 131, 158, 186, 202, 204, 218, 228, 230, 231,
                   257, 262, 267, 270, 271, 273, 318, 332, 334]
    elif machine == 'aarch64':
        arch = 0xC00000B7
        prlimit_number = 261
        allowed = [23, 24, 25, 29, 48, 56, 57, 61, 62, 63, 64, 65, 66,
                   67, 72, 73, 78, 79, 80, 93, 94, 96, 98, 99, 101,
                   113, 115, 124, 132, 134, 135, 139, 160, 163, 165,
                   169, 172, 173, 174, 175, 176, 177, 178, 214, 215,
                   216, 222, 226, 233, 278, 293]
    else:
        raise SandboxUnavailable()
    if sys.byteorder != 'little':
        raise SandboxUnavailable()
    # Landlock and prctl seccomp below apply to this one thread. Unexpected
    # dependency-created threads must never survive with broader permissions.
    if len(os.listdir('/proc/self/task')) != 1:
        raise SandboxUnavailable()
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    libc.prctl.restype = ctypes.c_int

    def checked(result):
        if result < 0:
            raise SandboxUnavailable()
        return result

    # Bind death to the actual spawning parent, including the race before prctl.
    checked(libc.prctl(1, signal.SIGKILL, 0, 0, 0))  # PR_SET_PDEATHSIG
    if os.getppid() != parent_pid:
        os._exit(70)
    checked(libc.prctl(4, 0, 0, 0, 0))  # PR_SET_DUMPABLE: no process-memory access
    checked(libc.prctl(38, 1, 0, 0, 0))  # PR_SET_NO_NEW_PRIVS
    abi = checked(libc.syscall(444, 0, 0, 1))
    if abi < 3:
        raise SandboxUnavailable()
    # Bits 0..14 cover execute, reads, all create/remove/write, refer, truncate.
    # No allow rules: all filesystem reads and writes denied, including /proc.
    ruleset = _Ruleset((1 << 15) - 1)
    descriptor = checked(libc.syscall(444, ctypes.byref(ruleset), ctypes.sizeof(ruleset), 0))
    try:
        checked(libc.syscall(446, descriptor, 0))
    finally:
        os.close(descriptor)
    old_descriptor_limit = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
    os.closerange(3, old_descriptor_limit)
    for key, value in [(resource.RLIMIT_CPU, cpu_seconds), (resource.RLIMIT_AS, memory_bytes),
                       (resource.RLIMIT_NOFILE, 64), (resource.RLIMIT_FSIZE, 0),
                       (resource.RLIMIT_CORE, 0), (resource.RLIMIT_NPROC, 0)]:
        resource.setrlimit(key, (value, value))
        if resource.getrlimit(key) != (value, value):
            raise SandboxUnavailable()
    instructions = [_Filter(0x20, 0, 0, 4), _Filter(0x15, 1, 0, arch),
                    _Filter(0x06, 0, 0, 0x80000000), _Filter(0x20, 0, 0, 0)]
    for number in allowed:
        instructions.extend([_Filter(0x15, 0, 1, number), _Filter(0x06, 0, 0, 0x7FFF0000)])
    # seccomp_data args begin at byte 16; each argument is a uint64_t.
    # prlimit64(pid, resource, new_limit, old_limit): only querying this process
    # via pid=0 and new_limit=NULL is needed by resource.getrlimit/glibc.
    # Check BOTH 32-bit halves on the supported little-endian architectures.
    # Every failed comparison jumps to the final EPERM (offsets below are
    # relative to this block: JEQ indices 0/2/4/6/8, deny index 10).
    instructions.extend([
        _Filter(0x15, 0, 9, prlimit_number),
        _Filter(0x20, 0, 0, 16), _Filter(0x15, 0, 7, 0),  # args[0] low
        _Filter(0x20, 0, 0, 20), _Filter(0x15, 0, 5, 0),  # args[0] high
        _Filter(0x20, 0, 0, 32), _Filter(0x15, 0, 3, 0),  # args[2] low
        _Filter(0x20, 0, 0, 36), _Filter(0x15, 0, 1, 0),  # args[2] high
        _Filter(0x06, 0, 0, 0x7FFF0000),
    ])
    instructions.append(_Filter(0x06, 0, 0, 0x00050001))  # SECCOMP_RET_ERRNO | EPERM
    filters = (_Filter * len(instructions))(*instructions)
    program = _Program(len(filters), filters)
    checked(libc.prctl(22, 2, ctypes.byref(program), 0, 0))  # PR_SET_SECCOMP FILTER
