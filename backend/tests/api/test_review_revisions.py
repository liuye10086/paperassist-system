from tests.api.test_analysis import client
from tests.api.test_review_rounds import make_round


def test_fixed_synthetic_journal_round_preview_and_adoption(client):
    from tests.api.test_journal_adaptation import adaptation_ready
    from app.domain.tasks.execution import run_task
    root,_,base,fixed,_,_=adaptation_ready(client)
    url=root.rsplit('/manuscripts/',1)[0]+'/reviews'
    body=dict(title='Fixed synthetic journal review',project_type='sci',synthetic=True,
              manuscript=dict(id=root.rsplit('/',1)[1],revision=base['revision'],version_id=base['id']),
              journal_target_id=fixed['target_id'],materials=[],
              sources=[dict(role='reviewer',label='Reviewer 1',format='text',text='1. Clarify the method.')])
    response=client.post(url+'/rounds',json=body,headers={'Idempotency-Key':'fixed-journal-round'})
    assert response.status_code==202,response.text
    saved=response.json();assert run_task(saved['task']['id'],1)['status']=='succeeded'
    round=client.get(url+'/rounds/'+saved['id']).json()
    assert round['constraints']['journal_target_id']==fixed['target_id']
    context_response=client.get(url+'/rounds/'+saved['id']+'/revision-context')
    assert context_response.status_code==200,context_response.text
    context=context_response.json()
    location=next(x for x in context['locations'] if x['kind']=='paragraph' and x['section_id']=='materials_and_methods')
    request=dict(plan_revision=round['revision'],expected_current_revision=context['expected_current_revision'],operations=[dict(
        item_id=round['items'][0]['id'],kind='replace_paragraph',location_id=location['id'],
        text=location['text']+' The existing method is retained.',evidence_ids=[context['evidence'][0]['id']],reason='Clarify the fixed method.')])
    path=url+'/rounds/'+saved['id']+'/revisions'
    response=client.post(path+'/preview',json=request)
    assert response.status_code==200,response.text
    preview=response.json();assert preview['can_adopt'],preview
    response=client.post(path,json=request|dict(preview_sha256=preview['preview_sha256']),headers={'Idempotency-Key':'fixed-journal-adopt'})
    assert response.status_code==202,response.text
    revision=response.json();task=run_task(revision['task']['id'],1)
    assert task['status']=='succeeded',task
    output=client.get(url+'/revisions/'+revision['id']).json()['result']['output']
    assert run_task(output['task_id'],1)['status']=='succeeded'
    public=client.get(root+'/versions/'+str(output['revision']))
    assert public.status_code==200,public.text
    assert public.json()['parent_version_id']==base['id']


def context_and_request(client, text='1. Clarify the method.\n2. Add an independent experiment.'):
    url, round, _, base = make_round(client, text)
    response = client.get(url+'/rounds/'+round['id']+'/revision-context')
    assert response.status_code == 200, response.text
    context = response.json()
    location = next(x for x in context['locations'] if x['kind']=='paragraph' and x['section_id']=='materials_and_methods')
    evidence = context['evidence'][0]['id']
    request = dict(plan_revision=round['revision'],expected_current_revision=context['expected_current_revision'],operations=[dict(item_id=round['items'][0]['id'],kind='replace_paragraph',location_id=location['id'],text=location['text']+' The existing method is retained.',evidence_ids=[evidence],reason='Clarify existing method without new facts.')])
    return url, round, base, context, request


def test_grounded_plan_consumes_fixed_text_and_material(client):
    url, round, base, context, request = context_and_request(client)
    assert context['grounded_plans'][0]['existing_content']
    assert context['grounded_plans'][0]['evidence']
    assert context['locations'][0]['id']
    assert context['evidence'][0]['content']


