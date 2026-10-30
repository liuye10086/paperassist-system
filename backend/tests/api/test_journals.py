from tests.api.test_analysis import client  # noqa: F401
from app.db.database import database_connection


def setup(client):
    p=client.post('/api/v1/projects',json=dict(name='synthetic journals',research_topic='cancer',project_type='sci')).json()
    return f'/api/v1/projects/{p["id"]}/journals'


def profile(**changes):
    fields={k:dict(value=v,status='verified',location='synthetic page 1 '+k,quote='synthetic '+str(v)) for k,v in dict(topics=['cancer'],scope=['oncology'],article_types=['research'],languages=['en'],oa=True,fee=dict(amount=100,currency='USD'),disciplines=['medicine'],unit_requirements=['university']).items()}
    fields['fee']['applicability']={'unconditional':True}
    return dict(name='synthetic Oncology',source_type='synthetic',source_text=' '.join(e['quote'] for e in fields.values()),source_url='https://journal.example.test',verified_on='2026-10-23',conditions='synthetic condition',permission='user_provided',fields=fields)|changes


def request(**changes):
    return dict(title='cancer trial',topics=['cancer'],article_type='research',language='en',hard_filters=['article_types','languages','oa','fee','disciplines','unit_requirements'])|changes


def post(client,path,body,key='one'):
    return client.post(path,json=body,headers={'Idempotency-Key':key})


def test_journal_frozen_history_filtering_task_contract_and_permissions(client):
    base=setup(client)
    config=client.get(base+'/config'); assert config.status_code==200,config.text
    assert config.json()['real_network_calls'] is False
    p=post(client,base+'/profiles',profile()).json()
    assert 'id' in p,p
    pending=profile();pending['name']='synthetic unknown';pending['fields'].pop('languages')
    q=post(client,base+'/profiles',pending,'pending').json()
    bad=profile();bad['name']='synthetic too costly';bad['fields']['fee']['value']['amount']=500
    post(client,base+'/profiles',bad,'bad')
    body=request(budget=dict(amount=200,currency='USD'),oa=True)
    r=post(client,base+'/recommendations',body)
    assert r.status_code==202,r.text
    item=r.json();assert item['result'] is None and item['input_snapshot']['manuscript'] is None
    assert post(client,base+'/recommendations',body).json()==item
    assert post(client,base+'/recommendations',request(title='changed')).status_code==409
    from app.domain.journals.execution import run_journal_task
    assert run_journal_task(item['task']['id'],1)['status']=='succeeded'
    saved=client.get(base+'/recommendations/'+item['id']).json()
    assert len(saved['result']['candidates'])==len(saved['result']['pending_verification'])==len(saved['result']['excluded'])==1
    reasons=saved['result']['candidates'][0]['reasons'];assert all(r['evidence']['location'] for r in reasons)
    assert saved['result']['candidates'][0]['profile']['synthetic'] is True
    assert client.get('/api/v1/tasks/'+item['task']['id']).json()['input_version']['kind']=='journal_recommendation'
    assert client.get('/api/v1/tasks/'+item['task']['id']+'/workspace').status_code==200
    changed=profile(previous_version_id=p['id'],source_status='unavailable')
    assert post(client,base+'/profiles',changed,'v2').status_code==201
    assert client.get(base+'/recommendations/'+item['id']).json()['result']==saved['result']
    newer=post(client,base+'/recommendations',request(language='fr'),'new').json()
    assert newer['id']!=item['id']
    assert run_journal_task(newer['task']['id'],1)['status']=='succeeded'
    assert client.get(base+'/recommendations/'+newer['id']).json()['result']['candidates']==[]
    from tests.integration.test_project_ownership import account_client
    otherbase=setup(client)
    assert client.get(otherbase+'/profiles/'+p['id']).status_code==404
    with account_client('journal-other@example.test')[0] as other:
        assert other.get(base+'/recommendations').status_code==404
    with database_connection() as db:
        assert db.execute('SELECT count(*) n FROM journal_recommendations').fetchone()['n']==2


