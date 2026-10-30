"""Export fixed authorized inputs; verify independent queue and offline runs.

No schemas/services/volumes are removed. Each attempt and failed output is kept.
Only this script's new disposable verification containers use --rm.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import time
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'script/dev'))
import cr_b02_runner as control
from verify_cr_b02_queue import Verification


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def sha256(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block:=stream.read(1024**2): digest.update(block)
    return digest.hexdigest()


def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(canonical(value)+b'\n')


def safe_name(value):
    if not isinstance(value,str) or not value or PurePosixPath(value).name!=value or any(c in value for c in '\\:') or value in {'.','..'}:
        raise ValueError('Unsafe exported file name')
    return value


def public_record(value):
    """Exclude storage routing and authenticated URLs from portable documents."""
    if isinstance(value,dict): return {k:public_record(v) for k,v in value.items() if k not in {'path','object_key','download_url'}}
    if isinstance(value,list): return [public_record(v) for v in value]
    if isinstance(value,str) and (re.search(r'(?<![A-Za-z0-9])[A-Za-z]:[\\/]',value) or value.startswith(('\\\\','file://'))):
        raise ValueError('Private absolute path cannot enter reproduction package')
    return value


def download(verification,member,path):
    """Stream authorized HTTP bytes to an attempt-owned path and verify identity."""
    path.parent.mkdir(parents=True,exist_ok=True)
    digest,size=hashlib.sha256(),0
    if path.exists(): raise ValueError('Retained download cannot be overwritten')
    with path.open('xb') as stream:
        with verification.client.stream('GET',member['download_url']) as response:
            verification.check(response)
            for block in response.iter_bytes():
                stream.write(block);digest.update(block);size+=len(block)
    if digest.hexdigest()!=member['sha256'] or size!=member['size_bytes']:
        raise RuntimeError('Authorized member hash/size differs; failed download retained')
    return dict(path=path.name,sha256=digest.hexdigest(),size_bytes=size)


def command(command,evidence,label,*,timeout=1500,allow_failure=False):
    started=time.monotonic()
    try:
        result=subprocess.run(command,cwd=ROOT,capture_output=True,timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        (evidence/(label+'.stdout')).write_bytes(exc.stdout or b'')
        (evidence/(label+'.stderr')).write_bytes(exc.stderr or b'')
        write_json(evidence/(label+'.command.json'),dict(command=command,exit_code=None,
            wall_seconds=time.monotonic()-started,timeout_seconds=timeout,status='timed_out'))
        raise RuntimeError('Scoped command timed out: '+label+'; partial logs retained') from exc
    (evidence/(label+'.stdout')).write_bytes(result.stdout)
    (evidence/(label+'.stderr')).write_bytes(result.stderr)
    receipt=dict(command=command,exit_code=result.returncode,wall_seconds=time.monotonic()-started)
    write_json(evidence/(label+'.command.json'),receipt)
    if result.returncode and not allow_failure: raise RuntimeError('Scoped command failed: '+label+'; raw logs retained')
    return result.stdout


def docker_base(image):
    if not re.fullmatch(r'sha256:[a-f0-9]{64}',image): raise ValueError('Docker config identity must be immutable')
    return ['docker','run','--rm','--network','none','--read-only','--memory','2g','--cpus','1',
        '--tmpfs','/tmp:rw,nosuid,nodev,size=512m,mode=1777']


def code_sources():
    backend=ROOT/'backend'
    return [*sorted((backend/'app/adapters/bio_engine').glob('*.py')),
        *sorted((backend/'app/adapters/bio_parser').glob('*.py')),
        *[backend/path for path in ['app/adapters/excel_sandbox.py','app/core/exceptions.py',
            'app/domain/bioinformatics/settings.py','app/domain/bioinformatics/parser_contracts.py']]]


def check_gate(evidence):
    from app.domain.bioinformatics.analysis_settings import engine_code_digest,engine_lock_digest
    gate=json.loads(control.GATE.read_bytes())
    if gate.get('gate_status')!='passed' or gate['code_digest']!=engine_code_digest() or gate['lock_sha256']!=engine_lock_digest():
        raise RuntimeError('Current code/lock/runtime gate is unavailable or stale')
    image=gate['image_digest']
    inspection=json.loads(command(['docker','image','inspect',image],evidence,'fixed-image-inspect'))[0]
    if inspection['Id']!=image or inspection['Os']+'/'+inspection['Architecture']!=gate['platform']:
        raise RuntimeError('Fixed local image/platform differs from gate')
    code="from pathlib import Path;import hashlib,json;r=Path('/app/app/adapters/bio_engine');h=hashlib.sha256();[(h.update(p.relative_to(r).as_posix().encode()+b'\\0'+p.read_bytes()+b'\\0')) for p in sorted(r.rglob('*.py'),key=lambda p:p.relative_to(r).as_posix())];print(json.dumps({'code_digest':h.hexdigest(),'lock_sha256':hashlib.sha256(Path('/app/requirements-bio.lock.txt').read_bytes()).hexdigest()}))"
    actual=json.loads(command([*docker_base(image),image,'/opt/paperassist-bio/bin/python','-c',code],evidence,'image-code-lock'))
    if any(actual[k]!=gate[k] for k in ('code_digest','lock_sha256')): raise RuntimeError('Fixed image code/lock differs from package source')
    expected={path.relative_to(ROOT/'backend').as_posix():sha256(path) for path in code_sources()}
    closure="from pathlib import Path;import hashlib,json;files="+repr(list(expected))+";print(json.dumps({p:hashlib.sha256((Path('/app')/p).read_bytes()).hexdigest() for p in files}))"
    actual_closure=json.loads(command([*docker_base(image),image,'/opt/paperassist-bio/bin/python','-c',closure],evidence,'image-shared-code-closure'))
    if expected!=actual_closure:raise RuntimeError('Shared scientific source closure differs from fixed image')
    gate_evidence=json.loads((control.RUNTIME/'runtime-gate-evidence.json').read_bytes())
    environment=gate_evidence['environment_identity']
    if hashlib.sha256(canonical(environment)).hexdigest()!=gate['environment_digest']:
        raise RuntimeError('Saved native/font/environment fingerprint differs from gate')
    return gate,environment


def export_result(v,result,destination):
    destination.mkdir(parents=True)
    members=[]
    for member in result['members']:
        filename=safe_name(member['key']+'.'+member['format'])
        download(v,member,destination/filename)
        members.append({k:member[k] for k in ('key','role','format','sha256','size_bytes')}|{'filename':filename})
    write_json(destination/'baseline.json',{'source':public_record(result['source']),'members':members})
    return members


def copy_code(package):
    backend=ROOT/'backend'
    # Small, explicit source closure: scientific engine imports the B01 parser
    # during trusted warmup; no database/API/config modules are exported.
    for source in code_sources():
        target=package/'code'/source.relative_to(backend)
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    for path in ['app','app/adapters','app/core','app/domain','app/domain/bioinformatics']:
        (package/'code'/path/'__init__.py').write_bytes(b'')
    shutil.copyfile(ROOT/'backend/requirements-bio.lock.txt',package/'requirements-bio.lock.txt')
    shutil.copyfile(ROOT/'script/cr_b02_reproduce.py',package/'reproduce.py')
    shutil.copyfile(ROOT/'script/cr_b02_repro_compare.py',package/'compare.py')
    dockerfile=(ROOT/'infra/worker/Dockerfile').read_text(encoding='utf-8').split('\nFROM ',1)[0]
    dockerfile=dockerfile.replace('COPY backend/requirements-bio.lock.txt','COPY requirements-bio.lock.txt')
    dockerfile=dockerfile.replace('COPY backend/app /app/app','COPY code/app /app/app')
    dockerfile=dockerfile.replace('COPY backend/tests/numeric /app/tests/numeric\n','')
    (package/'Dockerfile').write_text(dockerfile,encoding='utf-8')


def mapping_payload(v,recipe,original):
    identifier=recipe.get('observation_map_version_id')
    if not identifier:return None,None
    path=v.base+'/bio-observation-maps/'+recipe['observation_map_set_id']+'/versions/'+identifier
    first=v.get(path+'?page=1&page_size=100');rows=list(first['rows'])
    for page in range(2,(first['total']+99)//100+1): rows.extend(v.get(path+f'?page={page}&page_size=100')['rows'])
    # Canonical API reconstruction is accepted only if it matches the actual
    # mapping bytes read by the fixed original run. Never assert equivalence
    # from a preview or partial page.
    value=dict(schema_version=1,name=first['name'],raw_source=first['raw_source'],
        design_version_id=first['design_version_id'],table_source=None,rows=rows)
    content=canonical(value)
    member=next(i for i in original['manifest']['inputs'] if i['key']=='observation_map_index')
    if hashlib.sha256(content).hexdigest()!=member['sha256'] or len(content)!=member['size_bytes']:
        raise RuntimeError('Mapping API reconstruction does not match frozen input bytes; export blocked')
    return content,member


def export_package(v,original,recipe,gate,environment,directory):
    package=directory/'package';package.mkdir()
    copy_code(package)
    source=recipe['raw_source']
    raw_path=v.base+'/bio-datasets/'+source['dataset_id']+'/versions/'+source['dataset_version_id']
    raw=v.get(raw_path)
    if raw['source']!=source: raise RuntimeError('Fixed raw source differs')
    manifest_response=v.check(v.client.get(raw_path+'/manifest'))
    raw_content=manifest_response.content
    if hashlib.sha256(raw_content).hexdigest()!=source['manifest_sha256']:raise RuntimeError('Raw manifest bytes differ')
    raw_manifest=json.loads(raw_content)
    public_record(raw_manifest)  # Fail if an input has a private host path.
    write_json(package/'input/raw-manifest.json',raw_manifest)
    # Preserve exact original manifest bytes for the source SHA identity.
    (package/'input/raw-manifest.json').write_bytes(raw_content)
    public_members={m['id']:m for m in raw['members']};members={}
    for record in raw_manifest['members']:
        member=public_members[record['id']]
        if any(member[k]!=record[k] for k in ('sha256','size_bytes')):raise RuntimeError('Raw member manifest mismatch')
        filename=safe_name(record['key']+'.'+record['format'])
        relative='input/raw/'+filename
        download(v,member,package/relative)
        members[record['key']]=public_record(record)|{'path':relative}
    mapping_content,mapping_member=mapping_payload(v,recipe,original)
    if mapping_content is not None:
        (package/'input/observation-map.json').write_bytes(mapping_content)
        members['observation_map_index']=public_record(mapping_member)|{'path':'input/observation-map.json'}
    design_id=recipe.get('design_version_id')
    design=v.get(v.base+'/research-designs/'+design_id) if design_id else {'design_version_id':None,'status':'unconfirmed'}
    write_json(package/'input/design.json',public_record(design))
    files={f['id']:f for f in v.get(v.base+'/files')}
    originals=[]
    for frozen in raw_manifest['source_files']:
        item=files[frozen['id']]
        if item['sha256']!=frozen['sha256']:raise RuntimeError('Original source hash changed')
        filename=safe_name(item['filename'])
        relative='input/originals/'+item['id']+'/'+filename
        descriptor={'download_url':v.base+'/files/'+item['id']+'/download','sha256':frozen['sha256'],
            'size_bytes':frozen['size_bytes']}
        download(v,descriptor,package/relative)
        originals.append(public_record(frozen)|{'path':relative})
    actual={i['key']:i for i in original['manifest']['inputs']}
    if actual.keys()!=members.keys() or any(actual[k]['sha256']!=members[k]['sha256'] or actual[k]['size_bytes']!=members[k]['size_bytes'] for k in actual):
        raise RuntimeError('Package does not cover every actual original input')
    identity=public_record(original['manifest']['identity'])
    if identity.get('code_digest')!=gate['code_digest'] or identity.get('environment_digest')!=gate['environment_digest']:
        raise RuntimeError('Original analysis code/environment differs from current fixed gate')
    payload={'mode':'compute','raw':{'manifest':raw_manifest,'members':members},'config':recipe['params'],'identity':identity}
    write_json(package/'input/payload.json',public_record(payload))
    # public_record strips a path property by design: reinsert only generated,
    # verified relative paths into the portable worker payload.
    payload['raw']['members']={k:public_record(m)|{'path':m['path']} for k,m in members.items()}
    write_json(package/'input/payload.json',payload)
    write_json(package/'input/recipe.json',public_record(recipe))
    write_json(package/'input/processed-source.json',public_record(original['source']))
    write_json(package/'input/originals.json',originals)
    write_json(package/'environment.json',environment)
    write_json(package/'gate.json',gate)
    baseline=export_result(v,original,package/'baseline')
    readme=f'''# CR-B02 离线复现包

固定来源、配方、映射/设计身份、随机种子、原件、全部实际输入、科学源码闭包和完整 wheel-hash lock 均见 package.json 及 input/。包不需要账号、API 或在线数据下载。未知供体/分组仍未知；结果仅用于 spot 层探索。

已安装固定环境：Linux 同平台 {gate['platform']}，Docker image config ID `{gate['image_digest']}`。该 ID 只在本机镜像存储中可用；向其他机器分发时需自行传输该镜像。所有输入按 SHA256/size 重新校验。

在本包目录运行（将挂载源设为本包与一个新的空输出目录；示例使用 shell 当前目录，无私有固定路径）：

```sh
mkdir output
docker run --rm --network none --read-only --memory 2g --cpus 1 --tmpfs /tmp:rw,nosuid,nodev,size=512m,mode=1777 --mount "type=bind,source=$PWD,target=/bundle,readonly" --mount "type=bind,source=$PWD/output,target=/output" {gate['image_digest']} /opt/paperassist-bio/bin/python /bundle/reproduce.py --output /output
docker run --rm --network none --read-only --memory 2g --cpus 1 --tmpfs /tmp:rw,nosuid,nodev,size=512m,mode=1777 --mount "type=bind,source=$PWD,target=/bundle,readonly" --mount "type=bind,source=$PWD/output,target=/output" {gate['image_digest']} /opt/paperassist-bio/bin/python /bundle/compare.py /bundle/baseline /output --report /output/comparison.json
```

父脚本监测 child RSS≤2GiB、wall≤1380s（含预热）；子进程在读取用户输入前完成单线程预热、Landlock/seccomp 隔离，并设置 CPU 900s、地址空间 3GiB 等限制。容器 CPU=1、总内存=2GiB、网络关闭、根文件系统只读。绝不删除失败输出，换新空目录再运行。

PNG/PDF 规范字节 SHA 完全一致；整数/轴/mask/cluster/marker 排序与 NA mask 完全一致；float32 数值 rtol=1e-5 atol=1e-6；marker float64 rtol=1e-8 atol=1e-12；PCA 以绝对最大载荷及稳定 feature ID 统一符号；H5AD 核对层、轴、属性、稀疏数值，不要求压缩容器字节相同。时间/资源及外层运行身份不作为科学差异。

Dockerfile 是其他机器构建备选，使用固定官方 Python base digest、完整 hash lock 与固定字体/libgomp 版本。构建会联网安装公开依赖；此备选未自动执行，不代表已完成另一机器/另一平台新安装。Linux runtime 路径属于公开镜像布局，包不含客户主机绝对路径。

V16/V17 的已执行状态以包外保留的 report.json / report.zh-CN.txt 为准。工程复现通过不等于生物学验证或用户验收。
'''
    (package/'README.md').write_text(readme,encoding='utf-8')
    indexed=[]
    for path in sorted(package.rglob('*')):
        if path.is_file():
            indexed.append(dict(path=path.relative_to(package).as_posix(),size_bytes=path.stat().st_size,sha256=sha256(path)))
    metadata={'schema_version':1,'gate':gate,'source':original['source'],'recipe_version_id':recipe['id'],
        'observation_map_version_id':recipe.get('observation_map_version_id'),'design_version_id':design_id,
        'files':indexed,'baseline_member_count':len(baseline),'fresh_installation':'not_performed',
        'fresh_environment_method':'new_container_fixed_local_config_id_same_platform','biological_validation':'not_performed','user_acceptance':'pending'}
    write_json(package/'package.json',metadata)
    # Check exported textual files for private path strings and secret artifacts.
    for path in package.rglob('*'):
        if path.is_file() and path.suffix in {'.json','.md','.py','.txt'}:
            value=path.read_text(encoding='utf-8')
            if str(ROOT) in value or re.search(r'[A-Z]:\\\\?Users\\',value,re.I) or 'csrf_token' in value or 'credentials.json' in value:
                raise RuntimeError('Portable package private-path/credential scan failed')
    return package


def independent_run(v,recipe):
    run=v.post('independent-run',v.base+'/bio-analysis-runs',dict(raw_source=recipe['raw_source'],
        recipe_version_id=recipe['id'],expected_setup_revision=recipe['revision']),kind='run',expected=202)
    current=v.get(v.base+'/bio-analysis-runs/'+run['id'])['task']
    if current['status']=='succeeded':
        return v.get(v.base+'/bio-processed-datasets/'+current['result_bio_processed_dataset_version_id'])
    if current['status']=='failed':raise RuntimeError('Retained independent run failed; original task is preserved')
    if current['status']!='waiting_confirmation' and v.progress.get('actions',{}).get('independent-confirm',{}).get('response'):
        done=v.wait(current,'succeeded')
        return v.get(v.base+'/bio-processed-datasets/'+done['result_bio_processed_dataset_version_id'])
    v.wait(run['task'],'waiting_confirmation')
    view=v.get(v.base+'/bio-analysis-runs/'+run['id'])
    confirm=dict(task_revision=view['task']['revision'],checkpoint_id=view['checkpoint_id'],wait_id=view['wait_id'],
        candidate_sha256=view['candidate']['sha256'],expected_setup_revision=view['expected_setup_revision'])
    queued=v.post('independent-confirm',v.base+'/bio-analysis-runs/'+run['id']+'/confirm',confirm,kind='confirmation',expected=202)
    done=v.wait(queued,'succeeded')
    result=v.get(v.base+'/bio-processed-datasets/'+done['result_bio_processed_dataset_version_id'])
    v.progress['independent_analysis']={'run_id':run['id'],'result_id':result['id']};v.save()
    return result


def compare_in_container(package,candidate,gate,evidence,label):
    output=evidence/(label+'-comparison');output.mkdir()
    image=gate['image_digest']
    command([*docker_base(image),'--mount',f'type=bind,source={package},target=/bundle,readonly',
        '--mount',f'type=bind,source={candidate},target=/candidate,readonly',
        '--mount',f'type=bind,source={output},target=/comparison',image,'/opt/paperassist-bio/bin/python',
        '/bundle/compare.py','/bundle/baseline','/candidate','--report','/comparison/report.json'],evidence,label+'-compare',allow_failure=True)
    return json.loads((output/'report.json').read_bytes())


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--state',default=str(control.STATE))
    parser.add_argument('--phase',choices=['gse','synthetic'],default='gse')
    parser.add_argument('--fresh-environment',action='store_true')
    args=parser.parse_args();state=control.read_state(args.state);control.configure(state)
    pointer=json.loads((control.RUNTIME/(args.phase+'-verification-current.json')).read_bytes())
    source_progress=json.loads(Path(pointer['progress']).read_bytes())
    if source_progress.get('schema')!=state['schema'] or source_progress.get('status')!='passed':
        raise RuntimeError('Original real-queue verification must be complete in the current isolated schema')
    directory=control.RUNTIME/'reproducibility'/(args.phase+'-'+uuid4().hex);directory.mkdir(parents=True)
    control.worker_stack.protect_directory(directory)
    report={'schema_version':1,'status':'running','phase':args.phase,'biological_validation':'not_performed','user_acceptance':'pending',
        'V16':{'status':'not_executed'},'V17':{'status':'not_executed'}}
    write_json(directory/'report.json',report)
    v=None
    try:
        gate,environment=check_gate(directory)
        report['gate']=gate
        v=Verification(state,'reproducibility-'+args.phase)
        v.base='/api/v1/projects/'+source_progress['project_id']
        v.progress['project_id']=source_progress['project_id'];v.save()
        analysis=source_progress['analysis']
        recipe=v.get(v.base+'/bio-analysis-setups/'+analysis['recipe']['setup_id']+'/recipes/'+analysis['recipe']['id'])
        original=v.get(v.base+'/bio-processed-datasets/'+analysis['result']['id'])
        if original['source']!=source_progress['processed_source']:raise RuntimeError('Original processed identity changed')
        report['original_source']=original['source']
        report['resource_scopes']={'container':{'memory_bytes':2*1024**3,'cpus':1,'tmpfs_bytes':512*1024**2,
            'network':'none','root_filesystem':'read_only'},'child':{'rss_bytes':2*1024**3,'cpu_seconds':900,
            'address_space_bytes':3*1024**3,'trusted_warmup_seconds':180,'compute_wall_seconds':1200},
            'original':{k:original['manifest'][k] for k in ('resources','parent_resources') if k in original['manifest']}}
        package=export_package(v,original,recipe,gate,environment,directory)
        report['package']='package';report['package_sha256']=sha256(package/'package.json')
        write_json(directory/'report.json',report)
        second=independent_run(v,recipe)
        repeated=directory/'independent-result';export_result(v,second,repeated)
        report['independent_source']=second['source']
        report['resource_scopes']['independent']={k:second['manifest'][k] for k in ('resources','parent_resources') if k in second['manifest']}
        report['V16']=compare_in_container(package,repeated,gate,directory,'same-environment')
        if args.fresh_environment:
            fresh=directory/'fresh-container-output';fresh.mkdir()
            image=gate['image_digest']
            command([*docker_base(image),'--mount',f'type=bind,source={package},target=/bundle,readonly',
                '--mount',f'type=bind,source={fresh},target=/output',image,'/opt/paperassist-bio/bin/python',
                '/bundle/reproduce.py','--output','/output'],directory,'fresh-package-script')
            report['resource_scopes']['fresh']=json.loads((fresh/'result.json').read_bytes())['execution']
            report['V17']=compare_in_container(package,fresh,gate,directory,'fresh-environment')
            report['V17']['method']='new_container_fixed_config_id_same_platform_packaged_reproduce_script'
            report['V17']['fresh_installation']='not_performed'
        for item in json.loads((package/'package.json').read_bytes())['files']:
            if sha256(package/item['path'])!=item['sha256']:raise RuntimeError('Exported original/code/baseline changed after execution')
        # Re-download original members through the permission API after both runs
        # to prove the source objects were not modified by processing.
        source=recipe['raw_source'];raw=v.get(v.base+'/bio-datasets/'+source['dataset_id']+'/versions/'+source['dataset_version_id'])
        if raw['source']!=source:raise RuntimeError('Raw identity changed after repeat calculation')
        for member in raw['members']: v.download(member)
        for original_file in json.loads((package/'input/originals.json').read_bytes()):
            v.download({'download_url':v.base+'/files/'+original_file['id']+'/download',
                'sha256':original_file['sha256'],'size_bytes':original_file['size_bytes']})
        report['raw_source_after']='all_member_and_original_file_hashes_unchanged'
        report['status']='passed' if report['V16']['status']=='passed' and (not args.fresh_environment or report['V17']['status']=='passed') else 'failed'
    except BaseException as exc:
        report['status']='failed';report['failure']={'type':type(exc).__name__,'message':str(exc)[:2000]}
        raise
    finally:
        if v:v.client.close()
        write_json(directory/'report.json',report)
        brief=f"CR-B02 {args.phase} 工程复现：{report['status']}\nV16 同环境独立队列重算：{report['V16']['status']}\nV17 新容器执行交付脚本：{report['V17']['status']}\n原始输入状态：{report.get('raw_source_after','未完成复核')}\n全部尝试、原件、输出和原始命令/日志均保留。\n未执行另一机器全新安装；未进行生物学验证；用户验收待完成。\n"
        (directory/'report.zh-CN.txt').write_text(brief,encoding='utf-8')
        print(json.dumps({'status':report['status'],'V16':report['V16']['status'],'V17':report['V17']['status'],'evidence':str(directory)},ensure_ascii=False),flush=True)
    if report['status']!='passed':raise SystemExit(1)


if __name__=='__main__':main()
