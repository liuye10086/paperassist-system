"""Actual retained GSE facts -> Linux rendered figures/report, without reanalysis."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'script/.runtime/client-requirements-b03'
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'script/dev')]


def docker_renderer(kind):
    def execute(payload,output):
        attempt=Path(output).parent.resolve();leaf=Path(output).name
        def convert(value):
            if isinstance(value,dict):return {k:convert(v) for k,v in value.items()}
            if isinstance(value,list):return [convert(v) for v in value]
            if isinstance(value,str) and Path(value).is_absolute() and Path(value).is_relative_to(attempt):
                return '/work/'+Path(value).relative_to(attempt).as_posix()
            return value
        request=dict(payload=convert(payload),output='/work/'+leaf)
        image='paperassist-client-b02-worker:local';name='cr-b03-output-'+uuid4().hex[:12]
        code='''import json,sys,time,resource
from pathlib import Path
sys.path.insert(0,'/app')
from app.adapters.research_figure_render import execute_research_figure
from app.adapters.research_report_render import execute_research_report
data=json.load(sys.stdin)
started=time.monotonic()
result=(execute_research_figure if data.pop('kind')=='figure' else execute_research_report)(data['payload'],Path(data['output']))
result['verification']={'elapsed_seconds':time.monotonic()-started,'child_maxrss_kib':resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,'container_limit_bytes':int(Path('/sys/fs/cgroup/memory.max').read_text()),'container_peak_bytes':int(Path('/sys/fs/cgroup/memory.peak').read_text()),'network':'none'}
print(json.dumps(result))
'''
        request['kind']=kind
        args=['docker','run','--rm','-i','--name',name,'--label','paperassist.batch=CR-B03','--network','none','--read-only','--memory','4g','--cpus','1',
            '--tmpfs','/tmp:rw,nosuid,nodev,size=512m','--mount',f'type=bind,source={ROOT/"backend/app"},target=/app/app,readonly',
            '--mount',f'type=bind,source={attempt},target=/work','--entrypoint','python',image,'-I','-B','-c',code]
        completed=subprocess.run(args,input=json.dumps(request).encode(),capture_output=True,timeout=340)
        evidence=RUNTIME/'render-evidence';evidence.mkdir(exist_ok=True)
        (evidence/(name+'.stderr.txt')).write_bytes(completed.stderr)
        if completed.returncode:
            (evidence/(name+'.stdout.txt')).write_bytes(completed.stdout)
            raise RuntimeError('Linux render failed; evidence retained: '+name)
        result=json.loads(completed.stdout);measurement=result.pop('verification')
        (evidence/(name+'.json')).write_text(json.dumps(measurement,indent=2),encoding='utf-8')
        for item in result['outputs']:
            item['path']=str(attempt/Path(item['path']).relative_to('/work'))
        return result
    return execute


def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--version',type=int,default=1)
    args=parser.parse_args()
    if args.version<1:raise ValueError('Positive output version required')
    suffix='' if args.version==1 else '-v'+str(args.version)
    previous=None
    if args.version>1:
        prior='' if args.version==2 else '-v'+str(args.version-1)
        previous=json.loads((RUNTIME/('actual-output-verification'+prior+'.json')).read_text(encoding='utf-8'))
    state=json.loads((RUNTIME/'state.json').read_text(encoding='utf-8-sig'))
    if state['clone_status']!='verified' or state['source_schema']==state['schema']:raise ValueError('Requires verified isolated clone')
    os.environ.update(PAPERASSIST_ENV='test',PAPERASSIST_DB_SCHEMA=state['schema'],PAPERASSIST_DATA_DIR=state['assets'],
        PAPERASSIST_RESEARCH_STAGING_DIR=state['staging'],PAPERASSIST_PLOT_WORKER_ENABLED='0',PAPERASSIST_WRITING_LIVE_ENABLED='0',
        PAPERASSIST_NCBI_ENABLED='0',OPENAI_API_KEY='')
    memory=subprocess.run(['docker','run','--rm','--network','none','--read-only','--memory','64m','--entrypoint','python','paperassist-client-b02-worker:local',
        '-c',"from pathlib import Path;print(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:')))"],capture_output=True,check=True)
    available=int(memory.stdout.strip())*1024
    if available<4*1024**3:raise RuntimeError('Docker available memory below approved 4GiB gate')
    from app.adapters.storage import ProjectStore
    from app.domain.research_results.contracts import FindingVersionRequest,ResearchFigureRequest,ResearchReportRequest
    from app.domain.research_results.findings import ResearchFindingService
    from app.domain.research_results.figures import ResearchFigureService
    from app.domain.research_results.reports import ResearchReportService
    from app.domain.research_results.execution import run_research_task
    credentials=json.loads((Path(state['assets']).parent/'credentials.json').read_text(encoding='utf-8-sig'))
    store=ProjectStore(Path(state['assets']),owner_id=credentials['review']['id'])
    project='e8ba52c6-0e85-42ac-8205-dd70f1851f03';processed='f88123c7-b269-5c43-8974-dd36c62ecd46'
    finding,_=ResearchFindingService(store).create(project,FindingVersionRequest(title='GSE262082 固定空间分析事实',
        sources=[dict(source_kind='bio_processed_dataset_version',source_id=processed)]),'b03-actual-gse-finding-v1')
    svc=ResearchFigureService(store)
    with svc.store.connection() as db:
        figures=db.execute("SELECT id,config_json FROM bio_figure_versions WHERE project_id=%s AND processed_dataset_version_id=%s AND config_json->>'kind' IN ('umap','spatial_cluster') ORDER BY config_json->>'kind'",(project,processed)).fetchall()
    if len(figures)!=2:raise ValueError('Expected fixed UMAP/spatial figures')
    figure,_=svc.create(project,ResearchFigureRequest(mode='composite',panels=[dict(source=dict(source_kind='bio_figure_version',source_id=f['id']),label=label) for f,label in zip(figures,['A','B'])],
        title='空间分布与降维探索',caption='公共数据再分析；spot 层级的探索性聚类，不代表独立 donor 重复或已确认细胞类型。',
        caption_sources=[dict(source_kind='research_finding_version',source_id=finding['id'])],caption_fact_ids=[f['id'] for f in finding['content']['facts'] if f['locator']['field_path']=='summary.clusters'],
        formats=['png','tiff','pdf','svg'],**(dict(root_id=previous['figure_root_id'] if 'figure_root_id' in previous else previous['figure_version_id'],expected_revision=args.version-1) if previous else {})),'b03-actual-gse-figure-v'+str(args.version))
    for value,kind,engine in [(figure,'research_figure',docker_renderer('figure'))]:
        if value['task']['status']!='succeeded':
            result=run_research_task(value['task_id'],value['task']['revision'],task_type=kind,config=store.db_config,directory=store.directory,engine=engine,staging_directory=state['staging'])
            if not result or result['status']!='succeeded':raise RuntimeError('Actual figure task failed; retained '+value['task_id'])
    reports=ResearchReportService(store)
    report,_=reports.create(project,ResearchReportRequest(title='GSE262082 空间转录组分析报告',finding_version_id=finding['id'],figure_version_ids=[figure['id']],
        **(dict(root_id=previous.get('report_root_id',previous['report_version_id']),expected_revision=args.version-1) if previous else {})),'b03-actual-gse-report-v'+str(args.version))
    if report['task']['status']!='succeeded':
        result=run_research_task(report['task_id'],report['task']['revision'],task_type='research_report',config=store.db_config,directory=store.directory,engine=docker_renderer('report'),staging_directory=state['staging'])
        if not result or result['status']!='succeeded':raise RuntimeError('Actual report task failed; retained '+report['task_id'])
    final=reports.get(project,report['id']);export=RUNTIME/('actual-delivery'+suffix);export.mkdir(exist_ok=True)
    for member in final['members']:
        metadata,raw=reports.member(project,report['id'],member['id']);(export/metadata['filename']).write_bytes(raw)
    receipt=dict(project_id=project,finding_version_id=finding['id'],figure_version_id=figure['id'],report_version_id=report['id'],
        figure_root_id=figure['root_id'],report_root_id=report['root_id'],revision=args.version,
        docker_available_bytes_before=available,report_manifest_sha256=final['manifest_sha256'],members=final['members'],
        row_counts=final['manifest']['row_counts'],reanalysis_performed=False,real_model_calls=0,network_business_calls=0,
        validation='actual retained GSE outputs with Linux isolated render; not biological validation or user acceptance')
    (RUNTIME/('actual-output-verification'+suffix+'.json')).write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:receipt[k] for k in ('finding_version_id','figure_version_id','report_version_id','row_counts')},ensure_ascii=False))


if __name__=='__main__':main()
