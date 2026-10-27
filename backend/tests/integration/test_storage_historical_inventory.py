"""A2e: only new isolated schemas/roots, emulating pre-ledger typed history."""
import hashlib
import json
import shutil
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.adapters.storage import get_project_store
from app.db.database import database_connection, migration_connection
from app.domain.storage_governance import service as s
from tests.api.test_projects import client  # noqa: F401
from tests.api.test_admin_operations import accounts, admin  # noqa: F401
from tests.api.test_storage_governance import project
from tests.api.test_boxplot import cloud  # noqa: F401
from tests.integration.test_explanations import writer  # noqa: F401
from tests.integration.test_batch05_collection_persistence import collection_case  # noqa: F401


def legacy_root(tmp_path):
    """Copy new fixture assets, leaving original evidence intact; reset fixture ledger only."""
    source=get_project_store().directory
    root=tmp_path/'pre-ledger'
    shutil.copytree(source,root,ignore=shutil.ignore_patterns('.storage-intents','storage-candidates','task-staging'))
    with migration_connection(write=True) as db:
        assert db.config.schema.startswith('pa_test_')
        db.execute('DELETE FROM storage_references')
        db.execute('DELETE FROM storage_objects')
        db.execute('DELETE FROM storage_reservations')
    return root


@pytest.mark.parametrize('kind',['doc','v1','v2','v3','ocr'])
def test_typed_historical_document_and_checkpoint_objects(client,tmp_path,kind):
    from tests.integration.test_storage_document_candidates import candidate
    pid,task,execute,prefix=candidate(client,kind)
    result=execute(task)
    assert result['status'] in ('succeeded','waiting_confirmation')
    root=legacy_root(tmp_path)
    expected={p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}
    with database_connection(write=True) as db:
        before=list(db.execute('SELECT id,state_json FROM task_checkpoints ORDER BY id'))
        scan=s.inventory(db,root)
        actual={r['object_key']:r for r in db.execute('SELECT * FROM storage_objects')}
        assert set(actual)==set(expected), (set(expected)-set(actual),scan)
        assert scan['status']=='complete' and scan['typed_metadata_failure_count']==0
        assert s.usage(db,project_id=pid)['usage_bytes']==sum(map(len,expected.values()))
        assert list(db.execute('SELECT id,state_json FROM task_checkpoints ORDER BY id'))==before
        assert s.inventory(db,root)['physical_bytes']==sum(map(len,expected.values()))
        assert all(r['state']=='present' for r in actual.values())


@pytest.mark.parametrize('condition',['missing','changed','unreadable'])
def test_historical_derived_unknown_keeps_identity_and_last_known_size(client,tmp_path,monkeypatch,condition):
    from tests.integration.test_storage_document_candidates import candidate
    pid,task,execute,_=candidate(client,'doc');assert execute(task)['status']=='succeeded'
    root=legacy_root(tmp_path)
    with database_connection() as db:
        saved=db.execute('SELECT result_json FROM file_parse_results WHERE task_id=%s',(task['id'],)).fetchone()['result_json']
    record=saved['images'][0];path=root/record['object_key']
    if condition=='missing':path.unlink()  # Only the copied new synthetic fixture.
    if condition=='changed':path.write_bytes(b'altered-fixture')
    original=s._digest
    if condition=='unreadable':
        def read(p):
            if p==path:raise PermissionError('synthetic read denial')
            return original(p)
        monkeypatch.setattr(s,'_digest',read)
    with database_connection(write=True) as db:
        for _ in range(2):
            scan=s.inventory(db,root)
            row=db.execute('SELECT * FROM storage_objects WHERE object_key=%s',(record['object_key'],)).fetchone()
            assert row and row['state']==dict(missing='missing',changed='changed',unreadable='unknown')[condition]
            assert (row['size_bytes'],row['sha256'])==(record['size_bytes'],record['sha256'])
            assert scan['status']=='unknown'
            assert s.usage(db,project_id=pid)['unknown_object_count']==1


