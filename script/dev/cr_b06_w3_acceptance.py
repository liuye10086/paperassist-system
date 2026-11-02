"""Reuse fixed W2 bytes for W3 first/revision; final is exercised in the UI."""
import argparse
import hashlib
import json
from pathlib import Path
import time

import cr_b06_w3_runtime as runtime

RUNTIME = runtime.RUNTIME


def client():
    value=runtime.state();runtime.configure(value)
    from fastapi.testclient import TestClient
    from app.main import app
    c=TestClient(app)
    c.headers.update({'X-PaperAssist-Client':'web','Origin':'http://testserver'})
    credentials=runtime.read(Path(value['assets']).parent/'credentials.json')
    result=c.post('/api/v1/auth/login',json=credentials)
    assert result.status_code==200, result.status_code
    c.headers['X-CSRF-Token']=result.json()['csrf_token']
    return c,value


def execution_inventory():
    value=runtime.state();runtime.configure(value)
    from app.db.database import get_engine
    with get_engine().connect() as db:
        db.exec_driver_sql("SELECT set_config('search_path',%s,true)",(value['schema'],))
        tasks=[dict(x) for x in db.exec_driver_sql('SELECT id,task_type,input_digest FROM tasks ORDER BY id').mappings()]
        outputs={table:[row[0] for row in db.exec_driver_sql('SELECT id FROM '+table+' ORDER BY id')]
            for table in ('files','manuscript_versions','manuscript_exports','pdf_exports')}
        stored=[dict(x) for x in db.exec_driver_sql('SELECT object_key,sha256,size_bytes FROM storage_objects ORDER BY object_key').mappings()]
        prepared={x['task_id']:x['state_json']['prepared'] for x in db.exec_driver_sql(
            "SELECT DISTINCT ON (c.task_id) c.task_id,c.state_json FROM task_checkpoints c JOIN tasks t ON t.id=c.task_id "
            "WHERE t.task_type='delivery_package' AND t.status='succeeded' ORDER BY c.task_id,c.seq DESC").mappings()}
    return dict(tasks=tasks,outputs=outputs,storage_objects=stored,prepared_packages=prepared)


def save_execution_baseline():
    path=RUNTIME/'execution-baseline.json'
    if path.exists():return dict(reused=True,tasks=len(runtime.read(path)['tasks']))
    value=execution_inventory()
    assert len(value['tasks'])==runtime.read(RUNTIME/'copy-selection.json')['counts']['tasks']
    assert not any(x['task_type']=='delivery_package' for x in value['tasks'])
    runtime.save(path,value)
    return dict(tasks=len(value['tasks']),stored_objects=len(value['storage_objects']))


def request(c,label,path,body):
    folder=RUNTIME/'requests'/label;folder.mkdir(parents=True,exist_ok=True)
    intent=dict(path=path,body=body,request_key='w3-'+label)
    request_path=folder/'request.json';response_path=folder/'response.json'
    if request_path.exists():
        assert runtime.read(request_path)==intent, 'Saved request differs; retain original request identity'
        if response_path.exists():
            saved=runtime.read(response_path)
            assert saved['status_code'] in (200,201,202), 'Inspect the retained failed request before repair'
            return saved['body']
        raise RuntimeError('Unknown prior outcome; recover original request before another POST')
    runtime.save(request_path,intent)
    result=c.post(path,json=body,headers={'Idempotency-Key':intent['request_key']})
    runtime.save(response_path,dict(status_code=result.status_code,body=result.json()))
    assert result.status_code in (200,201,202), result.text
    return result.json()


def seed():
    c,value=client();base='/api/v1/projects/'+value['project_id']
    root=c.get(base+'/research-intake');assert root.status_code==200,root.text
    body=dict(expected_revision=root.json()['revision'],operation='save',content=dict(schema_version=1,services=['sci_draft'],
        notes='W3工程交付验证：只复用W2既有SCI双语DOCX、其精确来源PDF和原PNG。首次显式缺PDF，后续只加入既有PDF；不新增写作、翻译或科学分析。真实语义/图内语言、真实投稿合规和科学结论不在此工程验收范围。'),material_refs=[])
    # The initial engineering-requirements request was definitively rejected (422)
    # for missing schema_version. Retain it; this corrected body has its own identity.
    old=RUNTIME/'requests'/'engineering-requirements-v1'/'request.json'
    if old.exists():body=runtime.read(old)['body']
    requirement=request(c,'engineering-requirements-v1',base+'/requirements',body)
    intake=c.get(base+'/research-intake').json()
    delivery=next(d for d in intake['deliveries'] if d['kind']=='sci_draft')
    selection=dict(project_id=value['project_id'],delivery_id=delivery['id'],requirement_version_id=requirement['version']['id'])
    runtime.save(RUNTIME/'representative-selection.json',selection)
    return selection


