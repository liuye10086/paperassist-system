from tests.api.test_research_findings import client, selected_cell
from app.db.database import database_connection
import pytest


@pytest.fixture(autouse=True)
def synthetic_capacity(monkeypatch):
    from app.domain.storage_governance import service
    monkeypatch.setattr(service.shutil,'disk_usage',lambda _:type('Disk',(),{'total':100*1024**3,'free':90*1024**3})())


def setup_delivery(client):
    base,source=selected_cell(client)
    intake=client.get(base+'/research-intake').json()
    requirement=client.post(base+'/requirements',json={'expected_revision':1,'operation':'save','content':{'schema_version':1,'services':['analysis']},'material_refs':[]},headers={'Idempotency-Key':'requirements'}).json()['version']
    endpoint=base+'/deliveries/'+intake['deliveries'][0]['id']
    body=dict(stage='first',expected_revision=0,requirement_version_id=requirement['id'],change_note='Synthetic existing member only',opinion_round='engineering-1',required_formats=['xlsx','pdf'],members=[dict(kind='file',file_id=source['source_id'])])
    return base,endpoint,body


def test_snapshot_revision_gap_replay_acceptance_and_retention(client):
    base,path,body=setup_delivery(client)
    first=client.post(path+'/snapshots',json=body,headers={'Idempotency-Key':'freeze-first'})
    assert first.status_code==201,first.text
    first=first.json();assert first['completeness']=='missing_required' and first['gaps']==['required_format:pdf']
    assert client.post(path+'/snapshots',json=body,headers={'Idempotency-Key':'freeze-first'}).json()['id']==first['id']
    assert client.post(path+'/snapshots',json=dict(body,change_note='changed'),headers={'Idempotency-Key':'freeze-first'}).status_code==409
    assert client.post(path+'/snapshots',json=body,headers={'Idempotency-Key':'stale'}).status_code==409
    second=dict(body,stage='revision',expected_revision=1,parent_snapshot_id=first['id'],change_note='Keep explicit PDF gap')
    two=client.post(path+'/snapshots',json=second,headers={'Idempotency-Key':'freeze-second'});assert two.status_code==201,two.text
    final=dict(second,stage='final',expected_revision=2,parent_snapshot_id=two.json()['id'])
    three=client.post(path+'/snapshots',json=final,headers={'Idempotency-Key':'freeze-final'});assert three.status_code==201,three.text
    assert three.json()['completeness']=='missing_required'
    assert client.get(path+'/snapshots/'+first['id']).json()['sha256']==first['sha256']
    downloaded=client.get(first['members'][0]['download_url']);assert downloaded.status_code==200,downloaded.text
    from hashlib import sha256
    assert sha256(downloaded.content).hexdigest()==first['members'][0]['sha256']
    acceptance=dict(snapshot_sha256=first['sha256'],kind='accept',scope='工程夹具已有XLSX',reservations='PDF未齐',comment='Explicit owner operation')
    event=client.post(path+'/snapshots/'+first['id']+'/acceptances',json=acceptance,headers={'Idempotency-Key':'accept'});assert event.status_code==201,event.text
    assert event.json()['actor_kind']=='current_user'
    assert client.get(path+'/snapshots/'+first['id']).json()['sha256']==first['sha256']
    with database_connection() as db:
        refs=db.execute('SELECT snapshot_json FROM delivery_snapshots WHERE id=%s',(first['id'],)).fetchone()
        assert body['members'][0]['file_id'] in refs['snapshot_json']['source_file_ids']
        from app.domain.file_lifecycle.references import read_references
        file=db.execute('SELECT * FROM files WHERE id=%s',(body['members'][0]['file_id'],)).fetchone()
        owner=db.execute('SELECT user_id FROM delivery_snapshots WHERE id=%s',(first['id'],)).fetchone()['user_id']
        retained=read_references(db,file,owner)
        assert retained['groups']['delivery_snapshots'][0]['id']==first['id']
        assert 'research_results_history_retained' in retained['reasons']
    with pytest.raises(Exception,match='append-only'):
        with database_connection(write=True) as db:db.execute('UPDATE delivery_snapshots SET revision=99 WHERE id=%s',(first['id'],))
    blind=dict(body,mode='blind',expected_revision=3,parent_snapshot_id=three.json()['id'],stage='revision')
    assert client.post(path+'/snapshots/preview',json=blind).status_code==409
    assert client.post(path+'/snapshots',json=dict(body,members=[dict(kind='file',file_id='foreign')]),headers={'Idempotency-Key':'foreign'}).status_code in (404,409)