def test_journal_retry_preserves_input_snapshot_and_public_resume(client):
    base=setup(client);post(client,base+'/profiles',profile())
    item=post(client,base+'/recommendations',request()).json()
    from app.domain.journals.execution import run_journal_task
    def fail(snapshot): raise RuntimeError('synthetic failure')
    failed=run_journal_task(item['task']['id'],1,recommender=fail)
    assert failed['status']=='failed'
    resumed=post(client,'/api/v1/tasks/'+failed['id']+'/resume',dict(operation='retry',wait_id=None,expected_task_revision=failed['revision'],input_version=failed['input_version']),'resume')
    assert resumed.status_code==202,resumed.text
    assert run_journal_task(failed['id'],resumed.json()['revision'])['status']=='succeeded'
    saved=client.get(base+'/recommendations/'+item['id']).json()
    assert saved['input_snapshot']==item['input_snapshot']
    assert run_journal_task(failed['id'],resumed.json()['revision']) is None


def test_journal_metrics_gate_and_offline_url_adapter(client):
    base=setup(client);p=profile();p['fields']['sci']=dict(value=True,status='verified',location='PubMed',quote='PubMed')
    assert post(client,base+'/profiles',p).status_code==422
    p=profile();p['fields']['fee']['value']={'amount':1,'currency':'USD'};p['fields']['fee']['quote']=''
    assert post(client,base+'/profiles',p).status_code==422
    from app.domain.journals.web import OfflineWebAdapter
    import pytest
    visited=[]
    def resolver(host): return ['93.184.216.34']
    def transport(url,ips,timeout,max_bytes): visited.append(url);return dict(status=200,headers={},body=b'synthetic')
    adapter=OfflineWebAdapter(resolver=resolver,transport=transport)
    assert adapter.fetch('https://example.test')==b'synthetic'
    for url in ['http://127.0.0.1','https://[::1]','https://a:b@example.test','https://example.test:444','file:///x']:
        with pytest.raises(ValueError):adapter.fetch(url)
    assert len(visited)==1
    with pytest.raises(ValueError):OfflineWebAdapter(resolver=lambda h:['10.0.0.1'],transport=transport).fetch('https://example.test')
    with pytest.raises(ValueError):OfflineWebAdapter(resolver=resolver,transport=lambda *args:dict(status=302,headers={'location':'http://[::ffff:127.0.0.1]'},body=b'')).fetch('https://example.test')
    with pytest.raises(ValueError):OfflineWebAdapter().fetch('https://example.test')


def test_journal_soft_preferences_conditional_fees_and_source_quotation(client):
    base=setup(client)
    wrong=profile();wrong['fields']['topics']['quote']='not in original source'
    assert post(client,base+'/profiles',wrong,'fabricated').status_code==422
    conditional=profile();conditional['fields']['fee'].pop('applicability')
    cp=post(client,base+'/profiles',conditional,'conditional')
    assert cp.status_code==201,cp.text
    known=post(client,base+'/profiles',profile(official_url='https://official.example.test'),'known')
    assert known.status_code==201,known.text
    item=post(client,base+'/recommendations',request(language='fr',hard_filters=['article_types','fee'],budget=dict(amount=200,currency='USD'))).json()
    from app.domain.journals.execution import run_journal_task
    assert run_journal_task(item['task']['id'],1)['status']=='succeeded'
    result=client.get(base+'/recommendations/'+item['id']).json()['result']
    assert len(result['candidates'])==1 and len(result['pending_verification'])==1
    assert result['candidates'][0]['profile']['official_url']=='https://official.example.test'
    assert result['candidates'][0]['preference_match_count']==0
    assert result['excluded']==[]


