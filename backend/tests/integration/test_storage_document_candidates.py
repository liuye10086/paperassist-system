"""A2c: synthetic document/preparation/OCR candidates in isolated schemas."""
import hashlib
import json

import pytest

from app.adapters.storage import get_project_store
from app.db.database import database_connection, migration_connection
from app.domain.storage_governance.service import set_policy, usage
from tests.api.test_projects import client  # noqa: F401


def policy(project, extra):
    with database_connection(write=True) as db:
        before = usage(db, project_id=project)['usage_bytes']
        set_policy(db, 'project', project, before + extra, 'enforced')
    return before


def resume(client, failed, key='storage-retry'):
    workspace = client.get('/api/v1/tasks/'+failed['id']+'/workspace').json()
    assert workspace['allowed_actions'] == ['retry']
    response = client.post('/api/v1/tasks/'+failed['id']+'/resume', headers={'Idempotency-Key':key},
        json=dict(operation='retry', wait_id=None, expected_task_revision=failed['revision'], input_version=failed['input_version']))
    return response


def test_document_full_manifest_precedes_first_byte_and_http_retry_keeps_parse(client):
    from tests.api.test_document_versions import uploaded_docx
    from app.adapters.docx_parser import parse_docx
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    project, _, _, item, original = uploaded_docx(client)
    root = get_project_store().directory
    with database_connection() as db:
        snapshot=db.execute('SELECT input_snapshot FROM tasks WHERE id=%s',(item['task']['id'],)).fetchone()['input_snapshot']
    parsed=parse_docx(original,snapshot['file']['filename'],snapshot['settings'])
    assert parsed.document.images
    # JSON alone fits exactly; omitting the image manifest would falsely pass.
    before = policy(project['id'], len(parsed.document.model_dump_json().encode()))
    failed = run_parse_file_task(item['task']['id'], 1, parser=parse_docx)
    assert failed['status'] == 'failed' and failed['error_code'] == 'storage_quota_exceeded'
    assert not list((root/'documents').rglob('*.*'))
    policy(project['id'], 1000000)
    retried = resume(client, failed)
    assert retried.status_code == 202, retried.text
    assert run_parse_file_task(failed['id'], retried.json()['revision'], parser=parse_docx)['status'] == 'succeeded'
    with database_connection() as db:
        row = db.execute('SELECT * FROM file_parse_results WHERE task_id=%s', (failed['id'],)).fetchone()
        manifest = row['result_json']; records = [manifest['object'], *manifest['images']]
        assert len(records) == 3 and row['version'] == 1
        charged = db.execute("SELECT * FROM storage_reservations WHERE task_id=%s", (failed['id'],)).fetchall()
        assert len(charged) == len(records) and all(r['state']=='settled' for r in charged)
        assert all(r['owner_id'] == db.execute('SELECT owner_id FROM projects WHERE id=%s', (project['id'],)).fetchone()['owner_id'] for r in charged)
        assert usage(db, project_id=project['id'])['usage_bytes'] == before + sum(r['size_bytes'] for r in records)
    assert client.get(f"/api/v1/projects/{project['id']}/files/{item['file_id']}/download").content == original


def candidate(client, kind):
    if kind == 'doc':
        from tests.api.test_document_versions import uploaded_docx
        from app.adapters.docx_parser import parse_docx
        from app.domain.tasks.file_parse_execution import run_parse_file_task
        project, _, _, item, _ = uploaded_docx(client)
        return project['id'],item['task'],lambda task:run_parse_file_task(task['id'],task['revision'],parser=parse_docx),'documents'
    if kind == 'ocr':
        from tests.integration.test_ocr_review import setup_review, execute
        project, base, parent, task, _ = setup_review(client)
        return project['id'], task, execute, 'ocr-reviews'
    from tests.integration.test_dataset_preparation import create_preparation, run
    if kind == 'v1':
        base, _, _, _, task = create_preparation(client)
    else:
        from tests.integration.test_batch07_quality_pipeline import published, quality_task
        from tests.integration.test_batch09_filter_pipeline import filtering, ROWS
        base, parent = published(client, ROWS)
        if kind=='v3_quality':
            from tests.integration.test_batch09_filter_pipeline import accept
            filtered,_=filtering(client,base,parent)
            parent,_,_=accept(client,filtered,'filtered-parent')
        task, _ = quality_task(client, base, parent) if kind in ('v2','v3_quality') else filtering(client, base, parent)
    return base.split('/')[4], task, run, 'prepared-datasets'


