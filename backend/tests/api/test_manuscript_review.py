"""Local material reviews are immutable candidates and never scientific approvals."""
import copy
import pytest
from tests.api.test_manuscripts import client, setup, body
from tests.api.test_literature_evidence import post
from app.domain.tasks.execution import run_task
from app.db.database import database_connection


def ready(client, **changes):
    path, _, file = setup(client)
    root = post(client, path, body(**changes), 'base').json()
    assert run_task(root['versions'][0]['task_id'], 1)['status'] == 'succeeded'
    return path, root, path+'/'+root['id']+'/reviews', file


def decision(**changes):
    return dict(target_id='missing:ethics', status='supplied', value='Approved protocol', reason='Checked record', evidence='Signed laboratory protocol') | changes


def test_candidate_freezes_confirmation_and_publishes_explicitly(client):
    path, base, endpoint, _ = ready(client)
    old = copy.deepcopy(base['versions'][0]['snapshot'])
    context = client.get(endpoint+'/context?revision=1')
    assert context.status_code == 200, context.text
    request = dict(base_revision=1, decisions=[decision()])
    response = post(client, endpoint, request, 'review')
    assert response.status_code == 201, response.text
    review = response.json()
    assert review['status'] == 'candidate' and review['published_revision'] is None
    assert review['report']['scientifically_verified'] is False
    assert review['candidate']['sources'] == old['sources']
    assert review['candidate']['review']['decisions'][0]['created_by']
    assert client.get(path+'/'+base['id']).json()['current_revision'] == 1
    assert post(client, endpoint, request, 'review').json() == review
    assert post(client, endpoint, request | dict(decisions=[]), 'review').status_code == 409
    result = post(client, endpoint+'/'+review['id']+'/publish', dict(expected_revision=1), 'publish')
    assert result.status_code == 201, result.text
    root = result.json()
    assert root['versions'][1]['snapshot'] == old
    assert root['versions'][0]['snapshot'] == review['candidate']
    assert run_task(root['versions'][0]['task_id'], 1)['status'] == 'succeeded'
    assert post(client, endpoint+'/'+review['id']+'/publish', dict(expected_revision=1), 'publish').status_code == 200
    assert post(client, endpoint+'/'+review['id']+'/publish', dict(expected_revision=2), 'publish').status_code == 409
    export = post(client, path+'/'+base['id']+'/versions/2/exports', {}, 'export').json()
    assert run_task(export['task_id'], 1)['status'] == 'succeeded'
    download = client.get(path+'/'+base['id']+'/exports/'+export['id']+'/download')
    assert download.status_code == 200
    from io import BytesIO
    from docx import Document
    text = '\n'.join(p.text for p in Document(BytesIO(download.content)).paragraphs)
    assert 'Approved protocol' in text and 'not scientific verification' in text
    with database_connection() as db:
        from app.maintenance.database_audit import audit_database
        audit = audit_database(db)
        assert audit['ok'], audit['schema_issues'] or [c for c in audit['data_checks'] if c['invalid']]


def test_fresh_export_key_keeps_prior_review_export_and_snapshot(client):
    from app.adapters.manuscript_docx import RENDERER_VERSION
    path, base, endpoint, _ = ready(client)
    review = post(client, endpoint, dict(base_revision=1), 'review').json()
    published = post(client, endpoint+'/'+review['id']+'/publish',
                     dict(expected_revision=1), 'publish').json()
    version = published['versions'][0]
    assert run_task(version['task_id'], 1)['status'] == 'succeeded'
    exports = path+'/'+base['id']+'/versions/2/exports'
    old = post(client, exports, {}, 'old-export').json()
    assert run_task(old['task_id'], 1)['status'] == 'succeeded'
    old_url = path+'/'+base['id']+'/exports/'+old['id']+'/download'
    old_content = client.get(old_url).content
    with database_connection() as db:
        old_metadata = db.execute('SELECT metadata_json FROM manuscript_exports WHERE id=%s',
                                  (old['id'],)).fetchone()['metadata_json']
    fresh_response = post(client, exports, {}, 'fresh-render-v5')
    assert fresh_response.status_code == 201, fresh_response.text
    fresh = fresh_response.json()
    assert fresh['id'] != old['id'] and fresh['task_id'] != old['task_id']
    assert run_task(fresh['task_id'], 1)['status'] == 'succeeded'
    replay = post(client, exports, {}, 'old-export')
    assert replay.status_code == 200 and replay.json()['id'] == old['id']
    assert client.get(old_url).content == old_content
    current = client.get(path+'/'+base['id']+'/versions/2').json()
    assert current['snapshot'] == version['snapshot']
    assert len(client.get(exports).json()['items']) == 2
    with database_connection() as db:
        saved = db.execute('SELECT metadata_json FROM manuscript_exports WHERE id=%s',
                           (old['id'],)).fetchone()['metadata_json']
        metadata = db.execute('SELECT metadata_json FROM manuscript_exports WHERE id=%s',
                              (fresh['id'],)).fetchone()['metadata_json']
    assert saved == old_metadata
    assert metadata['renderer_version'] == RENDERER_VERSION == 'manuscript_docx_v5'
    fresh_url = path+'/'+base['id']+'/exports/'+fresh['id']+'/download'
    assert client.get(fresh_url).status_code == 200


