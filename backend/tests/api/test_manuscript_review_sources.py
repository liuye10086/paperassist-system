"""Real local numerical/figure source refresh (Linux sandbox only; no paid provider)."""
import sys
import pytest
from tests.api.test_manuscripts import client,body
from tests.api.test_literature_evidence import post
from tests.helpers.statistics import statistics_post
from app.domain.tasks.execution import run_task
from app.db.database import database_connection

pytestmark=pytest.mark.skipif(sys.platform!='linux',reason='Real numerical execution requires existing Linux sandbox')


def test_new_analysis_version_is_detected_and_selected_without_rebinding_old_text(client):
    from tests.api.test_descriptive import configured
    from tests.api.test_analysis import selection
    file_path,file=configured(client,[['Value','Group'],[27.555,'A'],[27.555,'A']],group_column=None)
    first=statistics_post(client,file_path+'/analysis-runs',json={'expected_revision':1,'idempotency_key':'analysis-first'}).json()
    path=file_path.split('/files/')[0]+'/manuscripts'
    source=dict(kind='analysis_run',id=first['id'],file_id=file['id'],role='computed_results')
    root=post(client,path,body(sources=[source],results_groups=[dict(id='main',title='Main',analysis_run_ids=[first['id']])]),'base').json()
    assert run_task(root['versions'][0]['task_id'],1)['status']=='succeeded'
    endpoint=path+'/'+root['id']+'/reviews'
    review=post(client,endpoint,dict(base_revision=1),'first').json()
    updated=client.put(file_path+'/analysis-setup',json=selection(expected_revision=1,group_column='B'))
    assert updated.status_code==200,updated.text
    second=statistics_post(client,file_path+'/analysis-runs',json={'expected_revision':2,'idempotency_key':'analysis-second'}).json()
    assert first['id']!=second['id'] and first['setup_revision']==1 and second['setup_revision']==2
    assert post(client,endpoint+'/'+review['id']+'/publish',dict(expected_revision=1),'stale').status_code==409
    context=client.get(endpoint+'/context').json()
    assert any('newer_analysis_run' in c['reasons'] for c in context['current_changes'])
    refreshed=post(client,endpoint,dict(base_revision=1,selected_sources=[source|dict(id=second['id'])]),'refresh')
    assert refreshed.status_code==201,refreshed.text
    refreshed=refreshed.json();candidate=refreshed['candidate']
    assert candidate['sources']==root['versions'][0]['snapshot']['sources']
    assert candidate['results_groups']==root['versions'][0]['snapshot']['results_groups']
    assert candidate['review']['selected_facts'] and all(f['source_id']==second['id'] for f in candidate['review']['selected_facts'])
    assert any('results:'+first['id'] in impact['locations'] for impact in refreshed['report']['impacts'])
    assert refreshed['report']['can_publish']


def test_new_figure_configuration_marks_linked_caption_without_mutating_frozen_image(client,monkeypatch):
    from tests.integration.test_batch05_figure_execution import queued_figure,IndependentLineProvider
    from app.domain.figure_workbench.execution import run_figure_workbench_task
    from app.domain.figure_workbench.contracts import SaveConfiguration
    from app.adapters.figure_workbench_store import read_bundle
    store,project,result,vid,task=queued_figure(client,monkeypatch)
    provider=IndependentLineProvider(result,pending=False)
    for _ in range(5):
        task=run_figure_workbench_task(task['id'],task['revision'],provider_factory=lambda:provider)
        if task['status']=='succeeded':break
    assert task['status']=='succeeded'
    figure=read_bundle(store.assets,project,task['result_figure_id'])['figure']
    path=f'/api/v1/projects/{project}/manuscripts'
    source=dict(kind='figure',id=figure['id'],file_id=result['file_id'],role='image_observation')
    root=post(client,path,body(sources=[source]),'base').json();run_task(root['versions'][0]['task_id'],1)
    endpoint=path+'/'+root['id']+'/reviews'
    with database_connection() as db:
        configuration=db.execute('SELECT * FROM figure_config_versions WHERE id=%s',(vid,)).fetchone()
    config=dict(configuration['config_json']);config['style']={'palette':'gray'}
    store.save(project,result['file_id'],result['id'],SaveConfiguration(configuration_id=configuration['configuration_id'],expected_revision=1,config=config))
    response=post(client,endpoint,dict(base_revision=1),'refresh')
    assert response.status_code==201,response.text
    review=response.json()
    assert any('figure_configuration_changed' in c['reasons'] for c in review['report']['source_changes'])
    assert any('caption:'+figure['id'] in i['locations'] for i in review['report']['impacts'])
    assert review['candidate']['results_groups']==root['versions'][0]['snapshot']['results_groups']

