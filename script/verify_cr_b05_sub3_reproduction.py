"""Scoped new-package exports, one verification and one requested offline operation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'script'),str(ROOT/'script/dev'),str(ROOT/'backend')]
from verify_cr_b05_sub3_acceptance import Acceptance,control
import verify_cr_b05_reproduction as insights
import verify_cr_b02_reproducibility as cells
os.environ['PAPERASSIST_CR_B05_SUBPACKAGE']='3'

def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def read(path):return json.loads(path.read_bytes())

def cell_package(acceptance):
    root=acceptance.output/'reproduction/pbmc3k';root.mkdir(parents=True,exist_ok=True);package=root/'package'
    receipt=root/'verification.json'
    if receipt.exists():return root,package,read(receipt)
    item=acceptance.record['paths']['pbmc3k'];base=acceptance.base(item['project_id'])
    original=acceptance.get(base+'/bio-processed-datasets/'+item['processed_id'])
    recipe=acceptance.get(base+'/bio-analysis-setups/'+item['setup_id']+'/recipes/'+original['source']['recipe_version_id'])
    # Reuse already downloaded, SHA-addressed formal members and the authorized original.
    local={}
    for folder in [acceptance.output/'delivery',control.RUNTIME/'materials/original']:
        for path in folder.rglob('*'):
            if path.is_file():local.setdefault(cells.sha256(path),path)
    old_download=cells.download;old_copy=cells.copy_code
    def reuse_download(view,member,path):
        source=local.get(member['sha256'])
        if source is None:return old_download(view,member,path)
        assert source.stat().st_size==member['size_bytes']
        path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,path)
        return dict(path=path.name,sha256=member['sha256'],size_bytes=member['size_bytes'])
    def code_closure(target):
        old_copy(target)
        for name in ('contracts.py','analysis_contracts.py','analysis_settings.py','single_cell_contracts.py'):
            source=ROOT/'backend/app/domain/bioinformatics'/name
            shutil.copyfile(source,target/'code/app/domain/bioinformatics'/name)
    cells.download=reuse_download;cells.copy_code=code_closure
    view=SimpleNamespace(base=base,get=acceptance.get,check=acceptance.check,client=acceptance.client)
    gate=read(control.BIO_GATE)
    # Avoid exposing local evidence paths; provenance stays in the external acceptance ledger.
    environment=dict(engine_version=gate['engine_version'],environment_digest=gate['environment_digest'],image_digest=gate['image_digest'],validation_scope='accepted numerical environment reused; new cell worker verified')
    try:package=cells.export_package(view,original,recipe,gate,environment,root)
    finally:cells.download=old_download;cells.copy_code=old_copy
    text=(package/'README.md').read_text(encoding='utf-8').replace('CR-B02','CR-B05 子包三').replace('结果仅用于 spot 层探索','结果仅用于单供体 cell 层探索；不能按细胞数量扩充独立供体 n').replace('V16/V17','本包')
    (package/'README.md').write_text(text,encoding='utf-8')
    metadata=read(package/'package.json');metadata['files']=[dict(path=p.relative_to(package).as_posix(),size_bytes=p.stat().st_size,sha256=cells.sha256(p)) for p in sorted(package.rglob('*')) if p.is_file() and p.name!='package.json']
    save(package/'package.json',metadata)
    for entry in metadata['files']:
        path=package/entry['path'];assert path.stat().st_size==entry['size_bytes'] and cells.sha256(path)==entry['sha256']
    proof=dict(status='passed',scope='all portable package members checked once',members=len(metadata['files']),package_sha256=cells.sha256(package/'package.json'),processed_id=original['id'],source=original['source'])
    save(receipt,proof);return root,package,proof


def insight_package(acceptance,kind):
    root=acceptance.output/'reproduction'/('enterotype-'+kind)
    if (root/'verification.json').exists():return root,root/'package',read(root/'acquisition.json')
    return insights.acquire(acceptance,'enterotype',kind)


def execute(acceptance,label,kind,action):
    root,package,receipt=cell_package(acceptance) if label=='pbmc3k' else insight_package(acceptance,kind)
    if action=='verify':return dict(status='passed',evidence=str(root/'verification.json'))
    done=root/(action+'-completed.json')
    if done.exists():return read(done)
    image=acceptance.state['worker_image_id'];attempt=root/('attempt-'+action+'-'+uuid4().hex);attempt.mkdir()
    name='pa-b05-sub3-repro-'+uuid4().hex[:16]
    interpreter='/opt/paperassist-bio/bin/python' if label=='pbmc3k' else '/opt/paperassist-bio-insights/bin/python'
    common=['docker','run','--name',name,'--network','none','--read-only','--memory','4g','--cpus','1','--pids-limit','64','--tmpfs','/tmp:rw,size=1g','--mount','type=bind,source='+str(package)+',target=/package,readonly','--mount','type=bind,source='+str(attempt)+',target=/attempt','--entrypoint',interpreter,image,'-B']
    args=['/package/reproduce.py','--output','/attempt/output'] if label=='pbmc3k' else ['/package/reproduce.py',action,'--output','/attempt/output','--manifest-sha256',receipt['manifest_sha256']]
    save(attempt/'request.json',dict(command=common+args,image=image))
    with (attempt/'stdout.json').open('wb') as out,(attempt/'stderr.txt').open('wb') as err:
        result=subprocess.run(common+args,stdout=out,stderr=err,timeout=2100,cwd=ROOT)
    save(attempt/'completion.json',dict(exit_code=result.returncode,container_retained=True))
    if result.returncode:raise RuntimeError('New reproduction failed; see '+str(attempt))
    if label=='pbmc3k':
        compare=common.copy();compare[compare.index('--name')+1]=name+'-compare'
        compared=subprocess.run(compare+['/package/compare.py','/package/baseline','/attempt/output','--report','/attempt/comparison.json'],capture_output=True,timeout=300)
        (attempt/'compare.stdout').write_bytes(compared.stdout);(attempt/'compare.stderr').write_bytes(compared.stderr)
        if compared.returncode:raise RuntimeError('New cell comparison failed; see '+str(attempt))
        operation=read(attempt/'output/result.json')['execution'];assert operation['violation'] is None and operation['child_peak_rss_bytes']<2*1024**3
        assert read(attempt/'comparison.json')['status']=='passed'
    else:
        operation=read(attempt/'output/operation.json');assert operation['status']=='completed' and operation['comparison']['passed'] is True
        assert operation['execution']['violation'] is None and operation['execution']['child_peak_rss_bytes']<2*1024**3
    proof=dict(status='passed',operation=action,evidence=str(attempt));save(done,proof)
    acceptance.record.setdefault('reproductions',{})[label+'-'+kind+'-'+action]=proof;acceptance.save();return proof

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('label',choices=['pbmc3k','enterotype']);parser.add_argument('--kind',choices=['comparison','figure'],default='comparison');parser.add_argument('--operation',choices=['verify','recompute','render'],default='verify');args=parser.parse_args()
    if args.label=='pbmc3k' and (args.kind!='comparison' or args.operation=='render'):parser.error('Cell package supports verify/recompute only')
    if args.label=='enterotype' and (args.operation=='render' and args.kind!='figure' or args.operation=='recompute' and args.kind!='comparison'):parser.error('Use comparison recompute or figure render')
    acceptance=Acceptance()
    try:print(json.dumps(execute(acceptance,args.label,args.kind,args.operation),ensure_ascii=False))
    finally:acceptance.client.close()
