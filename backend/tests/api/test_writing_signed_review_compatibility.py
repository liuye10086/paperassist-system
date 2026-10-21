"""Isolated historical-writer fixtures; real API/immutable rows, no live provider."""
from contextlib import contextmanager
from copy import deepcopy
import pytest
from tests.api.test_manuscript_writing_live_review import client,decision,literature_candidate
from tests.api.test_literature_evidence import post
from tests.api.test_manuscript_writing_language import approve
from app.domain.literature.service import digest
from app.domain.manuscript_writing.live_review_candidate import body_digest
from app.db.database import database_connection


@contextmanager
def historical_writer(monkeypatch,*,science=True):
    from app.domain.manuscript_writing import live_review,language_service
    with monkeypatch.context() as patch:
        if science:
            for name in ('prepare','finish'):
                original=getattr(live_review,name)
                patch.setattr(live_review,name,lambda *a,_fn=original,**kw:_fn(*a,**(kw|{'numeric_version':1})))
        original=language_service.prepare_candidate
        patch.setattr(language_service,'prepare_candidate',lambda *a,**kw:original(*a,**(kw|{'numeric_version':1})))
        def finish(candidate,identity,science_sha,**kw):
            candidate['writing_provenance'].update(language_review_id=identity,scientific_review_sha256=science_sha,verification_status='scientific_and_language_reviewed')
        patch.setattr(language_service.LanguageReviewService,'finish',staticmethod(finish))
        yield


def signed_literature(client,monkeypatch,display='−12',bound='12',quote='12'):
    from tests.api.test_literature_citations import CitationNcbi
    from app.adapters.ncbi import parse_fetch
    original=CitationNcbi.fetch
    with monkeypatch.context() as patch:
        def fetch(self,pmids):
            result=original(self,pmids)
            return parse_fetch(result.raw.replace(b'Synthetic protocol fixture; this is not a research finding.',('Observed value '+quote+'.').encode()),pmids)
        patch.setattr(CitationNcbi,'fetch',fetch)
        root,path,ctx,body,lit,_,review=literature_candidate(client)
    text='Observed value '+display+'.'
    claim=post(client,lit+'/evidence/claims',dict(content=text,context=ctx['claim_contexts']['introduction:1'],output_language='en'),'signed-claim').json()
    # Reuse the actual saved metadata identity, but create a new exact claim and
    # evidence/support decision for this paragraph; no inherited claim approval.
    metadata_id=body['paragraphs'][2]['claim']['bindings'][0]['metadata_version_id']
    with database_connection() as db:
        ev=db.execute('SELECT * FROM literature_claim_evidence WHERE id=%s',(review['evidence_ids'][0],)).fetchone()
    evidence=post(client,lit+'/evidence/claims/'+claim['id']+'/evidence',dict(claim_revision=1,project_reference_id=review['project_reference_id'],source_kind='abstract',search_id=ev['request_json']['search_id'],quote='Observed value '+quote+'.'),'signed-evidence')
    assert evidence.status_code==201,evidence.text
    support=post(client,lit+'/evidence/claims/'+claim['id']+'/reviews',dict(claim_revision=1,project_reference_id=review['project_reference_id'],evidence_ids=[evidence.json()['id']],status='supported',relevance='related',reason='Synthetic explicit support',narrowed_statement='',limitations='Synthetic abstract'),'signed-support')
    assert support.status_code==201,support.text
    body['paragraphs'][2].update(corrected_text=text,text_sha256=digest(text),classification='literature_claim',claim=dict(claim_id=claim['id'],claim_revision=1,bindings=[dict(review_id=support.json()['id'],metadata_version_id=metadata_id)]),numeric_bindings=[dict(occurrence=0,value=bound,kind='literature',evidence_id=evidence.json()['id'])])
    corrected=deepcopy(ctx['candidate']);corrected['sections'][2]['paragraphs'][0]['text']=text
    body['consistency']['body_sha256']=body_digest(corrected)
    return root,path,ctx,body


def language_body(client,path,science):
    response=client.get(path+'/reviews/'+science['id']+'/language-context')
    assert response.status_code==200,response.text
    return explicit_language(response.json())


def explicit_language(context):
    body=approve(context)
    for item,decision in zip(context['inventory'],body['decisions']):
        if item['kind']=='image' and item['no_text']:decision['decision']='no_text'
    return body


def publication(science,language):
    return dict(schema_version=2,expected_revision=1,review_id=science['id'],review_sha256=science['review_sha256'],language_review_id=language['id'],language_review_sha256=language['artifact_sha256'])


def test_new_science_wrong_sign_is_rejected_before_artifact_insert(client,monkeypatch):
    _,path,_,body=signed_literature(client,monkeypatch)
    response=post(client,path+'/reviews',body,'new-invalid')
    assert response.status_code==422,response.text
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM manuscript_writing_reviews').fetchone()['n']==0
    assert post(client,path+'/reviews',body|{'numeric_validation_version':1},'client-policy').status_code==422


