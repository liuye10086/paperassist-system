"""Real SQL/source identity and immutable finding version behavior."""
from tests.api.test_projects import client, create_project, upload


def selected_cell(client):
    response=client.post('/api/v1/projects',json={'name':'研究发现合成验收','research_topic':'合成来源核对',
        'project_type':'research','delivery_kinds':['analysis']},headers={'Idempotency-Key':'research-project'})
    assert response.status_code==201,response.text
    project=response.json()
    result=upload(client,project['id']);assert result.status_code==201,result.text
    file=result.json();file=file.get('file',file)
    return '/api/v1/projects/'+project['id'],dict(source_kind='original_file',source_id=file['id'],
        locator={'kind':'cell','sheet':'研究数据','cell':'B2'})


def test_preview_preserves_external_zero_and_cannot_promote_it_to_system_computation(client):
    base,source=selected_cell(client)
    preview=client.post(base+'/research-results/preview',json={'sources':[source]})
    assert preview.status_code==200,preview.text
    catalog=preview.json()['catalogs'][0];fact=catalog['facts'][0]
    assert fact['raw_value']==0 and fact['origin']=='external_result'
    assert fact['verification_status']=='unverified'
    assert catalog['source']['provenance']=='external_result'
    body={'title':'外部结果原值核对','sources':[source],'selected_fact_ids':[fact['id']],
          'claims':[{'id':'claim1','statement':'外部表格记录值为0，未重算。','fact_ids':[fact['id']],
                     'origin':'external_result','review_decision':'adopt'}]}
    created=client.post(base+'/research-findings',json=body,headers={'Idempotency-Key':'finding-one'})
    assert created.status_code==201,created.text
    saved=created.json();assert saved['revision']==1
    assert saved['content']['facts'][0]==fact
    replay=client.post(base+'/research-findings',json=body,headers={'Idempotency-Key':'finding-one'})
    assert replay.status_code==200 and replay.json()['id']==saved['id']
    altered=client.post(base+'/research-findings',json={**body,'title':'different'},headers={'Idempotency-Key':'finding-one'})
    assert altered.status_code==409


def test_source_change_notice_preserves_old_finding_and_lists_dependent_report(client):
    base,source=selected_cell(client)
    body={'title':'原发现','sources':[source]}
    first=client.post(base+'/research-findings',json=body,headers={'Idempotency-Key':'impact-first'}).json()
    report=client.post(base+'/research-reports',json={'title':'旧报告','finding_version_id':first['id']},headers={'Idempotency-Key':'impact-report'}).json()
    second=client.post(base+f"/research-findings/{first['set_id']}/versions",json={**body,'set_id':first['set_id'],'expected_revision':1,'title':'新发现'},headers={'Idempotency-Key':'impact-second'})
    assert second.status_code==201,second.text
    response=client.post(base+'/research-results/source-changes',json={'sources':[{'source_kind':'research_finding_version','source_id':first['id'],'sha256':first['sha256']}]})
    assert response.status_code==200,response.text
    item=response.json()['items'][0]
    assert item['newer_version_id']==second.json()['id'] and item['fixed_source_unchanged'] is True
    assert any(v['source_id']==report['id'] and v['source_kind']=='research_report_version' for v in item['affected'])
    assert client.get(base+f"/research-findings/{first['set_id']}/versions/{first['id']}").json()['sha256']==first['sha256']


def test_dependency_limit_counts_distinct_parents_not_cell_bindings(client):
    base,source=selected_cell(client)
    sources=[{**source,'locator':{**source['locator'],'cell':'B'+str(i)}} for i in range(1,101)]
    ids=[]
    for i in range(7):
        response=client.post(base+'/research-findings',json={'title':'多个定位来源 '+str(i),'sources':sources if i<6 else sources[:1]},headers={'Idempotency-Key':'many-cells-'+str(i)})
        assert response.status_code==201,response.text
        ids.append(response.json()['id'])
    response=client.post(base+'/research-results/source-changes',json={'sources':[source]})
    assert response.status_code==200,response.text
    item=response.json()['items'][0]
    assert {r['source_id'] for r in item['affected']}==set(ids)
    assert len(item['affected'])==7 and item['affected_truncated'] is False and item['automatic_replacement'] is False


