from tests.helpers.projection import check_projection,confirm_projection
from copy import deepcopy
import json
import pytest
from tests.api.test_analysis import client
from tests.integration.test_batch05_figure_store import source
from tests.integration.test_boxplot_execution import SyntheticPlotProvider
from app.domain.figure_workbench.contracts import SaveConfiguration,ConfirmProjection,GenerateFigure
from app.domain.figure_workbench.tasks import submit
from app.domain.figure_workbench.execution import run_figure_workbench_task
from app.adapters.figure_workbench_store import read_bundle
from app.domain.model_usage.service import ModelUsageService


def frozen_policy(payload,explanation=False):
    from app.domain.figure_workbench.tasks import prompt_version
    version=prompt_version(payload)
    return {'policy':{'model':'test-plot','prompt_version':version,'max_output_tokens':16000,'timeout_seconds':15,'tools':['code_interpreter'],'output_format':'text','price':{'version':'synthetic-only','model':'test-plot','input_micro_usd_per_million':100,'cached_input_micro_usd_per_million':50,'output_micro_usd_per_million':200}},'input_token_allowance':100000,'task_limit_micro_usd':1000000,'tool_reserve_micro_usd':1000,'tool_reserve_version':'synthetic-tool-only'}

class IndependentLineProvider(SyntheticPlotProvider):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        from io import BytesIO
        from PIL import Image
        buffer=BytesIO();Image.new('RGB',(2400,1600),'white').save(buffer,format='PNG');self.png=buffer.getvalue()
    def receipt(self):
        receipt=super().receipt()
        receipt['response']['output'][1]['content'][0]['annotations'][0]['filename']='/mnt/data/figure.png'
        return receipt
    def download(self,file_id,container_id,limit,*,policy):
        self.downloads.append(file_id)
        if file_id=='cfile_png':return self.png
        payload=self.payload
        manifest={k:deepcopy(payload[k]) for k in ('schema_version','figure_kind','language','plot_config')}
        manifest.update(payload['labels']);manifest['statistics']={'series':[{'group':None,'points':[{'x':1.,'y':9.,'n':1,'missing':0},{'x':2.,'y':8.,'n':1,'missing':0},{'x':3.,'y':7.,'n':1,'missing':0},{'x':4.,'y':6.,'n':1,'missing':0}]}]}
        if self.corrupt:manifest['statistics']['series'][0]['points'][0]['y']=99.
        return json.dumps(manifest).encode()


def queued_figure(client,monkeypatch,config=None,*,contract_version=1):
    store,project,result=source(client);args=(project,result['file_id'],result['id'])
    saved=store.save(*args,SaveConfiguration(config=config or {'figure_kind':'line','language':'en','projection':{'x_column':'A','y_column':'C'}}));vid=saved['version']['id']
    if contract_version in (1,2):
        # Freeze a genuine pre-batch06 configuration before any decision/task.
        # These regression tests retain v1 recovery and old provider receipt coverage.
        from app.db.database import database_connection
        from app.domain.external_processing import digest
        from psycopg.types.json import Jsonb
        with database_connection(write=True) as db:
            row=db.execute('SELECT * FROM figure_config_versions WHERE id=%s',(vid,)).fetchone()
            provenance={k:v for k,v in row['source_json'].items() if k!='figure_contract'}
            if contract_version==2:provenance['figure_contract']=2
            db.execute('UPDATE figure_config_versions SET source_json=%s,sha256=%s WHERE id=%s',(Jsonb(provenance),digest({'config':row['config_json'],'source':provenance}),vid))
    check=check_projection(store,*args,vid);confirm_projection(store,*args,vid,ConfirmProjection(input_sha256=check['input_sha256'],approved=True))
    preview=store.external_preview(*args,vid)
    monkeypatch.setattr('app.domain.figure_workbench.tasks.policy_for',frozen_policy)
    task=submit(store,*args,vid,GenerateFigure(idempotency_key='new-figure',external_processing={'confirmed':True,'payload_sha256':preview['payload_sha256']}))['task']
    service=ModelUsageService(store.tasks.user_id)
    for scope,key in [('user',store.tasks.user_id),('project',project)]:service.set_budget(scope,key,5000000,0)
    return store,project,result,vid,task