@pytest.mark.parametrize('unsafe,published',[(False,False),(True,False),(True,True)])
def test_old_science_reads_replays_and_only_safe_history_gets_new_approval(client,monkeypatch,unsafe,published):
    root,path,ctx,body=signed_literature(client,monkeypatch,'−12' if unsafe else '12')
    with historical_writer(monkeypatch):
        response=post(client,path+'/reviews',body,'old-science');assert response.status_code==201,response.text
        science=response.json();assert 'numeric_validation_version' not in science['report']
        lbody=language_body(client,path,science)
        response=post(client,path+'/language-reviews',lbody,'old-language');assert response.status_code==201,response.text
        language=response.json();payload=publication(science,language)
        if published:
            response=post(client,path+'/publish',payload,'old-publish');assert response.status_code==201,response.text
            saved=response.json()['versions'][0]['snapshot']
    assert client.get(path+'/reviews/'+science['id']).json()==science
    assert client.get(path+'/language-reviews/'+language['id']).json()==language
    assert post(client,path+'/reviews',body,'old-science').json()==science
    assert post(client,path+'/language-reviews',lbody,'old-language').json()==language
    if published:
        response=post(client,path+'/publish',payload,'old-publish');assert response.status_code==200,response.text
        assert client.get(root+'/versions/2').json()['snapshot']==saved
    else:
        response=post(client,path+'/language-reviews',lbody,'new-language')
        assert response.status_code==(422 if unsafe else 201),response.text
        if not unsafe:assert response.json()['candidate']['writing_provenance']['language_numeric_validation_version']==2
        response=post(client,path+'/publish',payload,'new-publish')
        assert response.status_code==(422 if unsafe else 201),response.text
        if unsafe:
            assert post(client,path+'/reviews',body,'new-science').status_code==422
            with database_connection() as db:
                assert db.execute('SELECT count(*) AS n FROM manuscript_writing_reviews').fetchone()['n']==1
                assert db.execute('SELECT count(*) AS n FROM manuscript_writing_language_reviews').fetchone()['n']==1


def image_science(client):
    from tests.api.test_manuscript_figure_language import setup
    from tests.api.test_manuscript_writing_live import authorize,request_v2,LiveFixture
    from tests.integration.test_literature_assistance import budgets
    from app.domain.tasks.execution import run_task
    from app.domain.manuscript_writing.execution import run_manuscript_writing_task
    project,file,figpath,request=setup(client);request['caption']='Temperature −5 C'
    response=post(client,figpath,request,'frozen-image');assert response.status_code==201,response.text
    figure=response.json();root=f'/api/v1/projects/{project}/manuscripts'
    response=post(client,root,dict(title='Signed caption study',output_language='en',sources=[dict(kind='figure_language_version',id=figure['id'],file_id=file['id'],role='image_observation')]),'fact')
    assert response.status_code==201,response.text
    manuscript=response.json();root+='/'+manuscript['id'];assert run_task(manuscript['versions'][0]['task_id'],1)['status']=='succeeded'
    bundle=post(client,root+'/writing-previews',dict(schema_version=2,base_revision=1,mode='full_draft',output_language='en',selected_source_ids=[figure['id']],selected_evidence_ids=[]),'bundle').json()
    _,auth=authorize(client,root,bundle);task=post(client,root+'/writing-requests',request_v2(bundle,auth),'write').json()['task'];budgets(client,task)
    assert run_manuscript_writing_task(task['id'],1,provider=LiveFixture())['status']=='succeeded'
    path=root+'/writing-requests/'+task['id'];ctx=client.get(path+'/review-context').json()
    science=post(client,path+'/reviews',decision(ctx),'science').json()
    return root,path,science


def test_old_language_sign_change_remains_readable_but_cannot_be_newly_published(client,monkeypatch):
    root,path,science=image_science(client)
    endpoint=path+'/reviews/'+science['id']+'/language-context'
    prep=dict(schema_version=2,review_id=science['id'],review_sha256=science['review_sha256'],edits=[dict(path='/results_groups/0/figures/0/caption',original_sha256=digest('Temperature −5 C'),text='Temperature 5 C',reason='Historical unsafe edit')],figure_versions=[])
    with historical_writer(monkeypatch,science=False):
        response=post(client,endpoint,prep,'old-preview');assert response.status_code==200,response.text
        lbody=explicit_language(response.json())|prep
        response=post(client,path+'/language-reviews',lbody,'old-language');assert response.status_code==201,response.text
        old=response.json()
    assert client.get(path+'/language-reviews/'+old['id']).json()==old
    assert post(client,path+'/language-reviews',lbody,'old-language').json()==old
    assert post(client,path+'/language-reviews',lbody,'new-language').status_code==422
    response=post(client,path+'/publish',publication(science,old),'new-publish')
    assert response.status_code in (409,422),response.text
    assert client.get(root).json()['current_revision']==1
    with database_connection() as db:assert db.execute('SELECT count(*) AS n FROM manuscript_writing_language_reviews').fetchone()['n']==1
    with historical_writer(monkeypatch,science=False):
        response=post(client,path+'/publish',publication(science,old),'historical-publish');assert response.status_code==201,response.text
    from app.domain.tasks.execution import run_task
    assert run_task(response.json()['versions'][0]['task_id'],1)['status']=='succeeded'
    rewrite,rewrite_body=rewrite_pending(client,root)
    response=post(client,rewrite+'/reviews',rewrite_body,'reject-inherited-language')
    assert response.status_code in (409,422),response.text