def test_stale_base_and_changed_source_after_review_block_publication(client):
    path, base, endpoint, file = ready(client)
    review = post(client, endpoint, dict(base_revision=1), 'r').json()
    post(client, path+'/'+base['id']+'/versions', body(expected_revision=1), 'new')
    assert post(client, endpoint+'/'+review['id']+'/publish', dict(expected_revision=1), 'p').status_code == 409
    assert post(client, endpoint, dict(base_revision=1), 'stale').status_code == 409


def test_source_drift_after_review_and_explicit_refresh_is_persisted(client):
    path, _, file = setup(client)
    source = dict(kind='original', id=file['id'], file_id=file['id'], role='methods')
    base = post(client, path, body(sources=[source]), 'b').json()
    run_task(base['versions'][0]['task_id'], 1)
    endpoint = path+'/'+base['id']+'/reviews'
    first = post(client, endpoint, dict(base_revision=1), 'r').json()
    with database_connection(write=True) as db:
        db.execute('UPDATE files SET sha256=%s WHERE id=%s', ('a'*64, file['id']))
    assert post(client, endpoint+'/'+first['id']+'/publish', dict(expected_revision=1), 'p').status_code == 409
    refreshed = post(client, endpoint, dict(base_revision=1), 'refresh')
    assert refreshed.status_code == 201, refreshed.text
    assert refreshed.json()['report']['source_changes']
    assert refreshed.json()['report']['impacts'][0]['pending_review'] is True
    assert refreshed.json()['report']['can_publish'] is False
    assert refreshed.json()['candidate']['sources'] == base['versions'][0]['snapshot']['sources']


def test_pending_na_and_evidence_cannot_waive_number_or_reference_guards(client):
    _, _, endpoint, _ = ready(client)
    request = dict(base_revision=1, decisions=[decision(status='not_applicable', value='', evidence='')], corrections=[dict(paragraph_id='methods:study_design', text='Mean 27.57; Figure 999.', source_ids=[], numeric_bindings=[])])
    response = post(client, endpoint, request, 'bad')
    assert response.status_code == 201, response.text
    review = response.json()
    assert not review['report']['can_publish']
    assert {'numeric','illustration'} <= {i['category'] for i in review['report']['issues'] if i['severity']=='error'}
    assert any(i['id']=='material:missing:ethics' for i in review['report']['issues'])
    assert post(client, endpoint+'/'+review['id']+'/publish', dict(expected_revision=1), 'p').status_code == 409
    assert post(client, endpoint, dict(base_revision=1, decisions=[decision(evidence='')]), 'empty').status_code == 422


def test_other_owner_cannot_read_context_candidates_history_or_publish(client):
    from tests.integration.test_project_ownership import account_client
    _, _, endpoint, _ = ready(client)
    review = post(client, endpoint, dict(base_revision=1), 'r').json()
    with account_client('review-other@example.test')[0] as other:
        for suffix in ('', '/context', '/'+review['id']):
            assert other.get(endpoint+suffix).status_code == 404
        assert post(other, endpoint, dict(base_revision=1), 'r').status_code == 404
        assert post(other, endpoint+'/'+review['id']+'/publish', dict(expected_revision=1), 'p').status_code == 404


