"""The old research checks consume persisted v2 science and language authority."""
from copy import deepcopy
import json
from tests.api.test_analysis import client
from tests.api.test_descriptive import configured
from tests.api.test_literature_evidence import post
from tests.api.test_manuscript_writing_live import authorize,request_v2,LiveFixture
from tests.api.test_manuscript_writing_live_review import decision
from tests.api.test_manuscript_writing_language import approve
from tests.integration.test_literature_assistance import budgets
from app.domain.literature.service import digest
from app.domain.tasks.execution import run_task
from app.domain.manuscript_writing.execution import run_manuscript_writing_task


def published(client):
    # An explicit legacy synthetic source tests the manuscript seam without
    # invoking the Linux-only numerical worker or claiming a verified receipt.
    from app.adapters.storage import get_project_store
    from app.db.database import get_database_config
    config=get_database_config();assert config.environment=='test' and config.schema.startswith('pa_test_')
    base,file=configured(client,[['Value','Group']]+[[3,'A'] for _ in range(8)])
    setup=client.get(base+'/analysis-setup').json()
    summary=dict(n=8,mean=3.0,std=0.0,min=3.0,q1=3.0,median=3.0,q3=3.0,max=3.0,iqr=0.0,warnings=[])
    result=get_project_store().save_analysis_run(base.split('/')[4],file['id'],dict(
        file_id=file['id'],filename=file['filename'],source_sha256=file['sha256'],setup_revision=setup['revision'],
        selection=setup['selection'],check=setup['check'],numeric_name='Value',group_name='Group',
        engine=dict(id='synthetic_fixture',python_version='synthetic_fixture',std_ddof=1,quantile_method='linear_inclusive'),
        started_at=setup['updated_at'],completed_at=setup['updated_at'],overall=summary,groups=[dict(label='A',statistics=summary)]))
    project=base.split('/')[4];root=f'/api/v1/projects/{project}/manuscripts'
    source=dict(kind='analysis_run',id=result['id'],file_id=file['id'],role='computed_results')
    response=post(client,root,dict(title='Synthetic fact chain',output_language='en',sources=[source],results_groups=[dict(id='main',title='Synthetic results',analysis_run_ids=[result['id']])]),'base')
    assert response.status_code==201,response.text
    first=response.json();root+='/'+first['id'];assert run_task(first['versions'][0]['task_id'],1)['status']=='succeeded'
    response=post(client,root+'/writing-previews',dict(schema_version=2,base_revision=1,mode='full_draft',output_language='en',selected_source_ids=[result['id']],selected_evidence_ids=[]),'preview')
    assert response.status_code==201,response.text
    bundle=response.json();_,auth=authorize(client,root,bundle)
    task=post(client,root+'/writing-requests',request_v2(bundle,auth),'write').json()['task'];budgets(client,task)
    values={key:str(result['overall'][key]) for key in ('n','mean')}
    class NumericFixture(LiveFixture):
        def receipt(self):
            value=super().receipt();output=json.loads(value['response']['output'][0]['content'][0]['text'])
            for section in output['sections']:
                if section['id'] in ('abstract','results'):
                    section['paragraphs'][0].update(text='n = '+values['n']+'; mean = '+values['mean'],source_aliases=['s1'],study_numeric_bindings=[dict(source_alias='s1',fact_path='/overall/'+k,value=v) for k,v in values.items()])
            value['response']['output'][0]['content'][0]['text']=json.dumps(output);return value
    assert run_manuscript_writing_task(task['id'],1,provider=NumericFixture())['status']=='succeeded'
    path=root+'/writing-requests/'+task['id'];ctx=client.get(path+'/review-context').json();body=decision(ctx)
    for p in body['paragraphs']:
        if p['paragraph_id'] in ('abstract:1','results:1'):
            p.update(classification='study_claim',numeric_bindings=[dict(occurrence=i,kind='study',value=v,source_alias='s1',fact_path='/overall/'+k) for i,(k,v) in enumerate(values.items())])
    response=post(client,path+'/reviews',body,'science');assert response.status_code==201,response.text
    science=response.json();url=path+'/reviews/'+science['id']+'/language-context'
    ctx=client.get(url).json()
    field=next(f for f in ctx['editable_fields'] if '/tables/0/rows/' in f['path'] and f['path'].endswith('/0'))
    edits=[dict(path=field['path'],original_sha256=field['original_sha256'],text=field['text']+' (reviewed label)',reason='Exact label translation; number and metric position unchanged.')]
    prep=dict(schema_version=2,review_id=science['id'],review_sha256=science['review_sha256'],edits=edits,figure_versions=[])
    response=post(client,url,prep,'language-preview');assert response.status_code==200,response.text
    language_body=approve(response.json());language_body['edits']=edits
    response=post(client,path+'/language-reviews',language_body,'language');assert response.status_code==201,response.text
    language=response.json()
    response=post(client,path+'/publish',dict(schema_version=2,expected_revision=1,review_id=science['id'],review_sha256=science['review_sha256'],language_review_id=language['id'],language_review_sha256=language['artifact_sha256']),'publish')
    assert response.status_code==201,response.text
    version=response.json()['versions'][0];assert run_task(version['task_id'],1)['status']=='succeeded'
    return root,version,science,language


