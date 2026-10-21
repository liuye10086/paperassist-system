"""Synthetic manual decisions; isolated PostgreSQL, no external provider."""
from copy import deepcopy
import pytest
from tests.api.test_manuscript_writing_live import client, create_live, LiveFixture
from tests.api.test_literature_evidence import post
from app.domain.manuscript_writing.execution import run_manuscript_writing_task
from app.domain.literature.service import digest
from app.db.database import database_connection


def pending(client):
    root, bundle, _, _, task = create_live(client)
    assert run_manuscript_writing_task(task['id'], task['revision'], provider=LiveFixture())['status']=='succeeded'
    path=root+'/writing-requests/'+task['id']
    response=client.get(path+'/review-context')
    assert response.status_code==200,response.text
    return root,path,response.json()


def decision(context):
    return dict(schema_version=2,candidate_sha256=context['candidate_sha256'],
        paragraphs=[dict(paragraph_id=p['id'],text_sha256=digest(p['text']),classification='non_claim',
            scientific_basis='Explicit synthetic human judgment.',numeric_bindings=[]) for s in context['candidate']['sections'] if s['id']!='references' for p in s['paragraphs']],
        consistency=dict(body_sha256=context['body_sha256'],title=dict(subject=True,direction=True,strength=True,basis='Compared against body.'),
            abstract=dict(objective=True,methods=True,key_results=True,conclusion=True,basis='Compared against body.')))


def test_review_is_immutable_raw_stays_pending_and_language_fails_closed(client):
    root,path,ctx=pending(client);body=decision(ctx)
    response=post(client,path+'/reviews',body,'review')
    assert response.status_code==201,response.text
    review=response.json()
    assert review['candidate']['writing_provenance']['verification_status']=='scientific_reviewed_language_pending'
    assert client.get(path).json()['candidate']==ctx['candidate']
    assert client.get(path+'/reviews/'+review['id']).json()==review
    assert post(client,path+'/reviews',body,'review').json()==review
    result=post(client,path+'/publish',dict(schema_version=2,expected_revision=1,review_id=review['id'],review_sha256=review['review_sha256']),'publish')
    assert result.status_code==409,result.text
    assert result.json()['detail']['code']=='manuscript_writing_language_required'
    assert client.get(root).json()['current_revision']==1


@pytest.mark.parametrize('legacy',[False,True])
def test_candidate_notice_version_preserves_saved_raw_science_and_audit(client,monkeypatch,legacy):
    from app.domain.manuscript_writing import live_execution
    from app.domain.manuscript_writing.live_review import LiveReviewService
    from app.maintenance.database_audit import audit_database
    original=live_execution.compose_live_candidate
    if legacy:
        monkeypatch.setattr(live_execution,'compose_live_candidate',lambda *a,**k: original(*a,**{**k,'composition_version':1}))
    root,path,ctx=pending(client)
    monkeypatch.setattr(live_execution,'compose_live_candidate',original)
    raw=deepcopy(ctx['candidate'])
    response=post(client,path+'/reviews',decision(ctx),'notice-review')
    assert response.status_code==201,response.text
    review=response.json()
    if legacy:
        assert 'composition_version' not in raw['writing_provenance']
        assert review['candidate']['notice']==raw['notice']
        assert review['candidate']['issues']==raw['issues']
    else:
        assert raw['writing_provenance']['composition_version']==2
        assert 'Full manuscript candidate' in raw['notice']
        assert 'Scientific review pending' in raw['notice']
        assert 'Explicit human scientific review recorded' in review['candidate']['notice']
    assert client.get(path).json()['candidate']==raw
    assert client.get(path+'/reviews/'+review['id']).json()==review
    # Re-run the same server-owned validation used for publish, without publishing.
    with database_connection() as db:
        task=db.execute('SELECT * FROM tasks WHERE id=%s',(ctx['request_id'],)).fetchone()
        from app.domain.report_collections.service import scoped_store
        service=LiveReviewService(scoped_store(task['user_id']))
        saved=service.row(db,task['project_id'],root.rsplit('/',1)[1],task['id'],review['id'])
        service.assert_current(db,task['project_id'],root.rsplit('/',1)[1],task['id'],saved)
        audit=audit_database(db)
        assert audit['ok'],audit['schema_issues'] or [c for c in audit['data_checks'] if c['invalid']]


