"""Report render/pack in a secret-free, memory- and time-bounded subprocess."""
import csv
import hashlib
import io
import json
from pathlib import Path
import signal
import subprocess
import sys


def renderer_identity():
    from importlib.metadata import version
    names=('research_report_render.py','research_report_child.py','research_report_docx.py','research_results_xlsx.py','research_report_images.py','research_method_text.py')
    paths=[Path(__file__).with_name(name) for name in names]+[Path(__file__).parents[1]/'domain/research_results/report_package.py']
    return dict(renderer_version='research_report_v1',code_digest=hashlib.sha256(b''.join(p.read_bytes() for p in paths)).hexdigest(),
        dependencies={name:version(name) for name in ('python-docx','openpyxl','Pillow','pdfplumber')},
        limits={'render_seconds':120,'package_seconds':180,'subprocess_memory_bytes':2*1024**3})


def stage_report_payload(payload,directory):
    directory=Path(directory);result=dict(payload)
    tables=[]
    for i,(table,raw) in enumerate(zip(payload['tables'],payload['table_raws'])):
        path=directory/f'table_{i}.tsv';path.write_bytes(raw);tables.append(dict(table,path=str(path.resolve())))
    figures=[]
    for i,figure in enumerate(payload['figures']):
        path=directory/f'figure_{i}.png';path.write_bytes(figure['raw'])
        figures.append(dict(config=figure['config'],format=figure.get('format','png'),path=str(path.resolve()),sha256=hashlib.sha256(figure['raw']).hexdigest()))
    files=[]
    for i,item in enumerate(payload['package_files']):
        path=directory/f'package_{i}.bin';path.write_bytes(item['raw'])
        files.append(dict(name=item['name'],path=str(path.resolve()),sha256=hashlib.sha256(item['raw']).hexdigest()))
    return dict(snapshot=payload['snapshot'],tables=tables,figures=figures,package_files=files)


def checked_bytes(item):
    path=Path(item['path'])
    if not path.is_absolute() or path.is_symlink() or getattr(path,'is_junction',lambda:False)() or path.stat().st_size>256*1024**2:
        raise ValueError('Invalid report input')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('Report source changed')
    return raw


