"""Run in the dedicated Linux B04 interpreter, never skip a missing runtime."""
import json
import os
import subprocess
import sys


def test_b04_budget_is_separate_and_can_only_tighten():
    from app.domain.bio_insights.settings import BioInsightsLimits
    from pydantic import ValidationError
    import pytest
    limits = BioInsightsLimits()
    assert (limits.compute_wall_seconds, limits.cpu_seconds, limits.warmup_seconds) == (1800, 1500, 180)
    assert limits.memory_bytes == 2 * 1024**3
    assert limits.numeric_threads == 1
    with pytest.raises(ValidationError):
        BioInsightsLimits(compute_wall_seconds=1801)


def test_missing_or_stale_runtime_receipt_is_blocked(tmp_path, monkeypatch):
    from app.domain.bio_insights.settings import runtime_identity
    receipt = tmp_path / 'runtime.json'
    monkeypatch.setenv('PAPERASSIST_BIO_INSIGHTS_RUNTIME_MANIFEST', str(receipt))
    assert runtime_identity()['available'] is False
    receipt.write_text(json.dumps({'status': 'passed', 'code_digest': '0' * 64}))
    assert runtime_identity()['available'] is False


def test_fitting_gsea_rendering_and_kernel_isolation():
    environment = {key: value for key, value in os.environ.items() if key in {'PATH', 'PYTHONPATH'}}
    result = subprocess.run([sys.executable, '-m', 'app.adapters.bio_insights_engine.runtime_probe'],
                            capture_output=True, text=True, env=environment, timeout=240)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['status'] == 'passed'
    assert report['interpreter'].startswith('/opt/paperassist-bio-insights/')
    assert report['packages']['pydeseq2'] == '0.5.4'
    assert report['packages']['gseapy'] == '1.3.1'
    assert report['isolation'] == {'network': 'denied', 'file': 'denied', 'fork': 'denied', 'subprocess': 'denied'}
    assert report['numeric_threads'] == report['warm_threads'] == 1
    assert report['checks']['aggregation'] and report['checks']['deseq2_fit'] and report['checks']['gsea']
    assert report['checks']['png_bytes'] > 1000 and report['checks']['render_formats'] == ['png']
    assert report['peak_rss_kib'] < 2 * 1024**2
    assert len(report['lock_sha256']) == len(report['code_digest']) == 64
    assert report['limits']['cpu_seconds'] == 1500
    assert report['container_memory_limit_bytes'] == 4 * 1024**3
    assert report['container_peak_memory_bytes'] < report['container_memory_limit_bytes']
    assert report['container_peak_tasks'] >= 2


def test_same_process_thread_allowed_but_fork_exec_and_unusual_clone_denied(tmp_path):
    script = r'''
import ctypes, errno, json, os, platform, threading
from pathlib import Path
from app.adapters.bio_insights_engine.sandbox import enter
libc = ctypes.CDLL(None, use_errno=True)
output = Path(os.environ['PROBE_OUTPUT'])
fds = enter([], output, os.getppid())
observed = []
worker = threading.Thread(target=lambda: observed.append('same_process_thread'))
worker.start(); worker.join()
assert observed == ['same_process_thread']
clone = 56 if platform.machine() == 'x86_64' else 220
for flags in [17, 0x10000, 0x100 | 0x800 | 0x10000 | 0x20000000]:
 ctypes.set_errno(0)
 assert libc.syscall(clone, flags, 0, 0, 0, 0) == -1
 assert ctypes.get_errno() == errno.EPERM
ctypes.set_errno(0)
assert libc.syscall(435, 0, 0) == -1 and ctypes.get_errno() == errno.ENOSYS
for action in [os.fork, lambda: os.execv('/bin/true', ['/bin/true'])]:
 try: action()
 except PermissionError: pass
 else: raise AssertionError('process creation/exec permitted')
print('thread_scope_passed')
'''
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True,
                            env={**os.environ, 'PROBE_OUTPUT': str(tmp_path)}, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'thread_scope_passed'
