"""Observe this fixed child process only; no limits or system settings changed."""
import os
import sys
import time


def measure_process():
    peak = None
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize',
                'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
                'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]

        get_current = ctypes.windll.kernel32.GetCurrentProcess
        get_current.restype = wintypes.HANDLE
        get_info = ctypes.windll.psapi.GetProcessMemoryInfo
        get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        get_info.restype = wintypes.BOOL
        values = Counters()
        values.cb = ctypes.sizeof(values)
        if get_info(get_current(), ctypes.byref(values), values.cb):
            peak = int(values.PeakWorkingSetSize)
    else:
        import resource
        usage = resource.getrusage(resource.RUSAGE_SELF)
        peak = int(usage.ru_maxrss) * (1 if sys.platform == 'darwin' else 1024)
    return {'cpu_seconds': time.process_time(), 'peak_rss_bytes': peak}