def test_actual_revision_preserves_waiting_items_and_public_version(client):
    from app.domain.tasks.execution import run_task
    url, round, base, context, body = context_and_request(client)
    path=url+'/rounds/'+round['id']+'/revisions'
    response=client.post(path+'/preview',json=body)
    assert response.status_code==200,response.text
    preview=response.json();assert preview['can_adopt'],preview
    assert preview['actual_changes'][0]['before'] != preview['actual_changes'][0]['after']
    body['preview_sha256']=preview['preview_sha256']
    response=client.post(path,json=body,headers={'Idempotency-Key':'adopt-one'})
    assert response.status_code==202,response.text
    saved=response.json(); assert run_task(saved['task']['id'],1)['status']=='succeeded'
    result=client.get(url+'/revisions/'+saved['id']).json()['result']
    assert result['output']['parent_version_id']==base['id']
    assert result['items'][0]['status']=='executing'
    assert result['items'][1]['status']=='waiting_material'
    assert run_task(result['output']['task_id'],1)['status']=='succeeded'
    result=client.get(url+'/revisions/'+saved['id']).json()['result']
    assert result['items'][0]['status']=='completed'
    public=client.get(f"/api/v1/projects/{round['project_id']}/manuscripts/{result['output']['manuscript_id']}/versions/{result['output']['revision']}")
    assert public.status_code==200,public.text
    assert public.json()['parent_version_id']==base['id']
    assert client.post(path,json=body,headers={'Idempotency-Key':'adopt-one'}).status_code==200
    historical=client.get(url+'/rounds/'+round['id']).json()
    assert all(i['status']!='completed' for i in historical['versions'][0]['items'])


def test_noop_and_missing_experiment_never_complete(client):
    url, round, base, context, body=context_and_request(client)
    path=url+'/rounds/'+round['id']+'/revisions/preview'
    body['operations'][0]['text']=next(x['text'] for x in context['locations'] if x['id']==body['operations'][0]['location_id'])
    response=client.post(path,json=body);assert response.status_code==200,response.text
    assert not response.json()['can_adopt']
    body['operations'][0]['item_id']=round['items'][1]['id'];body['operations'][0]['text']+=' New experiment is complete.'
    response=client.post(path,json=body);assert response.status_code==200,response.text
    assert not response.json()['can_adopt'] and response.json()['unexecuted']

def test_fixed_old_parent_and_current_revision_cas(client):
    from app.domain.tasks.execution import run_task
    url, round, base, context, body=context_and_request(client)
    path=url+'/rounds/'+round['id']+'/revisions'
    preview=client.post(path+'/preview',json=body).json();body['preview_sha256']=preview['preview_sha256']
    first=client.post(path,json=body,headers={'Idempotency-Key':'first'}).json()
    second=client.post(path,json=body,headers={'Idempotency-Key':'second'}).json()
    assert run_task(first['task']['id'],1)['status']=='succeeded'
    result=client.get(url+'/revisions/'+first['id']).json()['result'];assert run_task(result['output']['task_id'],1)['status']=='succeeded'
    assert run_task(second['task']['id'],1)['status']=='failed'
    assert client.get(url+'/revisions/'+second['id']).json()['result'] is None
    fresh=client.get(url+'/rounds/'+round['id']+'/revision-context').json()
    assert fresh['manuscript']['version_id']==base['id']
    body.pop('preview_sha256');body['expected_current_revision']=fresh['expected_current_revision'];body['operations'][0]['text']+=' Explicit old-parent edit.'
    preview=client.post(path+'/preview',json=body);assert preview.status_code==200,preview.text
    body['preview_sha256']=preview.json()['preview_sha256']
    saved=client.post(path,json=body,headers={'Idempotency-Key':'old-parent'}).json()
    assert run_task(saved['task']['id'],1)['status']=='succeeded'
    result=client.get(url+'/revisions/'+saved['id']).json()['result'];assert result['output']['parent_version_id']==base['id']
    assert run_task(result['output']['task_id'],1)['status']=='succeeded'
    assert client.get('/api/v1/tasks/'+saved['task']['id']+'/workspace').status_code==200


