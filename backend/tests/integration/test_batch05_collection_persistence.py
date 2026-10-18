"""Real isolated PostgreSQL persistence; source reader is a synthetic boundary fixture."""
from copy import deepcopy
import pytest
from tests.api.test_analysis import client
from tests.api.test_boxplot import cloud
from tests.integration.test_explanations import writer
from tests.integration.test_reports import report_ready
from tests.domain.test_batch05_collection_contracts import bundle


@pytest.fixture
def collection_case(client,cloud,writer,monkeypatch):
    from app.adapters.collection_store import CollectionStore
    from app.adapters.storage import ProjectStore
    from app.core.config import get_data_dir
    from app.db.database import database_connection
    base,file,result,figure,explanation,_=report_ready(client)
    project_id=base.split('/projects/')[1].split('/')[0]
    with database_connection() as db:
        owner=db.execute('SELECT owner_id FROM projects WHERE id=%s',(project_id,)).fetchone()['owner_id']
    store=ProjectStore(get_data_dir(),owner_id=owner)
    sample=bundle(); sample['result'].update(id=result['id'],file_id=file['id'])
    sample['figure'].update(id=figure['id'],analysis_run_id=result['id'],file_id=file['id'],sha256=figure['sha256'],size_bytes=figure['size_bytes'])
    sample['explanation'].update(id=explanation['id'],analysis_run_id=result['id'],figure_id=figure['id'],figure_sha256=figure['sha256'],size_bytes=figure['size_bytes'])
    sample['result']['source']['file_id']=file['id']
    saved=deepcopy(sample['explanation']); sample['explanation']=None
    def read(self,project,figure_id,explanation_id=None):
        value=deepcopy(sample)
        if explanation_id: value['explanation']=deepcopy(saved)
        return value
    monkeypatch.setattr(CollectionStore,'read_bundle',read)
    return CollectionStore(store),project_id,sample,saved


def body(sample,automatic=True):
    from app.domain.report_collections.contracts import CollectionRequest
    return CollectionRequest(title='Collection',language='zh-CN',automatic=automatic,items=[{'figure_id':sample['figure']['id']}])


def test_waiting_intent_has_no_task_and_repeated_save_is_idempotent(collection_case):
    repository,project,sample,_=collection_case
    saved=repository.create(project,body(sample),'create-1')
    assert repository.create(project,body(sample),'create-1')['id']==saved['id']
    assert saved['versions'][0]['requests'][0]['status']=='waiting'
    with repository.store.connection() as db:
        assert db.execute("SELECT count(*) AS n FROM tasks WHERE task_type='collection_word_report'").fetchone()['n']==0
        assert db.execute('SELECT count(*) AS n FROM report_build_requests').fetchone()['n']==1


def test_exact_dependency_advance_atomic_task_outbox_and_new_export_intent(collection_case):
    repository,project,sample,explanation=collection_case
    saved=repository.create(project,body(sample),'create-1'); version=saved['current_version_id']
    # Only the exact declared engine can satisfy the frozen dependency.
    with repository.store.connection(write=True) as db:
        db.execute('UPDATE explanations SET engine_version=%s WHERE id=%s',('figure_explanation_v1',explanation['id']))
    repository.advance(project,saved['versions'][0]['requests'][0]['id'])
    state=repository.get(project,saved['id']); automatic=state['versions'][0]['requests'][0]
    assert automatic['status']=='queued' and automatic['task_id']
    with repository.store.connection() as db:
        assert db.execute('SELECT count(*) AS n FROM task_outbox WHERE task_id=%s',(automatic['task_id'],)).fetchone()['n']==1
    explicit=repository.export(project,saved['id'],version,'explicit-1')
    assert explicit['export_revision']==2
    assert repository.export(project,saved['id'],version,'explicit-1')['id']==explicit['id']
    assert repository.export(project,saved['id'],version,'explicit-2')['export_revision']==3


def test_new_version_does_not_replace_previous_intent_and_conflict_is_rejected(collection_case):
    from app.core.exceptions import StorageError
    repository,project,sample,_=collection_case
    saved=repository.create(project,body(sample),'create-1')
    request=body(sample); request.expected_revision=1; request.title='Second'
    newer=repository.new_version(project,saved['id'],request,'version-2')
    assert len(newer['versions'])==2 and newer['current_version_id']!=saved['current_version_id']
    with pytest.raises(StorageError): repository.new_version(project,saved['id'],request,'version-3')
    with pytest.raises(StorageError): repository.create(project,request,'create-1')