def test_version_cas_and_cross_project_reference_and_fake_fact_are_rejected(client):
    base,source=selected_cell(client)
    body={'title':'版本保留','sources':[source]}
    created=client.post(base+'/research-findings',json=body,headers={'Idempotency-Key':'version-first'})
    assert created.status_code==201,created.text
    old=created.json();new={**body,'set_id':old['set_id'],'expected_revision':1,'title':'新版'}
    updated=client.post(base+f"/research-findings/{old['set_id']}/versions",json=new,headers={'Idempotency-Key':'version-next'})
    assert updated.status_code==201,updated.text
    assert updated.json()['revision']==2
    assert client.post(base+f"/research-findings/{old['set_id']}/versions",json=new,headers={'Idempotency-Key':'version-stale'}).status_code==409
    original=client.get(base+f"/research-findings/{old['set_id']}/versions/{old['id']}")
    assert original.status_code==200 and original.json()['content']['title']=='版本保留'
    other=create_project(client,'其他项目')
    assert client.post('/api/v1/projects/'+other['id']+'/research-results/preview',json={'sources':[source]}).status_code in (404,409)
    forged=client.post(base+'/research-findings',json={**body,'selected_fact_ids':['invented']},headers={'Idempotency-Key':'fake-fact'})
    assert forged.status_code==422
    assert forged.json()['detail']['code']=='research_fact_unresolved'


def test_source_browse_and_unknown_submission_recovery_are_owner_scoped(client):
    base,source=selected_cell(client)
    listed=client.get(base+'/research-results/sources?source_kind=original_file')
    assert listed.status_code==200,listed.text
    assert listed.json()['total']==1 and listed.json()['items'][0]['source_id']==source['source_id']
    assert client.get(base+'/research-results/sources?source_kind=original_file&page=0').status_code==422
    body={'title':'未知提交恢复','sources':[source]}
    created=client.post(base+'/research-findings',json=body,headers={'Idempotency-Key':'recover-one'})
    assert created.status_code==201,created.text
    recovered=client.get(base+'/research-requests/recover-one?kind=finding')
    assert recovered.status_code==200,recovered.text
    assert recovered.json()['id']==created.json()['id']
    other=create_project(client,'其他项目')
    assert client.get('/api/v1/projects/'+other['id']+'/research-requests/recover-one?kind=finding').status_code==404


def test_unsupported_locator_is_rejected_instead_of_ignoring_it(client):
    base,source=selected_cell(client)
    selected={**source,'locator':{'kind':'row','row_key':{'feature_id':'x'},'column':'value'}}
    response=client.post(base+'/research-results/preview',json={'sources':[selected]})
    assert response.status_code==422
    assert response.json()['detail']['code']=='research_locator_invalid'


def test_unresolved_conflict_is_retained_and_not_adoptable_as_a_resolved_claim(client):
    base,source=selected_cell(client);second={**source,'locator':{**source['locator'],'cell':'B3'}}
    preview=client.post(base+'/research-results/preview',json={'sources':[source,second]})
    assert preview.status_code==200,preview.text
    ids=[c['facts'][0]['id'] for c in preview.json()['catalogs']]
    body={'title':'保留冲突','sources':[source,second],'selected_fact_ids':ids,
          'conflicts':[{'id':'conflict1','fact_ids':ids,'note':'两份来源值不同'}],
          'claims':[{'id':'c1','statement':'值已确定','fact_ids':ids,'strength':'supported',
                     'review_decision':'adopt','conflicts':['conflict1']}]}
    denied=client.post(base+'/research-findings',json=body,headers={'Idempotency-Key':'claim-conflict'})
    assert denied.status_code==422,denied.text
    body['claims'][0].update(strength='unresolved',review_decision='needs_evidence')
    saved=client.post(base+'/research-findings',json=body,headers={'Idempotency-Key':'save-conflict'})
    assert saved.status_code==201,saved.text
    assert saved.json()['content']['conflicts'][0]['decision']=='unresolved'
    inherited={'source_kind':'research_finding_version','source_id':saved.json()['id']}
    followup={'title':'采用旧版本事实','sources':[inherited],
        'claims':[{'id':'reuse','statement':'已有事实已解决','fact_ids':[ids[0]],'review_decision':'adopt'}]}
    denied_again=client.post(base+'/research-findings',json=followup,headers={'Idempotency-Key':'inherited-conflict'})
    assert denied_again.status_code==422,denied_again.text
    followup['claims'][0]['review_decision']='needs_evidence'
    followup['selected_fact_ids']=[ids[0]]
    retained=client.post(base+'/research-findings',json=followup,headers={'Idempotency-Key':'retained-conflict'})
    assert retained.status_code==201,retained.text
    assert retained.json()['content']['conflicts']==saved.json()['content']['conflicts']
    followup['sources']=[{'source_kind':'research_finding_version','source_id':retained.json()['id']}]
    third=client.post(base+'/research-findings',json=followup,headers={'Idempotency-Key':'third-conflict'})
    assert third.status_code==201,third.text
    assert len(third.json()['content']['facts'])==1
    assert third.json()['content']['conflicts']==saved.json()['content']['conflicts']