@pytest.mark.parametrize('kind', ['v1', 'v2', 'v3', 'ocr'])
def test_wait_quota_failure_is_retryable_and_counts_whole_candidate(client, kind):
    project, task, execute, prefix = candidate(client, kind)
    root = get_project_store().directory
    old = set(root.rglob('*.json'))
    policy(project, 0)
    failed = execute(task)
    assert failed['status']=='failed' and failed['error_code']=='storage_quota_exceeded'
    assert set(root.rglob('*.json')) == old, 'No partial quality manifest or candidate before full admission'
    policy(project, 1000000)
    retried = resume(client, failed)
    assert retried.status_code==202, retried.text
    waiting = execute(retried.json())
    assert waiting['status']=='waiting_confirmation' and waiting['id']==task['id']
    with database_connection() as db:
        rows = db.execute('SELECT * FROM storage_reservations WHERE task_id=%s', (task['id'],)).fetchall()
        assert len(rows)==(2 if kind in ('v2','v3') else 1)
        owner=db.execute('SELECT user_id FROM tasks WHERE id=%s',(task['id'],)).fetchone()['user_id']
        assert all(r['state']=='settled' and r['project_id']==project and r['owner_id']==owner for r in rows)
        for row in rows:
            raw = (root/row['object_key']).read_bytes()
            assert (len(raw),hashlib.sha256(raw).hexdigest())==(row['size_bytes'],row['sha256'])


@pytest.mark.parametrize('kind', ['v2', 'v3', 'ocr'])
def test_wait_rollback_retains_exact_objects_and_http_retry_reuses_them(client, kind):
    project, task, execute, prefix = candidate(client, kind)
    root = get_project_store().directory
    old = set(root.rglob('*.json'))
    with migration_connection(write=True) as db:
        db.execute("""CREATE FUNCTION a2c_reject_wait() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic A2c rollback'; END $$""")
        db.execute('CREATE TRIGGER a2c_reject_wait BEFORE INSERT ON task_waits FOR EACH ROW EXECUTE FUNCTION a2c_reject_wait()')
    try:
        failed = execute(task)
        assert failed['status']=='failed'
    finally:
        with migration_connection(write=True) as db:
            db.execute('DROP TRIGGER a2c_reject_wait ON task_waits'); db.execute('DROP FUNCTION a2c_reject_wait()')
    saved = {p:p.read_bytes() for p in set(root.rglob('*.json'))-old if '.storage-intents' not in p.parts}
    assert len(saved)==(2 if kind in ('v2','v3') else 1)
    with database_connection() as db:
        rows=db.execute('SELECT * FROM storage_reservations WHERE task_id=%s',(task['id'],)).fetchall()
        assert len(rows)==len(saved) and all(r['state']=='reserved' for r in rows)
    policy(project, 0)
    rejected = resume(client, failed, 'too-small')
    assert rejected.status_code==409 and rejected.json()['detail']['code']=='storage_quota_exceeded'
    assert all(p.read_bytes()==raw for p,raw in saved.items())
    policy(project, 1000000)
    accepted = resume(client, failed)
    assert accepted.status_code==202, accepted.text
    assert execute(accepted.json())['status']=='waiting_confirmation'
    assert all(p.read_bytes()==raw for p,raw in saved.items())


def test_fresh_storage_schema_audit_details(postgres_schema):
    from app.maintenance.database_audit import audit_database
    with database_connection() as db:
        result=audit_database(db)
    assert result['schema_issues']==[], repr(result['schema_issues'])
    assert not [c for c in result['data_checks'] if c['invalid']], repr(result['data_checks'])


@pytest.mark.parametrize('statement,table,kind', [
    ('ALTER TABLE storage_policies ALTER COLUMN revision SET DEFAULT 1','storage_policies','column:revision'),
    ("ALTER TABLE storage_inventory_scans ALTER COLUMN id SET DEFAULT nextval('operational_collection_id_seq')",'storage_inventory_scans','column:id'),
    ("ALTER TABLE admin_configuration_events DROP CONSTRAINT admin_configuration_event_values; ALTER TABLE admin_configuration_events ADD CONSTRAINT admin_configuration_event_values CHECK (operation IN ('activate','rollback') AND length(reason) BETWEEN 5 AND 499)",'admin_configuration_events','check'),
    ('ALTER TABLE storage_objects ALTER COLUMN sha256 DROP NOT NULL','storage_objects','column:sha256'),
    ('ALTER TABLE storage_objects ALTER COLUMN size_bytes TYPE numeric','storage_objects','column:size_bytes'),
])
def test_audit_equivalence_still_rejects_actual_drift(postgres_schema, statement, table, kind):
    from app.maintenance.database_audit import audit_database
    with migration_connection(write=True) as db:
        for command in statement.split('; '):
            db.execute(command)
    with database_connection() as db:
        result=audit_database(db)
    assert not result['ok']
    assert {'table':table,'kind':kind} in result['schema_issues'], result['schema_issues']