@pytest.mark.parametrize('location',['target','part'])
def test_inventory_preserves_active_v2_primary_companion_and_move(accounts,location):
    store,pid=project(accounts);root=store.directory;fid=str(uuid4())
    target=root/'files'/(fid+'.xlsx');part=root/'task-staging'/'registered.part'
    png=b'candidate';descriptor=b'{"original":"candidate"}'
    with store.connection(write=True) as db:
        # Trustworthy old SQL identity must not turn active v2 into a v1 publication.
        db.execute('''INSERT INTO files(id,project_id,filename,file_type,size_bytes,sha256,uploaded_at,parse_status,uploader_id,object_key)
            VALUES(%s,%s,'synthetic.xlsx','xlsx',%s,%s,%s,'parsed',%s,%s)''',
            (fid,pid,len(png),hashlib.sha256(png).hexdigest(),datetime.now(timezone.utc).isoformat(),accounts[2]['id'],target.relative_to(root).as_posix()))
        hold=s.admit_candidate(db,root,pid,'active-v2',target,100,task_id='original-task',source_identity='original-source')
        s.capture_candidate(db,root,hold['id'],png,[target,part],source_identity='original-source',descriptor=descriptor,
            descriptor_path=root/'task-staging'/'companion.json',write_path=target if location=='target' else part)
        before=dict(db.execute('SELECT * FROM storage_reservations WHERE id=%s',(hold['id'],)).fetchone())
        scan=s.inventory(db,root)
        after=dict(db.execute('SELECT * FROM storage_reservations WHERE id=%s',(hold['id'],)).fetchone())
        assert after==before and not db.execute('SELECT id FROM storage_objects').fetchall()
        assert scan['unknown_bytes']==0 and scan['pending_physical_bytes']==len(png)+len(descriptor)
        assert s.usage(db,project_id=pid)['reserved_bytes']==len(png)+len(descriptor)
        assert scan['physical_bytes']==len(png)+len(descriptor)
        with pytest.raises(Exception):s.reserve(db,root,pid,'bypass',target,len(png),sha256=hashlib.sha256(png).hexdigest())
        s.publish_candidate(db,root,hold['id'])
        settled=s.inventory(db,root)
        assert settled['physical_bytes']==len(png)+len(descriptor)
        assert s.usage(db,project_id=pid)['usage_bytes']==len(png)+len(descriptor)
        assert s.usage(db,project_id=pid)['reserved_bytes']==0


def test_root_symlink_is_not_traversed(accounts,tmp_path):
    store,pid=project(accounts);outside=tmp_path/'outside';outside.mkdir();(outside/'private').write_bytes(b'private')
    link=tmp_path/'linked';link.symlink_to(outside,target_is_directory=True)
    with store.connection(write=True) as db:
        scan=s.inventory(db,link)
        assert scan['status']=='unknown' and scan['scan_failure_count']>=1
        assert scan['physical_bytes']==0 and scan['physical_object_count']==0


def assert_legacy_files(root,prefixes):
    expected={p.relative_to(root).as_posix() for prefix in prefixes for p in (root/prefix).rglob('*') if p.is_file()}
    assert expected
    with database_connection(write=True) as db:
        scan=s.inventory(db,root)
        actual={r['object_key'] for r in db.execute("SELECT * FROM storage_objects WHERE state='present'")}
        assert expected<=actual,(expected-actual,scan)
        assert scan['typed_metadata_failure_count']==0,scan
    return scan


def test_legacy_figures_reports_collection_and_language(client,cloud,writer,collection_case,tmp_path):
    from tests.integration.test_batch05_collection_persistence import body
    from app.domain.report_collections.execution import run_collection_word_task
    from app.adapters.report_store import ReportStore
    from app.domain.reports import context
    from tests.integration.test_storage_transactional_producers import sync_candidate
    repository,pid,sample,explanation=collection_case
    request=body(sample);request.items[0].explanation_id=explanation['id']
    saved=repository.create(pid,request,'inventory-collection');intent=saved['versions'][0]['requests'][0]
    assert run_collection_word_task(intent['task_id'],1)['status']=='succeeded'
    snapshot,state=context(repository.store,pid,sample['result']['file_id'],sample['result']['id'])
    assert state['ready'];reports=ReportStore(repository.store)
    reports.save(snapshot,reports.metadata(snapshot),b'synthetic-docx')
    _,_,produce,_=sync_candidate(client,'language');produce()
    root=legacy_root(tmp_path)
    assert_legacy_files(root,['figures','reports','collection_reports','manuscript_figure_language_versions'])