def test_complete_writing_lineage_survives_review_and_docx(client):
    from tests.api.test_manuscript_writing import candidate_ready
    path, base, writing, view, candidate = candidate_ready(client)
    full = post(client, writing+'/'+view['id']+'/publish', dict(expected_revision=1), 'full').json()
    run_task(full['versions'][0]['task_id'], 1)
    endpoint = path+'/'+base['id']+'/reviews'
    review = post(client, endpoint, dict(base_revision=2, decisions=[decision()]), 'r')
    assert review.status_code == 201, review.text
    review = review.json()
    assert review['candidate']['writing_provenance'] == candidate['writing_provenance']
    assert review['candidate']['sections'][3] == candidate['sections'][3]
    published = post(client, endpoint+'/'+review['id']+'/publish', dict(expected_revision=2), 'p')
    assert published.status_code == 201, published.text
    assert run_task(published.json()['versions'][0]['task_id'], 1)['status'] == 'succeeded'
    export = post(client, path+'/'+base['id']+'/versions/3/exports', {}, 'e').json()
    assert run_task(export['task_id'], 1)['status'] == 'succeeded'


@pytest.mark.parametrize('column,value', [('candidate_sha256','a'*64),('input_digest','b'*64),('rules_version','corrupt'),('report_sha256','c'*64)])
def test_review_audit_detects_frozen_corruption(client,column,value):
    from app.maintenance.manuscript_review_audit import audit_manuscript_reviews
    _, _, endpoint, _ = ready(client)
    review = post(client, endpoint, dict(base_revision=1), 'r').json()
    with database_connection() as db:
        assert all(c['invalid']==0 for c in audit_manuscript_reviews(db))
    with database_connection(write=True) as db:
        db.execute('UPDATE manuscript_reviews SET '+column+'=%s WHERE id=%s',(value,review['id']))
    assert client.get(endpoint+'/'+review['id']).status_code == 409
    with database_connection() as db:
        assert any(c['invalid'] for c in audit_manuscript_reviews(db))

def test_explicit_new_material_preserves_old_complete_prose_and_source_bindings(client):
    from tests.api.test_manuscript_writing import candidate_ready
    path,base,writing,view,candidate=candidate_ready(client)
    full=post(client,writing+'/'+view['id']+'/publish',dict(expected_revision=1),'full').json()
    run_task(full['versions'][0]['task_id'],1)
    available=client.get(path+'/candidates').json()['items']
    selected=next(i for i in available if i['kind']=='original')
    endpoint=path+'/'+base['id']+'/reviews'
    review=post(client,endpoint,dict(base_revision=2,selected_sources=[{k:selected[k] for k in ('id','kind','file_id')}|dict(role='methods')]),'new-material')
    assert review.status_code==201,review.text
    review=review.json();output=review['candidate']
    assert output['sections']==candidate['sections']
    assert output['sources']==candidate['sources']
    assert output['review']['selected_sources'][0]['id']==selected['id']
    assert output['review']['addendum'][0]['pending_impact']
    assert post(client,endpoint+'/'+review['id']+'/publish',dict(expected_revision=2),'p').status_code==201


def test_same_current_base_concurrent_publication_only_one_wins(client):
    _,_,endpoint,_=ready(client)
    a=post(client,endpoint,dict(base_revision=1),'a').json()
    b=post(client,endpoint,dict(base_revision=1,decisions=[decision(status='pending',value='',evidence='')]),'b').json()
    assert post(client,endpoint+'/'+a['id']+'/publish',dict(expected_revision=1),'pa').status_code==201
    assert post(client,endpoint+'/'+b['id']+'/publish',dict(expected_revision=1),'pb').status_code==409


def test_completed_review_base_and_published_version_corruption_is_audited(client):
    from app.maintenance.manuscript_review_audit import audit_manuscript_reviews
    path,base,endpoint,_=ready(client)
    review=post(client,endpoint,dict(base_revision=1),'r').json()
    root=post(client,endpoint+'/'+review['id']+'/publish',dict(expected_revision=1),'p').json()
    with database_connection(write=True) as db:
        db.execute('UPDATE manuscript_reviews SET base_version_id=%s WHERE id=%s',(root['versions'][0]['id'],review['id']))
    assert client.get(endpoint+'/'+review['id']).status_code==409
    with database_connection() as db: assert audit_manuscript_reviews(db)[0]['invalid']==1