def test_correct_negative_science_publishes_and_existing_checker_accepts_it(client,monkeypatch):
    root,path,_,body=signed_literature(client,monkeypatch,'− 12','-12','−12')
    response=post(client,path+'/reviews',body,'signed-science');assert response.status_code==201,response.text
    science=response.json();assert science['report']['numeric_validation_version']==2
    response=post(client,path+'/language-reviews',language_body(client,path,science),'signed-language');assert response.status_code==201,response.text
    language=response.json()
    response=post(client,path+'/publish',publication(science,language),'signed-publish');assert response.status_code==201,response.text
    from app.domain.tasks.execution import run_task
    assert run_task(response.json()['versions'][0]['task_id'],1)['status']=='succeeded'
    response=client.get(root+'/reviews/context');assert response.status_code==200,response.text
    assert not [i for i in response.json()['issues'] if i['category']=='numeric' and i['severity']=='error'],response.json()['issues']
    # Reconstruct a pre-sign-bridge checker report exactly, then create a new one.
    from app.domain.manuscript_review import service
    original=service.load_writing_context
    with monkeypatch.context() as patch:
        patch.setattr(service,'load_writing_context',lambda *a,**kw:original(*a,**(kw|{'check_version':1})))
        response=post(client,root+'/reviews',dict(base_revision=2),'old-check')
    assert response.status_code==201,response.text
    old=response.json()
    assert client.get(root+'/reviews/'+old['id']).json()==old
    response=post(client,root+'/reviews',dict(base_revision=2),'new-check');assert response.status_code==201,response.text
    assert not [i for i in response.json()['report']['issues'] if i['category']=='numeric' and i['severity']=='error']


def rewrite_pending(client,root):
    import json
    from tests.api.test_manuscript_writing_live import request_v2,LiveFixture
    from app.domain.manuscript_writing.execution import run_manuscript_writing_task
    from app.domain.model_usage.service import ModelUsageService
    from tests.helpers.tasks import task_owner
    response=post(client,root+'/writing-previews',dict(schema_version=2,base_revision=2,mode='rewrite_section',target_section='discussion',output_language='en',selected_source_ids=[],selected_evidence_ids=[]),'rewrite-preview')
    assert response.status_code==201,response.text
    bundle=response.json();tasks=[dict(logical_task_id='rewrite-'+str(i),bundles=[dict(bundle_id=bundle['id'],bundle_sha256=bundle['bundle_sha256'])]) for i in range(4)]
    auth=post(client,root.split('/manuscripts/')[0]+'/writing-authorizations',dict(schema_version=2,confirmed=True,tasks=tasks),'rewrite-authorize').json()
    request=request_v2(bundle,auth);request['logical_task_id']='rewrite-0'
    response=post(client,root+'/writing-requests',request,'rewrite-request');assert response.status_code==202,response.text
    task=response.json()['task'];ModelUsageService(task_owner(client)).set_budget('task',task['id'],5000000,0)
    class RewriteFixture(LiveFixture):
        def receipt(self):
            value=super().receipt();output=json.loads(value['response']['output'][0]['content'][0]['text'])
            output['sections']=[output['sections'][4]];value['response']['output'][0]['content'][0]['text']=json.dumps(output)
            return value
    assert run_manuscript_writing_task(task['id'],1,provider=RewriteFixture())['status']=='succeeded'
    path=root+'/writing-requests/'+task['id'];ctx=client.get(path+'/review-context').json();body=decision(ctx)
    body['paragraphs']=[p for p in body['paragraphs'] if p['paragraph_id'] in ctx['required_paragraph_ids']]
    return path,body


@pytest.mark.parametrize('unsafe',[False,True])
def test_rewrite_approval_revalidates_inherited_science_without_revoking_safe_history(client,monkeypatch,unsafe):
    root,path,_,body=signed_literature(client,monkeypatch,'−12' if unsafe else '12')
    from app.domain.tasks.execution import run_task
    with historical_writer(monkeypatch):
        science=post(client,path+'/reviews',body,'old-science').json()
        response=post(client,path+'/language-reviews',language_body(client,path,science),'old-language');assert response.status_code==201,response.text
        language=response.json()
        response=post(client,path+'/publish',publication(science,language),'old-publish');assert response.status_code==201,response.text
        assert run_task(response.json()['versions'][0]['task_id'],1)['status']=='succeeded'
    rewrite,rewrite_body=rewrite_pending(client,root)
    response=post(client,rewrite+'/reviews',rewrite_body,'rewrite-science')
    if unsafe:
        assert response.status_code in (409,422),response.text
        with database_connection() as db:assert db.execute('SELECT count(*) AS n FROM manuscript_writing_reviews WHERE request_id=%s',(rewrite.rsplit('/',1)[1],)).fetchone()['n']==0
    else:assert response.status_code==201,response.text
    assert client.get(path+'/reviews/'+science['id']).json()==science