def test_numeric_causal_and_foreign_location_are_blocked(client):
    url, round, base, context, body=context_and_request(client)
    path=url+'/rounds/'+round['id']+'/revisions/preview'
    body['operations'][0]['location_id']='results:1';body['operations'][0]['text']='n = 999; mean = 3.0'
    response=client.post(path,json=body);assert response.status_code==200,response.text
    assert not response.json()['can_adopt']
    assert any(i['severity']=='error' for i in response.json()['public_issues'])
    body['operations'][0]['text']='This establishes causation.'
    response=client.post(path,json=body);assert response.status_code==200,response.text
    assert not response.json()['can_adopt'] and response.json()['unexecuted']
    body['operations'][0]['location_id']='foreign-paragraph'
    assert client.post(path,json=body).status_code==422


def test_revision_failed_publish_retry_has_no_duplicate_result(client):
    from app.domain.tasks.execution import run_task
    from app.domain.review_rounds.revision_execution import run_review_revision_task
    from app.core.exceptions import StorageError
    url, round, base, context, body=context_and_request(client)
    path=url+'/rounds/'+round['id']+'/revisions'
    preview=client.post(path+'/preview',json=body).json();body['preview_sha256']=preview['preview_sha256']
    saved=client.post(path,json=body,headers={'Idempotency-Key':'retry'}).json()
    def interrupted():raise StorageError('storage_unavailable','test interruption',503)
    failed=run_review_revision_task(saved['task']['id'],1,before_publish=interrupted)
    assert failed['status']=='failed'
    assert client.get(url+'/revisions/'+saved['id']).json()['result'] is None
    retry=client.post('/api/v1/tasks/'+saved['task']['id']+'/retry',json={'expected_revision':failed['revision']})
    assert retry.status_code==202,retry.text
    assert run_task(saved['task']['id'],retry.json()['revision'])['status']=='succeeded'
    result=client.get(url+'/revisions/'+saved['id']).json()['result'];assert result
    assert run_task(saved['task']['id'],retry.json()['revision']) is None

def test_new_round_saved_plan_contains_real_frozen_content(client):
    url, round, base, context, body=context_and_request(client)
    item=round['items'][0]
    assert context['grounded_plans'][0]['existing_content'] in item['plan']
    assert item['evidence_ids']

def test_grounded_plan_reports_exact_statistics_and_tracks_material_content(client):
    from copy import deepcopy
    from app.domain.review_rounds.grounded import grounded_plans
    url, round, base, context, body=context_and_request(client)
    plans=grounded_plans(base['snapshot'],round['items'],[])
    assert 'n=8' in plans[0]['plan'] and 'mean=3.0' in plans[0]['plan']
    altered=deepcopy(base['snapshot']);altered['sources'][0]['content']['overall']['n']=13
    changed=grounded_plans(altered,round['items'],[])
    assert 'n=13' in changed[0]['plan'] and plans[0]['plan']!=changed[0]['plan']