def test_journal_selected_old_manuscript_material_ownership_and_audit(client):
    from tests.api.test_manuscripts import body as manuscript_body,setup as manuscript_setup
    path,filebase,file=manuscript_setup(client)
    created=post(client,path,manuscript_body(),'manuscript').json()
    assert 'id' in created,created
    from app.domain.tasks.execution import run_task
    run_task(created['versions'][0]['task_id'],1)
    assert post(client,path+'/'+created['id']+'/versions',manuscript_body(expected_revision=1,title='new title'),'v2').status_code==201
    base=path.removesuffix('/manuscripts')+'/journals'
    materials=[dict(kind='original',id=file['id'],file_id=file['id'])]
    item=post(client,base+'/recommendations',request(manuscript=dict(id=created['id'],revision=1),materials=materials)).json()
    assert item['input_snapshot']['manuscript']['revision']==1
    assert item['input_snapshot']['manuscript']['snapshot']==created['versions'][0]['snapshot']
    assert item['input_snapshot']['materials'][0]['sha256']==file['sha256']
    other=setup(client)
    assert post(client,other+'/recommendations',request(manuscript=dict(id=created['id'],revision=1)),'foreign').status_code==404
    assert post(client,other+'/recommendations',request(materials=materials),'foreign-material').status_code in (404,409)
    assert post(client,base+'/recommendations',request(manuscript=dict(id=created['id'],revision=999)),'missing').status_code==404
    with database_connection() as db:
        from app.maintenance.database_audit import audit_database
        audit=audit_database(db)
        assert audit['ok'],audit['schema_issues'] or [c for c in audit['data_checks'] if c['invalid']]

def test_journal_disabled_metrics_cannot_be_satisfied_through_unit_tags_and_lifecycle(client):
    from tests.api.test_analysis import add_file
    filebase,file=add_file(client)
    base=filebase.split('/files/')[0]+'/journals'
    p=profile(material=dict(kind='original',id=file['id'],file_id=file['id']))
    p['fields']['unit_requirements']['value']=['SCI','PubMed']
    saved=post(client,base+'/profiles',p).json()
    assert 'id' in saved,saved
    # Requirements remain unverified even if both submitted sides repeat the same metric tag.
    data=request(unit_requirements=['SCI'],hard_filters=['article_types','unit_requirements'])
    item=post(client,base+'/recommendations',data).json()
    from app.domain.tasks.execution import run_task
    run_task(item['task']['id'],1)
    result=client.get(base+'/recommendations/'+item['id']).json()['result']
    assert result['candidates']==[] and result['pending_verification']
    assessment=client.get(filebase+'/lifecycle/assessment')
    assert assessment.status_code==200,assessment.text
    assert assessment.json()['counts']['journal_material_refs']==1
    assert any(r['code']=='journal_history_retained' for r in assessment.json()['reasons'])
    project=client.post('/api/v1/projects',json=dict(name='synthetic thesis',research_topic='test',project_type='thesis')).json()
    assert client.get('/api/v1/projects/'+project['id']+'/journals/config').status_code==422

def test_journal_fee_numeric_shape_and_synthetic_lineage_cannot_upgrade(client):
    base=setup(client)
    p=profile();p['fields']['fee']['value']['amount']='100 USD'
    assert post(client,base+'/profiles',p,'text-cost').status_code==422
    p=profile();p['fields']['fee']['value']['amount']='100'
    assert post(client,base+'/profiles',p,'string-cost').status_code==422
    saved=post(client,base+'/profiles',profile(),'synthetic').json()
    assert post(client,base+'/profiles',profile(previous_version_id=saved['id'],source_type='official_local'),'upgrade').status_code==422