def test_research_context_and_check_report_accept_v2_facts_but_require_v2_publication(client):
    root,version,science,language=published(client)
    response=client.get(root+'/reviews/context');assert response.status_code==200,response.text
    errors=[i for i in response.json()['issues'] if i['category']=='numeric' and i['severity']=='error']
    assert not errors,errors
    response=post(client,root+'/reviews',dict(base_revision=2),'material-review')
    assert response.status_code==201,response.text
    review=response.json();assert not review['report']['can_publish']
    assert not [i for i in review['report']['issues'] if i['category']=='numeric' and i['severity']=='error']
    assert any(i['id']=='workflow:v2_scientific_language_review' and i['severity']=='error' for i in review['report']['issues'])
    assert client.get(root+'/reviews/'+review['id']).json()==review
    assert post(client,root+'/reviews',dict(base_revision=2),'material-review').json()==review
    response=post(client,root+'/reviews/'+review['id']+'/publish',dict(expected_revision=2),'blocked-publish')
    assert response.status_code==409,response.text
    assert response.json()['detail']['code']=='manuscript_review_v2_workflow_required'
    assert client.get(root+'/versions/2').json()['snapshot']==language['candidate']
    from app.db.database import database_connection
    from app.maintenance.manuscript_review_audit import audit_manuscript_reviews
    with database_connection() as db:
        assert audit_manuscript_reviews(db)[0]['invalid']==0


def test_v2_old_review_edits_are_rejected_without_changing_any_approved_artifact(client):
    root,version,science,language=published(client)
    path=root+'/writing-requests/'+version['snapshot']['writing_provenance']['request_id']
    before=client.get(path).json()
    edits=[dict(corrections=[dict(paragraph_id='results:1',text='A newly invented conclusion.',source_ids=[],numeric_bindings=[])]),
        dict(metadata=[dict(target_id='results:1',field='unit',value='kg',evidence='New unit')]),
        dict(associations=[dict(id='new',research_question='New question',evidence='New relationship')]),
        dict(decisions=[dict(target_id='missing:ethics',status='supplied',value='New approval',reason='New material',evidence='New document')]),
        dict(selected_sources=[dict(kind='original',id='new',file_id='new',role='methods')])]
    for index,edit in enumerate(edits):
        response=post(client,root+'/reviews',dict(base_revision=2,**edit),'blocked-edit-'+str(index))
        assert response.status_code==422,response.text
        assert response.json()['detail']['code']=='manuscript_review_v2_workflow_required'
    assert client.get(root+'/reviews').json()['items']==[]
    assert client.get(path).json()==before
    assert client.get(path+'/reviews/'+science['id']).json()==science
    assert client.get(path+'/language-reviews/'+language['id']).json()==language
    assert client.get(root+'/versions/2').json()['snapshot']==version['snapshot']


def test_historical_v2_material_report_replays_its_original_rules_and_cannot_publish(client,monkeypatch):
    root,version,science,language=published(client)
    # Produce a pre-bridge immutable row under the old composition rules.
    with monkeypatch.context() as old:
        old.setattr('app.domain.manuscript_review.service.load_writing_context',lambda *args:None)
        response=post(client,root+'/reviews',dict(base_revision=2),'historical')
    assert response.status_code==201,response.text
    legacy=response.json()
    assert any(i['category']=='numeric' and i['severity']=='error' for i in legacy['report']['issues'])
    assert client.get(root+'/reviews/'+legacy['id']).json()==legacy
    assert post(client,root+'/reviews',dict(base_revision=2),'historical').json()==legacy
    response=post(client,root+'/reviews/'+legacy['id']+'/publish',dict(expected_revision=2),'historical-publish')
    assert response.status_code==409,response.text
    assert response.json()['detail']['code']=='manuscript_review_v2_workflow_required'


def test_v2_authority_loader_does_not_accept_a_tampered_frozen_source_or_binding(client):
    root,version,science,language=published(client)
    from app.adapters.storage import get_project_store
    from app.domain.manuscript_review.service import ReviewService
    from app.domain.manuscript_review.writing_context import load_writing_context
    from app.domain.manuscript_review.checks import check_snapshot
    from app.db.database import database_connection
    project=root.split('/')[4];identity=root.split('/')[-1]
    from app.adapters.storage import ProjectStore
    with database_connection() as db:
        owner=db.execute('SELECT owner_id FROM projects WHERE id=%s',(project,)).fetchone()['owner_id']
        service=ReviewService(ProjectStore(get_project_store().directory,owner_id=owner))
        authority=load_writing_context(service.manuscripts,db,project,identity,version['snapshot'])
    changed=deepcopy(version['snapshot']);changed['sections'][3]['paragraphs'][0]['numeric_bindings'][0]['fact_path']='/overall/mean'
    assert any(i['severity']=='error' for i in check_snapshot(changed,writing_context=authority))
    changed=deepcopy(version['snapshot']);changed['results_groups'][0]['tables'][0]['rows'][0][0]='Unauthorized new metric label'
    assert any(i['severity']=='error' and i['location'].startswith('table:') for i in check_snapshot(changed,writing_context=authority))