def test_synthetic_full_writer_preserves_exact_rounded_review_and_publishes(client):
    import json
    from tests.api.test_descriptive import configured
    from tests.api.test_manuscript_writing_execution import WritingProvider,budgets
    from app.domain.manuscript_writing.execution import run_manuscript_writing_task
    file_path,file=configured(client,[['Value','Group'],[27.555,'A'],[27.555,'A']],group_column=None)
    analysis=statistics_post(client,file_path+'/analysis-runs',json={'expected_revision':1,'idempotency_key':'analysis'}).json()
    path=file_path.split('/files/')[0]+'/manuscripts'
    source=dict(kind='analysis_run',id=analysis['id'],file_id=file['id'],role='computed_results')
    root=post(client,path,body(sources=[source],results_groups=[dict(id='main',title='Main',analysis_run_ids=[analysis['id']])]),'base').json()
    assert run_task(root['versions'][0]['task_id'],1)['status']=='succeeded'
    endpoint=path+'/'+root['id']+'/reviews';fact_id='analysis_run:'+analysis['id']+':/overall/mean'
    request=dict(base_revision=1,metadata=[dict(target_id=fact_id,field='display_precision',value='2',evidence='Protocol precision')],corrections=[dict(paragraph_id='results:'+analysis['id'],text='Mean = 27.56; see Table 1.',source_ids=[analysis['id']],numeric_bindings=[dict(fact_id=fact_id,value='27.56')])])
    response=post(client,endpoint,request,'review');assert response.status_code==201,response.text
    review=response.json();assert review['report']['can_publish'],review['report']['issues']
    published=post(client,endpoint+'/'+review['id']+'/publish',dict(expected_revision=1),'review-publish')
    assert published.status_code==201,published.text
    assert run_task(published.json()['versions'][0]['task_id'],1)['status']=='succeeded'
    writing_endpoint=path+'/'+root['id']+'/writing-requests'
    writing=post(client,writing_endpoint,dict(base_revision=2,mode='full_draft'),'writing').json()
    budgets(client,writing['task'])
    class EchoReviewedProvider(WritingProvider):
        def create(self,*,policy,instructions,payload):
            assert 'fact_id' in instructions and 'unchanged' in instructions
            return super().create(policy=policy,instructions=instructions,payload=payload)
        def receipt(self):
            receipt=super().receipt()
            sections=[dict(id=s['id'],paragraphs=[{k:v for k,v in p.items() if k in ('id','text','source_ids','citations','numeric_bindings','origin')} for p in s['paragraphs']]) for s in self.payload['normalized_sections']]
            receipt['response']['output'][0]['content'][0]['text']=json.dumps(dict(sections=sections))
            return receipt
    done=run_manuscript_writing_task(writing['id'],writing['task']['revision'],provider=EchoReviewedProvider())
    assert done['status']=='succeeded',done
    saved=client.get(writing_endpoint+'/'+writing['id']).json()['candidate']
    assert saved['sections'][3]['paragraphs']==review['candidate']['results_groups'][0]['paragraphs']
    latest=post(client,writing_endpoint+'/'+writing['id']+'/publish',dict(expected_revision=2),'writing-publish')
    assert latest.status_code==201,latest.text
    assert run_task(latest.json()['versions'][0]['task_id'],1)['status']=='succeeded'
    export=post(client,path+'/'+root['id']+'/versions/3/exports',{},'docx').json()
    assert run_task(export['task_id'],1)['status']=='succeeded'