@pytest.mark.parametrize('mutation',['word','translation','coverage','title','abstract','body','number','old_claim'])
def test_review_rejects_inexact_incomplete_or_inherited_decisions(client,mutation):
    _,path,ctx=pending(client);body=decision(ctx)
    p=body['paragraphs'][2]
    if mutation=='word': p['corrected_text']='Synthetic candidate needs assessment.'
    if mutation=='translation': p['corrected_text']='合成候选需要人工审核。'
    if mutation=='coverage': body['paragraphs']=body['paragraphs'][:2]
    if mutation=='title': body['consistency']['title']['strength']=False
    if mutation=='abstract': del body['consistency']['abstract']['methods']
    if mutation=='body': body['consistency']['body_sha256']='0'*64
    if mutation=='number': p.update(corrected_text='There were 19 participants.',text_sha256=digest('There were 19 participants.'))
    if mutation=='old_claim': p.update(classification='literature_claim',claim=dict(claim_id='old',claim_revision=1,bindings=[dict(review_id='old',metadata_version_id='old')]))
    result=post(client,path+'/reviews',body,'bad')
    assert result.status_code in (404,409,422),result.text
    with database_connection() as db: assert db.execute('SELECT count(*) AS n FROM manuscript_writing_reviews').fetchone()['n']==0


def test_review_explicit_correction_requires_rebound_consistency_and_publish_sha(client,monkeypatch):
    root,path,ctx=pending(client);body=decision(ctx)
    p=body['paragraphs'][2];p.update(corrected_text='Human corrected introduction.',text_sha256=digest('Human corrected introduction.'))
    corrected=deepcopy(ctx['candidate'])
    corrected['sections'][2]['paragraphs'][0]['text']=p['corrected_text']
    from app.domain.manuscript_writing.live_review_candidate import body_digest
    body['consistency']['body_sha256']=body_digest(corrected)
    result=post(client,path+'/reviews',body,'corrected')
    assert result.status_code==201,result.text
    review=result.json()
    monkeypatch.setattr('app.domain.manuscript_writing.live_review.require_language_review',lambda *a,**k: None)
    payload=dict(schema_version=2,expected_revision=1,review_id=review['id'],review_sha256='0'*64)
    assert post(client,path+'/publish',payload,'publish').status_code==409
    payload['review_sha256']=review['review_sha256']
    published=post(client,path+'/publish',payload,'publish')
    assert published.status_code==201,published.text
    version=published.json()['versions'][0]
    assert version['snapshot']==review['candidate']
    from app.domain.tasks.execution import run_task
    assert run_task(version['task_id'],1)['status']=='succeeded'
    assert post(client,path+'/publish',payload,'publish').status_code==200
    assert client.get(path).json()['candidate']==ctx['candidate']
    export=post(client,root+'/versions/2/exports',{},'export')
    assert export.status_code==201,export.text
    assert run_task(export.json()['task_id'],1)['status']=='succeeded'
    assert client.get(root+'/versions/1').status_code==200
    from app.maintenance.database_audit import audit_database
    with database_connection() as db:
        audit=audit_database(db)
        assert audit['ok'],audit['schema_issues'] or [c for c in audit['data_checks'] if c['invalid']]
        assert any(c['table']=='manuscript_writing_reviews' for c in audit['data_checks'])


def literature_candidate(client,claim_context_override=None):
    from tests.api.test_literature_citations import seeded,binding
    from tests.api.test_manuscripts import body as manuscript_body
    from tests.api.test_manuscript_writing_live import authorize,request_v2
    from tests.integration.test_literature_assistance import budgets
    from app.domain.tasks.execution import run_task
    from app.domain.manuscript_writing.live_review_candidate import body_digest
    pid,lit,search,refs=seeded(client)
    root=f'/api/v1/projects/{pid}/manuscripts'
    base=post(client,root,manuscript_body(),'base').json();root+='/'+base['id']
    assert run_task(base['versions'][0]['task_id'],1)['status']=='succeeded'
    bundle=post(client,root+'/writing-previews',dict(schema_version=2,base_revision=1,mode='full_draft',output_language='en',selected_source_ids=[],selected_evidence_ids=[]),'preview').json()
    _,auth=authorize(client,root,bundle)
    task=post(client,root+'/writing-requests',request_v2(bundle,auth),'write').json()['task'];budgets(client,task)
    assert run_manuscript_writing_task(task['id'],1,provider=LiveFixture())['status']=='succeeded'
    path=root+'/writing-requests/'+task['id'];ctx=client.get(path+'/review-context').json();body=decision(ctx)
    text='Synthetic protocol fixture; this is not a research finding.'
    c=post(client,lit+'/evidence/claims',dict(content=text,context=claim_context_override or ctx['claim_contexts']['introduction:1'],output_language='en'),'new-claim').json()
    c,b,_,r=binding(client,lit,search,refs[0],c)
    body['paragraphs'][2].update(corrected_text=text,text_sha256=digest(text),classification='literature_claim',claim=dict(claim_id=c['id'],claim_revision=1,bindings=[b]))
    corrected=deepcopy(ctx['candidate']);corrected['sections'][2]['paragraphs'][0]['text']=text
    body['consistency']['body_sha256']=body_digest(corrected)
    return root,path,ctx,body,lit,c,r


