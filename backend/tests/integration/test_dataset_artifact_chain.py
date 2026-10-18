"""Historical pre-plan dataset chain without original reads or real providers."""
from tests.helpers.legacy_statistics import seed_legacy_statistics
import json
from io import BytesIO
import pytest
from psycopg.types.json import Jsonb
from app.db.database import database_connection
from app.adapters.storage import ProjectStore
from app.adapters.task_execution_store import ExecutionAssets, TaskExecutionStore
from app.adapters.task_store import TaskStore
from app.domain.tasks.contracts import TaskCreateRequest
from app.domain.tasks.service import TaskService
from app.domain.external_processing import disclosure
from tests.api.test_analysis import client, add_file, selection
from tests.api.test_dataset_analysis import version, forbid_original
from tests.helpers.tasks import task_owner
from tests.integration.test_boxplot_execution import SyntheticPlotProvider, run as run_plot
from tests.integration.test_explanation_execution import SyntheticProvider, run as run_explanation


def new_result(client):
    base, file = add_file(client)
    dataset = version(client, base)
    saved=client.put(base+'/analysis-setup',json=selection(dataset_id=dataset['id'],expected_revision=0))
    assert saved.status_code==200,saved.text
    # This suite retains the pre-plan dataset/boxplot_v2 historical contract.
    return base,file,seed_legacy_statistics(client,base)


def test_dataset_report_metadata_binds_source(client):
    from app.adapters.report_store import ReportStore, digest
    _, _, result = new_result(client)
    snapshot = {'result': result, 'source': result['source'],
                'figure': {'id': 'figure', 'sha256': 'a' * 64},
                'explanation': {'id': 'explanation'}}
    report = ReportStore.metadata(snapshot)
    assert report.get('source') == result['source']
    assert report['input_sha256'] == digest(snapshot)


def confirmed_task(client,base,file,result,kind,figure=None,explanation=None):
    owner=task_owner(client)
    request=TaskCreateRequest(task_type=kind,file_id=file['id'],analysis_run_id=result['id'],expected_revision=1,
        figure_id=figure['id'] if figure else None,explanation_id=explanation['id'] if explanation else None)
    store=TaskStore(owner)
    with store.connection() as db:
        frozen=store.source_snapshot(db,store.require_project(db,base.split('/')[4]),request)
    if kind!='word_report':
        preview=disclosure(frozen,kind,owner)
        request=request.model_copy(update={'external_processing':dict(version=preview['version'],confirmed=True,
            source_digest=preview['source_digest'],labels={v['key']:v['value'] for v in preview['labels']})})
    task,_=TaskService(owner).create(base.split('/')[4],request,idempotency_key=kind)
    if kind!='word_report':
        from app.domain.model_usage.service import ModelUsageService
        policy={'model':'test-plot' if kind=='boxplot' else 'test-explanation','prompt_version':'openai_boxplot_v1' if kind=='boxplot' else 'analysis_explanation_v1',
          'max_output_tokens':16000 if kind=='boxplot' else 10000,'timeout_seconds':15,'tools':['code_interpreter'] if kind=='boxplot' else [],
          'output_format':'text' if kind=='boxplot' else 'analysis_explanation_v1','price':{'version':'synthetic-only','model':'test-plot' if kind=='boxplot' else 'test-explanation',
          'input_micro_usd_per_million':100,'cached_input_micro_usd_per_million':50,'output_micro_usd_per_million':200}}
        frozen_policy={'policy':policy,'input_token_allowance':100000,'task_limit_micro_usd':1000000}
        if kind=='boxplot': frozen_policy.update(tool_reserve_micro_usd=1000,tool_reserve_version='synthetic-only')
        with database_connection(write=True) as db:
            db.execute("UPDATE tasks SET input_snapshot=jsonb_set(input_snapshot,%s,%s) WHERE id=%s",(['boxplot_policy' if kind=='boxplot' else 'explanation_policy'],Jsonb(frozen_policy),task['id']))
        service=ModelUsageService(owner)
        for scope,key in [('user',owner),('project',task['project_id']),('task',task['id'])]:
            budget=service.get_budget(scope,key)
            if budget['limit_micro_usd'] is None: service.set_budget(scope,key,1000000,0)
    return task,owner