@pytest.mark.parametrize('changed_grouping',[False,True],ids=['equivalent-pg-grouping','incorrect-or-bypass'])
def test_actual_check_boolean_grouping_is_preserved(postgres_schema, changed_grouping):
    from app.maintenance.database_audit import audit_database
    correct="length(reason)>=5 AND length(reason)<=500 AND (operator IS NULL OR (length(operator)>=1 AND length(operator)<=128))"
    incorrect="(length(reason)>=5 AND length(reason)<=500 AND operator IS NULL) OR (length(operator)>=1 AND length(operator)<=128)"
    with migration_connection(write=True) as db:
        witness=db.execute('SELECT ('+correct+') AS expected,('+incorrect+") AS incorrect FROM (VALUES ('x'::text,'cli'::text)) AS synthetic(reason,operator)").fetchone()
        assert witness==dict(expected=False,incorrect=True)
        db.execute('ALTER TABLE admin_audit_events DROP CONSTRAINT admin_audit_bounds')
        db.execute('ALTER TABLE admin_audit_events ADD CONSTRAINT admin_audit_bounds CHECK ('+(incorrect if changed_grouping else correct)+')')
    with database_connection() as db:
        result=audit_database(db)
    issue=dict(table='admin_audit_events',kind='check')
    assert (issue in result['schema_issues']) is changed_grouping, result['schema_issues']
    assert result['ok'] is (not changed_grouping)


def test_check_is_true_wrapper_cannot_be_dropped(postgres_schema):
    from app.maintenance.database_audit import audit_database
    predicate="(result_json IS NULL AND model_call_id IS NULL) OR (jsonb_typeof(result_json)='object' AND model_call_id IS NOT NULL)"
    with migration_connection(write=True) as db:
        witness=db.execute('SELECT (('+predicate+') IS TRUE) AS wrapped,('+predicate+") AS unwrapped FROM (VALUES (NULL::jsonb,'call'::text)) AS synthetic(result_json,model_call_id)").fetchone()
        assert witness==dict(wrapped=False,unwrapped=None)
        db.execute('ALTER TABLE literature_assistance_requests DROP CONSTRAINT literature_assistance_requests_result_check')
        db.execute('ALTER TABLE literature_assistance_requests ADD CONSTRAINT literature_assistance_requests_result_check CHECK ('+predicate+')')
    with database_connection() as db:
        result=audit_database(db)
    assert not result['ok']
    assert dict(table='literature_assistance_requests',kind='check') in result['schema_issues'],result['schema_issues']


@pytest.mark.parametrize('effective_at,invalid', [(123.0,0),(float('inf'),1)])
def test_native_double_time_audit_is_numeric_and_finite(client, effective_at, invalid):
    from app.maintenance.database_audit import audit_database
    with database_connection(write=True) as db:
        owner=db.execute('SELECT id FROM users LIMIT 1').fetchone()['id']
        db.execute("""INSERT INTO admin_audit_events(id,source,operator,target_user_id,after_role,after_active,reason,effective_at)
            VALUES ('a2c-synthetic-audit','cli','synthetic',%s,'admin',true,'synthetic numeric audit',%s)""",(owner,effective_at))
    with database_connection() as db:
        result=audit_database(db)
    check=next(c for c in result['data_checks'] if c['table']=='admin_audit_events' and c['column']=='effective_at')
    assert check['rows']==2 and check['invalid']==invalid, check


