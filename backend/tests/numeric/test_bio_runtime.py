"""Executed only by the dedicated Linux bio interpreter; no dependency skips."""
import importlib.util


def test_bio_environment_gate_exists():
    assert importlib.util.find_spec('app.adapters.bio_engine.runtime_probe') is not None


def test_real_numeric_runtime_and_linux_isolation():
    import json, os, subprocess, sys
    environment = {key:value for key,value in os.environ.items() if key in {'PATH','PYTHONPATH','MPLCONFIGDIR'}}
    result = subprocess.run([sys.executable,'-m','app.adapters.bio_engine.runtime_probe'],capture_output=True,text=True,env=environment)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['status'] == 'passed'
    assert report['scanpy'] == '1.11.5'
    assert report['isolation'] == {'network': 'denied', 'file': 'denied', 'fork': 'denied'}
    assert report['h5_roundtrip'] and report['png_bytes'] > 1000 and report['pdf_bytes'] > 1000


def test_sandbox_pins_full_member_budget_without_exhausting_open_files(tmp_path):
    import json, os, subprocess, sys
    source=tmp_path/'inputs';source.mkdir();output=tmp_path/'outputs';output.mkdir()
    paths=[]
    for index in range(512):
        path=source/str(index);path.write_text(str(index));paths.append(str(path))
    alias=source/'alias';os.link(paths[0],alias)
    paths.extend([paths[0],str(alias)])
    denied=source/'denied';denied.write_text('private')
    script='''
import json,os,resource,socket,sys
from pathlib import Path
from app.adapters.bio_engine.sandbox import enter
p=json.loads(sys.argv[1]);fds=enter([{'path':x} for x in p['paths']],Path(p['output']),os.getppid())
assert resource.getrlimit(resource.RLIMIT_NOFILE)==(1024,1024)
assert len(fds)==517,len(fds)
for index,path in enumerate(p['paths']):assert Path(path).read_text()==str(index if index<512 else 0)
for action in [lambda:Path(p['denied']).read_bytes(),lambda:socket.socket(),os.fork]:
 try:action()
 except PermissionError:pass
 else:raise AssertionError('unauthorized access')
print('full_member_budget_passed')
'''
    env={**os.environ,'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1'}
    result=subprocess.run([sys.executable,'-c',script,json.dumps({'paths':paths,'output':str(output),'denied':str(denied)})],env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert result.stdout.strip()=='full_member_budget_passed'