def first_revision():
    c,value=client();fixed=runtime.read(RUNTIME/'representative-selection.json')
    base=f'/api/v1/projects/{fixed["project_id"]}/deliveries/{fixed["delivery_id"]}'
    response=c.get(base+'/candidates');assert response.status_code==200,response.text
    candidates=response.json();runtime.save(RUNTIME/'existing-candidates.json',candidates)
    docx=next(x['selection'] for x in candidates['items'] if x['selection'].get('export_id')=='cf164bc3-c501-4aa0-a541-33012fe4316f')
    pdf=next(x['selection'] for x in candidates['items'] if x['selection'].get('export_id')=='d091159d-dcfd-4c01-b18e-123fecb8ce5e')
    png=next(x['selection'] for x in candidates['items'] if x['selection'].get('file_id')=='11672bf2-7c58-598e-89d1-86e4c514cd49')
    png=dict(png,figure_mapping=dict(figure_number='Figure 1',panel_order=['A'],caption='固定W2版式工程图，原字节复用；不作新的科学推断。',confirmed=True))
    shared=dict(requirement_version_id=fixed['requirement_version_id'],opinion_round='工程演示，无实际客户意见轮次',
        mode='complete',required_formats=['docx','pdf','png'],quality_items=['合成工程材料；真实双语语义、图内文字、真实合规和科学结论未由本次交付确认。'])
    first=request(c,'first-snapshot',base+'/snapshots',dict(shared,stage='first',parent_snapshot_id=None,expected_revision=0,
        change_note='首次工程交付：只纳入既有DOCX和原PNG；必需PDF明确待补，允许下载当前有效成员。',members=[docx,png]))
    assert first['completeness']=='missing_required'
    package=request(c,'first-package',base+'/snapshots/'+first['id']+'/package',{})
    runtime.save(RUNTIME/'first-package-task.json',package)
    revision=request(c,'revision-snapshot',base+'/snapshots',dict(shared,stage='revision',parent_snapshot_id=first['id'],expected_revision=first['revision'],
        change_note='修订工程交付：加入已存在且来源SHA匹配的W2 PDF；不重新导出，不生成中间ZIP。',members=[docx,pdf,png]))
    current=c.get(base+'/snapshots/'+first['id']).json()
    assert current['sha256']==first['sha256'] and current['completeness']=='missing_required'
    runtime.save(RUNTIME/'representative-stages.json',dict(first=first,revision=revision,final='pending_actual_browser',
        actual_packages_created=1,bottom_level_outputs_regenerated=0,source='W2 fixed SCI project; synthetic engineering only'))
    return dict(first_id=first['id'],revision_id=revision['id'],task_id=package['task_id'],final='pending_actual_browser')


def observe_first():
    c,_=client();fixed=runtime.read(RUNTIME/'representative-selection.json');stages=runtime.read(RUNTIME/'representative-stages.json')
    base=f'/api/v1/projects/{fixed["project_id"]}/deliveries/{fixed["delivery_id"]}/snapshots/{stages["first"]["id"]}'
    task_id=runtime.read(RUNTIME/'first-package-task.json')['task_id'];deadline=time.monotonic()+120
    while True:
        response=c.get('/api/v1/tasks/'+task_id);assert response.status_code==200,response.text
        task=response.json();runtime.save(RUNTIME/'first-task-observation.json',task)
        if task['status'] in ('succeeded','failed','cancelled'):break
        if time.monotonic()>=deadline:raise RuntimeError('Observation timeout; same task retained, do not POST another package')
        time.sleep(1)
    assert task['status']=='succeeded', task
    response=c.get(base+'/download');assert response.status_code==200,response.text
    raw=response.content;assert hashlib.sha256(raw).hexdigest()==response.headers['X-Content-SHA256']
    from app.domain.research_results.report_package import verify_package
    manifest=verify_package(raw)
    folder=RUNTIME/'outputs'/'first';folder.mkdir(parents=True,exist_ok=True)
    target=folder/'delivery.zip'
    if target.exists():assert target.read_bytes()==raw
    else:target.write_bytes(raw)
    runtime.save(folder/'manifest.json',manifest)
    result=dict(task_id=task_id,status=task['status'],sha256=hashlib.sha256(raw).hexdigest(),size_bytes=len(raw),
        member_count=len(manifest['members']),task_dispatch='existing RabbitMQ/Celery/dispatcher, no direct run_task',
        bottom_level_outputs_regenerated=0)
    runtime.save(folder/'receipt.json',result)
    return result