@pytest.mark.parametrize('kind',['v2','v3','v3_quality'])
def test_complete_quality_manifest_is_admitted_with_prepared_json(client, kind):
    from app.adapters.dataset_preparation_store import DatasetPreparationStore
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.domain.dataset_preparation.service import latest_checkpoint
    project,task,execute,_=candidate(client,kind)
    with database_connection() as db:
        frozen=db.execute('SELECT * FROM tasks WHERE id=%s',(task['id'],)).fetchone()
        checkpoint=latest_checkpoint(db,frozen)
    service=DatasetPreparationStore(TaskExecutionStore()).service(frozen)
    obj,manifest=service.build_candidate(frozen,checkpoint['state_json'])
    content=json.dumps(obj.model_dump(mode='json'),ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    assert manifest and obj.manifest.size_bytes==len(manifest)
    root=get_project_store().directory;old=set(root.rglob('*.json'))
    policy(project,len(content))
    failed=execute(task)
    assert failed['error_code']=='storage_quota_exceeded' and failed['status']=='failed'
    assert set(root.rglob('*.json'))==old
    policy(project,len(content)+len(manifest))
    accepted=resume(client,failed)
    assert accepted.status_code==202,accepted.text
    assert execute(accepted.json())['status']=='waiting_confirmation'


@pytest.mark.parametrize('kind',['doc','v3','ocr'])
def test_unknown_admission_without_bytes_rebuilds_exact_identity_on_http_resume(client, monkeypatch, kind):
    from app.domain.storage_governance import deterministic
    from app.core.exceptions import StorageError
    import importlib
    project,task,execute,_=candidate(client,kind)
    module=importlib.import_module('app.adapters.'+{'doc':'document_parse_store','v3':'dataset_preparation_store','ocr':'ocr_review_store'}[kind])
    original=deterministic.admit_manifest
    captured={}
    def lost_admission(*args,**kwargs):
        captured['rows']=original(*args,**kwargs)
        captured['snapshot']=args[2]['input_snapshot']
        raise StorageError('storage_unavailable','Synthetic rollback after durable immutable intents')
    with monkeypatch.context() as patch:
        patch.setattr(module,'admit_manifest',lost_admission)
        failed=execute(task)
    assert failed['status']=='failed' and failed['error_code']=='storage_unavailable'
    root=get_project_store().directory
    with database_connection() as db:
        recovered=db.execute('SELECT * FROM storage_reservations WHERE task_id=%s',(task['id'],)).fetchall()
        # Existing TaskExecutionStore.fail already reconciles storage intents;
        # no object bytes or SQL capture survived the injected admission rollback.
        assert recovered and all(r['state']=='unknown' and not (root/r['object_key']).exists() for r in recovered)
        assert db.execute('SELECT input_snapshot FROM tasks WHERE id=%s',(task['id'],)).fetchone()['input_snapshot']==captured['snapshot']
        fields=('id','namespace','project_id','owner_id','task_id','operation_key','object_key','size_bytes','sha256','kind')
        expected={r['id']:{k:r[k] for k in fields} for r in captured['rows']}
        assert {r['id']:{k:r[k] for k in fields} for r in recovered}==expected
        for row in recovered:
            intent=json.loads((root/'.storage-intents'/(row['id']+'.json')).read_bytes())
            assert {k:intent[k] for k in fields}==expected[row['id']]
    # Business GET also verifies current durable accounting; no SQL hand repair.
    visible=client.get('/api/v1/me/storage',params={'project_id':project})
    assert visible.status_code==200,visible.text
    assert visible.json()['reserved_bytes']>=sum({r['object_key']:r['size_bytes'] for r in recovered}.values())>0
    with database_connection() as db:
        rows=db.execute('SELECT * FROM storage_reservations WHERE task_id=%s ORDER BY id',(task['id'],)).fetchall()
        identities=[tuple(r[k] for k in ('id','task_id','operation_key','object_key','sha256','size_bytes','owner_id')) for r in rows]
        assert rows and all(r['state']=='unknown' and not (root/r['object_key']).exists() for r in rows)
    policy(project,0)
    rejected=resume(client,failed,'unknown-too-small')
    assert rejected.status_code==409 and rejected.json()['detail']['code']=='storage_quota_exceeded'
    policy(project,1000000)
    accepted=resume(client,failed)
    assert accepted.status_code==202,accepted.text
    assert execute(accepted.json())['status']==('succeeded' if kind=='doc' else 'waiting_confirmation')
    with database_connection() as db:
        rows=db.execute('SELECT * FROM storage_reservations WHERE task_id=%s ORDER BY id',(task['id'],)).fetchall()
        assert identities==[tuple(r[k] for k in ('id','task_id','operation_key','object_key','sha256','size_bytes','owner_id')) for r in rows]
        assert all(r['state']=='settled' for r in rows)


@pytest.mark.parametrize('kind',['v2','ocr'])
def test_disk_failure_and_http_resume_use_same_frozen_task(client, monkeypatch, kind):
    from app.domain.storage_governance import service
    project,task,execute,_=candidate(client,kind)
    root=get_project_store().directory;old=set(root.rglob('*.json'))
    with monkeypatch.context() as patch:
        patch.setattr(service,'disk_status',lambda _:dict(status='unknown',total_bytes=None,free_bytes=None,threshold_bytes=None,measured_at=None))
        failed=execute(task)
        assert failed['status']=='failed' and failed['error_code']=='storage_disk_insufficient'
        rejected=resume(client,failed,'disk-unavailable')
        assert rejected.status_code==507 and rejected.json()['detail']['code']=='storage_disk_insufficient'
    assert set(root.rglob('*.json'))==old
    accepted=resume(client,failed)
    assert accepted.status_code==202,accepted.text
    assert execute(accepted.json())['status']=='waiting_confirmation'


def test_explicit_document_resume_keeps_sibling_unknown_hold_charged(client):
    from app.domain.storage_governance.service import publication
    from app.core.exceptions import StorageError
    project,task,execute,_=candidate(client,'doc')
    root=get_project_store().directory;target=root/'a2c-registered-synthetic-sibling.bin'
    with pytest.raises(StorageError):
        with database_connection(write=True) as db:
            with publication(db,root,project,'a2c-synthetic-sibling',target,b'sibling',kind='fixture'):
                target.write_bytes(b'sibling')
                raise StorageError('storage_unavailable','Synthetic sibling rollback')
    failed=execute(task)
    assert failed['status']=='failed' and failed['error_code']=='storage_accounting_unknown'
    assert client.get('/api/v1/me/storage',params={'project_id':project}).status_code==200
    accepted=resume(client,failed)
    assert accepted.status_code==202,accepted.text
    assert execute(accepted.json())['status']=='succeeded'
    with database_connection() as db:
        sibling=db.execute("SELECT * FROM storage_reservations WHERE operation_key='a2c-synthetic-sibling'").fetchone()
        assert sibling['state']=='unknown' and sibling['size_bytes']==7
        assert usage(db,project_id=project)['reserved_bytes']==7
    assert target.read_bytes()==b'sibling'


@pytest.mark.parametrize('kind',['v2','v3_quality'])
def test_publish_after_quota_raise_retains_accepted_candidate_and_version(client, monkeypatch, kind):
    from tests.integration.test_dataset_preparation import review,decide,decision
    from app.adapters.prepared_dataset_objects import PreparedDatasetObjects
    project,task,execute,_=candidate(client,kind)
    assert execute(task)['status']=='waiting_confirmation'
    view=review(client,task);preview=client.get(view['preview_download_url']).content
    accepted=decide(client,task,decision(view)).json()
    with database_connection(write=True) as db:
        set_policy(db,'project',project,0,'enforced')
    def forbid_save(*args,**kwargs):
        raise AssertionError('Approved publication must reuse the original durable candidate')
    monkeypatch.setattr(PreparedDatasetObjects,'save',forbid_save)
    failed=execute(accepted)
    assert failed['status']=='failed' and failed['error_code']=='storage_quota_exceeded'
    assert client.get(view['preview_download_url']).content==preview
    policy(project,1000000)
    retried=resume(client,failed)
    assert retried.status_code==202,retried.text
    assert execute(retried.json())['status']=='succeeded'
    result=review(client,task)['result']
    assert client.get(result['download_url']).content==preview
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM prepared_dataset_versions WHERE task_id=%s',(task['id'],)).fetchone()['n']==1


def test_automatic_lease_recovery_never_authorizes_unknown_siblings(client):
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.domain.storage_governance.service import publication
    from app.core.exceptions import StorageError
    project,task,execute,_=candidate(client,'doc')
    root=get_project_store().directory;target=root/'a2c-registered-auto-sibling.bin'
    with pytest.raises(StorageError):
        with database_connection(write=True) as db:
            with publication(db,root,project,'a2c-auto-sibling',target,b'sibling',kind='fixture'):
                target.write_bytes(b'sibling')
                raise StorageError('storage_unavailable','Synthetic sibling rollback')
    repo=TaskExecutionStore()
    assert repo.claim(task['id'],task['revision'],task_type='parse_file') is not None
    with database_connection(write=True) as db:
        db.execute("UPDATE task_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE task_id=%s",(task['id'],))
    assert repo.recover_expired()>=1
    queued=client.get('/api/v1/tasks/'+task['id']).json()
    with database_connection() as db:
        event=db.execute('SELECT retry_reason FROM task_events WHERE task_id=%s AND seq=%s',(task['id'],queued['revision'])).fetchone()
        assert event['retry_reason']=='worker_interrupted'
    failed=execute(queued)
    assert failed['status']=='failed' and failed['error_code']=='storage_accounting_unknown'
    # The same task may proceed only after the actual human HTTP retry action.
    accepted=resume(client,failed)
    assert accepted.status_code==202,accepted.text
    assert execute(accepted.json())['status']=='succeeded'
    with database_connection() as db:
        sibling=db.execute("SELECT state,size_bytes FROM storage_reservations WHERE operation_key='a2c-auto-sibling'").fetchone()
        assert sibling==dict(state='unknown',size_bytes=7)
