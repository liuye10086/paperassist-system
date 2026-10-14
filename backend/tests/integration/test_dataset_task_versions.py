"""V2 creation, frozen source matching, waiting and strict recovery in isolated schemas."""
import copy
import pytest
from app.core.exceptions import StorageError
from app.adapters.task_store import TaskStore
from app.db.database import database_connection
from app.domain.tasks.service import TaskService
from app.domain.tasks.resume import TaskResumeService
from app.domain.tasks.contracts import TaskCreateRequest
from app.domain.tasks.waits import get_open_wait
from app.domain.external_processing import disclosure
from tests.api.test_analysis import client
from tests.api.test_dataset_analysis import version
from tests.integration.test_dataset_artifact_chain import new_result, confirmed_task
from tests.helpers.tasks import task_owner


def test_v2_creation_freezes_source_and_new_dataset_does_not_rebind(client):
    base,file,result=new_result(client)
    task,owner=confirmed_task(client,base,file,result,'boxplot')
    store=TaskStore(owner)
    with store.connection() as db:
        raw=store.require_task(db,task['id'])
    frozen=copy.deepcopy(raw['input_snapshot'])
    assert raw['workflow_version']=='boxplot_v2'
    assert frozen['schema_version']==2 and frozen['source']==result['source']
    assert frozen['versions']['statistics']=='descriptive_statistics_dataset_v1'
    assert set(frozen['file'])=={'id','filename','sha256','size_bytes','file_type'}
    version(client,base,1)
    assert store.get(task['id'])['input_version']['source']==result['source']
    with store.connection() as db:
        assert store.require_task(db,task['id'])['input_snapshot']==frozen
    workspace=client.get('/api/v1/tasks/'+task['id']+'/workspace')
    assert workspace.status_code==200,workspace.text
    assert workspace.json()['source']['dataset_source']==result['source']


def test_dataset_task_requires_new_confirmation_before_persistence(client):
    base,file,result=new_result(client)
    owner=task_owner(client); service=TaskService(owner)
    request=TaskCreateRequest(task_type='boxplot',file_id=file['id'],analysis_run_id=result['id'],expected_revision=1)
    with database_connection() as db:
        before=db.execute('SELECT count(*) AS n FROM tasks').fetchone()['n']
    with pytest.raises(StorageError) as error:
        service.create(base.split('/')[4],request,idempotency_key='missing-confirmation')
    assert error.value.code=='task_input_invalid'
    with service.store.connection() as db:
        frozen=service.store.source_snapshot(db,service.store.require_project(db,base.split('/')[4]),request)
    preview=disclosure(frozen,'boxplot',owner)
    old=dict(version=1,confirmed=True,source_digest=preview['source_digest'],labels={v['key']:v['value'] for v in preview['labels']})
    with pytest.raises(StorageError):
        service.create(base.split('/')[4],request.model_copy(update={'external_processing':old}),idempotency_key='old-confirmation')
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM tasks').fetchone()['n']==before
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']==0


def test_budget_wait_and_resume_compare_full_source_and_are_idempotent(client):
    base,file,result=new_result(client)
    task,owner=confirmed_task(client,base,file,result,'boxplot')
    service=TaskService(owner)
    running=service.transition(task['id'],expected_revision=1,status='running')
    waiting=service.transition(task['id'],expected_revision=running['revision'],status='waiting_confirmation',reason_code='budget_exceeded')
    store=TaskStore(owner)
    with store.connection() as db:
        wait=get_open_wait(db,store.require_task(db,task['id']))
    assert wait['input_version']==waiting['input_version']
    request=dict(operation='resume',wait_id=wait['id'],expected_task_revision=waiting['revision'],input_version=waiting['input_version'])
    altered=copy.deepcopy(request); altered['input_version']['source']['dataset_sha256']='c'*64
    resume=TaskResumeService(owner)
    with pytest.raises(StorageError) as error:
        resume.resume(task['id'],altered,idempotency_key='other-source')
    assert error.value.code=='task_source_conflict'
    resumed=resume.resume(task['id'],request,idempotency_key='resume')
    assert resumed['status']=='queued' and resumed['input_version']==waiting['input_version']
    assert resume.resume(task['id'],request,idempotency_key='resume')==resumed
    with store.connection() as db:
        assert get_open_wait(db,store.require_task(db,task['id'])) is None