def verify_final():
    """Read back the browser-created final and existing bytes; never submit work."""
    import io
    import zipfile
    from fastapi.testclient import TestClient
    c,_=client();fixed=runtime.read(RUNTIME/'representative-selection.json')
    stages=runtime.read(RUNTIME/'representative-stages.json')
    base=f'/api/v1/projects/{fixed["project_id"]}/deliveries/{fixed["delivery_id"]}/snapshots'
    response=c.get(base);assert response.status_code==200,response.text
    snapshots=response.json()['items'];assert len(snapshots)==3
    final=next(x for x in snapshots if x['stage']=='final')
    first=next(x for x in snapshots if x['stage']=='first')
    assert final['parent_snapshot_id']==stages['revision']['id']
    assert first['sha256']==stages['first']['sha256'] and first['completeness']=='missing_required'
    assert final['gaps']==[] and final['completeness']=='quality_unresolved'
    package=c.get(base+'/'+final['id']+'/package').json()
    assert package['task']['status']=='succeeded',package
    first_package=c.get(base+'/'+first['id']+'/package').json()
    assert first_package['task_id']==runtime.read(RUNTIME/'first-package-task.json')['task_id']
    response=c.get(base+'/'+final['id']+'/download');assert response.status_code==200,response.text
    raw=response.content;digest=hashlib.sha256(raw).hexdigest()
    assert digest==response.headers['X-Content-SHA256']
    from app.domain.research_results.report_package import verify_package
    manifest=verify_package(raw)
    assert manifest['identity']['snapshot_sha256']==final['sha256']
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        archived=json.loads(archive.read('delivery.json'))
        assert archived['sha256']==final['sha256']
        hashes=archive.read('SHA256SUMS.txt').decode().splitlines()
        for line in hashes:
            sha,name=line.split('  ',1)
            assert hashlib.sha256(archive.read(name)).hexdigest()==sha
        for member in final['members']:
            result=c.get(base+'/'+final['id']+'/members/'+member['id']+'/download')
            assert result.status_code==200 and result.content==archive.read(member['name'])
            assert result.headers['X-Content-SHA256']==member['sha256']
    events=c.get(base+'/'+final['id']+'/acceptances').json()['items']
    assert len(events)==1 and events[0]['snapshot_sha256']==final['sha256']
    before=runtime.read(RUNTIME/'execution-baseline.json');after=execution_inventory()
    old_tasks={x['id']:x for x in before['tasks']};current_tasks={x['id']:x for x in after['tasks']}
    assert all(current_tasks[k]==v for k,v in old_tasks.items())
    new_tasks=[v for k,v in current_tasks.items() if k not in old_tasks]
    assert {x['id'] for x in new_tasks}=={package['task_id'],first_package['task_id']}
    assert all(x['task_type']=='delivery_package' for x in new_tasks)
    assert after['outputs']==before['outputs'], 'Unexpected new lower-level output'
    originals={x['object_key']:x for x in before['storage_objects']}
    current={x['object_key']:x for x in after['storage_objects']}
    assert all(current[k]==v for k,v in originals.items())
    new_objects=[v for k,v in current.items() if k not in originals]
    prepared=after['prepared_packages'];assert set(prepared)=={x['id'] for x in new_tasks}
    package_members=[member for item in prepared.values() for member in item['members']]
    assert len(package_members)==2 and all(m['format']=='zip' for m in package_members)
    expected_objects={m['object_key']:{k:m[k] for k in ('object_key','sha256','size_bytes')}
        for m in package_members+[p['manifest_ref'] for p in prepared.values()]}
    assert {m['object_key']:m for m in new_objects}==expected_objects, 'Unexpected publication object'
    runtime.save(RUNTIME/'execution-budget-verification.json',dict(before=before,after=after,new_tasks=new_tasks,
        new_storage_objects=new_objects,bottom_level_output_identity_unchanged=True))
    from app.main import app
    denied=TestClient(app).get(base+'/'+final['id']+'/download')
    assert denied.status_code==401,denied.status_code
    folder=RUNTIME/'outputs'/'final';folder.mkdir(parents=True,exist_ok=True)
    target=folder/'delivery.zip'
    if target.exists():assert target.read_bytes()==raw
    else:target.write_bytes(raw)
    runtime.save(folder/'manifest.json',manifest)
    runtime.save(folder/'snapshot.json',final)
    runtime.save(folder/'acceptance-events.json',events)
    runtime.save(folder/'package.json',package)
    runtime.save(RUNTIME/'actual-snapshots.json',dict(items=snapshots))
    stages.update(final=final,actual_packages_created=2)
    runtime.save(RUNTIME/'representative-stages.json',stages)
    result=dict(snapshot_id=final['id'],snapshot_sha256=final['sha256'],task_id=package['task_id'],
        status=package['task']['status'],sha256=digest,size_bytes=len(raw),member_count=len(manifest['members']),
        fixed_artifacts=len(final['members']),zip_and_individual_downloads_equal=True,checksum_file_verified=True,
        original_first_snapshot_unchanged=True,first_package_identity_unchanged=True,unauthenticated_download=denied.status_code,
        browser_acceptance_event_id=events[0]['id'],customer_acceptance='pending; browser event is engineering scope only',
        actual_snapshots=len(snapshots),actual_packages=len(new_tasks),bottom_level_outputs_regenerated=0)
    runtime.save(folder/'receipt.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('seed','save-execution-baseline','first-revision','observe-first','verify-final'))
    args=parser.parse_args()
    print(json.dumps(globals()[args.action.replace('-','_')](),ensure_ascii=True,default=str))