def test_school_revision_without_journal_preserves_fixed_confirmation(client):
    from tests.api.test_school_exports import published
    from tests.api.test_review_rounds import upload_parsed
    from app.domain.tasks.execution import run_task
    from docx import Document
    from io import BytesIO
    path,root,_,manuscript=published(client);base=manuscript['versions'][0]
    stream=BytesIO();doc=Document();doc.add_paragraph('本研究采用固定材料记录的方法，现有局限性予以保留。');doc.save(stream)
    source=upload_parsed(client,path.split('/')[4],stream.getvalue(),'synthetic-method.docx')
    payload=dict(title='合成学校实际修改',project_type='thesis',synthetic=True,manuscript=dict(id=manuscript['id'],revision=base['revision'],version_id=base['id']),school_confirmation_id=base['snapshot']['thesis_context']['confirmation_id'],sources=[dict(role='advisor',label='导师',format='text',text='请澄清方法表述。')],materials=[dict(kind='document_version',file_id=source['file_id'],id=source['document_version_id'])])
    response=client.post(path+'/reviews/rounds',json=payload,headers={'Idempotency-Key':'school-round'});assert response.status_code==202,response.text
    round=response.json();run_task(round['task']['id'],1)
    context=client.get(path+'/reviews/rounds/'+round['id']+'/revision-context').json()
    assert '本研究采用固定材料记录的方法' in context['grounded_plans'][0]['plan']
    location=next(l for l in context['locations'] if l['kind']=='paragraph' and l['section_id']=='school-methods')
    round=client.get(path+'/reviews/rounds/'+round['id']).json()
    body=dict(plan_revision=round['revision'],expected_current_revision=1,operations=[dict(item_id=round['items'][0]['id'],kind='replace_paragraph',location_id=location['id'],text='本研究采用固定材料记录的方法，现有局限性予以保留。',evidence_ids=[source['document_version_id']],reason='明确采用已有方法资料正文。')])
    url=path+'/reviews/rounds/'+round['id']+'/revisions'
    response=client.post(url+'/preview',json=body);assert response.status_code==200,response.text
    preview=response.json();assert isinstance(preview['constraint_issues'],list) and preview['can_adopt'],preview
    response=client.post(url,json=body|dict(preview_sha256=preview['preview_sha256']),headers={'Idempotency-Key':'school-adopt'});assert response.status_code==202,response.text
    saved=response.json();assert run_task(saved['task']['id'],1)['status']=='succeeded'
    result=client.get(path+'/reviews/revisions/'+saved['id']).json()['result'];assert run_task(result['output']['task_id'],1)['status']=='succeeded'
    version=client.get(root+'/versions/'+str(result['output']['revision']));assert version.status_code==200,version.text
    assert version.json()['snapshot']['thesis_context']==base['snapshot']['thesis_context']
    assert any(p['text']=='本研究采用固定材料记录的方法，现有局限性予以保留。' for s in version.json()['snapshot']['sections'] for p in s['paragraphs'])
    from app.db.database import database_connection
    from app.maintenance.review_revision_audit import audit_review_revisions
    with database_connection() as db:assert all(check['invalid']==0 for check in audit_review_revisions(db))

def test_published_revision_common_check_recognizes_its_own_exact_prose(client):
    from app.domain.tasks.execution import run_task
    url, round, base, context, body=context_and_request(client)
    path=url+'/rounds/'+round['id']+'/revisions'
    preview=client.post(path+'/preview',json=body).json()
    saved=client.post(path,json=body|dict(preview_sha256=preview['preview_sha256']),headers={'Idempotency-Key':'checked-output'}).json()
    assert run_task(saved['task']['id'],1)['status']=='succeeded'
    result=client.get(url+'/revisions/'+saved['id']).json()['result'];assert run_task(result['output']['task_id'],1)['status']=='succeeded'
    root=f"/api/v1/projects/{round['project_id']}/manuscripts/{result['output']['manuscript_id']}"
    checked=client.get(root+'/reviews/context');assert checked.status_code==200,checked.text
    assert not [i for i in checked.json()['issues'] if i['severity']=='error' and i['category']=='numeric']

