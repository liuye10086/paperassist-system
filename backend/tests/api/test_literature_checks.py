"""Independent checks never mutate saved bibliographies or imply support."""
from tests.api.test_analysis import client
from tests.api.test_literature import project
from tests.api.test_literature_citations import seeded,binding,paragraph,draft_body
from tests.api.test_literature_evidence import post
from app.db.database import database_connection


def test_check_creation_history_idempotency_and_frozen_citation(client):
    _,lit,task,refs=seeded(client)
    c,b,_,_=binding(client,lit,task,refs[0])
    draft=post(client,lit+'/citations/drafts',draft_body(paragraph(c,b)),'draft').json()
    base=lit+'/checks';path=base+'/references/'+refs[0]['id']
    config=client.get(base+'/config').json()
    assert config['doi_network_enabled'] is False and config['doi_check_available'] is False
    assert config['doi_execution_kind']=='disabled'
    initial=client.get(base+'/candidates').json()
    assert initial['total']==3
    with database_connection() as db: assert db.execute('SELECT count(*) AS n FROM literature_check_receipts').fetchone()['n']==0
    body=dict(kind='saved_record',search_id=task['id'])
    first=post(client,path+'/receipts',body,'check')
    assert first.status_code==201,first.text
    receipt=first.json()
    assert receipt['result']['status']=='synthetic_match'
    assert receipt['result']['network_attempted'] is False and receipt['source_current'] is True
    assert receipt['output_language']=='zh-CN' and receipt['source_kind']=='synthetic_fixture'
    assert post(client,path+'/receipts',body,'check').json()==receipt
    assert post(client,path+'/receipts',{**body,'kind':'doi_resolution'},'check').status_code==409
    doi=post(client,path+'/receipts',{**body,'kind':'doi_resolution'},'doi')
    assert doi.status_code==201 and doi.json()['result']['status']=='not_checked'
    assert client.get(path+'/history').json()['total']==2
    assert client.get(path+'/history?page=2').json()['items']==[]
    candidate=next(x for x in client.get(base+'/candidates').json()['items'] if x['id']==refs[0]['id'])
    assert candidate['saved_record']['id']==receipt['id']
    assert client.get(path).json()==candidate
    assert candidate['content_support'][0]['latest_review']['status']=='supported'
    assert candidate['content_support'][0]['output_language']==c['output_language']
    assert candidate['sources'][0]['output_language']=='zh-CN'
    assert client.get(lit+'/citations/drafts/'+draft['id']).json()['snapshot']==draft['snapshot']
    assert post(client,path+'/receipts',{**body,'url':'https://evil.test'},'evil').status_code==422
    other=f'/api/v1/projects/{project(client)}/literature/checks/references/'+refs[0]['id']
    assert client.get(other+'/history').status_code==404
    assert post(client,other+'/receipts',body,'foreign').status_code==404


def test_another_owner_cannot_read_or_create_checks(client):
    from tests.integration.test_project_ownership import account_client
    _,lit,task,refs=seeded(client)
    with account_client('check-intruder@example.test')[0] as other:
        for suffix in ('/config','/candidates','/references/'+refs[0]['id']+'/history'):
            assert other.get(lit+'/checks'+suffix).status_code==404
        assert post(other,lit+'/checks/references/'+refs[0]['id']+'/receipts',dict(kind='saved_record',search_id=task['id']),'intruder').status_code==404