def render_report(payload,output,*,enforce_deadlines=False):
    from app.adapters.research_report_docx import build_report,report_text
    from app.adapters.research_results_xlsx import build_workbook
    from app.domain.research_results.report_package import make_package
    from app.adapters.research_report_images import as_png
    from app.adapters.research_method_text import presentation_enabled,canonical
    if enforce_deadlines:signal.alarm(120)
    snapshot=payload['snapshot'];tables=[]
    for table in payload['tables']:
        raw=checked_bytes(table);reader=csv.reader(io.StringIO(raw.decode('utf-8')),delimiter='\t',strict=True)
        if next(reader)!=table['columns']:raise ValueError('Report columns changed')
        tables.append(dict(table,rows=reader))
    figures=[dict(config=f['config'],content=as_png(checked_bytes(f),f.get('format','png'))) for f in payload['figures']]
    xlsx,counts=build_workbook(snapshot,tables)
    docx=build_report(snapshot,figures)
    finding=snapshot['finding']['content']
    methods='\n\n'.join(report_text(m['title'],snapshot['language'])+'\n'+report_text(m.get('description',''),snapshot['language'])+'\n'+json.dumps({k:m.get(k,{}) for k in ('executed','parameters','software','source')},ensure_ascii=False,sort_keys=True) for m in finding['methods'])
    if not methods:methods='No performed methods provided. External results have not been recomputed.' if snapshot['language']=='en' else '外部结果未重算；未提供已执行方法。'
    captions='\n\n'.join(f"Figure {i} "+f['config'].get('title','')+'\n'+f['config'].get('caption','') for i,f in enumerate(snapshot['figures'],1))
    files={'analysis.docx':docx,'results.xlsx':xlsx,'methods.txt':methods.encode('utf-8'),'captions.txt':captions.encode('utf-8') or b'No figures selected.\n',
        'parameters.json':json.dumps([m.get('parameters',{}) for m in finding['methods']],ensure_ascii=False,sort_keys=True,indent=2).encode('utf-8'),
        'sources.json':json.dumps(finding['sources'],ensure_ascii=False,sort_keys=True,indent=2).encode('utf-8'),
        'export_counts.json':json.dumps(counts,ensure_ascii=False,sort_keys=True,indent=2).encode('utf-8'),
        'report_snapshot.json':json.dumps(snapshot,ensure_ascii=False,sort_keys=True,indent=2).encode('utf-8')}
    if presentation_enabled(snapshot):
        files['method_index.json']=json.dumps([dict(method_id=m['id'],parameters_index=i,
            parameters_sha256=hashlib.sha256(canonical(m.get('parameters',{})).encode()).hexdigest())
            for i,m in enumerate(finding['methods'])],ensure_ascii=False,sort_keys=True,indent=2).encode('utf-8')
    files.update({item['name']:checked_bytes(item) for item in payload['package_files']})
    for index,table in enumerate(payload['tables']):files[f'tables/table_{index:03d}.tsv']=checked_bytes(table)
    script='''# Run beside this package with Python 3.12+, python-docx, openpyxl and the matching PaperAssist source checkout.
# Tables are stored completely in results.xlsx; source SHA and row counts are in export_counts.json.
# Figure source panels/configuration/rebuild scripts are under figures/figure_NN/.
import hashlib,json
from pathlib import Path
root=Path(__file__).resolve().parent
manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
for member in manifest['members']:
    raw=(root/member['name']).read_bytes()
    assert len(raw)==member['size_bytes'] and hashlib.sha256(raw).hexdigest()==member['sha256'],member['name']
print('All package members match the fixed manifest')
'''
    files['verify_package.py']=script.encode('utf-8')
    # The package can rebuild the DOCX and selected XLSX tables without database
    # credentials or original matrices. Figure reconstruction keeps its own
    # original panels and configuration beside each figure.
    for name in ('research_report_docx.py','research_results_xlsx.py','research_report_images.py','research_method_text.py'):
        files['rebuild_support/'+name]=Path(__file__).with_name(name).read_bytes()
    files['rebuild_support/__init__.py']=b'# Offline report rebuild helpers.\n'
    rebuild='''import io,json,csv,hashlib
from pathlib import Path
from rebuild_support.research_report_docx import build_report
from rebuild_support.research_results_xlsx import build_workbook
from rebuild_support.research_report_images import as_png
root=Path(__file__).resolve().parent
snapshot=json.loads((root/'report_snapshot.json').read_text(encoding='utf-8'))
counts=json.loads((root/'export_counts.json').read_text(encoding='utf-8'))
tables=[]
for index,table in enumerate(snapshot['tables']):
    raw=(root/f'tables/table_{index:03d}.tsv').read_bytes()
    assert hashlib.sha256(raw).hexdigest()==table['sha256']
    rows=csv.reader(io.StringIO(raw.decode('utf-8')),delimiter='\\t',strict=True)
    assert next(rows)==table['columns']
    tables.append(dict(table,rows=rows))
figures=[]
for i,figure in enumerate(snapshot['figures'],1):
    member=figure['document_image']
    raw=(root/f'figures/figure_{i:02d}'/(member['key']+'.'+member['format'])).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==member['sha256']
    figures.append(dict(config=figure['config'],content=as_png(raw,member['format'])))
out=root/'rebuilt';out.mkdir(exist_ok=True)
(out/'analysis.docx').write_bytes(build_report(snapshot,figures))
xlsx,summary=build_workbook(snapshot,tables)
(out/'results.xlsx').write_bytes(xlsx)
assert summary==counts
print('Report content and complete table row counts rebuilt; OOXML container timestamps may differ')
'''
    files['rebuild_report.py']=rebuild.encode('utf-8')
    from importlib.metadata import version
    files['requirements-rebuild.txt']=('\n'.join(name+'=='+version(name) for name in ('python-docx','openpyxl','Pillow','pdfplumber'))+'\n').encode()
    files['README.txt']=('先运行 python verify_package.py 校验全部固定成员；再在已安装 requirements-rebuild.txt 依赖的 Python 环境运行 python rebuild_report.py。\n'
        'Rebuild regenerates report content and complete selected result tables; DOCX/XLSX ZIP timestamps may differ.\n'
        '图件重建脚本位于各 figures/figure_NN 目录，使用固定原图和对应 PaperAssist 源码。原始大矩阵仅保留固定来源引用。\n').encode('utf-8')
    if enforce_deadlines:signal.alarm(180)
    zipped,manifest=make_package(files,dict(finding_version_id=snapshot['finding']['id'],finding_sha256=snapshot['finding']['sha256'],
        figure_versions=[dict(id=f['id'],sha256=f['manifest_sha256']) for f in snapshot['figures']],included_pdf=snapshot.get('included_pdf'),
        raw_matrices='fixed source references only',real_model_calls=0))
    manifest_raw=json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2).encode('utf-8')
    export_files=dict(docx=('analysis','docx',docx),xlsx=('results','xlsx',xlsx),methods=('methods','txt',files['methods.txt']),
        manifest=('manifest','json',manifest_raw),zip=('analysis_package','zip',zipped))
    outputs=[];output=Path(output)
    for role,(key,fmt,raw) in export_files.items():
        path=output/(key+'.'+fmt);path.write_bytes(raw)
        outputs.append(dict(key=key,role=role,format=fmt,path=str(path.resolve()),sha256=hashlib.sha256(raw).hexdigest(),size_bytes=len(raw),
            properties={'table_counts':counts} if role=='xlsx' else {}))
    if enforce_deadlines:signal.alarm(0)
    return dict(outputs=outputs,manifest=dict(schema_version=1,kind='research_report',finding_version_id=snapshot['finding']['id'],
        renderer_identity=renderer_identity(),row_counts=counts,package_manifest=manifest,real_model_calls=False,real_network_calls=False))


def execute_research_report(payload,output):
    from app.core.exceptions import StorageError
    if sys.platform!='linux':raise StorageError('research_environment_unavailable','报告安全生成需要 Linux Worker。',409)
    try:
        result=subprocess.run([sys.executable,'-I','-B',str(Path(__file__).with_name('research_report_child.py'))],
            input=json.dumps(dict(payload=payload,output=str(output))).encode('utf-8'),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            timeout=305,env={},cwd='/',start_new_session=True,check=False)
        if result.returncode== -signal.SIGALRM:raise StorageError('research_render_timeout','报告或打包超过执行时限。',422)
        if result.returncode or len(result.stdout)>2*1024**2:raise ValueError('Invalid report output')
        value=json.loads(result.stdout)
        if value.get('error')=='research_export_limit_exceeded':raise StorageError('research_export_limit_exceeded','报告超过单元格、文件数或容量限制，请减少选定结果或拆分报告。',422)
        if value['manifest'].get('renderer_identity')!=renderer_identity():raise ValueError('Report renderer changed')
        return value
    except subprocess.TimeoutExpired as exc:raise StorageError('research_render_timeout','报告或打包超过执行时限。',422) from exc
    except (ValueError,OSError) as exc:raise StorageError('research_output_invalid','报告未通过完整性检查，请减少数据范围或核对来源。',422) from exc
