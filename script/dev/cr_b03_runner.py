"""CR-B03 isolated acceptance services. No database/assets/volume deletion."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[2]
RUNTIME=ROOT/'script/.runtime/client-requirements-b03'
STATE=RUNTIME/'state.json'
WORKER_IMAGE='paperassist-client-b03-worker:local'
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'script/dev')]
import worker_stack


def read_state():
    state=json.loads(STATE.read_text(encoding='utf-8-sig'))
    if not re.fullmatch(r'pa_test_[a-f0-9]{32}',state.get('schema','')):raise ValueError('Invalid isolated schema')
    directory=RUNTIME/'acceptance'/state['schema']
    expected=dict(workspace=str(ROOT),assets=str(directory/'assets'),staging=str(directory/'staging'),bind_host='127.0.0.83',port=18083,
        url='http://127.0.0.83:18083',stack_project='pa-test-'+state['schema'][8:],clone_status='verified',public_database_modified=False)
    if any(state.get(k)!=v for k,v in expected.items()) or state['schema']==state['source_schema']:raise ValueError('Batch ownership differs')
    return state


def configure(state):
    os.environ.update(PAPERASSIST_ENV='test',PAPERASSIST_DB_SCHEMA=state['schema'],PAPERASSIST_DATA_DIR=state['assets'],
        PAPERASSIST_RESEARCH_STAGING_DIR=state['staging'],PAPERASSIST_PLOT_WORKER_ENABLED='0',PAPERASSIST_NCBI_ENABLED='0',
        PAPERASSIST_NCBI_CONFIG_FILE='',PAPERASSIST_NCBI_API_KEY='',PAPERASSIST_NCBI_EMAIL='',PAPERASSIST_WRITING_LIVE_ENABLED='0',
        OPENAI_API_KEY='',OPENAI_API_KEY_FILE='',PAPERASSIST_AUTH_TRUSTED_ORIGINS=state['url'],PAPERASSIST_AUTH_IDLE_SECONDS='86400',
        PAPERASSIST_AUTH_ABSOLUTE_SECONDS='604800',PAPERASSIST_EXPLANATION_POLICY_FILE='',PAPERASSIST_PLOT_POLICY_FILE='',
        PAPERASSIST_ANALYSIS_RECOMMENDATION_POLICY_FILE='')


def source_digest():
    source=ROOT/'backend/app';result=hashlib.sha256()
    for path in sorted(source.rglob('*.py'),key=lambda p:p.relative_to(source).as_posix()):
        result.update(path.relative_to(source).as_posix().encode()+b'\0'+path.read_bytes()+b'\0')
    return result.hexdigest()


def compose(stack,args,timeout=180):
    return worker_stack.docker(['compose','--project-name',stack.project,'--file',str(ROOT/'compose.workers.yml'),
        '--file',str(RUNTIME/'compose.override.json'),*args],stack=stack,timeout=timeout)


def build():
    read_state()
    # Reuse the locally verified dependencies. No registry pull or package install.
    base='paperassist-client-b02-worker:local'
    base_id=worker_stack.docker(['image','inspect','--format','{{.Id}}',base]).strip()
    dockerfile=RUNTIME/'Dockerfile.worker'
    worker_stack.private_write(dockerfile,'FROM '+base+'\nCOPY backend/app /app/app\n')
    worker_stack.docker(['build','--network','none','--pull=false','-f',str(dockerfile),'-t',WORKER_IMAGE,str(ROOT)],timeout=300)
    return {'image':WORKER_IMAGE,'base_image_id':base_id,'source_digest':source_digest()}


def workers():
    state=read_state();configure(state)
    from app.core.config import local_config
    image=worker_stack.docker(['image','inspect','--format','{{.Id}}',WORKER_IMAGE]).strip()
    check="from pathlib import Path;import hashlib;r=Path('/app/app');h=hashlib.sha256();[(h.update(p.relative_to(r).as_posix().encode()+b'\\0'+p.read_bytes()+b'\\0')) for p in sorted(r.rglob('*.py'),key=lambda p:p.relative_to(r).as_posix())];print(h.hexdigest())"
    actual=worker_stack.docker(['run','--rm','--network','none','--read-only','--memory','128m','--entrypoint','python',image,'-c',check]).strip()
    if actual!=source_digest():raise RuntimeError('Worker source differs; run build before workers')
    available=int(worker_stack.docker(['run','--rm','--network','none','--read-only','--memory','64m','--entrypoint','python',image,'-c',
        "from pathlib import Path;print(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:')))" ]).strip())*1024
    if available<4*1024**3:raise RuntimeError('Docker available memory below approved 4GiB gate')
    Path(state['staging']).mkdir(exist_ok=True)
    stack=worker_stack.prepare(ROOT,local_config(),test_id=state['schema'][8:],assets=Path(state['assets']))
    worker_stack.owned_containers(stack)
    config={'services':{name:{'image':image,'environment':{'PAPERASSIST_RESEARCH_STAGING_DIR':'/research-staging'},
        'volumes':[{'type':'bind','source':state['staging'],'target':'/research-staging'}],
        **({'mem_limit':'4g','cpus':1} if name=='worker' else {})} for name in ['worker','dispatcher']}}
    # Reuse the stopped B02 PDF renderer image without starting its stack.
    source_project='pa-test-'+state['source_schema'][8:]
    pdf_image=worker_stack.docker(['image','inspect','--format','{{.Id}}',source_project+'-pdf-renderer:local']).strip()
    config['services']['pdf-renderer']={'image':pdf_image}
    worker_stack.private_write(RUNTIME/'compose.override.json',json.dumps(config,indent=2))
    compose(stack,['config','--quiet'])
    compose(stack,['up','-d','--no-build','--wait','--wait-timeout','120'])
    state.update(worker_image=WORKER_IMAGE,worker_image_id=image,worker_source_digest=actual,pdf_image_id=pdf_image,
        docker_available_before_start=available,status='services_running')
    worker_stack.private_write(STATE,json.dumps(state,ensure_ascii=False,indent=2))
    return {'containers':worker_stack.owned_containers(stack),'source_digest':actual}


def port_open(state):
    with socket.socket() as connection:
        connection.settimeout(.2)
        return connection.connect_ex((state['bind_host'],state['port']))==0


def serve():
    state=read_state();configure(state)
    import uvicorn
    from fastapi.staticfiles import StaticFiles
    from app.main import app
    app.mount('/',StaticFiles(directory=ROOT/'frontend/dist',html=True),name='cr-b03-acceptance')
    uvicorn.run(app,host=state['bind_host'],port=state['port'],log_level='warning')


def start_api():
    state=read_state()
    if port_open(state):raise RuntimeError('Acceptance port occupied; no process changed')
    directory=Path(state['assets']).parent;receipt=directory/'api-process.json'
    if receipt.exists():
        history=directory/'api-process-history';history.mkdir(exist_ok=True)
        worker_stack.private_write(history/(uuid4().hex+'.json'),receipt.read_text(encoding='utf-8'))
    with (directory/'api.stdout.log').open('ab') as out,(directory/'api.stderr.log').open('ab') as err:
        child=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'serve'],cwd=ROOT/'backend',stdout=out,stderr=err,
            stdin=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    worker_stack.private_write(receipt,json.dumps({'pid':child.pid,'executable':sys.executable,'script':str(Path(__file__).resolve()),
        'workspace':str(ROOT),'port':state['port'],'source_digest':source_digest(),
        'frontend_index_sha256':hashlib.sha256((ROOT/'frontend/dist/index.html').read_bytes()).hexdigest()},indent=2))
    import urllib.request
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(80):
        try:
            with opener.open(state['url']+'/api/v1/health',timeout=.5) as response:
                if response.status==200:return {'api':'ready','url':state['url'],'pid':child.pid}
        except OSError:pass
        if child.poll() is not None:raise RuntimeError('API failed; inspect private batch stderr')
        time.sleep(.25)
    raise RuntimeError('API startup timed out; receipt retained')


def stop_api():
    state=read_state();receipt=Path(state['assets']).parent/'api-process.json'
    if not receipt.exists():return {'api':'no_recorded_process'}
    saved=json.loads(receipt.read_text(encoding='utf-8'))
    if saved['workspace']!=str(ROOT) or saved['script']!=str(Path(__file__).resolve()) or saved['port']!=state['port']:raise ValueError('Foreign API receipt')
    # Validate executable and exact batch script before stopping this recorded PID.
    command="""$r=[Console]::In.ReadToEnd()|ConvertFrom-Json
$p=Get-CimInstance Win32_Process -Filter ('ProcessId='+[int]$r.pid)
if ($null -eq $p) { exit 0 }
if (-not [string]::Equals($p.ExecutablePath,$r.executable,[StringComparison]::OrdinalIgnoreCase)) { throw 'API executable differs' }
if ($p.CommandLine.IndexOf($r.script,[StringComparison]::OrdinalIgnoreCase) -lt 0 -or $p.CommandLine -notmatch ' serve(?: |$)') { throw 'API command differs' }
Stop-Process -Id $p.ProcessId -ErrorAction Stop
"""
    completed=subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',command],input=json.dumps(saved).encode(),capture_output=True,timeout=15)
    if completed.returncode:raise RuntimeError('API ownership check failed; no broad process stop performed')
    for _ in range(20):
        if not port_open(state):return {'api':'stopped','pid':saved['pid'],'receipt_retained':True}
        time.sleep(.1)
    raise RuntimeError('API port remains occupied; no other process stopped')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['state','build','workers','serve','start-api','stop-api'])
    args=parser.parse_args()
    if args.action=='serve':serve();return
    result={'state':read_state,'build':build,'workers':workers,'start-api':start_api,'stop-api':stop_api}[args.action]()
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
