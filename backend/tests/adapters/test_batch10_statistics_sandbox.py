"""Production numerical boundary tests: no database, no isolation bypass."""
import importlib.util
import json
import os
import subprocess
import sys
import time

import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def runtime():
    assert importlib.util.find_spec('app.domain.fixed_statistics_runtime'), 'Shared numerical deadline is missing'
    from app.domain import fixed_statistics_runtime
    return fixed_statistics_runtime


def test_scope_deadline_includes_upstream_time_and_nested_scope():
    r = runtime()
    from app.domain.regression.common import NumericError
    with pytest.raises(NumericError) as caught:
        with r.numeric_execution_scope(.05) as outer:
            initial = r.remaining_seconds()
            time.sleep(.02)
            with r.numeric_execution_scope(60) as inner:
                assert inner.remaining_seconds() < initial - .01
                assert inner.deadline == outer.deadline
            time.sleep(.04)
    assert caught.value.code == 'numeric_timeout'


def test_scope_rejects_invalid_timeout():
    r = runtime()
    from app.domain.regression.common import NumericError
    for value in (0, -1, True, float('nan'), 61, 10**1000):
        with pytest.raises(NumericError):
            with r.numeric_execution_scope(value):
                pass


def test_scope_presence_is_reset_after_exit():
    r = runtime()
    assert callable(getattr(r, 'scope_active', None)), 'Scope presence API is missing'
    assert not r.scope_active()
    with r.numeric_execution_scope():
        assert r.scope_active()
    assert not r.scope_active()


def test_windows_fails_closed_even_if_cache_exists(monkeypatch):
    from app.domain.regression import bounded
    from app.domain.regression.common import NumericError
    monkeypatch.setattr(sys, 'platform', 'win32')
    with pytest.raises(NumericError) as caught:
        bounded.compute_bounded('descriptive', [1., 2.], {})
    assert caught.value.code == 'numeric_environment_unavailable'


def test_dispatch_rejects_unlisted_regression_method_before_kernel(monkeypatch):
    from app.domain.regression import runner, kernel
    from app.domain.regression.common import NumericError
    monkeypatch.setattr(kernel, 'compute_regression', lambda *args: {'unlisted_method_executed': True})
    with pytest.raises(NumericError) as caught:
        runner.compute_request(dict(task_type='regression', rows=[{'x': [1.], 'y': 0.}], selection={'method': 'unlisted'}))
    assert caught.value.code == 'numeric_invalid_input'


@pytest.mark.skipif(sys.platform != 'linux', reason='Requires real Linux Landlock/seccomp')
def test_real_sandbox_receipt_and_cache_are_distinct():
    r = runtime()
    from app.domain.regression import bounded
    bounded.clear_compute_cache()
    values = [1., 2., 4.]
    with r.numeric_execution_scope(60) as scope:
        assert bounded.compute_bounded('descriptive', values, {})['n'] == 3
        assert bounded.compute_bounded('descriptive', values, {})['n'] == 3
        receipts = scope.execution_receipts()
        assert len(receipts) == 2
        first, second = receipts
        assert first['memory_hard_limit'] == 1024 ** 3
        assert first['isolation'] == 'linux_landlock_seccomp'
        assert first['output_policy'] == 'bounded_pipe'
        assert first['child_cpu_seconds'] >= 0 and first['child_peak_rss_bytes'] > 0
        assert second['cache_hit'] and second['child_cpu_seconds'] is None
        assert second['child_peak_rss_bytes'] is None
        receipts.clear()
        assert len(r.execution_receipts()) == 2
    assert values == [1., 2., 4.]


@pytest.mark.skipif(sys.platform != 'linux', reason='Requires real Linux Landlock/seccomp')
def test_small_wall_deadline_reclaims_child():
    from app.domain.regression.bounded import compute_bounded
    from app.domain.regression.common import NumericError
    with pytest.raises(NumericError) as caught:
        compute_bounded('descriptive', [1., 2.], {}, timeout_seconds=.001)
    assert caught.value.code == 'numeric_timeout'


