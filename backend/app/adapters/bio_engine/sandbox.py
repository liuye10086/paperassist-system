"""Numerical child sandbox; trusted runtime trees are read only."""
import ctypes
import os
import platform
import signal
import sys

from app.adapters.excel_sandbox import SandboxUnavailable, _Filter, _Program, _Ruleset


class _PathRule(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


def enter(files, output, parent_pid):
    if len(files)>514:
        raise ValueError('input_member_limit')
    if sys.platform != "linux" or sys.byteorder != "little" or len(os.listdir("/proc/self/task")) != 1:
        raise SandboxUnavailable('requires_linux_single_thread:'+str(len(os.listdir('/proc/self/task'))) if sys.platform=='linux' else 'requires_linux')
    import resource
    machine = platform.machine()
    if machine == "x86_64":
        arch = 0xC000003E
        allowed = [0, 1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 23, 24, 25, 28,
                   32, 33, 35, 39, 60, 63, 72, 73, 74, 75, 77, 79, 89, 96, 97, 98, 99, 102, 104, 107, 108, 110,
                   131, 158, 186, 202, 204, 217, 218, 228, 230, 231, 257, 258, 262, 263, 267, 270, 271, 273, 302, 318, 332, 334]
    elif machine == "aarch64":
        arch = 0xC00000B7
        allowed = [17, 23, 24, 25, 29, 32, 34, 35, 45, 46, 48, 56, 57, 61, 62, 63, 64, 65, 66, 67, 68, 72, 73, 78,
                   79, 80, 82, 83, 93, 94, 96, 98, 99, 101, 113, 115, 124, 132, 134, 135, 139, 160, 163,
                   165, 169, 172, 173, 174, 175, 176, 177, 178, 214, 215, 216, 222, 226, 233, 261, 278, 293]
    else:
        raise SandboxUnavailable()
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    libc.prctl.restype = ctypes.c_int

    def checked(value):
        if value < 0:
            raise SandboxUnavailable()
        return value

    checked(libc.prctl(1, signal.SIGKILL, 0, 0, 0))
    if os.getppid() != parent_pid:
        os._exit(70)
    checked(libc.prctl(4, 0, 0, 0, 0))
    checked(libc.prctl(38, 1, 0, 0, 0))
    if checked(libc.syscall(444, 0, 0, 1)) < 3:
        raise SandboxUnavailable()
    descriptor = checked(libc.syscall(444, ctypes.byref(_Ruleset((1 << 15) - 1)), ctypes.sizeof(_Ruleset), 0))
    pinned_fds = []
    try:
        runtime = ['/opt/paperassist-bio', '/usr/local/lib/python3.11', '/usr/share/fonts/truetype/wqy']
        rules = [(str(item["path"]), 1 << 2) for item in files] + [(p, (1 << 2) | (1 << 3)) for p in runtime] + [
            (str(output), (1 << 1) | (1 << 2) | (1 << 3) | (1 << 5) | (1 << 7) | (1 << 8) | (1 << 14))]
        granted=set()
        for path, access in rules:
            fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                stat=os.fstat(fd)
                # Windows bind mounts require each distinct hardlink dentry
                # pinned too: an inode-only dedup denies its other paths.
                identity=(os.path.abspath(path),stat.st_dev,stat.st_ino,access)
                if identity in granted:
                    continue
                rule = _PathRule(access, fd)
                checked(libc.syscall(445, descriptor, 1, ctypes.byref(rule), 0))
                # Keep each granted inode/dentry pinned for the attempt. On
                # Windows host bind mounts, reopening after the last O_PATH
                # descriptor closes can otherwise fail Landlock with EACCES.
                pinned_fds.append(fd)
                granted.add(identity)
            finally:
                if fd not in pinned_fds:
                    os.close(fd)
        checked(libc.syscall(446, descriptor, 0))
    except BaseException:
        for fd in pinned_fds:
            os.close(fd)
        raise
    finally:
        os.close(descriptor)
    for key, value in [(resource.RLIMIT_CPU, 900), (resource.RLIMIT_AS, 3 * 1024**3),
                       # Up to 514 declared files plus four trusted/output
                       # grants remain pinned; leave bounded numeric I/O room.
                       (resource.RLIMIT_NOFILE, 1024), (resource.RLIMIT_FSIZE, 256 * 1024**2),
                       (resource.RLIMIT_CORE, 0), (resource.RLIMIT_NPROC, 0)]:
        resource.setrlimit(key, (value, value))
        if resource.getrlimit(key) != (value, value):
            raise SandboxUnavailable()
    instructions = [_Filter(0x20, 0, 0, 4), _Filter(0x15, 1, 0, arch), _Filter(0x06, 0, 0, 0x80000000),
                    _Filter(0x20, 0, 0, 0)]
    for number in allowed:
        instructions += [_Filter(0x15, 0, 1, number), _Filter(0x06, 0, 0, 0x7FFF0000)]
    instructions.append(_Filter(0x06, 0, 0, 0x00050001))
    filters = (_Filter * len(instructions))(*instructions)
    program = _Program(len(filters), filters)
    checked(libc.prctl(22, 2, ctypes.byref(program), 0, 0))
    return pinned_fds