def test_review_continuation_keeps_old_confirmation_and_method_numbers(client):
    path,base,endpoint,_=ready(client)
    request=dict(base_revision=1,decisions=[decision(value='IRB-2026-123; approved 2026-10-20')],metadata=[dict(target_id='methods:study_design',field='object',value='Synthetic',evidence='Study record')])
    first=post(client,endpoint,request,'r').json()
    assert first['report']['can_publish']
    published=post(client,endpoint+'/'+first['id']+'/publish',dict(expected_revision=1),'p').json()
    run_task(published['versions'][0]['task_id'],1)
    second=post(client,endpoint,dict(base_revision=2),'r2')
    assert second.status_code==201,second.text
    second=second.json()
    assert second['candidate']['review']['decisions']==first['candidate']['review']['decisions']
    assert second['candidate']['review']['metadata']==first['candidate']['review']['metadata']
    assert second['report']['can_publish']
    result=post(client,endpoint+'/'+second['id']+'/publish',dict(expected_revision=2),'p2')
    assert result.status_code==201,result.text
    assert run_task(result.json()['versions'][0]['task_id'],1)['status']=='succeeded'
    old=client.get(path+'/'+base['id']+'/versions/2').json()
    assert old['snapshot']==first['candidate']


def test_review_keeps_real_model_writing_waiting_for_authorization(client):
    path,base,endpoint,_=ready(client)
    review=post(client,endpoint,dict(base_revision=1),'r').json()
    published=post(client,endpoint+'/'+review['id']+'/publish',dict(expected_revision=1),'p').json()
    run_task(published['versions'][0]['task_id'],1)
    writing=post(client,path+'/'+base['id']+'/writing-requests',dict(base_revision=2,mode='full_draft'),'writing')
    assert writing.status_code==202,writing.text
    task=writing.json()['task']
    result=run_task(task['id'],task['revision'])
    assert result['status']=='waiting_confirmation'

def test_published_writing_after_review_uses_writing_validation_and_historical_review_lineage(client):
    from app.domain.manuscript_writing.context import compose_candidate,normalize_sections
    from app.domain.literature.service import digest
    from psycopg.types.json import Jsonb
    path,base,endpoint,_=ready(client)
    review=post(client,endpoint,dict(base_revision=1),'r').json()
    published=post(client,endpoint+'/'+review['id']+'/publish',dict(expected_revision=1),'p').json()
    run_task(published['versions'][0]['task_id'],1)
    writing_endpoint=path+'/'+base['id']+'/writing-requests'
    writing=post(client,writing_endpoint,dict(base_revision=2,mode='full_draft'),'w').json()
    with database_connection(write=True) as db:
        task=db.execute('SELECT * FROM tasks WHERE id=%s',(writing['id'],)).fetchone()
        sections=normalize_sections(task['input_snapshot']['base_snapshot'])
        for section in sections:
            if section['id'] not in ('title','references'):
                section['paragraphs']=[dict(id='new:'+section['id'],text='Missing facts require review.',source_ids=[],citations=[],numeric_bindings=[])]
        candidate=compose_candidate(dict(sections=sections),task['input_snapshot'])
        db.execute('UPDATE manuscript_writing_requests SET candidate_json=%s,candidate_sha256=%s WHERE task_id=%s',(Jsonb(candidate),digest(candidate),writing['id']))
        db.execute("UPDATE tasks SET status='succeeded' WHERE id=%s",(writing['id'],))
    result=post(client,writing_endpoint+'/'+writing['id']+'/publish',dict(expected_revision=2),'wp')
    assert result.status_code==201,result.text
    assert run_task(result.json()['versions'][0]['task_id'],1)['status']=='succeeded'
    assert result.json()['versions'][0]['snapshot']['review_history'][-1]['applies_to_current_text'] is False
    with database_connection() as db:
        from app.maintenance.manuscript_review_audit import audit_manuscript_reviews
        from app.maintenance.manuscript_writing_audit import audit_manuscript_writing
        assert all(c['invalid']==0 for c in audit_manuscript_reviews(db)+audit_manuscript_writing(db))