@pytest.mark.parametrize('kind',['pdf','layout','review'])
def test_legacy_manuscript_and_conversion_exports(client,tmp_path,monkeypatch,kind):
    from types import SimpleNamespace
    from app.domain.tasks.execution import run_task
    for module in ('pdf_exports','layout_exports'):
        monkeypatch.setattr('app.domain.'+module+'.service.renderer_identity',lambda:{'contract':'test-v1'})
        monkeypatch.setattr('app.domain.'+module+'.execution.renderer_identity',lambda:{'contract':'test-v1'})
    if kind=='review':
        from tests.api.test_review_documents import completed_revision,create_document
        url,run=completed_revision(client);doc=create_document(client,url,run)
        response=client.post(url+'/documents/'+doc['id']+'/exports',json={},headers={'Idempotency-Key':'inventory-review'})
        prefix='review_document_exports'
    elif kind=='layout':
        from tests.api.test_layout_exports import prepared
        url,source,request=prepared(client);response=client.post(url,json=request)
        monkeypatch.setattr('app.domain.layout_exports.execution.prepare_layout_docx',lambda raw,*a,**k:raw)
        prefix='layout_exports'
    else:
        from tests.api.test_pdf_exports import successful_docx
        url,source=successful_docx(client)
        response=client.post(url,json=dict(source_kind='manuscript_export',source_id=source['id'],request_key='inventory-pdf'))
        monkeypatch.setattr('app.domain.pdf_exports.execution.render_pdf',lambda *a,**k:SimpleNamespace(content=b'%PDF-synthetic',manifest={'contract':'test-v1'}))
        prefix='pdf_exports'
    assert response.status_code in (201,202),response.text
    assert run_task(response.json()['task_id'],1)['status']=='succeeded'
    root=legacy_root(tmp_path)
    assert_legacy_files(root,['manuscript_exports',prefix])


def test_legacy_literature_pmc_shared_receipts_keep_original_scope(client,tmp_path):
    from tests.integration.test_literature_pmc import prepare
    from tests.api.test_literature import create
    from tests.helpers.literature import SyntheticNcbi
    from tests.integration.test_literature_workflow import execute
    pid,_,ref,service,adapter,_,_=prepare(client,tmp_path)
    receipt,_=service.acquire(pid,ref['id'],'PMC123','inventory-pmc',adapter=adapter)
    cached=create(client,pid,key='inventory-cache').json();provider=SyntheticNcbi(2)
    assert execute(cached,provider)['status']=='succeeded' and not provider.calls
    with database_connection() as db:
        rows=list(db.execute("SELECT object_key,size_bytes FROM literature_fetch_receipts WHERE status='succeeded'"))
        pmc=db.execute('SELECT snapshot_json FROM literature_pmc_receipts WHERE id=%s',(receipt['id'],)).fetchone()['snapshot_json']
        rows.extend(r['object'] for r in pmc['responses'] if r['object'])
        expected={r['object_key']:r['size_bytes'] for r in rows}
        assert len(rows)>len(expected),'Cache references share physical bytes'
    root=legacy_root(tmp_path)
    with database_connection(write=True) as db:
        scan=s.inventory(db,root)
        actual={r['object_key']:r['size_bytes'] for r in db.execute('SELECT * FROM storage_objects')}
        assert actual==expected and s.usage(db,project_id=pid)['usage_bytes']==sum(expected.values())
        # New PMC recovery envelope has no pre-ledger SQL descriptor. With all
        # governance evidence intentionally removed it must remain unowned.
        assert scan['unknown_bytes']==sum(p.stat().st_size for p in (root/'literature').rglob('*') if p.is_file() and p.relative_to(root).as_posix() not in expected)
        assert scan['typed_metadata_failure_count']==0


