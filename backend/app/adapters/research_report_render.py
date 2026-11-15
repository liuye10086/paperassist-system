"""Report render/pack in a secret-free, memory- and time-bounded subprocess."""
import hashlib
import json
from pathlib import Path
import signal
import subprocess
import sys


def renderer_identity():
    from importlib.metadata import version
    names=('research_report_render.py','research_report_child.py','research_report_docx.py','research_results_xlsx.py',
        'research_report_images.py','research_method_text.py','reader_report_presentation.py')
    paths=[Path(__file__).with_name(name) for name in names]+[Path(__file__).parents[1]/'domain/research_results/report_package.py']
    return dict(renderer_version='research_report_v1',code_digest=hashlib.sha256(b''.join(p.read_bytes() for p in paths)).hexdigest(),
        dependencies={name:version(name) for name in ('python-docx','openpyxl','Pillow','pdfplumber')},
        limits={'render_seconds':120,'package_seconds':180,'subprocess_memory_bytes':2*1024**3})


def stage_report_payload(payload,directory):
    directory=Path(directory);result=dict(payload)
    tables=[]
    for i,(table,raw) in enumerate(zip(payload['tables'],payload['table_raws'])):
        path=directory/f"table_{i}.{table.get('format','tsv')}";path.write_bytes(raw);tables.append(dict(table,path=str(path.resolve())))
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
    from app.adapters.research_report_docx import build_report,reader_text
    from app.adapters.research_results_xlsx import build_workbook
    from app.domain.research_results.report_package import make_package
    from app.adapters.research_report_images import as_png
    from app.adapters.research_method_text import presentation_enabled,canonical,reader_method
    from app.adapters.reader_report_presentation import reader_figure,report_table
    if enforce_deadlines:signal.alarm(120)
    snapshot=payload['snapshot'];tables=[];cluster_summaries=[]
    record=snapshot.get('reader_report')
    provenance={'reader_report_provenance':record['provenance']} if record is not None else {}
    if record is not None:
        if [{k:v for k,v in table.items() if k!='path'} for table in payload['tables']]!=snapshot.get('tables',[]):
            raise ValueError('Selected report tables changed')
        if len(record['figures'])!=len(snapshot['figures']) or len(payload['figures'])!=len(snapshot['figures']):
            raise ValueError('Report narrative figure count changed')
        for staged,fixed in zip(payload['figures'],snapshot['figures']):
            if any(staged[k]!=fixed['document_image'][k] for k in ('format','sha256')):
                raise ValueError('Report narrative figure source changed')
    for index,table in enumerate(payload['tables'],1):
        parsed,summary=report_table(table,checked_bytes(table),summarize=record is not None)
        tables.append(parsed)
        if summary is not None:cluster_summaries.append((index,table['source'],*summary))
    figures=[dict(config=f['config'],content=as_png(checked_bytes(f),f.get('format','png'))) for f in payload['figures']]
    xlsx,counts=build_workbook(snapshot,tables)
    docx=build_report(snapshot,figures,cluster_summaries=cluster_summaries)
    finding=snapshot['finding']['content']
    methods='\n\n'.join('\n'.join(reader_text(text,snapshot['language']) for text in (m['title'],*m['paragraphs']))
        for m in (reader_method(method,snapshot['language']) for method in finding['methods']))
    if not methods:methods='No performed methods provided. External results have not been recomputed.' if snapshot['language']=='en' else '外部结果未重算；未提供已执行方法。'
    if record is None:
        shown_figures=[f['config'] for f in snapshot['figures']]
    else:
        shown_figures=[reader_figure(record,i) for i in range(1,len(figures)+1)]
    prefix='Figure' if snapshot['language']=='en' or record is None else '图'
    captions='\n\n'.join(f"{prefix} {i} "+f.get('title','')+'\n'+f.get('caption','') for i,f in enumerate(shown_figures,1))
    if not captions:captions='未选图件。\n' if prefix=='图' else 'No figures selected.\n'
    files={'analysis.docx':docx,'results.xlsx':xlsx,'methods.txt':methods.encode('utf-8'),'captions.txt':captions.encode('utf-8'),
        'parameters.json':json.dumps([m.get('parameters',{}) for m in finding['methods']],ensure_ascii=False,sort_keys=True,indent=2).encode('utf-8'),
        'sources.json':json.dumps(finding['sources'],ensure_ascii=False,sort_keys=True,indent=2).encode('utf-8'),
        'export_counts.json':json.dumps(counts,ensure_ascii=False,sort_keys=True,indent=2).encode('utf-8'),
        'report_snapshot.json':json.dumps(snapshot,ensure_ascii=False,sort_keys=True,indent=2).encode('utf-8')}
    if presentation_enabled(snapshot):
        files['method_index.json']=json.dumps([dict(method_id=m['id'],parameters_index=i,
            parameters_sha256=hashlib.sha256(canonical(m.get('parameters',{})).encode()).hexdigest())
            for i,m in enumerate(finding['methods'])],ensure_ascii=False,sort_keys=True,indent=2).encode('utf-8')
    files.update({item['name']:checked_bytes(item) for item in payload['package_files']})
    if record is not None:
        for index,figure in enumerate(snapshot['figures'],1):
            if figure['document_image']['format']=='pdf':
                # An older PDF-only figure remains a valid source. Rebuild the
                # report from the rendered bitmap without packaging the PDF.
                files[f'figures/figure_{index:02d}/document_image.png']=figures[index-1]['content']
    for index,table in enumerate(payload['tables']):files[f"tables/table_{index:03d}.{table.get('format','tsv')}"]=checked_bytes(table)
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
    for name in ('research_report_docx.py','research_results_xlsx.py','research_report_images.py',
                 'research_method_text.py','reader_report_presentation.py'):
        files['rebuild_support/'+name]=Path(__file__).with_name(name).read_bytes()
    files['rebuild_support/__init__.py']=b'# Offline report rebuild helpers.\n'
    rebuild='''import json,hashlib
from pathlib import Path
from rebuild_support.research_report_docx import build_report
from rebuild_support.research_results_xlsx import build_workbook
from rebuild_support.research_report_images import as_png
from rebuild_support.reader_report_presentation import report_table
root=Path(__file__).resolve().parent
snapshot=json.loads((root/'report_snapshot.json').read_text(encoding='utf-8'))
counts=json.loads((root/'export_counts.json').read_text(encoding='utf-8'))
manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
hashes={member['name']:member['sha256'] for member in manifest['members']}
tables=[]
cluster_summaries=[]
for index,table in enumerate(snapshot['tables']):
    raw=(root/f"tables/table_{index:03d}.{table.get('format','tsv')}").read_bytes()
    assert hashlib.sha256(raw).hexdigest()==table['sha256']
    parsed,summary=report_table(table,raw,summarize=snapshot.get('reader_report') is not None)
    tables.append(parsed)
    if summary is not None:cluster_summaries.append((index+1,table['source'],*summary))
figures=[]
for i,figure in enumerate(snapshot['figures'],1):
    member=figure['document_image']
    directory=f'figures/figure_{i:02d}'
    if member['format']=='pdf' and snapshot.get('reader_report') is not None:
        name=f'{directory}/document_image.png'
        content=(root/name).read_bytes()
        assert hashlib.sha256(content).hexdigest()==hashes[name]
    else:
        raw=(root/directory/(member['key']+'.'+member['format'])).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==member['sha256']
        content=as_png(raw,member['format'])
    figures.append(dict(config=figure['config'],content=content))
out=root/'rebuilt';out.mkdir(exist_ok=True)
(out/'analysis.docx').write_bytes(build_report(snapshot,figures,cluster_summaries=cluster_summaries))
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
        raw_matrices='fixed source references only',real_model_calls=0,**provenance))
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
        renderer_identity=renderer_identity(),row_counts=counts,package_manifest=manifest,real_model_calls=False,real_network_calls=False,**provenance))


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