@pytest.mark.skipif(sys.platform != 'linux', reason='Requires real Linux Landlock/seccomp')
@pytest.mark.parametrize('method', ['descriptive', 'pearson', 'spearman', 'welch_t', 'mann_whitney_u',
    'paired_t', 'wilcoxon', 'welch_anova', 'kruskal_wallis', 'ols', 'logistic', 'roc_auc', 'kaplan_meier'])
def test_all_thirteen_methods_run_under_real_limits(method):
    from app.domain.regression import bounded
    if method == 'descriptive':
        kind, rows, selected = method, [1., 2., 4.], {}
    elif method in ('pearson', 'spearman'):
        kind, rows, selected = 'correlation', [[float(i), float(i*2)] for i in range(1, 6)], dict(method=method, mode='pair', seed=0)
    elif method in ('ols', 'logistic'):
        selected = dict(method=method, covariates=[dict(column='A', type='continuous', unit='x', levels=[], reference=None)])
        if method == 'ols':
            rows = [dict(x=[float(i)], y=float(i + (i%3)), row=i+2) for i in range(20)]
        else:
            rows = [dict(x=[float(x)], y=float(y), row=i+2) for i, (x, y) in enumerate(
                [(0, 0)]*8 + [(0, 1)]*2 + [(1, 0)]*2 + [(1, 1)]*8)]
        kind = 'regression'
    elif method == 'roc_auc':
        kind, rows, selected = 'roc', [dict(outcome=i%2, score=float(i), row=i+2) for i in range(8)], dict(direction='higher_is_positive', evaluation_role='external_validation')
    elif method == 'kaplan_meier':
        kind, rows, selected = 'survival', [dict(time=float(i+1), event=i%2 == 0, group=0, row=i+2) for i in range(8)], dict(groups=[], time_unit='day')
    else:
        kind = 'group_comparison'
        rows = [[1., 2., 4., 5., 8.], [2., 4., 5., 8., 9.]]
        multiple = method in ('welch_anova', 'kruskal_wallis')
        if multiple:
            rows.append([4., 5., 7., 10., 12.])
        selected = dict(method=method, posthoc='all_pairs_holm' if multiple else 'none')
    bounded.clear_compute_cache()
    result = bounded.compute_bounded(kind, rows, selected)
    assert result and bounded.last_execution_receipt()['error_code'] is None