def test_shared_typed_objects_scan_unknown_and_http_projection(accounts):
    from app.adapters.storage import ProjectStore
    from fastapi.testclient import TestClient
    from app.main import app
    from tests.api.test_admin_operations import login
    store,one=project(accounts);other=ProjectStore(store.directory,owner_id=accounts[1]['id'])
    two=other.create_project('OTHER-PRIVATE-NAME','OTHER-PRIVATE-TOPIC','sci')['id']
    key='files/'+str(uuid4())+'.xlsx';raw=b'shared-physical';(store.directory/key).write_bytes(raw)
    with store.connection(write=True) as db:
        for pid,owner in ((one,accounts[2]['id']),(two,accounts[1]['id'])):
            db.execute('''INSERT INTO files(id,project_id,filename,file_type,size_bytes,sha256,uploaded_at,parse_status,uploader_id,object_key)
                VALUES(%s,%s,'PRIVATE-FILENAME','xlsx',%s,%s,%s,'parsed',%s,%s)''',
                (str(uuid4()),pid,len(raw),hashlib.sha256(raw).hexdigest(),datetime.now(timezone.utc).isoformat(),owner,key))
        before=list(db.execute('SELECT * FROM files ORDER BY id'))
    controls=store.directory/'.storage-intents';controls.mkdir();(controls/'unregistered-research.bin').write_bytes(b'unowned')
    with TestClient(app) as http:
        login(http,accounts[0]);response=http.post('/api/v1/admin/storage/scan');assert response.status_code==200,response.text
        value=response.json();assert value['usage_bytes']==len(raw)
        assert value['inventory']['physical_bytes']==len(raw)+len(b'unowned')
        assert value['inventory']['unknown_bytes']==len(b'unowned')
        assert http.get('/api/v1/admin/storage').json()['inventory']==value['inventory']
        for account,pid in ((accounts[2],one),(accounts[1],two)):
            login(http,account);value=http.get('/api/v1/me/storage',params={'project_id':pid}).json()
            assert value['usage_bytes']==len(raw)
            assert all(secret not in json.dumps(value) for secret in (key,'PRIVATE-FILENAME','OTHER-PRIVATE-NAME','OTHER-PRIVATE-TOPIC','unregistered-research'))
        login(http,accounts[2]);assert http.get('/api/v1/me/storage',params={'project_id':two}).status_code==404
    with store.connection() as db:assert list(db.execute('SELECT * FROM files ORDER BY id'))==before


def test_damaged_historical_prepared_manifest_does_not_guess_child_owner(client,tmp_path):
    from tests.integration.test_storage_document_candidates import candidate
    pid,task,execute,_=candidate(client,'v2');assert execute(task)['status']=='waiting_confirmation'
    root=legacy_root(tmp_path)
    with database_connection() as db:
        row=db.execute('SELECT state_json FROM task_checkpoints WHERE task_id=%s ORDER BY seq DESC LIMIT 1',(task['id'],)).fetchone()
        obj=row['state_json']['candidate'];saved=json.loads((root/obj['object_key']).read_bytes());child=saved['manifest']
    (root/obj['object_key']).write_bytes(b'changed-synthetic')
    with database_connection(write=True) as db:
        scan=s.inventory(db,root)
        assert scan['status']=='unknown' and scan['typed_metadata_errors']['checkpoint_candidate']>=1
        assert not db.execute('SELECT id FROM storage_objects WHERE object_key=%s',(child['object_key'],)).fetchone()
        parent=db.execute('SELECT * FROM storage_objects WHERE object_key=%s',(obj['object_key'],)).fetchone()
        assert parent['state']=='changed' and parent['size_bytes']==obj['size_bytes'] and parent['sha256']==obj['sha256']