def test_new_exact_claim_rebuilds_citations_and_later_negative_review_blocks_publish(client,monkeypatch):
    root,path,ctx,body,lit,c,r=literature_candidate(client)
    result=post(client,path+'/reviews',body,'review');assert result.status_code==201,result.text
    review=result.json();assert len(review['candidate']['references'])==1
    assert review['candidate']['sections'][2]['paragraphs'][0]['text'].endswith('(1)')
    negative={k:r[k] for k in ('claim_revision','project_reference_id','evidence_ids','relevance','reason','narrowed_statement','limitations')}
    negative['status']='unsupported'
    assert post(client,lit+'/evidence/claims/'+c['id']+'/reviews',negative,'negative').status_code==201
    monkeypatch.setattr('app.domain.manuscript_writing.live_review.require_language_review',lambda *a,**k:None)
    result=post(client,path+'/publish',dict(schema_version=2,expected_revision=1,review_id=review['id'],review_sha256=review['review_sha256']),'publish')
    assert result.status_code==409,result.text
    assert client.get(path+'/reviews/'+review['id']).json()==review
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM manuscript_versions').fetchone()['n']==1


@pytest.mark.parametrize('drift',['word','translation','old_context'])
def test_existing_supported_claim_cannot_certify_changed_or_unbound_new_paragraph(client,drift):
    _,path,ctx,body,lit,c,r=literature_candidate(client,'legacy context' if drift=='old_context' else None)
    from app.domain.manuscript_writing.live_review_candidate import body_digest
    if drift!='old_context':
        text='Translated synthetic statement.' if drift=='translation' else c['content'].replace('protocol','research')
        body['paragraphs'][2].update(corrected_text=text,text_sha256=digest(text))
        corrected=deepcopy(ctx['candidate']);corrected['sections'][2]['paragraphs'][0]['text']=text
        body['consistency']['body_sha256']=body_digest(corrected)
    result=post(client,path+'/reviews',body,'invalid')
    assert result.status_code in (409,422),result.text


def test_literature_review_publish_persists_exact_relations_and_immutable_artifact(client,monkeypatch):
    root,path,ctx,body,lit,c,r=literature_candidate(client)
    result=post(client,path+'/reviews',body,'review');assert result.status_code==201,result.text
    review=result.json()
    for sql in ('UPDATE manuscript_writing_reviews SET review_sha256=review_sha256','DELETE FROM manuscript_writing_reviews'):
        with pytest.raises(Exception):
            with database_connection(write=True) as db: db.execute(sql)
    monkeypatch.setattr('app.domain.manuscript_writing.live_review.require_language_review',lambda *a,**k:None)
    result=post(client,path+'/publish',dict(schema_version=2,expected_revision=1,review_id=review['id'],review_sha256=review['review_sha256']),'publish')
    assert result.status_code==201,result.text
    version=result.json()['versions'][0]
    from app.domain.tasks.execution import run_task
    assert run_task(version['task_id'],1)['status']=='succeeded'
    with database_connection() as db:
        rows=db.execute('SELECT * FROM manuscript_citations WHERE version_id=%s',(version['id'],)).fetchall()
        assert len(rows)==1 and rows[0]['claim_id']==c['id'] and rows[0]['review_id']==r['id']
        from app.maintenance.database_audit import audit_database
        audit=audit_database(db)
        assert audit['ok'],audit['schema_issues'] or [c for c in audit['data_checks'] if c['invalid']]


