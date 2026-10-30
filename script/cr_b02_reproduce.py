"""Standalone offline entry point copied as reproduce.py into each delivery."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import struct
import subprocess
import sys
import time


def relative_file(root, name):
    if not isinstance(name,str) or not name or '\\' in name or ':' in name:
        raise ValueError('Package paths must be local relative POSIX paths')
    path=PurePosixPath(name)
    if path.is_absolute() or PureWindowsPath(name).is_absolute() or '..' in path.parts:
        raise ValueError('Package path escape')
    target=root.joinpath(*path.parts)
    if not target.resolve().is_relative_to(root.resolve()) or any(p.is_symlink() for p in [target,*target.parents] if p.is_relative_to(root)):
        raise ValueError('Package symlink/path escape')
    return target


def sha256(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        while block:=stream.read(1024**2): digest.update(block)
    return digest.hexdigest()


def main():
    parser=argparse.ArgumentParser(description='Reproduce only the supplied fixed analysis, without API credentials or network.')
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parent
    package=json.loads((root/'package.json').read_bytes())
    for item in package['files']:
        path=relative_file(root,item['path'])
        if path.stat().st_size!=item['size_bytes'] or sha256(path)!=item['sha256']:
            raise ValueError('Exported package integrity differs: '+item['path'])
    payload=json.loads((root/'input/payload.json').read_bytes())
    for member in payload['raw']['members'].values(): member['path']=str(relative_file(root,member['path']))
    output=Path(args.output).resolve()
    output.mkdir(parents=True,exist_ok=True)
    if any(output.iterdir()): raise ValueError('Output must be a new empty directory; old failures are preserved')
    payload['output_directory']=str(output)
    body=json.dumps(payload,ensure_ascii=False,allow_nan=False).encode()
    worker=root/'code/app/adapters/bio_engine/worker.py'
    # -I ignores host/user Python paths; worker locates only the exported code tree.
    command=[sys.executable,'-I','-B',str(worker),str(os.getpid())]
    started=time.monotonic()
    process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        env={'PATH':os.environ.get('PATH',''),'LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1'})
    # Worker contract adds CPU/address-space limits; this parent enforces RSS.
    import threading
    outcome={}
    def communicate():
        try: outcome['streams']=process.communicate(struct.pack('!I',len(body))+body)
        except BaseException as exc: outcome['exception']=exc
    thread=threading.Thread(target=communicate,daemon=True); thread.start()
    peak=0; violation=None
    while thread.is_alive():
        if time.monotonic()-started>1380: violation='wall_1380_seconds'
        try:
            status=Path('/proc')/str(process.pid)/'status'
            fields=dict(line.split(':',1) for line in status.read_text().splitlines() if ':' in line)
            current=int(fields.get('VmRSS','0 kB').split()[0])*1024
            peak=max(peak,current)
            if current>2*1024**3: violation='child_RSS_2GiB'
        except (OSError,ValueError): pass
        if violation: process.kill()
        thread.join(.1)
    if 'exception' in outcome: raise outcome['exception']
    stdout,stderr=outcome['streams']
    (output/'worker.stdout.bin').write_bytes(stdout); (output/'worker.stderr.txt').write_bytes(stderr)
    receipt={'exit_code':process.returncode,'child_peak_rss_bytes':peak,'wall_seconds':time.monotonic()-started,
        'rss_limit_bytes':2*1024**3,'wall_limit_seconds':1380,'violation':violation,'engine_code_digest':package['gate']['code_digest']}
    result=None
    if stdout.startswith(b'READY\n'):
        try: result=json.loads(stdout.removeprefix(b'READY\n'))
        except ValueError: pass
    receipt['worker_status']='completed' if result and 'result' in result else 'failed'
    (output/'result.json').write_text(json.dumps({'execution':receipt,'worker':result},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if process.returncode or violation or not result or 'error' in result: raise RuntimeError('Reproduction failed; output logs retained')
    print(json.dumps(receipt))


if __name__=='__main__': main()
