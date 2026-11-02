"""The two actual integration gaps, without renderer or package execution."""
from hashlib import sha256
from datetime import timedelta
from uuid import uuid4
import pytest
from psycopg.types.json import Jsonb
from tests.api.test_delivery_snapshots import client,synthetic_capacity,setup_delivery
from tests.api.test_delivery_snapshot_review_fixes import post,tiny_pdf
from app.db.database import database_connection


def finish_static_task(identifier):
    from app.adapters.task_execution_store import TaskExecutionStore
    repository=TaskExecutionStore();lease=repository.claim(identifier,1);assert lease
    with repository.connection(write=True) as db:repository._finish(db,repository.require_lease(db,lease),'succeeded',None)


def test_legacy_manuscript_candidates_freeze_and_download_share_scoped_mapping(client,monkeypatch):
    from tests.api.test_manuscripts import body
    p=client.post('/api/v1/projects',json=dict(name='Legacy SCI',research_topic='Static integration fixture',project_type='sci')).json();base='/api/v1/projects/'+p['id']
    root=post(client,base+'/manuscripts',body(),'legacy-root');assert root.status_code==201,root.text
    root=root.json();version=root['versions'][0];finish_static_task(version['task_id'])
    exported=post(client,base+'/manuscripts/'+root['id']+'/versions/1/exports',{},'static-export');assert exported.status_code==201,exported.text
    exported=exported.json();finish_static_task(exported['task_id']);docx=b'Already existing static DOCX boundary bytes'
    metadata=dict(id=exported['id'],filename='fixed.docx',sha256=sha256(docx).hexdigest(),size_bytes=len(docx),input_sha256=version['snapshot'] and sha256(b'unused').hexdigest())
    from app.domain.manuscripts.service import ManuscriptService
    monkeypatch.setattr(ManuscriptService,'export',lambda self,project,manuscript,identifier,download=False:(metadata,docx) if download else metadata)
    with database_connection(write=True) as db:db.execute('UPDATE manuscript_exports SET metadata_json=%s WHERE id=%s',(Jsonb(metadata),exported['id']))
    from tests.helpers.historical_pdf_exports import historical_pdf
    pdf=historical_pdf(base+'/pdf-exports','manuscript_export',exported['id'],raw=tiny_pdf())
    with database_connection() as db:
        before=dict(db.execute('SELECT * FROM manuscripts WHERE id=%s',(root['id'],)).fetchone())
    assert before['delivery_id'] is None and before['document_kind'] is None
    intake=client.get(base+'/research-intake').json();delivery=next(d for d in intake['deliveries'] if d['kind']=='sci_draft');path=base+'/deliveries/'+delivery['id']
    requirement=post(client,base+'/requirements',dict(expected_revision=1,operation='save',content=dict(schema_version=1,services=['sci_draft']),material_refs=[]),'legacy-requirement').json()['version']
    selections=[dict(kind='manuscript_export',manuscript_id=root['id'],version_id=version['id'],export_id=exported['id'])]
    request=dict(stage='first',expected_revision=0,requirement_version_id=requirement['id'],change_note='Static legacy scope only',opinion_round='not applicable',members=selections,required_formats=['docx'])
    candidates=client.get(path+'/candidates');assert candidates.status_code==200,candidates.text
    found={m['selection']['kind'] for m in candidates.json()['items']}
    frozen=post(client,path+'/snapshots',request,'legacy-freeze')
    assert 'manuscript_export' in found and 'pdf_export' not in found
    assert frozen.status_code==201,frozen.text
    rejected=post(client,path+'/snapshots',dict(request,members=selections+[dict(kind='pdf_export',export_id=pdf['id'])]),'rejected-new-pdf')
    assert rejected.status_code==422,rejected.text
    assert client.get(pdf['download_url']).content==tiny_pdf()
    frozen=frozen.json()
    assert [client.get(m['download_url']).content for m in frozen['members']]==[docx]
    assert [m['sha256'] for m in frozen['members']]==[metadata['sha256']]
    assert post(client,path+'/snapshots',request,'legacy-freeze').json()['id']==frozen['id']
    with database_connection() as db:assert dict(db.execute('SELECT * FROM manuscripts WHERE id=%s',(root['id'],)).fetchone())==before
    # The existing database guard already rejects an incompatible explicit link.
    # Keep that rejection instead of weakening the schema to create invalid state.
    with pytest.raises(Exception,match='Invalid manuscript delivery kind'):
        with database_connection(write=True) as db:
            wrong=str(uuid4());db.execute("INSERT INTO research_deliveries(id,project_id,kind,name,origin,active,revision,created_by,created_at,updated_at) VALUES(%s,%s,'analysis','Different delivery','user_selected',true,1,%s,clock_timestamp(),clock_timestamp())",(wrong,p['id'],before['user_id']))
            db.execute("UPDATE manuscripts SET delivery_id=%s,document_kind='sci' WHERE id=%s",(wrong,root['id']))
    with database_connection() as db:assert dict(db.execute('SELECT * FROM manuscripts WHERE id=%s',(root['id'],)).fetchone())==before


