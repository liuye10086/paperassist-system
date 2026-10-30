"""Offline, isolated PaperAssist release operations; all failed targets are retained."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / 'script/.runtime/stage10-batch04'
RELEASES = RUNTIME / 'releases'
BASE = 'sha256:299060c24730e5d7aeebab34b7f960ee5548e4ed2a76454a38eac80f78f3c10b'
POSTGRES = 'postgres@sha256:edb0c08dc33befd0262ab3b5cf1c4f3f8cfd8b09e88c05b45adee29d6761ddb6'
BROKER = 'rabbitmq:4.3.6-alpine@sha256:2cb43283d8bbd3caa6c0f0dc00e96c8de772df33df7fd8af6aee4d605aeb8ada'
RENDERER = 'sha256:8b341880cc1533d0a301e7c9ec60493aba67f1464e1efc00820db9044b15bfde'
FONTS = 'arial.ttf arialbd.ttf arialbi.ttf ariali.ttf simsun.ttc calibri.ttf calibrib.ttf calibrii.ttf calibriz.ttf calibril.ttf calibrili.ttf msyh.ttc msyhbd.ttc msyhl.ttc cambria.ttc simhei.ttf times.ttf timesbd.ttf timesbi.ttf timesi.ttf'.split()


def utc(): return datetime.now(timezone.utc).isoformat()
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))


def atomic(path, value):
    path=Path(path); temporary=path.with_name(path.name+'.'+uuid4().hex+'.writing')
    with temporary.open('x',encoding='utf-8',newline='\n') as stream:
        stream.write(json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True) if not isinstance(value,str) else value)
        stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)


def private(directory):
    if os.name=='nt':
        import csv
        result=subprocess.run(['whoami','/user','/fo','csv','/nh'],capture_output=True,check=True,timeout=10)
        sid=next(csv.reader(result.stdout.decode('utf-8',errors='replace').splitlines()))[1]
        subprocess.run(['icacls',str(directory),'/inheritance:r','/grant:r',f'*{sid}:(OI)(CI)F'],capture_output=True,check=True,timeout=10)
    else: directory.chmod(0o700)


def validate_namespace(namespace):
    if not re.fullmatch('[a-z][a-z0-9-]{0,31}',namespace): raise ValueError('Invalid release namespace')
    return namespace


def new_directory(namespace):
    validate_namespace(namespace)
    directory=RELEASES/namespace
    if directory.exists(): raise ValueError('Fresh target already exists; retain it and choose another namespace')
    directory.mkdir(parents=True,exist_ok=False); private(directory)
    return directory.resolve()


def run(arguments, *, environment=None, timeout=120, input_text=None):
    try:
        result=subprocess.run(arguments,cwd=ROOT,env=environment,capture_output=True,text=True,
                              encoding='utf-8',errors='replace',input=input_text,timeout=timeout)
    except (OSError,subprocess.TimeoutExpired):
        raise RuntimeError('Local command unavailable or timed out; evidence retained') from None
    if result.returncode:
        # Third-party error messages can contain connection strings. Never relay them.
        raise RuntimeError('Local command failed (exit '+str(result.returncode)+'); inspect the isolated service privately')
    return result.stdout


def docker(arguments,**kwargs): return run(['docker',*arguments],**kwargs)


def environment(state):
    # Do not inherit application credentials or Docker Compose overrides.
    env={key:value for key,value in os.environ.items() if not key.startswith(('PAPERASSIST_','COMPOSE_','RELEASE_')) and key not in ('OPENAI_API_KEY','ANTHROPIC_API_KEY')}
    env.update(RELEASE_PROJECT=state['project'],RELEASE_NAMESPACE=state['namespace'],RELEASE_DIRECTORY=state['directory'],
               RELEASE_IMAGE=state['candidate']['image'],RELEASE_ROOT=str(ROOT),RELEASE_PORT=str(state['port']),RELEASE_FONTS=state['fonts'])
    return env


def candidate_compose(value):
    directory=Path(value['receipt']).parent
    manifest=directory/'source-manifest.json'; path=directory/'context/compose.release.yml'
    if sha(manifest)!=value['source_manifest_sha256']: raise ValueError('Compose manifest binding differs')
    entries=[entry for entry in read(manifest) if entry['path']=='compose.release.yml']
    if len(entries)!=1 or not path.is_file() or sha(path)!=entries[0]['sha256'] or path.stat().st_size!=entries[0]['bytes']:
        raise ValueError('Candidate Compose snapshot differs')
    return path


def compose(state, arguments, **kwargs):
    return docker(['compose','--project-name',state['project'],'--file',str(candidate_compose(state['candidate'])),*arguments],environment=environment(state),**kwargs)


def load(namespace, *, verify_resources=True):
    validate_namespace(namespace); directory=(RELEASES/namespace).resolve(); state=read(directory/'state.json')
    if (state.get('namespace')!=namespace or state.get('project')!='pa-release-'+namespace or state.get('root')!=str(ROOT)
            or state.get('directory')!=str(directory)):
        raise ValueError('Release identity mismatch')
    if verify_resources: owned(state)
    return state


def save(state): atomic(Path(state['directory'])/'state.json',state)


def named_resources(project, *, fresh=False):
    result={}
    for kind,suffixes in [('volume',['database','broker']),('network',['private','front'])]:
        names=set(docker([kind,'ls','--format','{{.Name}}']).splitlines())
        for suffix in suffixes:
            name=project+'_'+suffix
            if name not in names: continue
            if fresh: raise ValueError('Fresh Docker target already exists by exact resource name')
            resource=json.loads(docker([kind,'inspect',name]))[0]
            labels=resource.get('Labels') or {}
            if labels.get('com.docker.compose.project')!=project or labels.get('com.docker.compose.'+kind)!=suffix:
                raise ValueError('Docker resource binding differs')
            if kind=='network' and resource.get('Internal') is not (suffix=='private'):
                raise ValueError('Docker network isolation binding differs')
            result[name]=resource
    return result


def owned(state):
    resources=named_resources(state['project'])
    ids=docker(['ps','-aq','--filter','label=com.docker.compose.project='+state['project']]).split()
    if not ids: return []
    rows=json.loads(docker(['inspect',*ids]))
    result=[]
    for row in rows:
        identity,labels,status=row['Id'],row['Config']['Labels'],row['State']
        if labels.get('io.paperassist.release')!=state['namespace'] or labels.get('io.paperassist.workspace')!=str(ROOT):
            raise ValueError('Docker project collision')
        service=labels.get('com.docker.compose.service'); network=state['project']+'_private'
        attached=row.get('NetworkSettings',{}).get('Networks',{})
        allowed=[{network}]
        if service=='api': allowed.append({network,state['project']+'_front'})
        if set(attached) not in allowed or any(name not in resources or info.get('NetworkID')!=resources[name]['Id'] for name,info in attached.items()):
            raise ValueError('Container network binding differs')
        if service in ('db','broker'):
            volume=state['project']+('_database' if service=='db' else '_broker')
            target='/var/lib/postgresql' if service=='db' else '/var/lib/rabbitmq'
            mounts=[m for m in row.get('Mounts',[]) if m['Destination']==target]
            if volume not in resources or len(mounts)!=1 or mounts[0].get('Type')!='volume' or mounts[0].get('Name')!=volume:
                raise ValueError('Container volume binding differs')
        result.append(dict(id=identity,service=service,state=status,image=row.get('Image')))
    return result


def require_stopped(state, services):
    for item in owned(state):
        if item['service'] in services and (item['state']['Running'] or item['state'].get('ExitCode')==137 or item['state'].get('OOMKilled')):
            raise ValueError('Service did not stop gracefully; consistency is not established')


@contextmanager
def operation(state):
    # A persistent lock file serializes watch, backup, migration and switches.
    path=Path(state['directory'])/'operation.lock'
    with path.open('a+b') as stream:
        stream.seek(0); stream.write(b'0'); stream.flush(); stream.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try: yield
        finally:
            stream.seek(0)
            if os.name=='nt': msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else: fcntl.flock(stream,fcntl.LOCK_UN)


def source_files(root=ROOT):
    roots=['backend/app','backend/alembic','frontend/dist','infra/api','script/release','third_party']
    result=[]
    for name in roots:
        for path in sorted((root/name).rglob('*')):
            relative=path.relative_to(root)
            if path.is_symlink(): raise ValueError('Candidate cannot contain symlinks')
            if path.is_file() and not any(part.startswith('.env') or part in {'__pycache__','data','backups','private','tests','node_modules','.git'} for part in relative.parts) and path.suffix not in {'.pyc','.pyo','.pem','.key'}:
                result.append(relative)
    result.extend(Path(name) for name in ['backend/requirements.txt','backend/alembic.ini','compose.release.yml'] if (root/name).is_file())
    return sorted(result)


def file_manifest(root):
    result=[]
    for path in sorted(root.rglob('*')):
        if path.is_symlink(): raise ValueError('Symlink unsupported')
        if path.is_file(): result.append(dict(path=path.relative_to(root).as_posix(),bytes=path.stat().st_size,sha256=sha(path)))
    return result


def validate_files(root, entries):
    names=set()
    for entry in entries:
        name=entry['path']; relative=PurePosixPath(name)
        if (not name or name in names or relative.is_absolute() or '..' in relative.parts or '\\' in name or ':' in name
            or relative.as_posix()!=name or any((root/Path(*relative.parts[:i])).is_symlink() for i in range(1,len(relative.parts)+1))):
            raise ValueError('Unsafe manifest path')
        path=root/name; names.add(name)
        if not path.is_file() or path.stat().st_size!=entry['bytes'] or sha(path)!=entry['sha256']: raise ValueError('Manifest bytes differ')
    if {entry['path'] for entry in file_manifest(root)}!=names: raise ValueError('Unexpected files in snapshot')


def candidate(path):
    path=Path(path).resolve(); value=read(path)
    if not re.fullmatch('sha256:[0-9a-f]{64}',value.get('image','')): raise ValueError('Candidate requires immutable full image ID')
    if sha(path.parent/'source-manifest.json')!=value.get('source_manifest_sha256'): raise ValueError('Candidate manifest mismatch')
    inspected=json.loads(docker(['image','inspect',value['image'],'--format','{"Id":{{json .Id}},"Labels":{{json .Config.Labels}}}']))
    if inspected['Id']!=value['image']: raise ValueError('Candidate image missing')
    if (inspected.get('Labels') or {}).get('io.paperassist.source-manifest')!=value['source_manifest_sha256']: raise ValueError('Image source manifest binding differs')
    value['receipt']=str(path)
    candidate_compose(value)
    return value


def preflight(fonts):
    system=json.loads(docker(['info','--format','{{json .}}'],timeout=20))
    if system['OSType']!='linux' or system['NCPU']<4 or system['MemTotal']<7*1024**3: raise ValueError('Linux Docker requires at least 4 CPU / 7 GiB for this bounded stack')
    images={name:docker(['image','inspect',ref,'--format','{{.Id}}'],timeout=15).strip() for name,ref in [('base',BASE),('postgres',POSTGRES),('broker',BROKER),('renderer',RENDERER)]}
    missing=[name for name in FONTS if not (fonts/name).is_file()]
    if missing or not (ROOT/'frontend/dist/index.html').is_file(): raise ValueError('Local frontend dist or required fonts missing')
    checked=docker(['run','--pull=never','--network=none','--name','pa-release-requirements-'+uuid4().hex[:12],
                    '--workdir','/releaseapp','--mount',f'type=bind,source={ROOT / "backend/requirements.txt"},target=/releaseapp/requirements.txt,readonly',
                    '--mount',f'type=bind,source={ROOT / "infra/api/release_entry.py"},target=/releaseapp/release_entry.py,readonly',
                    BASE,'python','release_entry.py','requirements'],timeout=30)
    return dict(at=utc(),images=images,cpus=system['NCPU'],memory_bytes=system['MemTotal'],font_count=len(FONTS),requirements=json.loads(checked),network_calls=0)


def build(fonts):
    receipt=preflight(fonts)
    directory=RUNTIME/'candidates'/uuid4().hex; context=directory/'context'; context.mkdir(parents=True)
    entries=[]
    for relative in source_files():
        source=ROOT/relative; target=context/relative; target.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(source,target)
        entries.append(dict(path=relative.as_posix(),bytes=target.stat().st_size,sha256=sha(target)))
    atomic(directory/'source-manifest.json',entries); shutil.copyfile(directory/'source-manifest.json',context/'source-manifest.json')
    tag='paperassist-release:'+directory.name
    base_tag='paperassist-offline-base:'+BASE.split(':')[1]
    docker(['tag',BASE,base_tag])
    builder=docker(['context','show']).strip()
    description=docker(['buildx','inspect',builder])
    if not re.search(r'^Driver:\s+docker\s*$',description,re.M): raise ValueError('Offline build requires the current context Docker driver')
    docker(['build','--builder',builder,'--pull=false','--network=none','--build-arg','BASE_IMAGE='+base_tag,'--build-arg','SOURCE_MANIFEST_SHA256='+sha(directory/'source-manifest.json'),'--file',str(context/'infra/api/Dockerfile'),'--tag',tag,str(context)],timeout=600)
    image=docker(['image','inspect',tag,'--format','{{.Id}}']).strip()
    value=dict(image=image,source_manifest_sha256=sha(directory/'source-manifest.json'),created_at=utc(),preflight=receipt)
    atomic(directory/'candidate.json',value)
    return str(directory/'candidate.json')


def binding(state): return dict(schema_version=1,namespace=state['namespace'],environment='production',database_schema='public')


def maintenance(state, mode):
    if mode not in ('normal','maintenance'): raise ValueError('Invalid maintenance mode')
    path=Path(state['directory'])/'control/maintenance.json'; expected=binding(state)
    if path.exists() and any(read(path).get(key)!=value for key,value in expected.items()): raise ValueError('Maintenance binding differs')
    atomic(path,dict(expected,mode=mode,updated_at=utc(),retry_after_seconds=30))


def create(namespace,candidate_path,port,fonts):
    if not 1024<=port<=65535: raise ValueError('Explicit unprivileged HTTPS port required')
    value=candidate(candidate_path); validate_namespace(namespace)
    project='pa-release-'+namespace
    named_resources(project,fresh=True)
    if docker(['ps','-aq','--filter','label=com.docker.compose.project='+project]).strip() or docker(['volume','ls','-q','--filter','label=com.docker.compose.project='+project]).strip() or docker(['network','ls','-q','--filter','label=com.docker.compose.project='+project]).strip():
        raise ValueError('Fresh Docker target already exists')
    directory=new_directory(namespace)
    for name in ['private','tls','control','assets','backups']: (directory/name).mkdir()
    state=dict(namespace=namespace,project=project,directory=str(directory),root=str(ROOT),candidate=value,port=port,fonts=str(fonts.resolve()),initialized=False,created_at=utc())
    runtime_password=secrets.token_hex(32); owner_password=secrets.token_hex(32); broker_password=secrets.token_hex(32)
    private_files={'database-url':f'postgresql+psycopg://paperassist_runtime:{runtime_password}@db:5432/paperassist_system',
                   'migration-url':f'postgresql+psycopg://paperassist_owner:{owner_password}@db:5432/paperassist_system',
                   'postgres-password':secrets.token_hex(32),'runtime-password':runtime_password,'owner-password':owner_password,
                   'broker-url':f'amqp://paperassist:{broker_password}@broker:5672/paperassist_release_{namespace}',
                   'rabbitmq.conf':f'default_user = paperassist\ndefault_pass = {broker_password}\ndefault_vhost = paperassist_release_{namespace}\n'}
    for name,value in private_files.items(): atomic(directory/'private'/name,value)
    maintenance(state,'maintenance'); save(state)
    docker(['run','--pull=never','--network=none','--name',project+'-tls-'+uuid4().hex[:8],'--user','0',
            '--mount',f'type=bind,source={directory / "tls"},target=/run/tls',state['candidate']['image'],'python','release_entry.py','tls'],timeout=30)
    compose(state,['config','--quiet'])
    return state


def operator(state, action, *, migration=False, extra=None, timeout=120, containers=None):
    candidate_compose(state['candidate'])
    if migration:
        return compose(state,['run','--no-deps','-T','--pull','never','migration','python','release_entry.py',action,*(extra or [])],timeout=timeout)
    if action not in {'check','drain','fingerprint','collect'} or extra: raise ValueError('Unsupported collector action')
    rows=[item for item in (owned(state) if containers is None else containers) if item['service']=='collector' and item['image']==state['candidate']['image']]
    if len(rows)>1: raise ValueError('Multiple collectors for candidate')
    if rows:
        identity=rows[0]['id']
        if not rows[0]['state']['Running']: docker(['start',identity],timeout=30)
    else:
        identity=compose(state,['run','-d','--no-deps','--pull','never','--name',state['project']+'-collector-'+state['candidate']['image'].split(':')[1][:12],'collector','python','-c','import signal; signal.signal(signal.SIGTERM, lambda *_: exit(0)); signal.pause()'],timeout=30).strip()
    return docker(['exec',identity,'python','release_entry.py',action],timeout=timeout)


def stop_collector(state):
    ids=[item['id'] for item in owned(state) if item['service']=='collector' and item['state']['Running']]
    if ids: docker(['stop','-t','10',*ids],timeout=30)
    require_stopped(state,{'collector'})


def bootstrap(state):
    if state['initialized']: raise ValueError('Initialization target already used')
    compose(state,['up','-d','--pull','never','--no-build','--wait','--wait-timeout','120','db','broker'],timeout=150)
    directory=Path(state['directory'])/'private'
    runtime_password=(directory/'runtime-password').read_text(); owner_password=(directory/'owner-password').read_text()
    if not all(re.fullmatch('[0-9a-f]{64}',value) for value in [runtime_password,owner_password]): raise ValueError('Private role material invalid')
    sql=f"""CREATE ROLE paperassist_owner LOGIN PASSWORD '{owner_password}';
