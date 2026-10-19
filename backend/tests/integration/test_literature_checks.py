import copy
import pytest
from psycopg.types.json import Jsonb
from tests.api.test_analysis import client
from tests.api.test_literature_citations import seeded
from tests.api.test_literature_evidence import post
from app.db.database import database_connection


def test_saved_source_check_accepts_own_identity_with_other_pmids_in_reference_list(client):
    from app.adapters.ncbi import parse_fetch
    from app.domain.literature.execution import run_literature_task
    from tests.api.test_literature import create, project
    from tests.api.test_literature_citations import CitationNcbi

    class ReferenceListNcbi(CitationNcbi):
        def fetch(self, pmids):
            result = super().fetch(pmids)
            reference = b'''<ReferenceList><Reference><Citation>Synthetic cited work</Citation>
                <ArticleIdList><ArticleId IdType="pubmed">880000001</ArticleId>
                <ArticleId IdType="doi">10.1234/cited</ArticleId></ArticleIdList>
                </Reference></ReferenceList>'''
            return parse_fetch(result.raw.replace(b'</PubmedData>', reference + b'</PubmedData>'), pmids)

    pid = project(client)
    task = create(client, pid).json()
    provider = ReferenceListNcbi(2)
    assert run_literature_task(task['id'], task['revision'], client=provider)['status'] == 'succeeded'
    lit = f'/api/v1/projects/{pid}/literature'
    reference = next(r for r in client.get(lit + '/references').json()['items'] if r['record']['doi'])
    path = lit + '/checks/references/' + reference['id']
    checked = post(client, path + '/receipts', dict(kind='saved_record', search_id=task['id']), 'with-references')
    assert checked.status_code == 201, checked.text
    receipt = checked.json()
    assert receipt['result']['status'] == 'synthetic_match'
    assert receipt['result']['network_attempted'] is False
    assert receipt['source_current'] is True
    assert receipt['result']['source']['pmid'] == reference['pmid']
    metadata = post(client, lit + '/citations/references/' + reference['id'] + '/metadata',
                    dict(expected_revision=0, mode='extract', search_id=task['id']), 'metadata-with-references')
    assert metadata.status_code == 201, metadata.text
    assert metadata.json()['metadata']['pmid'] == reference['pmid']
    assert metadata.json()['metadata']['doi'] == reference['record']['doi']
    assert client.get(path + '/history').json()['items'] == [receipt]
    assert [call[0] for call in provider.calls] == ['esearch', 'efetch']
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n'] == 0


@pytest.mark.parametrize('change',['title','pmid','bytes','source_kind'])
def test_changed_original_preserves_check_history_and_records_conflict(client,change):
    _,lit,task,refs=seeded(client)
    path=lit+'/checks/references/'+refs[0]['id'];body=dict(kind='saved_record',search_id=task['id'])
    first=post(client,path+'/receipts',body,'before')
    assert first.status_code==201,first.text
    frozen=first.json()['result']
    with database_connection(write=True) as db:
        hit=db.execute('SELECT * FROM literature_search_hits WHERE project_reference_id=%s',(refs[0]['id'],)).fetchone()
        if change in ('title','pmid'):
            record=copy.deepcopy(hit['record_json']);record[change]='Changed' if change=='title' else '99999'
            db.execute('UPDATE literature_search_hits SET record_json=%s WHERE id=%s',(Jsonb(record),hit['id']))
        elif change=='bytes':
            from app.core.config import get_data_dir
            from pathlib import Path
            row=db.execute('SELECT * FROM literature_fetch_receipts WHERE id=%s',(hit['receipt_id'],)).fetchone()
            (Path(get_data_dir())/row['object_key']).write_bytes(b'corrupt original')
        else:
            db.execute("UPDATE literature_fetch_receipts SET source_kind='ncbi_eutilities' WHERE id=%s",(hit['receipt_id'],))
    history=client.get(path+'/history')
    assert history.status_code==200,history.text
    assert history.json()['items'][0]['result']==frozen
    assert history.json()['items'][0]['source_current'] is False
    conflict=post(client,path+'/receipts',body,'after')
    assert conflict.status_code==201,conflict.text
    assert conflict.json()['result']['status']=='source_conflict'
    assert client.get(path+'/history').json()['total']==2


def test_corrupt_frozen_check_is_rejected(client):
    _,lit,task,refs=seeded(client)
    path=lit+'/checks/references/'+refs[0]['id']
    response=post(client,path+'/receipts',dict(kind='saved_record',search_id=task['id']),'check')
    assert response.status_code==201,response.text
    with database_connection(write=True) as db:
        db.execute("UPDATE literature_check_receipts SET snapshot_json='{}'::jsonb")
    assert client.get(path+'/history').status_code==409


