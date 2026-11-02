"""Acquire and execute only the actual B05 formal packages, offline and serially."""
import argparse
import hashlib
import json
from pathlib import Path,PurePosixPath
import stat
import subprocess
from uuid import uuid4
import zipfile

from verify_cr_b05_acceptance import Acceptance,profiles,control
from verify_cr_b04_reproducibility import checked_package_metadata,load_reproducer


def extract_checked(archive_path,folder):
    with zipfile.ZipFile(archive_path) as archive:
        items=archive.infolist();names=[m.filename for m in items]
        if len(names)!=len(set(names)) or len(items)>10000 or sum(m.file_size for m in items)>2*1024**3:raise ValueError('Package member budget or uniqueness differs')
        for m in items:
            path=PurePosixPath(m.filename)
            if (m.orig_filename!=m.filename or not m.filename or path.is_absolute() or path.as_posix()!=m.filename or '\\' in m.filename or ':' in m.filename
                    or any(p in ('.','..') for p in path.parts) or stat.S_ISLNK(m.external_attr>>16)
                    or not (folder/m.filename).resolve().is_relative_to(folder.resolve())):raise ValueError('Unsafe package member path')
        for m in items:
            if m.is_dir():continue
            path=folder/m.filename;path.parent.mkdir(parents=True,exist_ok=True)
            raw=archive.read(m)
            if path.exists():
                if path.read_bytes()!=raw:raise ValueError('Retained package file differs; not overwriting')
            else:
                with path.open('xb') as handle:handle.write(raw)


def acquire(acceptance,label,kind):
    result=acceptance.record['results'][label+'-'+kind];key=label+'-'+kind
    root=acceptance.output/'reproduction'/key;root.mkdir(parents=True,exist_ok=True)
    receipt_path=root/'acquisition.json';archive_path=root/'formal-package.zip';package=root/'package'
    if receipt_path.exists():
        receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
        assert receipt['result_id']==result['id'] and receipt['archive_sha256']==hashlib.sha256(archive_path.read_bytes()).hexdigest()
    else:
        if archive_path.exists():raise ValueError('Unreceipted archive retained; inspect before any new download')
        url=acceptance.base(result['project_id'])+'/bio-insight-results/'+result['id']+'/reproducibility-package'
        with acceptance.client.stream('GET',url) as response:
            response.raise_for_status();anchor=response.headers['X-Reproducibility-Manifest-SHA256'];size=0;sha=hashlib.sha256()
            with archive_path.open('xb') as handle:
                for chunk in response.iter_bytes():
                    size+=len(chunk)
                    if size>2*1024**3:raise ValueError('Formal reproduction ZIP exceeds budget')
                    sha.update(chunk);handle.write(chunk)
        receipt=dict(project_id=result['project_id'],result_id=result['id'],manifest_sha256=anchor,archive_sha256=sha.hexdigest(),archive_bytes=size)
        receipt_path.write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    extract_checked(archive_path,package);metadata=checked_package_metadata(package,receipt['manifest_sha256'])
    assert metadata['identity']['result_version_id']==result['id'] and metadata['identity']['project_id']==result['project_id']
    assert metadata['formal_manifest_sha256']==result['manifest_sha256'] and metadata['analysis_inputs_self_contained'] is True
    verification=load_reproducer(package/'reproduce.py').operate(package,'verify',manifest_sha256=receipt['manifest_sha256'])
    (root/'verification.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2),encoding='utf-8')
    return root,package,receipt


def execute(acceptance,label,kind,action,*,acquired=None):
    root,package,receipt=acquired if acquired is not None else acquire(acceptance,label,kind)
    if action=='verify':return dict(status='passed',operation=action,evidence=str(root))
    state=control.read_state();image=state['worker_image_id']
    assert image==control.worker_stack.docker(['image','inspect','--format','{{.Id}}',control.WORKER_IMAGE]).strip()
    available=int(control.worker_stack.docker(['run','--rm','--network','none','--read-only','--memory','64m','--entrypoint','python',image,'-c',"from pathlib import Path;print(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:')))"]).strip())*1024
    if available<4*1024**3:raise ValueError('Docker MemAvailable below 4GiB')
    attempt=root/('attempt-'+action+'-'+uuid4().hex);attempt.mkdir();name='pa-b05-reproduce-'+uuid4().hex[:20]
    command=['docker','run','--name',name,'--network','none','--read-only','--memory','4g','--cpus','1','--pids-limit','64','--tmpfs','/tmp:rw,size=1g',
        '--mount','type=bind,source='+str(package)+',target=/package,readonly','--mount','type=bind,source='+str(attempt)+',target=/attempt',
        '--entrypoint','/opt/paperassist-bio-insights/bin/python',image,'-B','/package/reproduce.py',action,'--output','/attempt/output','--manifest-sha256',receipt['manifest_sha256']]
    (attempt/'request.json').write_text(json.dumps(dict(command=command,image=image,container=name),indent=2),encoding='utf-8')
    with (attempt/'stdout.json').open('wb') as out,(attempt/'stderr.txt').open('wb') as err:
        try:completed=subprocess.run(command,stdout=out,stderr=err,timeout=2100,cwd=control.ROOT)
        except subprocess.TimeoutExpired:
            control.worker_stack.docker(['stop','--time','10',name],timeout=30)
            raise RuntimeError('Reproduction timed out; exact attempt/container retained') from None
    (attempt/'completion.json').write_text(json.dumps(dict(exit_code=completed.returncode,container_retained=True)),encoding='utf-8')
    if completed.returncode:raise RuntimeError('Reproduction failed; evidence retained at '+str(attempt))
    operation=json.loads((attempt/'output/operation.json').read_text(encoding='utf-8'))
    assert operation['status']=='completed' and operation['comparison']['passed'] is True
    assert operation['execution']['child_peak_rss_bytes']<2*1024**3 and operation['execution']['violation'] is None
    acceptance.record.setdefault('reproductions',{})[label+'-'+kind]=dict(operation=action,status='passed',evidence=str(attempt),manifest_sha256=receipt['manifest_sha256'],peak_rss_bytes=operation['execution']['child_peak_rss_bytes'])
    acceptance.save();return dict(status='passed',operation=action,evidence=str(attempt))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--path',required=True,choices=list(profiles()));parser.add_argument('--kind',choices=['comparison','distribution'],required=True);parser.add_argument('--operation',choices=['verify','recompute','render'],default='verify');parser.add_argument('--evidence',default='acceptance');args=parser.parse_args()
    if (args.operation=='recompute' and args.kind!='comparison') or (args.operation=='render' and args.kind!='distribution'):parser.error('Use comparison recompute or exact distribution render')
    print(json.dumps(execute(Acceptance(args.evidence),args.path,args.kind,args.operation),ensure_ascii=False))