def test_journal_offline_web_redirect_size_timeout_ipv6_and_rank_limits(client,monkeypatch):
    from app.domain.journals.web import OfflineWebAdapter
    from app.domain.journals.recommendation import recommend
    from app.domain.journals.contracts import RecommendationRequest
    import pytest
    assert OfflineWebAdapter(resolver=lambda h:['2606:4700:4700::1111'],transport=lambda *args:dict(status=200,headers={},body=b'ok')).fetch('https://[2606:4700:4700::1111]')==b'ok'
    for ips in [['93.184.216.34','127.0.0.1'],['::ffff:10.1.2.3'],['169.254.169.254'],['fc00::1'],['2001:db8::1']]:
        with pytest.raises(ValueError):OfflineWebAdapter(resolver=lambda h:ips,transport=lambda *a:pytest.fail('unsafe transport invoked')).fetch('https://example.test')
    calls=[]
    def redirect(url,*args):
        calls.append(url)
        return dict(status=302,headers={'location':'https://redirect.test'},body=b'')
    with pytest.raises(ValueError):OfflineWebAdapter(resolver=lambda h:['93.184.216.34'],transport=redirect,max_redirects=1).fetch('https://example.test')
    assert len(calls)==2
    for response in [dict(status=200,headers={},body=b'12345'),dict(status=200,headers={'Content-Length':'9'},body=b'ok')]:
        with pytest.raises(ValueError):OfflineWebAdapter(resolver=lambda h:['93.184.216.34'],transport=lambda *a:response,max_bytes=4).fetch('https://example.test')
    from types import SimpleNamespace
    ticks=iter([0,6]);monkeypatch.setattr('app.domain.journals.web.time',SimpleNamespace(monotonic=lambda:next(ticks)))
    with pytest.raises(ValueError,match='Timeout'):OfflineWebAdapter(resolver=lambda h:['93.184.216.34'],transport=lambda *a:dict(status=200,headers={},body=b'ok')).fetch('https://example.test')
    research=RecommendationRequest.model_validate(request(hard_filters=['article_types'])).model_dump(mode='json')
    profiles=[]
    for index in range(7):
        p=profile();p.update(id=str(index),source_status='available',synthetic=True)
        if index==6:p['fields']['languages']['value']=['fr']
        profiles.append(p)
    result=recommend(dict(research=research,profiles=profiles))
    assert len(result['candidates'])==3 and result['candidate_total']==7
    assert result['candidates'][0]['profile']['id']=='0'
    research['limit']=5
    assert len(recommend(dict(research=research,profiles=profiles))['candidates'])==5
    assert recommend(dict(research=research,profiles=[]))['candidates']==[]


def test_journal_science_unit_requirement_is_not_a_metric_abbreviation(client):
    from app.domain.journals.recommendation import recommend
    from app.domain.journals.contracts import RecommendationRequest
    for term in ('Faculty of Science approved list','Neuroscience institute list'):
        p=profile();p.update(id='synthetic-science',source_status='available',synthetic=True)
        p['fields']['unit_requirements'].update(value=[term],quote=term)
        p['source_text']+='\n'+term
        research=RecommendationRequest.model_validate(request(unit_requirements=[term],hard_filters=['article_types','unit_requirements'])).model_dump(mode='json')
        result=recommend(dict(research=research,profiles=[p]))
        assert len(result['candidates'])==1,term
    for term in ('SCI','SCIE','SCI/SCIE','JCR Q1','影响因子要求'):
        research['unit_requirements']=[term]
        p['fields']['unit_requirements']['value']=[term]
        result=recommend(dict(research=research,profiles=[p]))
        assert not result['candidates'] and result['pending_verification'],term


def web_source_guide(client, **changes):
    from tests.api.test_journal_format import guide
    base=setup(client)
    p=post(client,base+'/profiles',profile(source_type='official_local'),'web-profile').json()
    data=guide(p,source_type='official_local',name='Recorded guide',permission='offline test source',**changes)
    response=post(client,base+'/guides',data,'web-source')
    assert response.status_code==201,response.text
    return base,response.json()


def test_controlled_web_guide_endpoint_disabled_and_project_permissions(client,monkeypatch):
    from tests.integration.test_project_ownership import account_client
    base,g=web_source_guide(client)
    monkeypatch.setenv('PAPERASSIST_JOURNAL_WEB_ENABLED','0')
    monkeypatch.setattr('app.domain.journals.web.resolve_public_candidates',lambda *a: (_ for _ in ()).throw(AssertionError('network while disabled')))
    endpoint=base+'/guides/'+g['id']+'/fetch'
    response=post(client,endpoint,{},'disabled')
    assert response.status_code==409,response.text
    assert client.get(base+'/config').json()['web_acquisition']['enabled'] is False
    other=setup(client)
    assert post(client,other+'/guides/'+g['id']+'/fetch',{},'foreign').status_code==404
    with account_client('web-other@example.test')[0] as other_user:
        assert post(other_user,endpoint,{},'other-user').status_code==404
    assert len(client.get(base+'/guides').json()['items'])==1


