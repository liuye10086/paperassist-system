"""Run only explicit B04 packages; missing state/materials fail without substitutes."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'script/.runtime/client-requirements-b04'


def load_reproducer(path):
    spec=importlib.util.spec_from_file_location('b04_offline_reproducer',path)
    module=importlib.util.module_from_spec(spec);previous=sys.dont_write_bytecode
    try:sys.dont_write_bytecode=True;spec.loader.exec_module(module)
    finally:sys.dont_write_bytecode=previous
    return module


def checked_package_metadata(package,anchor):
    manifest=package/'package.json'
    if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size>4*1024**2:raise ValueError('Package manifest missing or invalid')
    raw=manifest.read_bytes()
    if anchor and hashlib.sha256(raw).hexdigest()!=anchor:raise ValueError('Package manifest anchor differs')
    metadata=json.loads(raw);matches=[m for m in metadata['files'] if m['path']=='reproduce.py'];script=package/'reproduce.py'
    if len(matches)!=1 or script.is_symlink() or not script.is_file() or script.stat().st_size!=matches[0]['size_bytes'] or hashlib.sha256(script.read_bytes()).hexdigest()!=matches[0]['sha256']:
        raise ValueError('Packaged verification code differs from anchored file declaration')
    return metadata


def state_packages(path):
    state=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not re.fullmatch(r'pa_test_[a-f0-9]{32}',state.get('schema','')) or Path(state.get('workspace','')).resolve()!=ROOT:
        raise ValueError('Explicit current B04 schema/workspace identity is required')
    packages=state.get('reproducibility_packages')
    if not isinstance(packages,list) or not packages:raise ValueError('B04 state has no actual exported reproducibility_packages')
    for item in packages:
        package=Path(item['package_path']).resolve()
        if not package.is_relative_to(RUNTIME.resolve()) or not re.fullmatch('[a-f0-9]{64}',item.get('manifest_sha256','')):
            raise ValueError('State package path/manifest identity is outside this B04 runtime')
        manifest=json.loads((package/'package.json').read_bytes());identity=manifest['identity']
        target=item.get('result_version_id') or item.get('resource_version_id')
        if not target or identity.get('project_id')!=item.get('project_id') or target not in (identity.get('result_version_id'),identity.get('resource_version_id')):
            raise ValueError('State package references a different project/result/resource')
    return packages


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',type=Path);parser.add_argument('--state',type=Path,default=RUNTIME/'state.json')
    parser.add_argument('--operation',choices=['verify','recompute','render','all'],default='verify');parser.add_argument('--output',type=Path)
    parser.add_argument('--resource',action='append',default=[]);parser.add_argument('--manifest-sha256');parser.add_argument('--python')
    parser.add_argument('--config',type=Path);parser.add_argument('--receipt',type=Path)
    args=parser.parse_args(argv);resources={}
    for value in args.resource:
        sha,separator,path=value.partition('=')
        if not separator or not re.fullmatch('[a-f0-9]{64}',sha) or sha in resources:raise ValueError('Unique SHA256=PATH resources are required')
        resources[sha]=path
    entries=[dict(package_path=str(args.package.resolve()),manifest_sha256=args.manifest_sha256)] if args.package else state_packages(args.state)
    receipt=args.receipt or RUNTIME/'reproducibility'/('verification-'+uuid4().hex+'.json')
    if receipt.exists():raise ValueError('Refusing to overwrite an earlier receipt')
    results=[];failure=None
    try:
        for index,item in enumerate(entries):
            package=Path(item['package_path']).resolve();metadata=checked_package_metadata(package,item.get('manifest_sha256'))
            module=load_reproducer(package/'reproduce.py');actions=['verify','recompute','render'] if args.operation=='all' else [args.operation]
            operations=[];entry=dict(package_path=str(package),identity=metadata['identity'],operations=operations);results.append(entry)
            for action in actions:
                if action=='render' and not metadata.get('render',{}).get('supported'):
                    operations.append(dict(operation='render',status='not_applicable',reason='Resource import has no figure output'));continue
                output=None
                if action!='verify':
                    if args.output is None:raise ValueError('An explicit independent --output root is required for recompute/render')
                    output=args.output/str(index)/action
                config=args.config or (Path(item['render_config_path']) if item.get('render_config_path') else None)
                attempt=dict(operation=action,status='running',output=str(output) if output else None);operations.append(attempt)
                report=module.operate(package,action,output,resources,item.get('manifest_sha256'),args.python,config)
                attempt.update(status='completed',report=report)
    except Exception as exc:
        failure=str(exc)
        if results and results[-1]['operations'] and results[-1]['operations'][-1].get('status')=='running':
            results[-1]['operations'][-1].update(status='failed',error=failure)
    result=dict(schema_version=1,status='failed' if failure else 'passed',requested_operation=args.operation,packages=results,error=failure,
                actual_only=True,real_model_calls=0,real_network_calls=False,biological_validation=False,user_acceptance=False)
    receipt.parent.mkdir(parents=True,exist_ok=True)
    with receipt.open('x',encoding='utf-8') as stream:json.dump(result,stream,ensure_ascii=False,indent=2)
    print(json.dumps(dict(status=result['status'],receipt=str(receipt),error=failure),ensure_ascii=False))
    if failure:raise RuntimeError('B04 reproducibility verification failed; exact receipt retained: '+str(receipt))
    return result


if __name__=='__main__':main()