CREATE ROLE paperassist_runtime LOGIN PASSWORD '{runtime_password}';
ALTER DATABASE paperassist_system OWNER TO paperassist_owner;
REVOKE ALL ON DATABASE paperassist_system FROM PUBLIC;
GRANT CONNECT ON DATABASE paperassist_system TO paperassist_runtime;
ALTER SCHEMA public OWNER TO paperassist_owner;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
"""
    compose(state,['exec','-T','db','psql','-X','-v','ON_ERROR_STOP=1','-U','postgres','-d','paperassist_system'],input_text=sql)
    state['initialized']=True; state['schema_ready']=False; save(state)


def initialize(state,revision='head'):
    bootstrap(state)
    operator(state,'migrate',migration=True,extra=['--revision',revision],timeout=300)
    state['schema_ready']=revision=='head'; state['revision']=revision; save(state)
    if revision=='head': operator(state,'check')


def resume_migration(state,path,revision):
    if not state.get('initialized') or state.get('schema_ready'): raise ValueError('Resume requires bootstrapped incomplete target')
    if read(Path(state['directory'])/'control/maintenance.json').get('mode')!='maintenance': raise ValueError('Maintenance required')
    require_stopped(state,{'api','worker','dispatcher','collector'})
    selected=candidate(path); previous=state['candidate']; state['candidate']=selected; save(state)
    operator(state,'migrate',migration=True,extra=['--revision',revision],timeout=300)
    if revision=='head': operator(state,'check')
    state['schema_ready']=revision=='head'; state['revision']=revision; save(state)
    atomic(Path(state['directory'])/('resume-'+uuid4().hex+'.json'),dict(at=utc(),previous=previous,selected=selected,revision=revision))


def up(state):
    if not state.get('schema_ready'): raise ValueError('Explicit forward migration/check required before service startup')
    operator(state,'check')
    compose(state,['up','-d','--pull','never','--no-build','--wait','--wait-timeout','120','renderer','worker','dispatcher','api'],timeout=150)


def sample(state):
    observations=dict(binding(state),observed_at=utc(),services={},worker_startup_id=None,external_limits=None)
    control=Path(state['directory'])/'control'; startup=control/'worker-startup.json'
    before=read(startup) if startup.exists() else None
    containers=owned(state)
    worker_ids=[item['id'] for item in containers if item['service']=='worker' and item['state']['Running']]
    def probe(key, command):
        rows=[item for item in containers if item['service']==key and item['state']['Running']]
        status='unavailable'
        if len(rows)==1:
            try: docker(['exec',rows[0]['id'],*command],timeout=8); status='healthy'
            except RuntimeError: pass
        return key,dict(status=status,observed_at=utc())
    probes=[('worker',['python','-m','app.workers','health','worker']),('dispatcher',['python','-m','app.workers','health','dispatch']),('broker',['rabbitmq-diagnostics','-q','ping'])]
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures=[pool.submit(probe,key,command) for key,command in probes]
        observations['services']=dict(future.result() for future in futures)
    after=read(startup) if startup.exists() else None
    after_ids=docker(['ps','-q','--no-trunc','--filter','label=com.docker.compose.project='+state['project'],'--filter','label=com.docker.compose.service=worker']).split()
    if before and before==after and worker_ids==after_ids and len(worker_ids)==1 and observations['services']['worker']['status']=='healthy':
        # A receipt predating the currently running process is not effective evidence.
        worker=next(item for item in containers if item['id']==worker_ids[0])
        current=json.loads(docker(['inspect',worker['id']]))[0]
        started=datetime.fromisoformat(worker['state']['StartedAt'].replace('Z','+00:00'))
        receipt_time=datetime.fromisoformat(before['observed_at'])
        if (current['Id']==worker['id'] and current['Image']==worker['image'] and current['State']['Running']
                and current['State']['StartedAt']==worker['state']['StartedAt'] and receipt_time>=started):
            observations['worker_startup_id']=before['startup_id']
    observations['observed_at']=utc(); atomic(control/'observations.json',observations)
    operator(state,'collect',timeout=8,containers=containers)
    return read(control/'status.json')


def task_counts(state): return json.loads(operator(state,'drain',timeout=30))


def quiesce(state, timeout=180):
    maintenance(state,'maintenance')
    compose(state,['stop','-t','120','api'],timeout=140)
    require_stopped(state,{'api'})
    deadline=time.monotonic()+timeout
    while any(task_counts(state).values()):
        if time.monotonic()>=deadline: raise ValueError('Tasks did not drain; maintenance retained, no snapshot taken')
        time.sleep(2)
    compose(state,['stop','-t','120','dispatcher','worker'],timeout=140)
    require_stopped(state,{'api','dispatcher','worker'})
    if any(task_counts(state).values()): raise ValueError('Tasks changed after final stop; no snapshot taken')
    stop_collector(state)


def backup(state):
    quiesce(state)
    directory=Path(state['directory'])/'backups'/uuid4().hex; directory.mkdir()
    before=json.loads(operator(state,'fingerprint'))
    stop_collector(state)
    archive='/backups/'+directory.name+'/database.dump'
    compose(state,['exec','-T','db','pg_dump','-U','postgres','-d','paperassist_system','--format=custom','--no-owner','--no-privileges','--schema=public','--file',archive],timeout=180)
    shutil.copytree(Path(state['directory'])/'assets',directory/'assets')
    after=json.loads(operator(state,'fingerprint'))
    stop_collector(state)
    if before!=after: raise ValueError('Database changed across snapshot; retain failed evidence')
    assets=file_manifest(directory/'assets'); validate_files(Path(state['directory'])/'assets',assets)
    shutil.copyfile(Path(state['candidate']['receipt']).parent/'source-manifest.json',directory/'source-manifest.json')
    value=dict(format_version=1,namespace=state['namespace'],database_schema='public',candidate=state['candidate'],
               created_at=utc(),quiescence='api_graceful_stop_tasks_zero_executors_stopped',database_sha256=sha(directory/'database.dump'),
               source_manifest_sha256=sha(directory/'source-manifest.json'),assets=assets,fingerprint=before,retention='retain_all')
    atomic(directory/'backup.json',value); atomic(directory/'backup.sha256',sha(directory/'backup.json'))
    return str(directory)


def validate_backup(path, selected):
    path=Path(path).resolve(); value=read(path/'backup.json')
    if (sha(path/'backup.json')!=(path/'backup.sha256').read_text() or sha(path/'database.dump')!=value['database_sha256']
        or sha(path/'source-manifest.json')!=value['source_manifest_sha256'] or selected['image']!=value['candidate']['image']
        or selected['source_manifest_sha256']!=value['source_manifest_sha256']): raise ValueError('Backup/candidate pairing or hash mismatch')
    validate_files(path/'assets',value['assets'])
    return value


def restore(namespace,backup_path,candidate_path,port,fonts):
    selected=candidate(candidate_path); source=Path(backup_path).resolve(); receipt=validate_backup(source,selected)
    state=create(namespace,candidate_path,port,fonts); bootstrap(state)
    directory=Path(state['directory']); retained=directory/'backups'/'restore-input'; shutil.copytree(source,retained)
    # New target has only its empty public schema. Exclude its CREATE/COMMENT TOC records.
    archive='/backups/restore-input/database.dump'
    listing=compose(state,['exec','-T','db','pg_restore','--list',archive])
    kept=[]
    for line in listing.splitlines():
        if re.search(r' SCHEMA - public | COMMENT - SCHEMA public ',line): continue
        kept.append(line)
    atomic(retained/'restore.list','\n'.join(kept)+'\n')
    compose(state,['exec','-T','db','pg_restore','-U','postgres','-d','paperassist_system','--role=paperassist_owner','--exit-on-error','--no-owner','--no-privileges','--use-list=/backups/restore-input/restore.list',archive],timeout=180)
    shutil.copytree(source/'assets',directory/'assets',dirs_exist_ok=True)
    # upgrade(head) also grants the exact runtime metadata allowlist on restored objects.
    operator(state,'migrate',migration=True,timeout=300); operator(state,'check')
    observed=json.loads(operator(state,'fingerprint'))
    if observed!=receipt['fingerprint']: raise ValueError('Restored database fingerprint differs')
    validate_files(directory/'assets',receipt['assets'])
    state['schema_ready']=True; state['revision']='head'; save(state)
    atomic(directory/'restore-receipt.json',dict(at=utc(),source_backup=str(source),source_namespace=receipt['namespace'],target_namespace=namespace,database_and_assets_verified=True,candidate_image=selected['image']))
    return state


def switch(state,path):
    mode=read(Path(state['directory'])/'control/maintenance.json')
    if mode.get('mode')!='maintenance': raise ValueError('Explicit maintenance window required for candidate switch')
    selected=candidate(path)
    if state.get('schema_ready'): quiesce(state)
    else: require_stopped(state,{'api','worker','dispatcher','collector'})
    previous=state['candidate']; state['candidate']=selected
    # A failed switch keeps the selected image and maintenance intent for diagnosis.
    save(state); operator(state,'migrate',migration=True,timeout=300); operator(state,'check')
    state['schema_ready']=True; state['revision']='head'; save(state)
    atomic(Path(state['directory'])/('switch-'+uuid4().hex+'.json'),dict(at=utc(),previous=previous,selected=selected,forward_migration_verified=True))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['preflight','build','create','init','resume-migration','up','status','sample','watch','maintenance','backup','restore','switch','stop'])
    parser.add_argument('--namespace'); parser.add_argument('--candidate'); parser.add_argument('--backup')
    parser.add_argument('--port',type=int); parser.add_argument('--fonts',type=Path,default=Path('C:/Windows/Fonts'))
    parser.add_argument('--mode',choices=['normal','maintenance']); parser.add_argument('--revision',choices=['head','0052_admin_configurations'],default='head')
    args=parser.parse_args()
    try:
        if args.action=='preflight': result=preflight(args.fonts)
        elif args.action=='build': result=build(args.fonts)
        elif args.action in ('create','restore'):
            if not args.namespace or not args.candidate or args.port is None: raise ValueError('namespace, candidate and port required')
            if args.action=='restore':
                if not args.backup: raise ValueError('backup required')
                state=restore(args.namespace,args.backup,args.candidate,args.port,args.fonts)
            else: state=create(args.namespace,args.candidate,args.port,args.fonts)
            result=dict(namespace=state['namespace'],directory=state['directory'])
        else:
            if not args.namespace: raise ValueError('namespace required')
            state=load(args.namespace,verify_resources=args.action not in ('sample','watch'))
            if args.action=='watch':
                while True:
                    started=time.monotonic()
                    try:
                        with operation(state): sample(load(args.namespace,verify_resources=False))
                    except (OSError,RuntimeError,ValueError): print('Sample unavailable; retained receipt will become unknown after 45 seconds.',flush=True)
                    time.sleep(max(0,15-(time.monotonic()-started)))
            with operation(state):
                if args.action=='init': initialize(state,args.revision); result={'initialized':True,'revision':args.revision}
                elif args.action=='resume-migration': resume_migration(state,args.candidate,args.revision); result={'resumed':True,'revision':args.revision}
                elif args.action=='up': up(state); result={'started':True,'maintenance_unchanged':True}
                elif args.action=='sample': result=sample(state)
                elif args.action=='status': result={'containers':owned(state),'maintenance':read(Path(state['directory'])/'control/maintenance.json')}
                elif args.action=='maintenance': maintenance(state,args.mode); result={'mode':args.mode}
                elif args.action=='backup': result={'backup':backup(state)}
                elif args.action=='switch': switch(state,args.candidate); result={'switched':True,'maintenance_unchanged':True}
                elif args.action=='stop': compose(state,['stop','-t','120'],timeout=180); stop_collector(state); result={'stopped':True,'retention':'retain_all'}
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    except KeyboardInterrupt: return 130
    except (ValueError,RuntimeError,OSError,KeyError,TypeError,subprocess.SubprocessError):
        print('Release operation failed; isolated target/evidence retained. Verify explicit arguments, local images, ownership, hashes and private service diagnostics. No credentials are printed.',file=sys.stderr)
        return 1


if __name__=='__main__': raise SystemExit(main())