def test_finite_split_order_caption_and_exact_citation_keep_originals():
    from copy import deepcopy
    from app.domain.manuscript_writing.contracts import SECTION_IDS
    from app.domain.review_rounds.grounded import apply_operations
    paragraph=lambda identity,text:dict(id=identity,text=text,source_ids=['material'],citations=[],numeric_bindings=[],origin='user_provided')
    sections=[dict(id=key,paragraphs=[]) for key in SECTION_IDS]
    next(s for s in sections if s['id']=='materials_and_methods')['paragraphs']=[paragraph('method','First sentence. Second sentence.')]
    next(s for s in sections if s['id']=='discussion')['paragraphs']=[paragraph('claim','Reviewed claim.'),paragraph('limitation','Known limitation.')]
    binding=dict(project_reference_id='ref',review_id='review',claim_id='claim',metadata_version_id='metadata')
    snapshot=dict(output_language='en',sections=sections,sources=[dict(id='material',kind='document_version',content={'text':'Existing methods and figure notes.'})],results_groups=[dict(id='group',figures=[dict(id='fig',caption='Saved caption.',source_ids=['material'])],tables=[])],references=[],citation_snapshot=dict(paragraphs=[dict(id='c1',fragments=[dict(kind='claim',bindings=[binding])])],output=dict(paragraphs=[dict(id='c1',text='Reviewed claim.')])))
    original=deepcopy(snapshot)
    items=[dict(id=str(n),original_text='Clarify wording.',category='expression',flags=[],needs=[],decision=None,status='pending',uncompleted_reason='Pending.') for n in range(4)]
    common=dict(evidence_ids=['material'],reason='Use the saved evidence.')
    operations=[dict(common,item_id='0',kind='split_paragraph',location_id='method',text='First sentence.\n\nSecond sentence.'),dict(common,item_id='1',kind='reorder_paragraphs',location_id='discussion',paragraph_ids=['limitation','claim']),dict(common,item_id='2',kind='figure_caption',location_id='fig',text='Clarified saved caption.'),dict(common,item_id='3',kind='bind_citation',location_id='claim',text='c1')]
    candidate,changes,unexecuted,strict,_=apply_operations(snapshot,items,[],operations)
    assert snapshot==original and len(changes)==4 and not unexecuted
    methods=next(s for s in candidate['sections'] if s['id']=='materials_and_methods')['paragraphs']
    assert [p['id'] for p in methods]==['method','method:split:2']
    discussion=next(s for s in candidate['sections'] if s['id']=='discussion')['paragraphs']
    assert discussion[1]['citations']==[binding]
    assert candidate['results_groups'][0]['figures'][0]['caption']=='Clarified saved caption.'


def test_one_selected_heading_does_not_apply_unselected_guide_changes():
    from app.domain.manuscript_writing.contracts import SECTION_IDS
    from app.domain.journals.display import defaults,context
    from app.domain.review_rounds.grounded import apply_operations
    snapshot=dict(output_language='en',sections=[dict(id=k,paragraphs=[]) for k in SECTION_IDS],sources=[dict(id='material',kind='document_version',content={'text':'Fixed guideline.'})],results_groups=[],references=[])
    names=dict(defaults(snapshot)['names']);names.update(abstract='Summary',discussion='Interpretation')
    rule=dict(id='names',key='section_display_names',value=[dict(section_id=k,display_name=v) for k,v in names.items()],status='known',source_id='guide',quote='Explicit display mapping')
    target=dict(selected_requirements=[rule],warnings=[],conflicts=[])
    item=dict(id='item',original_text='Use the journal abstract heading.',category='format',flags=[],needs=[],decision=None,status='pending',uncompleted_reason='Pending.')
    op=dict(item_id='item',kind='section_title',location_id='abstract',text='Summary',evidence_ids=['material'],reason='Fixed guideline heading.')
    candidate,changes,_,_,_=apply_operations(snapshot,[item],[],[op],target=target)
    assert context(candidate)['names']['abstract']=='Summary'
    assert context(candidate)['names']['discussion']==defaults(snapshot)['names']['discussion']
    assert changes[0]['evidence'][-1]['kind']=='journal_requirement'

def test_plan_changed_after_preview_rejects_publication_without_new_version(client):
    from app.domain.review_rounds.revision_execution import run_review_revision_task
    from tests.api.test_review_rounds import edits
    url, round, base, context, body=context_and_request(client)
    path=url+'/rounds/'+round['id']+'/revisions'
    preview=client.post(path+'/preview',json=body).json()
    saved=client.post(path,json=body|dict(preview_sha256=preview['preview_sha256']),headers={'Idempotency-Key':'drift-adopt'}).json()
    def update_plan():
        items=edits(round);items[0]['plan']='改变了具体处理计划，需要重新预览。'
        response=client.post(url+'/rounds/'+round['id']+'/plans',json=dict(expected_revision=round['revision'],items=items),headers={'Idempotency-Key':'drift-plan'})
        assert response.status_code==201,response.text
    failed=run_review_revision_task(saved['task']['id'],1,before_publish=update_plan)
    assert failed['status']=='failed'
    assert client.get(url+'/revisions/'+saved['id']).json()['result'] is None
    assert client.get(url+'/rounds/'+round['id']+'/revision-context').json()['expected_current_revision']==context['expected_current_revision']