def test_new_plot_independent_manifest_durable_receipts_and_original_png(client,monkeypatch):
    store,project,result,vid,task=queued_figure(client,monkeypatch)
    provider=IndependentLineProvider(result,pending=False)
    for _ in range(5):
        task=run_figure_workbench_task(task['id'],task['revision'],provider_factory=lambda:provider)
        assert task is not None
        if task['status'] in ('succeeded','failed'):break
    assert task['status']=='succeeded',task
    assert provider.posts==['container','upload','response']
    bundle=read_bundle(store.assets,project,task['result_figure_id'])
    assert bundle['figure']['schema_version']==5
    assert bundle['figure']['figure_config_version_id']==vid
    assert store.assets.figure_png(bundle['figure'])==provider.png
    assert bundle['figure']['figure_number'] is None
    assert bundle['figure']['statistics']['series'][0]['points'][0]['y']==9.


def test_independent_cloud_disagreement_never_publishes_figure(client,monkeypatch):
    store,project,result,vid,task=queued_figure(client,monkeypatch);provider=IndependentLineProvider(result,pending=False);provider.corrupt=True
    for _ in range(5):
        task=run_figure_workbench_task(task['id'],task['revision'],provider_factory=lambda:provider)
        assert task is not None
        if task['status'] in ('succeeded','failed'):break
    assert task['status']=='failed' and task['error_code']=='plot_result_mismatch'
    assert store.state(project,result['file_id'],result['id'])['configurations'][0]['figure'] is None


@pytest.mark.parametrize('failure',['plot_files_missing','plot_no_execution','plot_output_limit','openai_incomplete','plot_invalid_result'])
def test_recorded_plot_output_failure_allows_explicit_new_intent(client,monkeypatch,failure):
    from app.db.database import database_connection
    from app.domain.tasks.workspace import TaskWorkspaceService
    store,project,result,vid,task=queued_figure(client,monkeypatch)
    class BadOutput(IndependentLineProvider):
        def receipt(self):
            receipt=super().receipt();response=receipt['response']
            if failure=='plot_files_missing':response['output'][1]['content'][0]['annotations'].pop(0)
            elif failure=='plot_no_execution':response['output'].pop(0)
            elif failure=='openai_incomplete':receipt['status']=response['status']='incomplete'
            return receipt
        def download(self,*args,**kwargs):
            if failure=='plot_output_limit':return b' '* (8*1024*1024+1)
            if failure=='plot_invalid_result':return super().download(*args,**kwargs).replace(b'"y": 9.0',b'"y": 1e400')
            return super().download(*args,**kwargs)
    provider=BadOutput(result,pending=False)
    for _ in range(5):
        task=run_figure_workbench_task(task['id'],task['revision'],provider_factory=lambda:provider)
        assert task is not None
        if task['status']=='failed':break
    assert task['status']=='failed' and task['error_code']==failure,task
    assert TaskWorkspaceService(store.tasks.user_id).get(task['id'])['allowed_actions']==[]
    with database_connection() as db:old=dict(db.execute('SELECT * FROM model_calls WHERE task_id=%s',(task['id'],)).fetchone())
    assert old['provider_response_id'] and old['status']=='completed'
    args=(project,result['file_id'],result['id'],vid)
    preview=store.external_preview(*args)
    new=submit(store,*args,GenerateFigure(idempotency_key='after-recorded-failure',external_processing={'confirmed':True,'payload_sha256':preview['payload_sha256']}))['task']
    assert new['id']!=task['id'] and new['status']=='queued'
    with database_connection() as db:
        assert dict(db.execute('SELECT * FROM model_calls WHERE id=%s',(old['id'],)).fetchone())==old
        assert db.execute('SELECT count(*) AS n FROM model_calls WHERE task_id=%s',(new['id'],)).fetchone()['n']==0
    assert provider.posts==['container','upload','response']