def test_citation_new_version_refresh_is_visible_without_reusing_new_support(client):
    from tests.api.test_literature_citations import seeded,binding,paragraph,draft_body
    pid,lit,task,refs=seeded(client)
    claim,bound,_,_=binding(client,lit,task,refs[0])
    citation=post(client,lit+'/citations/drafts',draft_body(paragraph(claim,bound)),'citation').json()
    path=f'/api/v1/projects/{pid}/manuscripts'
    root=post(client,path,body(citation_draft=dict(id=citation['id'],revision=1)),'base').json()
    assert run_task(root['versions'][0]['task_id'],1)['status']=='succeeded'
    endpoint=path+'/'+root['id']+'/reviews'
    initial=post(client,endpoint,dict(base_revision=1),'initial')
    assert initial.status_code==201,initial.text
    newer=post(client,lit+'/citations/drafts/'+citation['id']+'/versions',draft_body(paragraph(claim,bound),expected_revision=1),'citation-v2')
    assert newer.status_code==201,newer.text
    review=post(client,endpoint,dict(base_revision=1),'refresh')
    assert review.status_code==201,review.text
    review=review.json()
    assert any(c['kind']=='citation_draft' for c in review['report']['source_changes'])
    assert review['report']['impacts'][0]['scope']=='conservative'
    assert review['candidate']['citation_snapshot']==root['versions'][0]['snapshot']['citation_snapshot']
    assert post(client,endpoint+'/'+initial.json()['id']+'/publish',dict(expected_revision=1),'p').status_code==409
    latest=post(client,lit+'/citations/drafts/'+citation['id']+'/versions',draft_body(paragraph(claim,bound),expected_revision=2),'citation-v3')
    assert latest.status_code==201,latest.text
    assert post(client,endpoint+'/'+review['id']+'/publish',dict(expected_revision=1),'changed-again').status_code==409

@pytest.mark.parametrize('kind,status,code',[('missing',404,'manuscript_review_not_found'),('invalid',422,'manuscript_review_input_invalid'),('blocked',409,'manuscript_review_blocked')])
def test_review_api_exposes_specific_public_error_codes(client,kind,status,code):
    _,_,endpoint,_=ready(client)
    if kind=='missing': response=client.get(endpoint+'/nonexistent-review')
    elif kind=='invalid': response=post(client,endpoint,dict(base_revision=1,corrections=[dict(paragraph_id='missing',text='Replacement')]),'invalid-target')
    else:
        review=post(client,endpoint,dict(base_revision=1,corrections=[dict(paragraph_id='methods:study_design',text='Mean = 999')]),'blocked').json()
        response=post(client,endpoint+'/'+review['id']+'/publish',dict(expected_revision=1),'publish')
    assert response.status_code==status and response.json()['detail']['code']==code,response.text

def test_supplied_caption_without_literature_support_cannot_publish(client):
    from tests.api.test_document_versions import uploaded_docx
    from app.domain.tasks.file_parse_execution import run_parse_file_task
    from app.adapters.docx_parser import parse_docx
    project,_,_,uploaded,_=uploaded_docx(client)
    assert run_parse_file_task(uploaded['task']['id'],1,parser=parse_docx)['status']=='succeeded'
    path=f'/api/v1/projects/{project["id"]}/manuscripts'
    selected=next(s for s in client.get(path+'/candidates').json()['items'] if s['kind']=='document_version')
    root=post(client,path,body(sources=[{k:selected[k] for k in ('kind','id','file_id')}|dict(role='image_observation')]),'base').json()
    assert run_task(root['versions'][0]['task_id'],1)['status']=='succeeded'
    figure=root['versions'][0]['snapshot']['results_groups'][0]['figures'][0]
    endpoint=path+'/'+root['id']+'/reviews'
    review=post(client,endpoint,dict(base_revision=1,decisions=[decision(target_id='caption:'+figure['id'],value='Measured signal [999, 1000].')]),'caption')
    assert review.status_code==201,review.text
    review=review.json()
    assert not review['report']['can_publish']
    assert any(i['category']=='reference' and i['location']=='caption:'+figure['id'] for i in review['report']['issues'])
    published=post(client,endpoint+'/'+review['id']+'/publish',dict(expected_revision=1),'pub')
    assert published.status_code==409 and published.json()['detail']['code']=='manuscript_review_blocked'
    assert client.get(path+'/'+root['id']).json()['current_revision']==1
