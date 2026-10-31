"""Portable B04 verify/recompute/render; no API credentials or network calls."""
import argparse
import copy
import csv
from decimal import Decimal,InvalidOperation
import hashlib
import json
import os
from pathlib import Path,PurePosixPath,PureWindowsPath
import re
import struct
import subprocess
import sys
from threading import Thread
import time

P_FIELDS={'p_value','q_value','q_within_contrast','q_global_family','system_recomputed_q','nominal_p_value',
          'fdr_q_value','fwer_p_value','primary_q'}
EFFECT_FIELDS={'effect_value','effect_log2fc','effect_log2_normalized','lfc_se','wald_statistic','base_mean',
               'statistic','es','nes','score','partial_score','primary_effect','gene_ratio','bg_ratio','enrichment_ratio'}
MISSING={'','NA','N/A','null','None'}
SIGNED_FIELDS={'effect_value','effect_log2fc','effect_log2_normalized','primary_effect','statistic','wald_statistic','es','nes'}


def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')


def strict_json(content):
    def pairs(values):
        result={}
        for key,value in values:
            if key in result:raise ValueError('Duplicate JSON key')
            result[key]=value
        return result
    return json.loads(content,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def relative_file(root,name):
    if not isinstance(name,str) or not name or '\\' in name or ':' in name or any(ord(c)<32 for c in name):raise ValueError('Unsafe package path')
    value=PurePosixPath(name)
    if value.is_absolute() or PureWindowsPath(name).is_absolute() or value.as_posix()!=name or any(part in ('.','..') for part in value.parts):raise ValueError('Package path escape')
    root=Path(root).resolve();path=root.joinpath(*value.parts)
    if not path.resolve().is_relative_to(root):raise ValueError('Package path escape')
    for part in [path,*path.parents]:
        if part==root:break
        if part.is_symlink() or getattr(part,'is_junction',lambda:False)():raise ValueError('Package symlink/junction')
    return path


def sha256(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk:=stream.read(1024**2):result.update(chunk)
    return result.hexdigest()


def check_file(path,record):
    if Path(path).is_symlink() or not Path(path).is_file() or type(record['size_bytes']) is not int or Path(path).stat().st_size!=record['size_bytes'] or sha256(path)!=record['sha256']:
        raise ValueError('File SHA/size mismatch: '+str(record.get('path',path)))


def table_shape(path,fmt,*,header='declared'):
    if header not in ('declared','uninterpreted'):raise ValueError('Invalid table header contract')
    with Path(path).open('r',encoding='utf-8-sig',newline='') as stream:
        rows=csv.reader(stream,delimiter='\t' if fmt=='tsv' else ',',strict=True)
        columns=next(rows,None)
        if not columns or header=='declared' and len(columns)!=len(set(columns)):raise ValueError('Invalid table columns')
        count=1 if header=='uninterpreted' else 0
        for row in rows:
            if len(row)!=len(columns):raise ValueError('Invalid table row width')
            count+=1
            if count>10000000:raise ValueError('Table row limit')
    if header=='uninterpreted':return dict(format=fmt,header='uninterpreted',column_count=len(columns),records=count)
    return dict(format=fmt,columns=columns,rows=count)


def resource_paths(package,root,resources,needed=None):
    result={};missing=[]
    for record in package.get('required_resources',[]):
        if needed is not None and record['path'] not in needed:continue
        path=resources.get(record['sha256'])
        if path is None:
            local=relative_file(root,record['path'])
            if local.is_file():path=local
        if path is None:missing.append(record['sha256']);continue
        path=Path(path).absolute()
        if path.is_symlink() or any(p.is_symlink() or getattr(p,'is_junction',lambda:False)() for p in path.parents):raise ValueError('External resource symlink/junction')
        check_file(path,record);result[record['path']]=path
    if missing:raise ValueError('Missing required resource SHA256: '+','.join(missing))
    return result


def verify_package(root,resources=None,manifest_sha256=None,needed=None):
    root=Path(root).resolve();resources=resources or {};manifest=root/'package.json'
    if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size>4*1024**2:raise ValueError('Package manifest missing or invalid')
    if manifest_sha256 and sha256(manifest)!=manifest_sha256:raise ValueError('Package manifest anchor differs')
    package=strict_json(manifest.read_bytes())
    if package.get('schema_version')!=1 or package.get('kind')!='bio_insights_reproduction':raise ValueError('Unsupported reproduction package')
    listed={'package.json'};tables=[]
    for record in package['files']:
        if record['path'] in listed:raise ValueError('Duplicate package member')
        listed.add(record['path']);path=relative_file(root,record['path']);check_file(path,record)
        if 'table' in record:
            shape=table_shape(path,record['table']['format'],header=record['table'].get('header','declared'))
            if shape!=record['table']:raise ValueError('Table columns/row count mismatch: '+record['path'])
            tables.append(dict(path=record['path'],**shape))
    allowed=listed|{r['path'] for r in package.get('required_resources',[])}
    for path in root.rglob('*'):
        if path.is_symlink() or getattr(path,'is_junction',lambda:False)():raise ValueError('Package symlink/junction')
        if path.is_file() and path.relative_to(root).as_posix() not in allowed:raise ValueError('Unlisted package file: '+path.relative_to(root).as_posix())
    resolved=resource_paths(package,root,resources,needed)
    payload=strict_json(relative_file(root,'input/payload.json').read_bytes())
    if any(package['identity'].get(key)!=value for key,value in payload['identity'].items()):raise ValueError('Payload identity differs')
    if hashlib.sha256(canonical(payload['config'])).hexdigest()!=package['frozen_config_sha256']:raise ValueError('Frozen configuration differs')
    if sha256(relative_file(root,'provenance/task-input.json'))!=package['task_input_sha256']:raise ValueError('Frozen task input differs')
    if sha256(relative_file(root,'provenance/formal-manifest.json'))!=package['formal_manifest_sha256']:raise ValueError('Formal result manifest differs')
    frozen=[{key:s[key] for key in ('source_kind','source_id','role','sha256','project_id','locator')} for s in payload['sources']]
    if hashlib.sha256(canonical(frozen)).hexdigest()!=package['identity']['source_digest']:raise ValueError('Frozen source digest differs')
    proofs=package['source_proofs'];required_records={r['path']:r for r in package.get('required_resources',[])}
    required_names=set(required_records);file_records={r['path']:r for r in package['files']}
    input_payloads=[payload]
    if 'input/render-payload.json' in file_records:input_payloads.append(strict_json(relative_file(root,'input/render-payload.json').read_bytes()))
    for frozen_payload in input_payloads:
        for source in frozen_payload['sources']:
            for container in (source,source.get('raw',{})):
                for member in container.get('members',{}).values():
                    name=member['path'];record=required_records.get(name) or file_records.get(name)
                    if record is None or any(member.get(key)!=record.get(key) for key in ('sha256','size_bytes')):
                        raise ValueError('Frozen input member differs from package SHA/size declaration')
                    if needed is not None and name in required_names and name not in needed:continue
                    check_file(resolved.get(name) or relative_file(root,name),member)
    for source in payload['sources']:
        matches=[p for p in proofs if all(p[key]==source[key] for key in ('source_kind','source_id','sha256'))]
        if not matches:raise ValueError('Frozen source proof missing')
        for proof in matches:
            if proof['proof']=='canonical_member_hashes':
                if hashlib.sha256(canonical(proof['member_hashes'])).hexdigest()!=proof['sha256']:raise ValueError('Annotation member identity differs')
            else:
                name=proof['path']
                if needed is not None and name in required_names and name not in needed:continue
                path=resolved.get(name) or relative_file(root,name)
                if sha256(path)!=proof['sha256']:raise ValueError('Frozen source SHA differs')
    proof=package.get('environment_proof')
    if not proof or not package.get('engine_code_files') or not package.get('lock_path'):
        raise ValueError('Code/environment/lock proof is missing')
    if proof:
        identity=package['identity']
        if hashlib.sha256(canonical(proof['environment'])).hexdigest()!=identity['environment_digest']:raise ValueError('Environment identity mismatch')
        code=package.get('engine_code_files',[]);digest=hashlib.sha256()
        for record in code:
            digest.update(record['relative_name'].encode()+b'\0'+relative_file(root,record['path']).read_bytes()+b'\0')
        if digest.hexdigest()!=identity['code_digest']:raise ValueError('Engine code digest mismatch')
        if sha256(relative_file(root,package['lock_path']))!=identity['lock_sha256']:raise ValueError('Environment lock digest mismatch')
    return dict(status='verified',files=len(package['files']),tables=tables,provided_external_resources=len(resolved),
        fully_self_contained=package.get('fully_self_contained',False),authenticated_anchor_provided=bool(manifest_sha256),
        code_and_environment_verified=True,executed_analysis=False,real_network_calls=False)


def compare_table(baseline,actual,fmt='tsv'):
    differences=[];passed=True;count=0
    with Path(baseline).open(encoding='utf-8-sig',newline='') as left,Path(actual).open(encoding='utf-8-sig',newline='') as right:
        a=csv.DictReader(left,delimiter='\t' if fmt=='tsv' else ',');b=csv.DictReader(right,delimiter='\t' if fmt=='tsv' else ',')
        if a.fieldnames!=b.fieldnames:return dict(passed=False,reason='columns_differ',numeric_differences=[])
        from itertools import zip_longest
        for row,(first,second) in enumerate(zip_longest(a,b),1):
            count+=1
            if first is None or second is None:passed=False;differences.append(dict(row=row,field='',reason='row_count_differs'));continue
            for field in a.fieldnames:
                x,y=first[field],second[field]
                if x==y:continue
                tolerance=Decimal('1e-10') if field in P_FIELDS else Decimal('1e-8') if field in EFFECT_FIELDS else None
                reason='deterministic_field_differs';delta=None;okay=False
                if tolerance is not None and x not in MISSING and y not in MISSING:
                    try:
                        xv,yv=Decimal(x),Decimal(y)
                        if xv.is_finite() and yv.is_finite():
                            delta=abs(xv-yv);okay=delta<=tolerance;reason='numeric_difference'
                            if field in SIGNED_FIELDS and (xv>0)-(xv<0)!=(yv>0)-(yv<0):okay=False;reason='direction_changed'
                    except InvalidOperation:pass
                if not okay:passed=False
                if len(differences)<10000:differences.append(dict(row=row,field=field,baseline=x,actual=y,absolute_difference=str(delta) if delta is not None else None,
                    tolerance=str(tolerance) if tolerance is not None else None,within_tolerance=okay,reason=reason))
    return dict(passed=passed,rows=count,numeric_differences=differences)


def _json_equal(a,b,field=''):
    if type(a) is not type(b):return False
    if isinstance(a,dict):return set(a)==set(b) and all(_json_equal(a[k],b[k],k) for k in a)
    if isinstance(a,list):return len(a)==len(b) and all(_json_equal(x,y,field) for x,y in zip(a,b))
    if type(a) in (float,int) and field in P_FIELDS|EFFECT_FIELDS:
        if field in SIGNED_FIELDS and (a>0)-(a<0)!=(b>0)-(b<0):return False
        return abs(Decimal(str(a))-Decimal(str(b)))<=Decimal('1e-10' if field in P_FIELDS else '1e-8')
    return a==b


def pdf_content(path):
    """Compare fixed Matplotlib page boxes/vector/font streams, excluding dates."""
    import zlib
    content=Path(path).read_bytes()
    if not content.startswith(b'%PDF-'):raise ValueError('Invalid PDF')
    streams=[]
    for match in re.finditer(rb'stream\r?\n(.*?)\r?\nendstream',content,re.S):
        header=content[max(0,content.rfind(b'obj',0,match.start())):match.start()]
        raw=match.group(1)
        if b'/FlateDecode' in header:
            decoder=zlib.decompressobj();raw=decoder.decompress(raw,64*1024**2+1)
            if len(raw)>64*1024**2 or decoder.unconsumed_tail or not decoder.eof:raise ValueError('PDF stream expansion limit')
        streams.append(hashlib.sha256(raw).hexdigest())
    boxes=re.findall(rb'/MediaBox\s*\[([^\]]+)\]',content)
    if not streams or not boxes:raise ValueError('PDF lacks explicit page/vector streams')
    return dict(page_boxes=[b' '.join(box.split()).decode('ascii') for box in boxes],streams=streams,
                page_count=len(re.findall(rb'/Type\s*/Page\b',content)))


def compare_outputs(package,root,result,output,resources=None):
    actual={m['key']:m for m in result['outputs']};details=[];passed=True
    expected_members=[m for m in package['baseline'] if m.get('recomputed',True) and m.get('role')!='original_resource']
    if {m['key'] for m in expected_members}!=set(actual):
        passed=False;details.append(dict(key='',passed=False,reason='output_member_set_differs'))
    requirements={r['path']:r for r in package.get('required_resources',[])};resources=resources or {}
    for expected in expected_members:
        key=expected['key'];member=actual.get(key)
        if member is None:passed=False;details.append(dict(key=key,passed=False,reason='missing_output'));continue
        path=Path(member['path'])
        if not path.resolve().is_relative_to(Path(output).resolve()):raise ValueError('Worker output path escape')
        check_file(path,member);baseline=relative_file(root,expected['path']);fmt=expected['format']
        if expected['path'] in requirements and requirements[expected['path']]['sha256'] in resources:baseline=Path(resources[requirements[expected['path']]['sha256']])
        if fmt in ('tsv','csv'):comparison=compare_table(baseline,path,fmt)
        elif key=='manifest':
            before=strict_json(baseline.read_bytes());after=strict_json(path.read_bytes())
            for value in (before,after):value.pop('members',None)
            comparison=dict(passed=_json_equal(before,after),reason='manifest_identity_methods_and_summary')
        elif fmt=='json':comparison=dict(passed=_json_equal(strict_json(baseline.read_bytes()),strict_json(path.read_bytes())))
        elif fmt in ('png','tiff'):
            from PIL import Image
            with Image.open(baseline) as a,Image.open(path) as b:comparison=dict(passed=a.size==b.size and a.mode==b.mode and a.info.get('dpi')==b.info.get('dpi') and a.tobytes()==b.tobytes(),comparison='decoded_pixels_and_dpi_exact')
        elif fmt=='pdf':comparison=dict(passed=pdf_content(baseline)==pdf_content(path),comparison='pdf_decompressed_vector_font_streams_and_page_boxes')
        elif fmt=='svg':
            import xml.etree.ElementTree as ET
            def normalized(file):
                tree=ET.fromstring(file.read_bytes())
                # Matplotlib writes the render wall clock as Dublin Core
                # metadata. It has no bearing on visible vector content.
                for parent in tree.iter():
                    for child in list(parent):
                        if child.tag=='{http://purl.org/dc/elements/1.1/}date':parent.remove(child)
                mapping={item.attrib['id']:'i'+str(i) for i,item in enumerate(tree.iter()) if 'id' in item.attrib}
                for item in tree.iter():
                    for name,value in list(item.attrib.items()):
                        if name=='id':item.attrib[name]=mapping[value]
                        else:
                            value=re.sub(r'#([A-Za-z_][\w:.-]*)',lambda match:'#'+mapping.get(match[1],match[1]),value)
                            item.attrib[name]=value
                return ET.tostring(tree)
            comparison=dict(passed=normalized(baseline)==normalized(path),comparison='svg_content_normalized_ids_without_generation_date')
        else:comparison=dict(passed=sha256(baseline)==sha256(path),comparison='exact_bytes')
        passed=passed and comparison['passed'];details.append(dict(key=key,**comparison))
    return dict(passed=passed,members=details,p_q_absolute_tolerance='1e-10',effect_es_nes_absolute_tolerance='1e-8',
                deterministic_fields='exact; original external text and NA masks never converted')


def hydrate(payload,root,package,resources):
    result=copy.deepcopy(payload)
    required={r['path']:r for r in package.get('required_resources',[])}
    for source in result.get('sources',[]):
        for container in (source,source.get('raw',{})):
            for member in container.get('members',{}).values():
                name=member['path']
                member['path']=str(Path(resources[required[name]['sha256']]).absolute() if name in required and required[name]['sha256'] in resources else relative_file(root,name))
                check_file(member['path'],member)
    return result


def execute_child(command,payload,output):
    """One independent child, bounded RSS/wall/stdout; all failed logs retained."""
    body=canonical(payload)
    if len(body)>2*1024**2:raise ValueError('Worker input envelope exceeds 2 MiB')
    started=time.monotonic();process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        env={'PATH':os.environ.get('PATH',''),'LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1'})
    outcome={};exceeded=[]
    def consume(name,stream,limit):
        total=0
        with (output/name).open('wb') as target:
            while chunk:=stream.read(65536):
                total+=len(chunk)
                if total>limit:exceeded.append(name);process.kill();break
                target.write(chunk)
        stream.close()
    readers=[Thread(target=consume,args=('worker.stdout.bin',process.stdout,2097158),daemon=True),
             Thread(target=consume,args=('worker.stderr.txt',process.stderr,4194304),daemon=True)]
    for thread in readers:thread.start()
    try:process.stdin.write(struct.pack('!I',len(body))+body);process.stdin.close()
    except BrokenPipeError:pass
    peak=0;violation=None
    while process.poll() is None:
        if time.monotonic()-started>1980:violation='wall_1980_seconds'
        try:
            fields=dict(line.split(':',1) for line in (Path('/proc')/str(process.pid)/'status').read_text().splitlines() if ':' in line)
            rss=int(fields.get('VmRSS','0 kB').split()[0])*1024;peak=max(peak,rss)
            if rss>2*1024**3:violation='RSS_2GiB'
        except (OSError,ValueError):pass
        if violation:process.kill()
        time.sleep(.1)
    for thread in readers:thread.join(timeout=5)
    if any(t.is_alive() for t in readers):raise RuntimeError('Worker output readers did not terminate')
    if exceeded:violation='output_limit:'+','.join(exceeded)
    stdout=(output/'worker.stdout.bin').read_bytes()
    answer=None
    if len(stdout)<=2*1024**2+6 and stdout.startswith(b'READY\n'):
        try:answer=strict_json(stdout[6:])
        except ValueError:pass
    receipt=dict(command=command,exit_code=process.returncode,wall_seconds=time.monotonic()-started,child_peak_rss_bytes=peak,
        rss_limit_bytes=2*1024**3,wall_limit_seconds=1980,violation=violation,real_network_calls=False)
    (output/'execution.json').write_bytes(canonical(receipt))
    if process.returncode or violation or not answer or 'result' not in answer:raise RuntimeError('Offline child failed; exact attempt logs retained')
    (output/'worker-result.json').write_bytes(canonical(answer))
    return answer['result'],receipt


def project_for_pipe(root,payload):
    """Use the exact attested scientific transport projection, never a local copy."""
    path=relative_file(root,'code/app/adapters/bio_insights_engine/transport.py')
    if not path.is_file():return payload  # Small historical packages retain their original protocol.
    import importlib.util
    spec=importlib.util.spec_from_file_location('b04_packaged_transport',path)
    module=importlib.util.module_from_spec(spec);old=sys.dont_write_bytecode
    try:sys.dont_write_bytecode=True;spec.loader.exec_module(module)
    finally:sys.dont_write_bytecode=old
    return module.project_transport_payload(payload)


def operate(root,operation,output=None,resources=None,manifest_sha256=None,python=None,config=None):
    root=Path(root).resolve();resources=resources or {};package=strict_json((root/'package.json').read_bytes())
    if operation=='verify':return verify_package(root,resources,manifest_sha256)
    if operation not in ('recompute','render'):raise ValueError('Unknown operation')
    payload=strict_json(relative_file(root,'input/payload.json').read_bytes())
    if operation=='render':
        if not package.get('render',{}).get('supported'):raise ValueError('This resource package has no scientific figure to render')
        payload=strict_json(relative_file(root,'input/render-payload.json').read_bytes())
        if config is not None:payload['config']=strict_json(Path(config).read_bytes())
        elif payload.get('config') is None:raise ValueError('Explicit --config is required to select a result/contrast/term and figure type')
        ids={payload['config']['result_source_id'],*(payload['config'].get('result_source_ids') or [])}
        if payload['config'].get('processed_source_id'):ids.add(payload['config']['processed_source_id'])
        payload['sources']=[s for s in payload['sources'] if s['source_id'] in ids]
        if {s['source_id'] for s in payload['sources']}!=ids:raise ValueError('Render configuration references an unexported source')
        needed={m['path'] for s in payload['sources'] for group in (s,s.get('raw',{})) for m in group.get('members',{}).values()}
        verify_package(root,resources,manifest_sha256,needed)
    else:verify_package(root,resources,manifest_sha256)
    output=Path(output).absolute() if output else None
    if output is None or output.exists() or output.resolve().is_relative_to(root):raise ValueError('Output must be a new directory outside the immutable package')
    output.mkdir(parents=True);artifacts=output/'artifacts';artifacts.mkdir()
    payload=hydrate(payload,root,package,resources)
    payload['output_directory']=str(artifacts.resolve());payload['_runtime_identity']=package['runtime_identity']
    payload=project_for_pipe(root,payload)
    interpreter=python or package['interpreter']
    script=relative_file(root,'render_worker.py' if operation=='render' else 'code/app/adapters/bio_insights_engine/worker.py')
    result,receipt=execute_child([str(interpreter),'-I','-B',str(script),str(os.getpid())],payload,output)
    if result.get('identity')!=payload['identity'] or result.get('kind')!=payload['kind'] or result.get('status')!='completed':raise RuntimeError('Child identity/status differs')
    paths=set();keys=set()
    for member in result['outputs']:
        path=Path(member['path'])
        if path.is_symlink() or path.resolve().parent!=artifacts.resolve() or member['key'] in keys:raise RuntimeError('Child output identity/path differs')
        check_file(path,member);paths.add(path.resolve());keys.add(member['key'])
    if paths!={p.resolve() for p in artifacts.iterdir()}:raise RuntimeError('Unlisted child output')
    comparison=None
    if operation=='recompute':comparison=compare_outputs(package,root,result,artifacts,resources)
    elif package.get('render',{}).get('exact_original_figure') and config is None:
        display=copy.deepcopy(package);display['baseline']=[m for m in package['baseline'] if m['key']=='plot_data' or m['format'] in ('png','tiff','svg','pdf')]
        displays=copy.deepcopy(result);displays['outputs']=[m for m in result['outputs'] if m['key']=='plot_data' or m['format'] in ('png','tiff','svg','pdf')]
        comparison=compare_outputs(display,root,displays,artifacts,resources)
    report=dict(operation=operation,status='completed' if comparison is None or comparison['passed'] else 'comparison_failed',
        execution=receipt,comparison=comparison,workflow_reexecuted=operation=='recompute',
        analysis_recomputed=operation=='recompute' and payload['kind'] in ('bio_comparison','bio_enrichment','bio_candidate'),
        render_path_calls_fit_or_enrichment=False if operation=='render' else None,
        synthetic_status=package.get('synthetic_status','unknown'),fully_self_contained=package.get('fully_self_contained',False))
    (output/'operation.json').write_bytes(canonical(report))
    if report['status']!='completed':raise RuntimeError('Recomputed output differs; operation.json preserves numeric differences')
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('operation',choices=['verify','recompute','render'])
    parser.add_argument('--package',type=Path,default=Path(__file__).resolve().parent);parser.add_argument('--output',type=Path)
    parser.add_argument('--resource',action='append',default=[],metavar='SHA256=PATH');parser.add_argument('--manifest-sha256')
    parser.add_argument('--python');parser.add_argument('--config',type=Path)
    args=parser.parse_args(argv);resources={}
    for value in args.resource:
        sha,separator,path=value.partition('=')
        if not separator or not re.fullmatch('[a-f0-9]{64}',sha) or sha in resources:raise ValueError('Each external resource requires one unique SHA256=PATH')
        resources[sha]=path
    report=operate(args.package,args.operation,args.output,resources,args.manifest_sha256,args.python,args.config)
    print(json.dumps(report,ensure_ascii=False,sort_keys=True));return report


if __name__=='__main__':main()