def caption_candidate_checks(text):
    from app.domain.manuscript_writing.contracts import SECTION_IDS
    from app.domain.review_rounds.grounded import apply_operations
    from app.domain.manuscript_review.checks import check_snapshot
    snapshot=dict(output_language='en',sections=[dict(id=k,paragraphs=[]) for k in SECTION_IDS],sources=[dict(id='material',kind='document_version',content={'text':'Existing figure evidence.'})],results_groups=[dict(id='group',paragraphs=[],tables=[],figures=[dict(id='fig',number=1,caption='Saved source caption.',caption_origin='source',caption_status='supplied',source_ids=['material'],numeric_bindings=[])])],references=[],issues=[])
    item=dict(id='item',original_text='Clarify the figure caption.',category='figure',flags=[],needs=[],decision=None,status='pending',uncompleted_reason='Pending.')
    op=dict(item_id='item',kind='figure_caption',location_id='fig',text=text,evidence_ids=['material'],reason='Use fixed figure evidence.')
    candidate,changes,_,strict,_=apply_operations(snapshot,[item],[],[op])
    return snapshot,candidate,check_snapshot(candidate,strict_locations=strict)


def test_edited_source_caption_cannot_hide_unknown_figure_reference():
    original,candidate,issues=caption_candidate_checks('See Figure 99.')
    assert any(i['severity']=='error' and i['category']=='illustration' and i['location']=='caption:fig' for i in issues),issues
    assert candidate['results_groups'][0]['figures'][0]['caption_origin']=='user_provided'
    assert original['results_groups'][0]['figures'][0]['caption_origin']=='source'


def test_edited_caption_valid_reference_and_unknown_numeric_unit_checks():
    _,candidate,issues=caption_candidate_checks('See Figure 1.')
    assert not [i for i in issues if i['severity']=='error'],issues
    _,_,issues=caption_candidate_checks('The value is 999 mg.')
    assert any(i['severity']=='error' and i['category']=='numeric' and i['location']=='caption:fig' for i in issues),issues

def test_partial_item_retains_actual_changes_without_claiming_completion(client):
    from app.domain.tasks.execution import run_task
    url,round,base,context,body=context_and_request(client,'1. Clarify the method.')
    body['operations'].append(dict(body['operations'][0],location_id='discussion:1',text='This establishes causation.'))
    path=url+'/rounds/'+round['id']+'/revisions'
    response=client.post(path+'/preview',json=body);assert response.status_code==200,response.text
    preview=response.json();assert preview['can_adopt'] and len(preview['actual_changes'])==1 and preview['unexecuted']
    response=client.post(path,json=body|dict(preview_sha256=preview['preview_sha256']),headers={'Idempotency-Key':'partial-item'});assert response.status_code==202,response.text
    saved=response.json();assert run_task(saved['task']['id'],1)['status']=='succeeded'
    result=client.get(url+'/revisions/'+saved['id']).json()['result'];assert run_task(result['output']['task_id'],1)['status']=='succeeded'
    result=client.get(url+'/revisions/'+saved['id']).json()['result']
    assert result['items'][0]['status']=='waiting_material',result['items'][0]
    assert result['items'][0]['actual_changes'] and result['items'][0]['uncompleted_reason']
    assert 'completion' not in result['items'][0]
    current=client.get(url+'/rounds/'+round['id']).json()
    assert current['items'][0]['status']=='waiting_material'

def test_revision_context_exposes_separate_verified_citation_choices(client):
    _,_,_,context,_=context_and_request(client)
    assert context.get('citation_candidates')==[]