def test_package_task_contract_and_in_memory_zip(client):
    from app.domain.delivery_packages.render import build_package
    from app.domain.research_results.report_package import verify_package
    base,path,body=setup_delivery(client)
    saved=client.post(path+'/snapshots',json=body,headers={'Idempotency-Key':'package-snapshot'});assert saved.status_code==201,saved.text
    saved=saved.json();member=saved['members'][0]
    raw=client.get(member['download_url']).content
    package,manifest=build_package(saved,[raw])
    assert verify_package(package)==manifest
    import io,zipfile,json
    with zipfile.ZipFile(io.BytesIO(package)) as z:
        assert z.read(member['name'])==raw
        assert json.loads(z.read('delivery.json'))['sha256']==saved['sha256']
    endpoint=path+'/snapshots/'+saved['id']+'/package'
    queued=client.post(endpoint,json={},headers={'Idempotency-Key':'package-one'});assert queued.status_code==201,queued.text
    assert queued.json()['task']['task_type']=='delivery_package'
    assert client.post(endpoint,json={},headers={'Idempotency-Key':'package-one'}).json()['task_id']==queued.json()['task_id']
    task_id=queued.json()['task_id']
    assert client.get('/api/v1/tasks/'+task_id).status_code==200
    assert client.get('/api/v1/tasks/'+task_id+'/workspace').status_code==200
    with database_connection() as db:
        from app.maintenance.research_results_audit import validate_research_task_source
        task=db.execute('SELECT * FROM tasks WHERE id=%s',(task_id,)).fetchone()
        assert validate_research_task_source(db,task)['id']==saved['id']
    from app.adapters.task_execution_store import TaskExecutionStore
    repository=TaskExecutionStore();lease=repository.claim(task_id,1,task_type='delivery_package');assert lease
    with database_connection(write=True) as db:db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s AND attempt_no=%s",(task_id,lease.attempt_no))
    assert repository.recover_expired()==1
    assert repository.heartbeat(lease) is False
    recovered=client.get(endpoint).json();assert recovered['task_id']==task_id and recovered['task']['status']=='queued'
    assert client.post(endpoint,json={},headers={'Idempotency-Key':'package-one'}).json()['task_id']==task_id
    with database_connection() as db:
        assert db.execute("SELECT count(*) AS n FROM tasks WHERE task_type='delivery_package'").fetchone()['n']==1
        assert db.execute('SELECT count(*) AS n FROM task_attempts WHERE task_id=%s',(task_id,)).fetchone()['n']==1




def test_image_metadata_pdf_and_missing_dpi_do_not_invent_resolution():
    from app.domain.delivery_packages.sources import image_properties
    import io
    from PIL import Image
    output=io.BytesIO();Image.new('RGB',(8,6)).save(output,format='PNG')
    png=image_properties(output.getvalue(),'png');assert png['pixels']==[8,6] and png['dpi_measured'] is None
    svg=image_properties(b'<svg xmlns="http://www.w3.org/2000/svg" width="10mm" height="10mm"><image href="data:image/png;base64,AA=="/></svg>','svg')
    assert svg['contains_raster'] is True and svg['dpi_measured'] is None
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 72 144] /Resources << >> >>']
    raw=b'%PDF-1.4\n';offsets=[0]
    for i,obj in enumerate(objects,1):offsets.append(len(raw));raw+=str(i).encode()+b' 0 obj\n'+obj+b'\nendobj\n'
    start=len(raw);raw+=b'xref\n0 4\n0000000000 65535 f \n'+b''.join(f'{v:010d} 00000 n \n'.encode() for v in offsets[1:])+b'trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n'+str(start).encode()+b'\n%%EOF\n'
    pdf=image_properties(raw,'pdf');assert pdf['page_sizes_mm']==[[25.4,50.8]] and pdf['contains_raster'] is False and pdf['dpi_measured'] is None