def test_local_worker_preserves_original_png_and_late_old_export(collection_case):
    from app.domain.report_collections.execution import run_collection_word_task
    from io import BytesIO
    from zipfile import ZipFile
    repository,project,sample,explanation=collection_case
    request=body(sample); request.items[0].explanation_id=explanation['id']
    saved=repository.create(project,request,'create-1')
    old=saved['versions'][0]['requests'][0]
    request.expected_revision=1; request.title='New version'
    newer=repository.new_version(project,saved['id'],request,'v2')
    result=run_collection_word_task(old['task_id'],1,config=repository.store.db_config,directory=repository.store.directory)
    assert result and result['status']=='succeeded'
    current=repository.get(project,saved['id'])
    assert current['current_version_id']==newer['current_version_id']
    report=next(v for v in current['versions'] if v['id']==saved['current_version_id'])['requests'][0]['report']
    metadata,content=repository.download(project,saved['id'],report['id'])
    with ZipFile(BytesIO(content)) as archive:
        assert [archive.read(n) for n in archive.namelist() if n.startswith('word/media/')]==[repository.store.figure_png(sample['figure'])]
    assert run_collection_word_task(old['task_id'],1,config=repository.store.db_config,directory=repository.store.directory) is None



def test_background_compensation_recovers_published_explanation_without_browser(collection_case):
    from app.domain.report_collections.service import advance_pending
    repository,project,sample,explanation=collection_case
    saved=repository.create(project,body(sample),'create-1')
    with repository.store.connection(write=True) as db:
        db.execute('UPDATE explanations SET engine_version=%s WHERE id=%s',('figure_explanation_v1',explanation['id']))
    assert advance_pending(config=repository.store.db_config,directory=repository.store.directory)==1
    advance_pending(config=repository.store.db_config,directory=repository.store.directory)
    with repository.store.connection() as db:
        assert db.execute("SELECT count(*) AS n FROM tasks WHERE task_type='collection_word_report'").fetchone()['n']==1
    assert repository.get(project,saved['id'])['versions'][0]['requests'][0]['status']=='queued'


def test_concurrent_same_export_key_creates_single_intent(collection_case):
    from concurrent.futures import ThreadPoolExecutor
    repository,project,sample,explanation=collection_case
    saved=repository.create(project,body(sample),'create-1')
    with ThreadPoolExecutor(max_workers=3) as pool:
        requests=list(pool.map(lambda _:repository.export(project,saved['id'],saved['current_version_id'],'same-click'),range(3)))
    assert len({r['id'] for r in requests})==1
    assert {r['export_revision'] for r in requests}=={2}


def test_changed_frozen_figure_blocks_export_and_owner_scope_is_enforced(collection_case):
    from app.core.exceptions import StorageError
    repository,project,sample,_=collection_case
    saved=repository.create(project,body(sample),'create-1')
    sample['figure']['title']='changed'
    with pytest.raises(StorageError) as error:
        repository.export(project,saved['id'],saved['current_version_id'],'changed')
    assert error.value.code=='collection_source_conflict'
    with pytest.raises(StorageError): repository.get('other-project',saved['id'])
    with repository.store.connection() as db:
        assert db.execute('SELECT count(*) AS n FROM report_build_requests').fetchone()['n']==1


def test_legacy_png_request_returns_specific_numbering_conflict(collection_case):
    from app.adapters.collection_store import CollectionStore
    from app.core.exceptions import StorageError
    repository,project,sample,_=collection_case
    # Bypass the fixture's reader patch to exercise the public compatibility guard.
    with repository.store.connection() as db:
        legacy=db.execute('SELECT id FROM figures WHERE figure_config_version_id IS NULL LIMIT 1').fetchone()
    with pytest.raises(StorageError) as error:
        repository.require_compatible_figure(project,legacy['id'])
    assert error.value.code=='collection_legacy_numbering'


def test_worker_rejects_task_snapshot_digest_corruption(collection_case):
    from app.domain.report_collections.execution import run_collection_word_task
    repository,project,sample,explanation=collection_case
    request=body(sample); request.items[0].explanation_id=explanation['id']
    state=repository.create(project,request,'create-1');task_id=state['versions'][0]['requests'][0]['task_id']
    with repository.store.connection(write=True) as db:
        db.execute('UPDATE tasks SET input_digest=%s WHERE id=%s',('a'*64,task_id))
    task=run_collection_word_task(task_id,1,config=repository.store.db_config,directory=repository.store.directory)
    assert task['status']=='failed'
    assert repository.get(project,state['id'])['versions'][0]['requests'][0]['report'] is None