def complete_chain(client,monkeypatch):
    base,file,result=new_result(client)
    task,owner=confirmed_task(client,base,file,result,'boxplot')
    monkeypatch.setattr(ProjectStore,'original',forbid_original)
    monkeypatch.setattr(ExecutionAssets,'original',forbid_original)
    provider=SyntheticPlotProvider(result,pending=False)
    current=task
    for _ in range(8):
        current=run_plot(current,provider)
        if current['status'] in ('failed','succeeded'): break
    assert current['status']=='succeeded',current
    assert set(provider.payload)=={'labels','values','groups'}
    with database_connection() as db:
        row=db.execute('SELECT * FROM tasks WHERE id=%s',(task['id'],)).fetchone()
        assert row['workflow_version']=='boxplot_v2' and row['input_snapshot']['schema_version']==2
        figure=json.loads(db.execute('SELECT figure_json FROM figures WHERE id=%s',(current['result_figure_id'],)).fetchone()['figure_json'])
    assert figure['source']==result['source']
    task,owner=confirmed_task(client,base,file,result,'explanation',figure)
    explanation_provider=SyntheticProvider()
    current=run_explanation(task,explanation_provider)
    assert current['status']=='succeeded',current
    with database_connection() as db:
        explanation=json.loads(db.execute('SELECT explanation_json FROM explanations WHERE id=%s',(current['result_explanation_id'],)).fetchone()['explanation_json'])
    assert explanation['source']==result['source']
    task,owner=confirmed_task(client,base,file,result,'word_report',figure,explanation)
    from app.domain.tasks.execution import run_word_task
    current=run_word_task(task['id'],task['revision'])
    assert current['status']=='succeeded',current
    workspace=client.get('/api/v1/tasks/'+task['id']+'/workspace')
    assert workspace.status_code==200,workspace.text
    assert workspace.json()['source']['dataset_source']==result['source']
    download=client.get(workspace.json()['artifacts']['report']['download_url'])
    assert download.status_code==200,download.text
    from docx import Document
    text='\n'.join(p.text for p in Document(BytesIO(download.content)).paragraphs)
    assert '原始数据版本 1' in text and file['filename'] in text
    assert result['source']['dataset_id'] not in text and result['source']['dataset_sha256'] not in text
    return {'base': base, 'file': file, 'result': result, 'figure': figure, 'explanation': explanation,
            'word_task': current, 'report_url': workspace.json()['artifacts']['report']['download_url']}


def test_dataset_full_chain_keeps_source_and_no_technical_ids_outbound(client,monkeypatch):
    complete_chain(client,monkeypatch)


@pytest.mark.parametrize('target', ['figure_download', 'explanation', 'report_download', 'report_input'])
def test_dataset_read_paths_reject_cross_version_artifact(client,monkeypatch,target):
    chain = complete_chain(client,monkeypatch)
    result, base = chain['result'], chain['base']
    run_url = base + '/analysis-runs/' + result['id']
    with database_connection(write=True) as db:
        if target == 'figure_download':
            value = {**chain['figure'], 'source': {**result['source'], 'dataset_version': 2}}
            db.execute('UPDATE figures SET figure_json=%s WHERE id=%s',
                       (json.dumps(value), value['id']))
            url = run_url + '/figures/' + value['id'] + '/download'
        elif target == 'explanation':
            value = {**chain['explanation'], 'source': {**result['source'], 'dataset_version': 2}}
            db.execute('UPDATE explanations SET explanation_json=%s WHERE id=%s',
                       (json.dumps(value), value['id']))
            url = run_url + '/explanation'
        else:
            row = db.execute('SELECT * FROM reports WHERE id=%s',
                             (chain['word_task']['result_report_id'],)).fetchone()
            field = 'input_json' if target == 'report_input' else 'report_json'
            value = json.loads(row[field])
            value['source'] = {**result['source'], 'dataset_version': 2}
            db.execute('UPDATE reports SET ' + field + '=%s WHERE id=%s', (json.dumps(value), row['id']))
            url = chain['report_url']
    response = client.get(url)
    assert response.status_code == 409, (target, response.status_code)