@pytest.mark.parametrize('failure',['explanation_invalid_json','explanation_refused','explanation_output_limit','explanation_incomplete'])
def test_recorded_explanation_failure_allows_explicit_new_intent(client,monkeypatch,failure):
    from app.db.database import database_connection
    from app.domain.figure_workbench.execution import run_figure_explanation_task
    from app.domain.figure_workbench.explanations import build_payload
    from app.domain.external_processing import digest
    store,project,result,vid,plot=queued_figure(client,monkeypatch);provider=IndependentLineProvider(result,pending=False)
    for _ in range(5):
        plot=run_figure_workbench_task(plot['id'],plot['revision'],provider_factory=lambda:provider)
        if plot['status']=='succeeded':break
    bundle=read_bundle(store.assets,project,plot['result_figure_id'])
    def policy(payload,explanation=False):
        value=frozen_policy(payload);value['policy'].update(prompt_version='figure_explanation_v1',tools=[],output_format='analysis_explanation_v2');return value
    monkeypatch.setattr('app.domain.figure_workbench.tasks.policy_for',policy)
    external={'confirmed':True,'payload_sha256':digest(build_payload(bundle))}
    args=(store,project,result['file_id'],result['id'],vid)
    task=submit(*args,GenerateFigure(idempotency_key='bad-explanation',external_processing=external),figure_id=plot['result_figure_id'])['task']
    class BadExplanation(FigureExplanationProvider):
        def create(self,**kwargs):
            receipt=super().create(**kwargs);response=receipt['response'];part=response['output'][0]['content'][0]
            if failure=='explanation_invalid_json':part['text']='broken json'
            elif failure=='explanation_refused':part.update(type='refusal',refusal='synthetic refusal')
            elif failure=='explanation_output_limit':part['text']=' '*(96*1024+1)
            else:receipt['status']=response['status']='incomplete'
            return receipt
    bad=BadExplanation();task=run_figure_explanation_task(task['id'],task['revision'],provider_factory=lambda:bad)
    assert task and task['status']=='failed' and task['error_code']==failure,task
    with database_connection() as db:old=dict(db.execute('SELECT * FROM model_calls WHERE task_id=%s',(task['id'],)).fetchone())
    new=submit(*args,GenerateFigure(idempotency_key='regenerate-explanation',external_processing=external),figure_id=plot['result_figure_id'])['task']
    assert new['id']!=task['id'] and new['status']=='queued'
    with database_connection() as db:assert dict(db.execute('SELECT * FROM model_calls WHERE id=%s',(old['id'],)).fetchone())==old
    assert len(bad.posts)==1


def test_unknown_submission_never_allows_paid_regeneration(client,monkeypatch):
    from app.db.database import database_connection
    from app.core.exceptions import StorageError
    store,project,result,vid,task=queued_figure(client,monkeypatch)
    provider=IndependentLineProvider(result,pending=False);provider.fail_post='response'
    for _ in range(5):
        task=run_figure_workbench_task(task['id'],task['revision'],provider_factory=lambda:provider)
        assert task is not None
        if task['status']=='waiting_confirmation':break
    assert task['reason_code']=='submission_unknown',task
    with database_connection(write=True) as db:
        old=dict(db.execute('SELECT * FROM model_calls WHERE task_id=%s',(task['id'],)).fetchone())
        assert not old['provider_response_id'] and old['status']=='submission_unknown'
        db.execute("UPDATE tasks SET status='failed',error_code='plot_files_missing' WHERE id=%s",(task['id'],))
    args=(project,result['file_id'],result['id'],vid);preview=store.external_preview(*args)
    with pytest.raises(StorageError) as error:submit(store,*args,GenerateFigure(idempotency_key='must-not-repost',external_processing={'confirmed':True,'payload_sha256':preview['payload_sha256']}))
    assert error.value.code=='task_transition_invalid'
    with database_connection() as db:
        assert dict(db.execute('SELECT * FROM model_calls WHERE id=%s',(old['id'],)).fetchone())==old
        assert db.execute("SELECT count(*) AS n FROM tasks WHERE task_type='figure_workbench' AND project_id=%s",(project,)).fetchone()['n']==1
    assert provider.posts==['container','upload','response']