def test_new_metadata_after_review_blocks_publication_and_old_artifact_remains_readable(client,monkeypatch):
    _,path,ctx,body,lit,c,r=literature_candidate(client)
    result=post(client,path+'/reviews',body,'review');assert result.status_code==201,result.text
    review=result.json();binding=review['candidate']['citation_snapshot']['paragraphs'][0]['fragments'][0]['bindings'][0]
    response=post(client,lit+'/citations/references/'+r['project_reference_id']+'/metadata',
        dict(expected_revision=1,mode='extract',search_id=binding['metadata_source']['source']['search_id']),'new-metadata')
    assert response.status_code==201,response.text
    monkeypatch.setattr('app.domain.manuscript_writing.live_review.require_language_review',lambda *a,**k:None)
    result=post(client,path+'/publish',dict(schema_version=2,expected_revision=1,review_id=review['id'],review_sha256=review['review_sha256']),'publish')
    assert result.status_code==409,result.text
    assert client.get(path+'/reviews/'+review['id']).json()==review
    assert post(client,path+'/reviews',body,'stale-review').status_code==409


def test_raw_or_review_sha_cannot_be_replaced_after_scientific_review(client,monkeypatch):
    _,path,ctx=pending(client);review=post(client,path+'/reviews',decision(ctx),'review').json()
    monkeypatch.setattr('app.domain.manuscript_writing.live_review.require_language_review',lambda *a,**k:None)
    changed=deepcopy(ctx['candidate']);changed['sections'][2]['paragraphs'][0]['text']+=' Tampered.'
    from psycopg.types.json import Jsonb
    with database_connection(write=True) as db:
        db.execute('UPDATE manuscript_writing_requests SET candidate_json=%s,candidate_sha256=%s WHERE task_id=%s',(Jsonb(changed),digest(changed),ctx['request_id']))
    result=post(client,path+'/publish',dict(schema_version=2,expected_revision=1,review_id=review['id'],review_sha256=review['review_sha256']),'publish')
    assert result.status_code==409,result.text


def test_review_rewrite_keeps_non_target_sections_and_citation_table_exact(client,monkeypatch):
    from tests.api.test_manuscript_writing_live import authorize,request_v2
    from tests.integration.test_literature_assistance import budgets
    from app.domain.tasks.execution import run_task
    import json
    root,path,ctx,body,lit,c,r=literature_candidate(client)
    first=post(client,path+'/reviews',body,'review').json()
    monkeypatch.setattr('app.domain.manuscript_writing.live_review.require_language_review',lambda *a,**k:None)
    result=post(client,path+'/publish',dict(schema_version=2,expected_revision=1,review_id=first['id'],review_sha256=first['review_sha256']),'publish')
    assert result.status_code==201,result.text
    assert run_task(result.json()['versions'][0]['task_id'],1)['status']=='succeeded'
    bundle=post(client,root+'/writing-previews',dict(schema_version=2,base_revision=2,mode='rewrite_section',target_section='discussion',output_language='en',selected_source_ids=[],selected_evidence_ids=[]),'rewrite-preview')
    assert bundle.status_code==201,bundle.text
    bundle=bundle.json()
    tasks=[dict(logical_task_id='task-'+str(i),bundles=[dict(bundle_id=bundle['id'],bundle_sha256=bundle['bundle_sha256'])]) for i in range(4)]
    auth=post(client,root.split('/manuscripts/')[0]+'/writing-authorizations',dict(schema_version=2,confirmed=True,tasks=tasks),'rewrite-auth').json()
    task=post(client,root+'/writing-requests',request_v2(bundle,auth),'rewrite').json()['task']
    from app.domain.model_usage.service import ModelUsageService
    from tests.helpers.tasks import task_owner
    ModelUsageService(task_owner(client)).set_budget('task',task['id'],5000000,0)
    provider=LiveFixture();original=provider.receipt
    def receipt():
        value=original();output=json.loads(value['response']['output'][0]['content'][0]['text']);output['sections']=[output['sections'][4]]
        output['sections'][0]['paragraphs'][0]['text']='Explicitly revised discussion.'
        value['response']['output'][0]['content'][0]['text']=json.dumps(output);return value
    provider.receipt=receipt
    assert run_manuscript_writing_task(task['id'],1,provider=provider)['status']=='succeeded'
    path=root+'/writing-requests/'+task['id'];ctx=client.get(path+'/review-context').json();body=decision(ctx)
    body['paragraphs']=[p for p in body['paragraphs'] if p['paragraph_id'] in ctx['required_paragraph_ids']]
    result=post(client,path+'/reviews',body,'rewrite-review');assert result.status_code==201,result.text
    second=result.json()
    assert all(s==first['candidate']['sections'][i] for i,s in enumerate(second['candidate']['sections']) if s['id']!='discussion')
    assert second['candidate']['references']==first['candidate']['references']