def test_injected_fixed_doi_history_language_and_no_doi(client):
    from app.adapters.doi import DoiClient
    from app.api.literature_checks import get_check_service
    from app.api.dataset_preparation import Store
    from app.domain.literature_checks.service import LiteratureCheckService
    from app.main import app
    from tests.api.test_literature import create,request
    from tests.api.test_literature_citations import CitationNcbi
    from app.domain.literature.execution import run_literature_task
    _,lit,task,refs=seeded(client)
    pid=lit.split('/')[4]
    newer=create(client,pid,{**request(),'output_language':'en'},'english').json()
    assert run_literature_task(newer['id'],1,client=CitationNcbi(3))['status']=='succeeded'
    calls=[]
    class Response:
        status_code=302
        headers={'Location':'https://publisher.example/offline'}
        def close(self): pass
        @property
        def content(self): raise AssertionError('body forbidden')
    class FixedSession:
        def get(self,*args,**kwargs): calls.append(1);return Response()
    def factory(store:Store):
        return LiteratureCheckService(store,DoiClient(enabled=True,session=FixedSession(),execution_kind='synthetic_fixture'))
    app.dependency_overrides[get_check_service]=factory
    try:
        cfg=client.get(lit+'/checks/config').json()
        assert cfg['doi_check_available'] and not cfg['doi_network_enabled'] and cfg['doi_execution_kind']=='synthetic_fixture'
        path=lit+'/checks/references/'+refs[0]['id']+'/receipts'
        body=dict(kind='doi_resolution',search_id=newer['id'])
        r=post(client,path,body,'sim')
        assert r.status_code==201,r.text
        assert r.json()['output_language']=='en'
        assert r.json()['result']['status']=='resolved' and not r.json()['result']['network_attempted']
        assert post(client,path,body,'sim').status_code==200 and len(calls)==1
        old=post(client,path,{**body,'search_id':task['id']},'oldlang')
        assert old.json()['output_language']=='zh-CN'
        missing=next(r for r in refs if not r['record']['doi'])
        r=post(client,lit+'/checks/references/'+missing['id']+'/receipts',body,'no-doi')
        assert r.status_code==201 and r.json()['result']['status']=='not_applicable'
        assert len(calls)==2
    finally:
        app.dependency_overrides.pop(get_check_service,None)


def test_synthetic_check_service_rejects_non_test_environment(tmp_path):
    from types import SimpleNamespace
    from app.adapters.doi import DoiClient
    from app.domain.literature_checks.service import LiteratureCheckService
    from app.core.exceptions import StorageError
    assets=SimpleNamespace(owner_id='offline',db_config=SimpleNamespace(environment='development'),directory=tmp_path)
    with pytest.raises(StorageError):
        LiteratureCheckService(assets,DoiClient(enabled=True,session=object(),execution_kind='synthetic_fixture'))


def test_rehashed_unexpected_result_fields_are_rejected(client):
    from app.domain.literature.service import digest
    _,lit,task,refs=seeded(client)
    path=lit+'/checks/references/'+refs[0]['id']
    r=post(client,path+'/receipts',dict(kind='saved_record',search_id=task['id']),'check')
    assert r.status_code==201,r.text
    with database_connection(write=True) as db:
        row=db.execute('SELECT * FROM literature_check_receipts').fetchone()
        snapshot=copy.deepcopy(row['snapshot_json']);snapshot['result']['response_body']='must not be accepted'
        db.execute('UPDATE literature_check_receipts SET snapshot_json=%s,snapshot_sha256=%s WHERE id=%s',(Jsonb(snapshot),digest(snapshot),row['id']))
    assert client.get(path+'/history').status_code==409


def test_doi_failures_are_independent_immutable_receipts(client):
    import requests
    from app.adapters.doi import DoiClient
    from app.api.literature_checks import get_check_service
    from app.api.dataset_preparation import Store
    from app.domain.literature_checks.service import LiteratureCheckService
    from app.main import app
    _,lit,task,refs=seeded(client)
    codes=iter([302,404,429,'timeout'])
    class Response:
        def __init__(self,code):
            self.status_code=code;self.headers={'Location':'https://publisher.example/offline'}
        def close(self): pass
    class Fixed:
        def get(self,*args,**kwargs):
            code=next(codes)
            if code=='timeout': raise requests.Timeout()
            return Response(code)
    adapter=DoiClient(enabled=True,session=Fixed(),execution_kind='synthetic_fixture')
    def factory(store:Store): return LiteratureCheckService(store,adapter)
    app.dependency_overrides[get_check_service]=factory
    try:
        path=lit+'/checks/references/'+refs[0]['id']
        results=[]
        for index,expected in enumerate(('resolved','not_found','rate_limited','timeout')):
            response=post(client,path+'/receipts',dict(kind='doi_resolution',search_id=task['id']),str(index))
            assert response.status_code==201,response.text
            assert response.json()['result']['status']==expected
            results.append(response.json())
        history=client.get(path+'/history').json()
        assert history['total']==4 and history['items']==list(reversed(results))
    finally:
        app.dependency_overrides.pop(get_check_service,None)


def test_source_row_language_drift_does_not_replace_saved_task_language(client):
    _,lit,task,refs=seeded(client)
    with database_connection(write=True) as db:
        row=db.execute('SELECT * FROM literature_searches WHERE task_id=%s',(task['id'],)).fetchone()
        changed={**row['input_json'],'output_language':'en'}
        db.execute('UPDATE literature_searches SET input_json=%s WHERE task_id=%s',(Jsonb(changed),task['id']))
    response=post(client,lit+'/checks/references/'+refs[0]['id']+'/receipts',dict(kind='saved_record',search_id=task['id']),'drift')
    assert response.status_code==201,response.text
    assert response.json()['output_language']=='zh-CN'
    assert response.json()['result']['status']=='source_conflict'