def test_grouped_report_members_reduce_full_reads_preserving_sha_scope_and_corruption(client,monkeypatch):
    """Static tiny member fixture; no report renderer or package executor is called."""
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.adapters.task_store import DatasetTaskAssets
    from app.adapters.research_objects import ResearchObjects
    from app.domain.research_results.reports import ResearchReportService
    from app.domain.delivery_packages.service import DeliveryService
    from app.domain.delivery_packages.sources import resolve_members
    from app.domain.delivery_packages.contracts import Selection
    from app.domain.bioinformatics.contracts import canonical
    from app.core.config import get_data_dir
    from uuid import uuid4
    from hashlib import sha256
    from psycopg.types.json import Jsonb
    base,path,body=setup_delivery(client);project=base.rsplit('/',1)[-1];delivery=path.rsplit('/',1)[-1]
    finding=client.post(base+'/research-findings',json=dict(title='Tiny static closure',sources=[dict(source_kind='original_file',source_id=body['members'][0]['file_id'])]),headers={'Idempotency-Key':'read-finding'}).json()
    response=client.post(base+'/research-reports',json=dict(title='Static fixture only',finding_version_id=finding['id']),headers={'Idempotency-Key':'read-report'});assert response.status_code==201,response.text
    report=response.json();repository=TaskExecutionStore();lease=repository.claim(report['task_id'],1,task_type='research_report');assert lease
    with repository.connection(write=True) as db:
        task=repository.require_lease(db,lease);assets=DatasetTaskAssets(task['user_id'],repository.config,get_data_dir());objects=ResearchObjects(assets.directory);members=[]
        for index in (1,2):
            raw=f'Frozen output {index}\n'.encode()
            if index==2:
                from app.domain.research_results.report_package import make_package
                raw,_=make_package({'table.tsv':b'value\n0\n'},dict(kind='tiny_fixture'))
            record=objects.describe(report['id'],raw);objects.write(record,raw)
            member=dict(id=str(uuid4()),key='tiny_'+str(index),role='methods' if index==1 else 'zip',format='txt' if index==1 else 'zip',**record,properties={});members.append(member)
        manifest=dict(schema_version=1,members=[{k:v for k,v in m.items() if k!='object_key'} for m in members]);manifest_ref=objects.describe(report['id'],canonical(manifest),json=True);objects.write(manifest_ref,canonical(manifest))
        for record in [*members,manifest_ref]:
            object_id=str(uuid4());db.execute("INSERT INTO storage_objects(id,namespace,object_key,size_bytes,sha256,state,scanned_at) VALUES(%s,'local:assets-v1',%s,%s,%s,'present',clock_timestamp())",(object_id,record['object_key'],record['size_bytes'],record['sha256']))
            db.execute("INSERT INTO storage_references(object_id,project_id,owner_id,kind) VALUES(%s,%s,%s,'research_report')",(object_id,project,task['user_id']))
        cp=db.execute('SELECT * FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(task['id'],)).fetchone()
        done=ResearchReportService(assets).publish(db,task,cp,repository.now(db),dict(manifest_ref=manifest_ref,members=members),progress=lambda:None);assert done['status']=='succeeded'
    reads=[];original=ResearchObjects.read
    def counted(self,record):reads.append(record['object_key']);return original(self,record)
    monkeypatch.setattr(ResearchObjects,'read',counted)
    service=ResearchReportService(assets);old=[service.member(project,report['id'],m['id'])[1] for m in members];old_count=len(reads);reads.clear()
    selections=[Selection(kind='research_report_member',version_id=report['id'],member_id=m['id']) for m in members]
    delivery_service=DeliveryService(assets)
    with delivery_service.store.connection() as db:
        resolved,raws,_=resolve_members(delivery_service,db,project,dict(id=delivery),selections,'complete')
    new_count=len(reads)
    assert raws==old and [sha256(r).hexdigest() for r in raws]==[m['sha256'] for m in resolved]
    import io,zipfile
    with zipfile.ZipFile(io.BytesIO(raws[1])) as inner:
        assert resolved[1]['source_metadata']['inner_manifest_sha256']==sha256(inner.read('manifest.json')).hexdigest()
    from app.domain.delivery_packages.render import build_package
    tiny_snapshot=dict(id='fixture',sha256='a'*64,mode='complete',members=resolved,changes={},gaps=[],quality_items=[],completeness='complete')
    packed,_=build_package(tiny_snapshot,raws)
    with zipfile.ZipFile(io.BytesIO(packed)) as outer:assert outer.read(resolved[1]['name'])==raws[1]
    assert old_count==14 and new_count==5,(old_count,new_count)
    print('full_read_probe baseline=14 grouped=5 identical_selected_sha=true')
    # Exact version and scope remain mandatory; changing any original member still rejects.
    with delivery_service.store.connection() as db:
        with pytest.raises(Exception):resolve_members(delivery_service,db,project,dict(id=delivery),[Selection(kind='research_report_member',version_id='wrong',member_id=members[0]['id'])],'complete')
    target=objects.path(members[0]['object_key']);target.write_bytes(b'corrupted')
    with pytest.raises(Exception):service.member(project,report['id'],members[0]['id'])
    with delivery_service.store.connection() as db:
        with pytest.raises(Exception):resolve_members(delivery_service,db,project,dict(id=delivery),selections,'complete')

def test_opinion_round_identifier_requires_fixed_event_and_server_notices_are_carried(client):
    base,path,body=setup_delivery(client)
    candidates=client.get(path+'/candidates');assert candidates.status_code==200,candidates.text
    assert candidates.json()['opinion_rounds']==[]
    bad=client.post(path+'/snapshots/preview',json=dict(body,opinion_round_id='foreign-round',opinion_round_event_id='foreign-event'))
    assert bad.status_code==404,bad.text
    frozen=client.post(path+'/snapshots',json=body,headers={'Idempotency-Key':'explicit-no-round'});assert frozen.status_code==201,frozen.text
    assert frozen.json()['opinion_round_binding']['status']=='not_applicable'
    from app.domain.delivery_packages.sources import inherited_notices
    notices=inherited_notices(dict(finding=dict(content=dict(limitations=['region enriched, not pure cells'],claims=[dict(strength='exploratory',review_decision='pending')])),presentation=dict(quality=dict(language_review='pending'),blind=dict(status='unverified'))))
    assert any('region enriched' in str(v) for v in notices)
    assert any('pending' in str(v) for v in notices)

def test_existing_report_task_records_observable_source_and_combined_render_stages(client,tmp_path):
    """Stop at the engine callback; no document/report/package is rendered."""
    base,path,body=setup_delivery(client)
    source=dict(source_kind='original_file',source_id=body['members'][0]['file_id'])
    finding=client.post(base+'/research-findings',json=dict(title='Progress fixture',sources=[source]),headers={'Idempotency-Key':'progress-finding'}).json()
    report=client.post(base+'/research-reports',json=dict(title='Progress fixture',finding_version_id=finding['id']),headers={'Idempotency-Key':'progress-report'}).json()
    observed=[]
    def stop_at_engine(payload,output):
        with database_connection() as db:
            rows=db.execute('SELECT state_json FROM task_checkpoints WHERE task_id=%s ORDER BY seq',(report['task_id'],)).fetchall()
            observed.extend(r['state_json'].get('stage') for r in rows)
        from app.core.exceptions import StorageError
        raise StorageError('research_environment_unavailable','Synthetic callback stops before rendering.',409)
    from app.domain.research_results.execution import run_research_task
    result=run_research_task(report['task_id'],1,task_type='research_report',engine=stop_at_engine,staging_directory=tmp_path/'stage')
    assert result['status']=='failed'
    assert observed[-3:]==['source_verification','organizing_report_inputs','rendering_report_and_package'],observed