@pytest.mark.skipif(sys.platform != 'linux', reason='Requires real Linux Landlock/seccomp')
def test_bootstrap_prewarms_below_one_gib_with_one_cpu_and_thread():
    code = '''import json,os
from app.adapters.fixed_statistics_runner import prepare_runtime
prepare_runtime()
status={line.split(':',1)[0]:line.split(':',1)[1].strip() for line in open('/proc/self/status') if line.startswith(('Threads:','VmSize:','VmRSS:'))}
status['cpu_count']=len(os.sched_getaffinity(0))
print(json.dumps(status))
'''
    result = subprocess.run([sys.executable, '-c', code], env={'PYTHONPATH': '/app', 'OPENBLAS_NUM_THREADS': '8'}, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr.decode()
    status = json.loads(result.stdout)
    print('fixed_bootstrap_resources=', json.dumps(status))
    assert status['Threads'] == '1' and status['cpu_count'] == 1
    assert int(status['VmSize'].split()[0])*1024 < 1024**3


def _probe_code(tail, cpu_seconds=30):
    return '''import json,os,resource,socket,sys,time
from pathlib import Path
from app.adapters.fixed_statistics_runner import prepare_runtime
from app.adapters.excel_sandbox import enter_sandbox
prepare_runtime()
enter_sandbox(cpu_seconds=%d,memory_bytes=1024**3,parent_pid=os.getppid())
''' % cpu_seconds + tail


@pytest.mark.skipif(sys.platform != 'linux', reason='Requires real Linux Landlock/seccomp')
def test_sandbox_denies_files_network_fork_exec_and_keeps_hard_limits():
    code = _probe_code('''denied=[]
operations={'read':lambda:Path('/app/app/domain/regression/kernel.py').read_bytes(),
'write':lambda:Path('/tmp/forbidden-statistics-write').write_bytes(b'no'),
'network':lambda:socket.socket(),'fork':lambda:os.fork(),
'exec':lambda:os.execv('/bin/true',['true']),
'proc_environment':lambda:Path('/proc/1/environ').read_bytes()}
for name,operation in operations.items():
    try: operation()
    except PermissionError: denied.append(name)
print(json.dumps({'denied':denied,'limits':[resource.getrlimit(k)[0] for k in (resource.RLIMIT_CPU,resource.RLIMIT_AS,resource.RLIMIT_NOFILE,resource.RLIMIT_FSIZE,resource.RLIMIT_NPROC)]}))
''')
    result = subprocess.run([sys.executable, '-c', code], env={'PYTHONPATH': '/app'}, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr.decode()
    data = json.loads(result.stdout)
    print('fixed_sandbox_permissions=', json.dumps(data))
    assert data['denied'] == ['read', 'write', 'network', 'fork', 'exec', 'proc_environment']
    assert data['limits'] == [30, 1024**3, 64, 0, 0]


@pytest.mark.skipif(sys.platform != 'linux', reason='Requires real Linux Landlock/seccomp')
def test_cpu_and_memory_denial_in_prewarmed_sandbox():
    memory = _probe_code('''try:
    bytearray(2*1024**3)
except MemoryError:
    print('memory_denied')
''')
    result = subprocess.run([sys.executable, '-c', memory], env={'PYTHONPATH': '/app'}, capture_output=True, timeout=15)
    assert result.returncode == 0 and result.stdout.strip() == b'memory_denied', result.stderr.decode()
    # Same production limiter with a shorter probe-only CPU quota.
    cpu = _probe_code('while True: pass', cpu_seconds=1)
    result = subprocess.run([sys.executable, '-c', cpu], env={'PYTHONPATH': '/app'}, capture_output=True, timeout=15)
    assert result.returncode in (-9, -24)


@pytest.mark.skipif(sys.platform != 'linux', reason='Requires real Linux child transport')
def test_pipe_caps_output_and_does_not_inherit_parent_secrets(monkeypatch):
    from app.adapters.excel_process import _run_child
    from app.core.exceptions import StorageError
    monkeypatch.setenv('DATABASE_URL', 'synthetic-only')
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-only')
    monkeypatch.setenv('SOURCE_PATH', '/synthetic-only')
    code = "import os,json; print('READY',flush=True); print(json.dumps({'leaked':any(k in os.environ for k in ['DATABASE_URL','OPENAI_API_KEY','SOURCE_PATH'])}))"
    assert _run_child([sys.executable, '-c', code], b'', timeout_seconds=3, max_output_bytes=1024)['leaked'] is False
    overflow = "import os; os.write(1,b'READY\\n'); os.write(1,b'x'*(16*1024*1024+1))"
    with pytest.raises(StorageError) as caught:
        _run_child([sys.executable, '-c', overflow], b'', timeout_seconds=3, max_output_bytes=16*1024*1024)
    assert caught.value.code == 'parse_output_invalid'


@pytest.mark.skipif(sys.platform != 'linux', reason='Requires real Linux child transport')
def test_shared_deadline_includes_lock_wait():
    import threading
    from app.domain.regression import bounded
    from app.domain.regression.common import NumericError
    r = runtime()
    held, release = threading.Event(), threading.Event()
    def hold():
        with bounded._CACHE_LOCK:
            held.set()
            release.wait(2)
    holder = threading.Thread(target=hold)
    holder.start()
    assert held.wait(1)
    try:
        started = time.monotonic()
        with pytest.raises(NumericError) as caught:
            with r.numeric_execution_scope(.04) as scope:
                bounded.compute_bounded('descriptive', [1., 2.], {})
        assert caught.value.code == 'numeric_timeout'
        assert scope.execution_receipts()[0]['child_cpu_seconds'] is None
        assert time.monotonic()-started < .5
    finally:
        release.set()
        holder.join(2)


@pytest.mark.skipif(sys.platform != 'linux', reason='Requires real Linux parent-death signaling')
def test_parent_death_reaps_prewarmed_child():
    import ctypes
    assert ctypes.CDLL(None).prctl(36, 1, 0, 0, 0) == 0
    code = _probe_code('print(os.getpid(),flush=True);time.sleep(30)')
    launcher = 'import subprocess,sys;p=subprocess.Popen([sys.executable,"-c",sys.argv[1]]);p.wait()'
    parent = subprocess.Popen([sys.executable, '-c', launcher, code], env={'PYTHONPATH': '/app'}, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    child_pid = None
    try:
        child_pid = int(parent.stdout.readline())
        parent.kill()
        parent.wait(timeout=3)
        deadline = time.monotonic()+3
        while time.monotonic() < deadline:
            reaped, status = os.waitpid(child_pid, os.WNOHANG)
            if reaped:
                child_pid = None
                assert os.waitstatus_to_exitcode(status) == -9
                break
            time.sleep(.02)
        else:
            pytest.fail('Numerical sandbox survived parent death')
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait()
        if child_pid:
            os.kill(child_pid, 9)
            os.waitpid(child_pid, 0)
        parent.stdout.close()
        parent.stderr.close()


@pytest.mark.skipif(sys.platform != 'linux', reason='Requires real Linux numerical sandbox')
@pytest.mark.parametrize('kind', ['line', 'bar', 'violin'])
def test_fixed_figure_projection_uses_same_real_sandbox(kind):
    from app.domain.regression.bounded import compute_bounded, last_execution_receipt
    rows = [dict(row=i+2, x=float(i), y=float(i), category='A') for i in range(3)]
    result = compute_bounded('figure_projection', rows, {'figure_kind': kind, 'projection': {}})
    assert result['method']['kind'] == kind and result['audit']['valid_n'] == 3
    if kind == 'line':
        assert [point['y'] for point in result['series'][0]['points']] == [0., 1., 2.]
    elif kind == 'bar':
        assert result['series'][0]['points'][0]['value'] == 3
    else:
        assert result['series'][0]['median'] == 1 and len(result['series'][0]['density']) == 256
    assert last_execution_receipt()['isolation'] == 'linux_landlock_seccomp'


@pytest.mark.skipif(sys.platform != 'linux', reason='Requires real Linux numerical sandbox')
def test_projection_error_preserves_only_fixed_reason():
    from app.domain.regression.bounded import compute_bounded
    from app.domain.regression.common import NumericError
    with pytest.raises(NumericError) as caught:
        compute_bounded('figure_projection', [dict(row=2, x=1., y=2.), dict(row=3, x=1., y=3.)], {'figure_kind': 'line', 'projection': {}})
    assert caught.value.code == 'figure_projection_invalid'
    assert caught.value.reason == 'duplicate_x'


@pytest.mark.skipif(sys.platform != 'linux', reason='Requires real Linux numerical sandbox')
def test_boxplot_series_keeps_fraction_quantiles_and_outliers_under_sandbox():
    from app.domain.regression.bounded import compute_bounded
    result = compute_bounded('boxplot_series', [1., 2., 3., 4., 100.], {})
    assert result == dict(n=5, q1=2., median=3., q3=4., whislo=1., whishi=4., fliers=[100.], outlier_count=1)