def test_imported_non_uuid_asset_ids_keep_original_typed_paths(accounts):
    store,pid=project(accounts);stamp=datetime.now(timezone.utc).isoformat()
    records={kind:dict(id='legacy_'+kind+'-1',size_bytes=len(kind),sha256=hashlib.sha256(kind.encode()).hexdigest())
        for kind in ('file','figure','report')}
    paths={kind:prefix+'/'+records[kind]['id']+suffix for kind,prefix,suffix in
        [('file','files','.xlsx'),('figure','figures','.png'),('report','reports','.docx')]}
    for kind,key in paths.items():
        path=store.directory/key;path.parent.mkdir(exist_ok=True);path.write_bytes(kind.encode())
    with store.connection(write=True) as db:
        file=records['file'];figure=records['figure'];report=records['report']
        db.execute('''INSERT INTO files(id,project_id,filename,file_type,size_bytes,sha256,uploaded_at,parse_status)
            VALUES(%s,%s,'legacy.xlsx','xlsx',%s,%s,%s,'parsed')''',(file['id'],pid,file['size_bytes'],file['sha256'],stamp))
        db.execute("INSERT INTO analysis_runs(id,file_id,setup_revision,engine_version,completed_at,result_json) VALUES('legacy_run',%s,1,'legacy',%s,'{}')",(file['id'],stamp))
        db.execute("INSERT INTO figures(id,analysis_run_id,renderer_version,figure_json) VALUES(%s,'legacy_run','legacy',%s)",(figure['id'],json.dumps(figure)))
        db.execute("INSERT INTO explanations(id,analysis_run_id,figure_id,engine_version,explanation_json) VALUES('legacy_explanation','legacy_run',%s,'legacy','{}')",(figure['id'],))
        db.execute("INSERT INTO reports(id,analysis_run_id,explanation_id,renderer_version,report_json,input_json) VALUES(%s,'legacy_run','legacy_explanation','legacy',%s,'{}')",(report['id'],json.dumps(report)))
        scan=s.inventory(db,store.directory)
        actual={r['object_key'] for r in db.execute("SELECT * FROM storage_objects WHERE state='present'")}
        assert actual==set(paths.values()),scan
        assert scan['status']=='complete' and s.usage(db,project_id=pid)['usage_bytes']==sum(r['size_bytes'] for r in records.values())


def test_control_directory_link_persists_failed_preflight_without_reconciliation(admin,accounts,tmp_path,monkeypatch):
    store,pid=project(accounts)
    store.save_file(pid,'synthetic.xlsx',b'synthetic-original',None,None)
    first=admin.post('/api/v1/admin/storage/scan')
    assert first.status_code==200,first.text
    successful=first.json()['inventory'];assert successful['status']=='complete'
    with store.connection() as db:
        before={table:list(db.execute('SELECT * FROM '+table+' ORDER BY 1')) for table in
            ('storage_objects','storage_references','storage_reservations','files')}
    control=store.directory/'.storage-intents';retained=tmp_path/'retained-fixture-journals'
    control.rename(retained)  # Only this test's new isolated evidence, retained intact.
    bytes_before={p.name:p.read_bytes() for p in retained.iterdir()}
    control.symlink_to(retained,target_is_directory=True)
    called=[];reconcile=s.reconcile_intents
    def traced(*args,**kwargs):
        called.append(True)
        return reconcile(*args,**kwargs)
    monkeypatch.setattr(s,'reconcile_intents',traced)
    for _ in range(2):
        failed=admin.post('/api/v1/admin/storage/scan')
        assert failed.status_code==200,failed.text
        receipt=failed.json()['inventory']
        assert receipt['status']=='unknown' and receipt['coverage']=='not_started'
        assert receipt['error_code']=='storage_control_directory_unsafe'
        assert receipt['scanned_at']>successful['scanned_at'] and receipt['scan_failure_count']==1
        assert receipt['physical_bytes'] is None and receipt['physical_object_count'] is None
        assert receipt['last_successful_scan']==successful
        assert receipt['last_successful_scanned_at']==successful['scanned_at']
        assert str(retained) not in json.dumps(receipt) and 'synthetic.xlsx' not in json.dumps(receipt)
        with store.connection() as db:
            assert db.execute('SELECT summary FROM storage_inventory_scans WHERE id=1').fetchone()['summary']==receipt
            assert {table:list(db.execute('SELECT * FROM '+table+' ORDER BY 1')) for table in before}==before
    assert called==[],'Control-directory preflight must finish before any reconcile mutation'
    assert {p.name:p.read_bytes() for p in retained.iterdir()}==bytes_before