def test_progress_public_projection_is_bounded_scoped_and_fixed_per_attempt(client):
    base,path,body=setup_delivery(client);saved=post(client,path+'/snapshots',body,'progress-snapshot').json();package_path=path+'/snapshots/'+saved['id']+'/package'
    queued=post(client,package_path,{},'progress-task').json();identifier=queued['task_id']
    from app.domain.bioinformatics.service import append_checkpoint
    with database_connection(write=True) as db:
        task=dict(db.execute('SELECT * FROM tasks WHERE id=%s',(identifier,)).fetchone());anchor=db.execute("SELECT clock_timestamp()-interval '120 seconds' AS time").fetchone()['time'];original_sha=task['input_digest'];original_snapshot=task['input_snapshot']
        db.execute('UPDATE tasks SET created_at=%s,updated_at=%s WHERE id=%s',(anchor,anchor,identifier))
        cp=dict(db.execute('SELECT * FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(identifier,)).fetchone());db.execute('UPDATE task_checkpoints SET created_at=%s WHERE id=%s',(anchor,cp['id']))
        for number,start,end in ((1,1,10),(2,30,50)):
            db.execute("INSERT INTO task_attempts(id,task_id,attempt_no,status,started_at,finished_at,reason_code,error_code,error_category) VALUES(%s,%s,%s,'failed',%s,%s,'execution_failed','storage_unavailable','temporary')",(str(uuid4()),identifier,number,anchor+timedelta(seconds=start),anchor+timedelta(seconds=end)))
            for moment,stage in ((start+1,'source_verification'),(end-10 if number==2 else end-2,'writing_package')):
                cp=append_checkpoint(db,dict(task,updated_at=anchor+timedelta(seconds=moment)),'check','check',dict(cp['state_json'],stage=stage,completed_members=1,total_members=1,prepared=dict(private_path='must-never-be-public')),cp)
        db.execute("UPDATE tasks SET status='failed',revision=6,current_attempt=2,reason_code='execution_failed',error_code='storage_unavailable',updated_at=%s WHERE id=%s",(anchor+timedelta(seconds=50),identifier))
    first=client.get('/api/v1/tasks/'+identifier+'/progress');assert first.status_code==200,first.text
    first=first.json();second=client.get('/api/v1/tasks/'+identifier+'/progress').json()
    assert first['project_id']==base.rsplit('/',1)[-1] and first['delivery_id']==saved['delivery_id'] and first['snapshot_id']==saved['id']
    progress=first['progress'];assert progress['attempt_no']==2 and progress['stage']=='writing_package'
    assert progress['stage_elapsed_seconds']==10 and second['progress']['stage_elapsed_seconds']==10
    assert [s['stage'] for s in progress['stages']]==['source_verification','writing_package']
    assert [s['elapsed_seconds'] for s in progress['stages']]==[9,10]
    assert progress['stage_ended_at'] is not None and progress['completed_members']==1
    assert 'private_path' not in str(first) and 'prepared' not in str(first)
    assert client.get(package_path).json()['progress']['stages']==progress['stages']
    with database_connection() as db:
        current=db.execute('SELECT * FROM tasks WHERE id=%s',(identifier,)).fetchone();assert current['input_digest']==original_sha and current['input_snapshot']==original_snapshot
    # The second supported task exposes its frozen input stage without rendering.
    file_id=body['members'][0]['file_id'];finding=post(client,base+'/research-findings',dict(title='Static progress',sources=[dict(source_kind='original_file',source_id=file_id)]),'progress-finding').json()
    report=post(client,base+'/research-reports',dict(title='Static progress',finding_version_id=finding['id']),'progress-report').json()
    projected=client.get('/api/v1/tasks/'+report['task_id']+'/progress');assert projected.status_code==200,projected.text
    assert projected.json()['progress']['stage']=='frozen_inputs' and projected.json()['progress']['stage_elapsed_seconds']==0
    from app.auth.service import create_user
    create_user('other-progress@paperassist.local','isolated-other-password')
    login=client.post('/api/v1/auth/login',json=dict(email='other-progress@paperassist.local',password='isolated-other-password'));assert login.status_code==200,login.text
    assert client.get('/api/v1/tasks/'+identifier+'/progress').status_code==404
