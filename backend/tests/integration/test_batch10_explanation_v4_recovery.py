"""Frozen v3 response recovery and coexisting v4 intents, all providers synthetic."""
from copy import deepcopy
import pytest
from tests.api.test_analysis import client
from tests.integration.test_batch05_figure_execution import queued_figure
from tests.integration.test_batch06_pipeline import IndependentV2LineProvider,checked_policy
from tests.integration.test_batch08_recovery import PendingExplanationProvider,finish,step,raw_task,saved_call
from app.domain.figure_workbench import explanations as e
from app.domain.figure_workbench.execution import run_figure_workbench_task,run_figure_explanation_task
from app.domain.figure_workbench.tasks import submit
from app.domain.figure_workbench.contracts import GenerateFigure
from app.adapters.figure_workbench_store import read_bundle
from app.adapters.collection_store import CollectionStore
from app.domain.report_collections.contracts import CollectionRequest
from app.domain.report_collections.execution import run_collection_word_task
from app.domain.external_processing import digest
from app.core.exceptions import StorageError


@pytest.fixture(autouse=True)
def frozen_historical_v4_default(monkeypatch):
    original=e.version_for
    monkeypatch.setattr(e,'version_for',lambda figure,*,version=None:original(figure,version=version or e.V4_VERSION))
    enrich=CollectionStore.enrich_bundle
    def frozen_collection_dependency(self,project_id,value):
        item=enrich(self,project_id,value)
        if item['configuration'].get('figure_contract')==3:
            item['dependency_engine']=e.V4_VERSION
        return item
    monkeypatch.setattr(CollectionStore,'enrich_bundle',frozen_collection_dependency)


def test_frozen_v3_recovers_original_response_while_new_v4_and_collections_are_distinct(client,monkeypatch):
    store,project,result,version,plot=queued_figure(client,monkeypatch,contract_version=3)
    plot=finish(plot,IndependentV2LineProvider(result,pending=False),run_figure_workbench_task)
    assert plot['status']=='succeeded',plot
    bundle=read_bundle(store.assets,project,plot['result_figure_id'])
    monkeypatch.setattr('app.domain.figure_workbench.tasks.policy_for',checked_policy)
    def request(payload,key):return GenerateFigure(idempotency_key=key,external_processing={'confirmed':True,'payload_sha256':digest(payload)})
    args=(store,project,result['file_id'],result['id'],version)
    original=e.version_for
    repository=CollectionStore(store.assets)
    # Simulate the pre-upgrade default when this immutable task was queued.
    with monkeypatch.context() as old_code:
        old_code.setattr(e,'version_for',lambda figure,*,version=None:original(figure,version=version or 'figure_explanation_v3'))
        old_payload=e.build_payload(bundle)
        old=submit(*args,request(old_payload,'old-v3'),figure_id=bundle['figure']['id'])['task']
        provider=PendingExplanationProvider()
        old=step(old,provider,run_figure_explanation_task)
        assert old['status']=='running',old
        enrich=repository.enrich_bundle
        def legacy_dependency(project_id,value):
            enriched=enrich(project_id,value);enriched['dependency_engine']='figure_explanation_v3'
            return enriched
        old_code.setattr(repository,'enrich_bundle',legacy_dependency)
        old_collection=repository.create(project,CollectionRequest(title='Old pending v3',language='en',items=[{'figure_config_version_id':version}]),'old-v3-report')
        assert old_collection['versions'][0]['items'][0]['dependency_engine']=='figure_explanation_v3'
        assert old_collection['versions'][0]['requests'][0]['status']=='waiting'
    frozen=deepcopy(raw_task(old)['input_snapshot']);call=saved_call(old)
    assert frozen['explanation_policy']['policy']['prompt_version']=='figure_explanation_v3'
    new_payload=e.build_payload(bundle)
    assert new_payload['figure_explanation_contract']==4
    with pytest.raises(StorageError):submit(*args,request(new_payload,'blocked-v4'),figure_id=bundle['figure']['id'])
    provider.pending=False
    old=finish(old,provider,run_figure_explanation_task)
    assert old['status']=='succeeded',old
    assert len(provider.posts)==1 and provider.gets==[call['provider_response_id']]
    assert saved_call(old)['id']==call['id'] and saved_call(old)['input_digest']==call['input_digest']
    assert raw_task(old)['input_snapshot']==frozen
    historical=read_bundle(store.assets,project,bundle['figure']['id'],old['result_explanation_id'])
    assert historical['explanation']['engine']['id']=='figure_explanation_v3'
    from app.domain.report_collections.service import advance_pending
    def build_word(collection):
        advance_pending(config=repository.store.db_config,directory=repository.store.directory)
        row=repository.get(project,collection['id'])['versions'][0]['requests'][0]
        done=run_collection_word_task(row['task_id'],1,config=repository.store.db_config,directory=repository.store.directory)
        assert done and done['status']=='succeeded',done
        report=repository.get(project,collection['id'])['versions'][0]['requests'][0]['report']
        return report['id'],repository.download(project,collection['id'],report['id'])[1]
    old_report,old_word=build_word(old_collection)
    new_collection=repository.create(project,CollectionRequest(title='New v4',language='en',items=[{'figure_config_version_id':version}]),'new-v4-report')
    assert new_collection['versions'][0]['requests'][0]['status']=='waiting'
    new=submit(*args,request(new_payload,'new-v4'),figure_id=bundle['figure']['id'])['task']
    assert new['id']!=old['id']
    assert submit(*args,request(new_payload,'new-v4'),figure_id=bundle['figure']['id'])['task']['id']==new['id']
    assert raw_task(new)['input_snapshot']['explanation_policy']['policy']['prompt_version']=='figure_explanation_v4'
    next_provider=PendingExplanationProvider(pending=False)
    create=next_provider.create
    def unique_receipt(**kwargs):
        receipt=create(**kwargs);receipt['response_id']=receipt['response']['id']='resp_v4_new'
        return receipt
    monkeypatch.setattr(next_provider,'create',unique_receipt)
    new=finish(new,next_provider,run_figure_explanation_task)
    assert new['status']=='succeeded',new
    current=read_bundle(store.assets,project,bundle['figure']['id'],new['result_explanation_id'])
    assert current['explanation']['engine']['id']=='figure_explanation_v4'
    assert read_bundle(store.assets,project,bundle['figure']['id'],old['result_explanation_id'])==historical
    build_word(new_collection)
    assert repository.download(project,old_collection['id'],old_report)[1]==old_word
    assert repository.get(project,old_collection['id'])['versions'][0]['items'][0]['dependency_engine']=='figure_explanation_v3'