class FigureExplanationProvider:
    def __init__(self):self.posts=[];self.closed=0
    def create(self,*,policy,instructions,payload):
        self.posts.append(payload)
        draft={key:'; '.join('{{'+ref+'}}' for ref in refs) for key,refs in payload['required_references'].items()}
        usage={'input_tokens':100,'output_tokens':50,'total_tokens':150,'input_tokens_details':{'cached_tokens':0,'cache_write_tokens':0}}
        response={'id':'resp_new_figure_explanation','model':'test-plot','status':'completed','usage':usage,'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(draft)}]}]}
        return {'response_id':response['id'],'request_id':'req_new_explanation','model':'test-plot','status':'completed','usage':usage,'response':response}
    def close(self):self.closed+=1


def complete_figure_bundle(client,monkeypatch):
    store,project,result,vid,task=queued_figure(client,monkeypatch);provider=IndependentLineProvider(result,pending=False)
    for _ in range(5):
        task=run_figure_workbench_task(task['id'],task['revision'],provider_factory=lambda:provider)
        assert task is not None
        if task['status']=='succeeded':break
    assert task['status']=='succeeded'
    bundle=read_bundle(store.assets,project,task['result_figure_id'])
    from app.domain.figure_workbench.explanations import build_payload
    from app.domain.external_processing import digest
    def explanation_policy(payload,explanation=False):
        frozen=frozen_policy(payload);frozen['policy'].update(prompt_version='figure_explanation_v1',output_format='analysis_explanation_v2',tools=[])
        frozen.pop('tool_reserve_micro_usd');frozen.pop('tool_reserve_version');frozen['task_limit_micro_usd']=500000
        return frozen
    monkeypatch.setattr('app.domain.figure_workbench.tasks.policy_for',explanation_policy)
    request=GenerateFigure(idempotency_key='explain-new',external_processing={'confirmed':True,'payload_sha256':digest(build_payload(bundle))})
    task=submit(store,project,result['file_id'],result['id'],vid,request,figure_id=bundle['figure']['id'])['task']
    from app.domain.figure_workbench.execution import run_figure_explanation_task
    provider=FigureExplanationProvider();task=run_figure_explanation_task(task['id'],task['revision'],provider_factory=lambda:provider)
    assert task is not None and task['status']=='succeeded',task
    return store,project,result,read_bundle(store.assets,project,bundle['figure']['id'],task['result_explanation_id'])


def test_new_figure_has_its_own_six_section_explanation_and_fact_binding(client,monkeypatch):
    store,project,result,bundle=complete_figure_bundle(client,monkeypatch)
    assert bundle['explanation']['figure_sha256']==bundle['figure']['sha256']
    assert len(bundle['explanation']['sections'])==6
    assert bundle['explanation']['engine']['id']=='figure_explanation_v1'
    assert bundle['explanation']['verification']['status']=='references_checked'

def test_verified_candidate_recovers_without_cloud_or_overwriting_existing_png(client,monkeypatch):
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.adapters.task_store import TaskStore
    from tests.integration.test_task_execution import expired
    from tests.integration.test_boxplot_execution import lease_for
    import app.domain.figure_workbench.execution as execution
    store,project,result,vid,task=queued_figure(client,monkeypatch);provider=IndependentLineProvider(result,pending=False)
    original=execution._publish_figure
    monkeypatch.setattr(execution,'_publish_figure',lambda *args: (_ for _ in ()).throw(RuntimeError('synthetic crash after bytes')))
    for _ in range(3):
        updated=run_figure_workbench_task(task['id'],task['revision'],provider_factory=lambda:provider)
        if updated is None:break
        task=updated
    assert updated is None
    expired(lease_for(task));assert TaskExecutionStore().recover_expired()>=1
    task=TaskStore(store.tasks.user_id).get(task['id'])
    monkeypatch.setattr(execution,'_publish_figure',original)
    done=run_figure_workbench_task(task['id'],task['revision'],provider_factory=lambda:(_ for _ in ()).throw(AssertionError('must reuse local bytes')))
    assert done['status']=='succeeded'
    bundle=read_bundle(store.assets,project,done['result_figure_id']);target=store.assets.figures_dir/(bundle['figure']['id']+'.png')
    assert target.read_bytes()==provider.png


def test_existing_candidate_target_is_never_overwritten(client,monkeypatch):
    import pytest
    from app.domain.figure_workbench.execution import write_candidate
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.core.exceptions import StorageError
    from hashlib import sha256
    store,project,result,vid,task=queued_figure(client,monkeypatch);repository=TaskExecutionStore();lease=repository.claim(task['id'],task['revision'])
    figure={'id':'existing-candidate','sha256':sha256(b'new').hexdigest(),'size_bytes':3}
    store.assets.figures_dir.mkdir(parents=True,exist_ok=True);target=store.assets.figures_dir/'existing-candidate.png';target.write_bytes(b'old')
    with pytest.raises(StorageError):write_candidate(repository,lease,store,figure,b'new')
    assert target.read_bytes()==b'old'

def test_budget_wait_resumes_existing_intent_and_never_posts_before_admission(client,monkeypatch):
    from app.db.database import database_connection
    from app.domain.tasks.workspace import TaskWorkspaceService
    from app.domain.tasks.resume import TaskResumeService
    store,project,result,vid,task=queued_figure(client,monkeypatch)
    with database_connection(write=True) as db:db.execute('UPDATE model_budgets SET limit_micro_usd=0 WHERE scope_type=%s AND scope_key=%s',('task',task['id']))
    provider=IndependentLineProvider(result,pending=False)
    waiting=run_figure_workbench_task(task['id'],task['revision'],provider_factory=lambda:provider)
    assert waiting['status']=='waiting_confirmation' and waiting['reason_code']=='budget_exceeded'
    assert provider.posts==[]
    view=TaskWorkspaceService(store.tasks.user_id).get(task['id']);assert view['allowed_actions']==['resume']
    with database_connection(write=True) as db:db.execute('UPDATE model_budgets SET limit_micro_usd=1000000 WHERE scope_type=%s AND scope_key=%s',('task',task['id']))
    resumed=TaskResumeService(store.tasks.user_id).resume(task['id'],{'operation':'resume','wait_id':view['wait']['id'],'expected_task_revision':waiting['revision'],'input_version':waiting['input_version']},idempotency_key='resume-budget')
    for _ in range(4):
        resumed=run_figure_workbench_task(resumed['id'],resumed['revision'],provider_factory=lambda:provider)
        assert resumed is not None
        if resumed['status']=='succeeded':break
    assert resumed['status']=='succeeded' and resumed['id']==task['id']

class IndependentBarViolinProvider(IndependentLineProvider):
    def download(self,file_id,container_id,limit,*,policy):
        if file_id=='cfile_png':return self.png
        import math
        p=self.payload;manifest={k:deepcopy(p[k]) for k in ('schema_version','figure_kind','language','plot_config')};manifest.update(p['labels'])
        if p['figure_kind']=='bar':
            series=[{'group':None,'points':[{'category':c,'n':1,'denominator':3,'value':1/3,'sd':None,'reason':None} for c in (7.,8.,9.)]}]
        else:
            # Independent direct Gaussian formula, fixed dataset [5,6,7,8,9], no scipy/kernel imports.
            h=math.sqrt(2.5)*5**(-.2);grid=[5.+i*4./255 for i in range(256)]
            density=[sum(math.exp(-.5*((x-y)/h)**2) for y in (5.,6.,7.,8.,9.))/(5*h*math.sqrt(2*math.pi)) for x in grid]
            series=[{'group':None,'n':5,'bandwidth':h,'min':5.,'max':9.,'grid':grid,'density':density,'q1':6.,'median':7.,'q3':8.}]
        manifest['statistics']={'series':series}
        return json.dumps(manifest).encode()


import pytest
@pytest.mark.parametrize('kind',['bar','violin'])
def test_new_bar_violin_cloud_numerics_use_independent_oracle(client,monkeypatch,kind):
    config={'figure_kind':kind,'language':'en','projection':{'category_column':'C','bar_stat':'proportion','included_categories':[7.,8.,9.]} if kind=='bar' else {'y_column':'C'}}
    store,project,result,vid,task=queued_figure(client,monkeypatch,config)
    provider=IndependentBarViolinProvider(result,pending=False)
    for _ in range(4):
        task=run_figure_workbench_task(task['id'],task['revision'],provider_factory=lambda:provider)
        assert task is not None
        if task['status'] in ('succeeded','failed'):break
    assert task['status']=='succeeded',task
    assert not {'series','statistics','expected','source','audit'} & provider.payload.keys()
    assert read_bundle(store.assets,project,task['result_figure_id'])['figure']['figure_kind']==kind