def test_controlled_web_guide_fixed_transport_creates_version_and_replay_is_offline(client,monkeypatch):
    from app.domain.journals.web import ControlledWebAdapter
    base,g=web_source_guide(client)
    calls=[]
    def transport(url,*args):
        calls.append(url)
        if url.endswith('/guide'):return dict(status=302,headers={'Location':'/authors'},body=b'')
        return dict(status=200,headers={'Content-Type':'text/plain','ETag':'offline-v2'},body=b'Maximum body words: 2500; count: en_whitespace_body')
    controlled=ControlledWebAdapter(enabled=True,allowed_origins=['https://journal.example.test'],resolver=lambda h:['93.184.216.34'],transport=transport)
    monkeypatch.setattr('app.domain.journals.configuration.configured_web_adapter',lambda:controlled)
    endpoint=base+'/guides/'+g['id']+'/fetch'
    result=post(client,endpoint,{},'fetch-v2')
    assert result.status_code==201,result.text
    saved=result.json()
    assert saved['previous_version_id']==g['id'] and saved['source_url'].endswith('/authors')
    assert saved['retrieval']['requested_url']==g['source_url']
    assert saved['retrieval']['etag']=='offline-v2' and len(saved['retrieval']['body_sha256'])==64
    assert saved['verification_level']=='web_fetch_unverified'
    assert saved['source_version'].startswith('web-sha256:')
    assert saved['requirements'][0]['value']==2500
    assert client.get(base+'/guides/'+g['id']).json()==g
    assert post(client,endpoint,{},'fetch-v2').json()==saved
    assert len(calls)==2
    assert post(client,endpoint,{},'another-successor').status_code==409
    assert len(calls)==2
    assert post(client,endpoint,{'url':'https://other.test'},'arbitrary').status_code==422


def test_controlled_web_guide_permission_and_failure_keep_history(client,monkeypatch):
    from app.domain.journals.web import ControlledWebAdapter
    calls=[]
    controlled=ControlledWebAdapter(enabled=True,allowed_origins=['https://journal.example.test'],resolver=lambda h:['93.184.216.34'],transport=lambda *a:calls.append(a) or dict(status=503,headers={},body=b''))
    monkeypatch.setattr('app.domain.journals.configuration.configured_web_adapter',lambda:controlled)
    base,g=web_source_guide(client,permission_status='unknown')
    assert post(client,base+'/guides/'+g['id']+'/fetch',{},'permission').status_code==422
    assert calls==[]
    base,g=web_source_guide(client)
    failed=post(client,base+'/guides/'+g['id']+'/fetch',{},'failure')
    assert failed.status_code==422,failed.text
    assert 'Unavailable' in failed.json()['detail']['message']
    assert len(client.get(base+'/guides').json()['items'])==1


def test_controlled_web_guide_incomplete_response_preserves_source_version(client,monkeypatch):
    from app.domain.journals.web import ControlledWebAdapter
    def incomplete(*args): raise ValueError('Incomplete HTTP response')
    controlled=ControlledWebAdapter(enabled=True,allowed_origins=['https://journal.example.test'],
        resolver=lambda h:['93.184.216.34'],transport=incomplete)
    monkeypatch.setattr('app.domain.journals.configuration.configured_web_adapter',lambda:controlled)
    base,g=web_source_guide(client)
    failed=post(client,base+'/guides/'+g['id']+'/fetch',{},'incomplete-response')
    assert failed.status_code==422,failed.text
    assert 'Incomplete HTTP response' in failed.json()['detail']['message']
    assert client.get(base+'/guides').json()['items']==[g]