def test_dataset_task_creation_rejects_missing_frozen_object(client):
    from pathlib import Path
    from app.core.config import get_data_dir
    base,file,result=new_result(client)
    owner=task_owner(client); store=TaskStore(owner)
    request=TaskCreateRequest(task_type='boxplot',file_id=file['id'],analysis_run_id=result['id'],expected_revision=1)
    with store.connection() as db:
        row=db.execute('SELECT object_key FROM dataset_versions WHERE id=%s',(result['source']['dataset_id'],)).fetchone()
    (Path(get_data_dir())/row['object_key']).unlink()
    with store.connection() as db:
        with pytest.raises(StorageError):
            store.source_snapshot(db,store.require_project(db,base.split('/')[4]),request)

def test_same_revision_setup_source_switch_is_not_current(client):
    import json
    base,file,result=new_result(client)
    task,owner=confirmed_task(client,base,file,result,'boxplot')
    with database_connection(write=True) as db:
        row=db.execute('SELECT setup_json FROM analysis_setups WHERE file_id=%s',(file['id'],)).fetchone()
        setup=json.loads(row['setup_json']); setup['source']['dataset_id']='different-source'
        db.execute('UPDATE analysis_setups SET setup_json=%s WHERE file_id=%s',(json.dumps(setup),file['id']))
    workspace=client.get('/api/v1/tasks/'+task['id']+'/workspace')
    assert workspace.status_code==200,workspace.text
    assert not workspace.json()['source']['is_current']
    assert workspace.json()['source']['dataset_source']==result['source']


def test_matching_predecessor_refuses_same_run_with_changed_dataset_source(client):
    from psycopg.types.json import Jsonb
    from app.domain.plot_tasks import matching_task
    base,file,result=new_result(client)
    task,owner=confirmed_task(client,base,file,result,'boxplot')
    with database_connection(write=True) as db:
        db.execute("UPDATE tasks SET input_snapshot=jsonb_set(input_snapshot,'{source,dataset_id}',%s) WHERE id=%s",(Jsonb('changed'),task['id']))
    with pytest.raises(StorageError) as error:
        matching_task(TaskStore(owner),base.split('/')[4],result)
    assert error.value.code=='task_source_conflict'

@pytest.mark.parametrize('damage', ['missing', 'bytes', 'snapshot'])
def test_workspace_rejects_invalid_frozen_dataset_after_setup_changes(client, monkeypatch, damage):
    from pathlib import Path
    from app.core.config import get_data_dir
    from psycopg.types.json import Jsonb
    from tests.api.test_analysis import selection
    from tests.integration.test_dataset_artifact_chain import complete_chain
    from app.adapters.storage import ProjectStore
    from app.adapters.task_execution_store import ExecutionAssets
    original_reader = ProjectStore.original
    execution_reader = ExecutionAssets.original
    chain = complete_chain(client, monkeypatch)
    # Restore only the reader; retain isolation and authentication fixtures.
    monkeypatch.setattr(ProjectStore, 'original', original_reader)
    monkeypatch.setattr(ExecutionAssets, 'original', execution_reader)
    second = version(client, chain['base'], 1)
    from app.adapters.storage import ProjectStore
    from tests.api.test_dataset_analysis import forbid_original
    monkeypatch.setattr(ProjectStore, 'original', forbid_original)
    monkeypatch.setattr(ExecutionAssets, 'original', forbid_original)
    saved = client.put(chain['base']+'/analysis-setup', json=selection(dataset_id=second['id'], expected_revision=1))
    assert saved.status_code == 200, saved.text
    url = '/api/v1/tasks/'+chain['word_task']['id']+'/workspace'
    historical = client.get(url)
    assert historical.status_code == 200, historical.text
    assert not historical.json()['source']['is_current']
    assert historical.json()['artifacts']['report']
    assert client.get(chain['report_url']).status_code == 200
    with database_connection(write=True) as db:
        row = db.execute('SELECT object_key FROM dataset_versions WHERE id=%s', (chain['result']['source']['dataset_id'],)).fetchone()
        if damage == 'snapshot':
            db.execute("UPDATE tasks SET input_snapshot=jsonb_set(input_snapshot,'{source,dataset_version}',%s) WHERE id=%s", (Jsonb(2), chain['word_task']['id']))
    path = Path(get_data_dir())/row['object_key']
    if damage == 'missing':
        path.unlink()
    elif damage == 'bytes':
        path.write_bytes(b'broken')
    response = client.get(url)
    assert response.status_code == 409, response.text
