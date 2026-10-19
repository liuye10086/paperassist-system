"""Synthetic bytes only; isolated database and private immutable provenance."""
import copy
import httpx
import pytest
from app.db.database import database_connection
from tests.api.test_analysis import client
from tests.api.test_literature import project, create
from tests.api.test_literature_evidence import post, claim
from tests.helpers.literature import SyntheticNcbi
from tests.domain.test_literature_pmc import xml


def prepare(client, tmp_path, *, body=True, license='https://creativecommons.org/licenses/by/4.0/'):
    from app.adapters.ncbi import parse_fetch
    from app.domain.literature.execution import run_literature_task
    from app.core.config import get_data_dir
    from app.db.database import get_database_config
    from app.adapters.storage import ProjectStore
    from app.domain.literature_live import Batch06Ledger
    class Ncbi(SyntheticNcbi):
        def fetch(self, pmids):
            raw=super().fetch(pmids).raw.replace(b'</ArticleIdList>',b'<ArticleId IdType="pmc">PMC123</ArticleId></ArticleIdList>')
            return parse_fetch(raw,pmids)
    pid=project(client); task=create(client,pid).json()
    assert run_literature_task(task['id'],1,client=Ncbi(2))['status']=='succeeded'
    refs=client.get(f'/api/v1/projects/{pid}/literature/references').json()['items']
    ref=next(r for r in refs if r['record']['abstract'])
    with database_connection() as db: owner=db.execute('SELECT owner_id FROM projects WHERE id=%s',(pid,)).fetchone()['owner_id']
    assets=ProjectStore(get_data_dir(),owner_id=owner)
    import importlib.util
    assert importlib.util.find_spec('app.domain.literature_pmc') is not None, 'PMC service is required'
    from app.domain.literature_pmc.service import LiteraturePmcService
    from app.adapters.pmc import PmcAdapter
    ledger=Batch06Ledger(tmp_path/'pmc-ledger.jsonl',batch_id='pmc-test',schema=get_database_config().schema,public_inputs=[],pmcids=['PMC123'])
    calls=[]
    def handler(req):
        calls.append(req)
        return httpx.Response(200,content=xml(pmid=ref['record']['pmid'],body=body,license=license))
    adapter=PmcAdapter(ledger,transport=httpx.MockTransport(handler))
    return pid,refs,ref,LiteraturePmcService(assets),adapter,calls,task


def test_private_receipt_quote_replay_original_tamper_and_audit(client,tmp_path):
    pid,refs,ref,svc,adapter,calls,search=prepare(client,tmp_path)
    receipt,status=svc.acquire(pid,ref['id'],'PMC123','fetch',adapter=adapter)
    assert status==201 and receipt['status']=='succeeded'
    assert svc.acquire(pid,ref['id'],'PMC123','fetch',adapter=adapter)==(receipt,200)
    assert len(calls)==2
    base=f'/api/v1/projects/{pid}/literature/pmc'
    assert client.get(base+'/receipts').json()['total']==1
    source=client.get(base+'/receipts/'+receipt['id']+'/source').json()
    item=source['items'][0]
    evidence_path=f'/api/v1/projects/{pid}/literature/evidence'
    c=claim(client,evidence_path)
    request=dict(claim_revision=1,project_reference_id=ref['id'],source_kind='pmc',pmc_receipt_id=receipt['id'],item_id=item['id'],quote='body text')
    response=post(client,evidence_path+'/claims/'+c['id']+'/evidence',request,'quote')
    assert response.status_code==201,response.text
    assert response.json()['reading_scope']=='pmc_fulltext'
    assert source['scope']['whole_article_verified'] is False
    assert post(client,evidence_path+'/claims/'+c['id']+'/evidence',{**request,'quote':'Abstract only.'},'abstract-forgery').status_code==422
    other=project(client)
    assert client.get(f'/api/v1/projects/{other}/literature/pmc/receipts/'+receipt['id']+'/source').status_code==404
    assert client.post(base+'/receipts',json={}).status_code in (404,405)
    from app.maintenance.literature_pmc_audit import audit_literature_pmc
    with database_connection() as db:
        assert all(v['invalid']==0 for v in audit_literature_pmc(db))
        row=db.execute('SELECT * FROM literature_pmc_receipts').fetchone()
    svc.objects.path(row['snapshot_json']['responses'][1]['object']['object_key']).write_bytes(b'tampered')
    assert client.get(evidence_path+'/claims/'+c['id']+'/evidence').status_code==409
    with database_connection() as db: assert any(v['invalid'] for v in audit_literature_pmc(db))


@pytest.mark.parametrize('kwargs,expected',[({'body':False},'pmc_body_missing'),({'license':''},'pmc_license_denied')])
def test_failure_receipt_cannot_quote(client,tmp_path,kwargs,expected):
    pid,refs,ref,svc,adapter,calls,_=prepare(client,tmp_path,**kwargs)
    receipt,_=svc.acquire(pid,ref['id'],'PMC123','fetch',adapter=adapter)
    assert receipt['status']==expected
    if expected=='pmc_body_missing': assert receipt['license']['code']=='CC-BY-4.0'
    source=svc.source(pid,receipt['id'])
    assert source['items']==[] and source['status']==expected
    path=f'/api/v1/projects/{pid}/literature/evidence'; c=claim(client,path)
    response=post(client,path+'/claims/'+c['id']+'/evidence',dict(claim_revision=1,project_reference_id=ref['id'],source_kind='pmc',pmc_receipt_id=receipt['id'],item_id='pmc-item-1',quote='Abstract only.'),'bad')
    assert response.status_code==422,response.text


def test_comparison_frozen_concise_multiple_refs_old_snapshot_and_manual_gate(client,tmp_path):
    from app.domain.literature_assistance.contracts import request_adapter,validate_result
    pid,refs,ref,svc,adapter,_,search=prepare(client,tmp_path)
    receipt,_=svc.acquire(pid,ref['id'],'PMC123','fetch',adapter=adapter)
    path=f'/api/v1/projects/{pid}/literature/evidence'; c=claim(client,path)
    first=post(client,path+'/claims/'+c['id']+'/evidence',dict(claim_revision=1,project_reference_id=ref['id'],source_kind='abstract',search_id=search['id'],quote='Synthetic protocol fixture'),'e1').json()
    second_ref=next(r for r in refs if r['id']!=ref['id'])
    second_receipt,_=svc.acquire(pid,second_ref['id'],'PMC123','fetch-other',adapter=adapter)
    second=post(client,path+'/claims/'+c['id']+'/evidence',dict(claim_revision=1,project_reference_id=second_ref['id'],source_kind='pmc',pmc_receipt_id=second_receipt['id'],item_id='pmc-item-1',quote='Actual body text.'),'e2')
    # This adapter always returns first PMID: mismatched body cannot be evidence.
    assert second.status_code==422
    adapter.client.close()
    adapter.client=httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(200,content=xml(pmid=second_ref['record']['pmid']))))
    second_receipt,_=svc.acquire(pid,second_ref['id'],'PMC123','fetch-other-good',adapter=adapter)
    second=post(client,path+'/claims/'+c['id']+'/evidence',dict(claim_revision=1,project_reference_id=second_ref['id'],source_kind='pmc',pmc_receipt_id=second_receipt['id'],item_id='pmc-item-1',quote='Actual body text.'),'e2good').json()
    url=f'/api/v1/projects/{pid}/literature/assistance/tasks'
    old=dict(kind='evidence_review',claim_id=c['id'],claim_revision=1,project_reference_id=ref['id'],evidence_ids=[first['id']],output_language='en')
    old_task=post(client,url,old,'old').json()
    with database_connection() as db: old_snapshot=copy.deepcopy(db.execute('SELECT input_snapshot FROM tasks WHERE id=%s',(old_task['id'],)).fetchone()['input_snapshot'])
    req=dict(kind='evidence_comparison',claim_id=c['id'],claim_revision=1,evidence_ids=[first['id'],second['id']],output_language='en')
    request_adapter.validate_python(req)
    response=post(client,url,req,'compare');assert response.status_code==202,response.text
    from app.domain.literature_assistance.service import require_snapshot
    with database_connection() as db:
        task=db.execute('SELECT * FROM tasks WHERE id=%s',(response.json()['id'],)).fetchone()
        snapshot=require_snapshot(task)
        assert snapshot['schema_version']==2
        assert len(snapshot['material']['references'])==2
        assert all('abstract' not in r['record'] for r in snapshot['material']['references'])
        assert db.execute('SELECT input_snapshot FROM tasks WHERE id=%s',(old_task['id'],)).fetchone()['input_snapshot']==old_snapshot
        assert require_snapshot(db.execute('SELECT * FROM tasks WHERE id=%s',(old_task['id'],)).fetchone())==old_snapshot
        assert db.execute('SELECT count(*) AS n FROM literature_claim_reviews').fetchone()['n']==0
    result=dict(status='supported',relevance='related',reason='Comparison',narrowed_statement='',limitations=['Selected excerpts only'],evidence_ids=req['evidence_ids'],comparison='conflicting')
    with pytest.raises(ValueError): validate_result(result,snapshot)
    result['status']='needs_review'; assert validate_result(result,snapshot)['comparison']=='conflicting'
    assert post(client,url,{**req,'evidence_ids':[first['id']]},'one-ref').status_code==422
    assert post(client,url,{**req,'evidence_ids':[first['id'],first['id']]},'duplicate').status_code==422
    from app.domain.literature_assistance.execution import run_assistance_task
    waiting=run_assistance_task(task['id'],task['revision'])
    assert waiting['status']=='waiting_confirmation'
    workspace=client.get('/api/v1/tasks/'+task['id']+'/workspace')
    assert workspace.status_code==200,workspace.text
    assert workspace.json()['task']['input_version']['assistance_kind']=='evidence_comparison'
    from tests.api.test_literature_citations import draft_body,paragraph
    forged=post(client,f'/api/v1/projects/{pid}/literature/citations/drafts',draft_body(paragraph(c,dict(review_id=task['id'],metadata_version_id='not-a-manual-review'))),'comparison-is-not-review')
    assert forged.status_code in (404,409),forged.text


def test_empty_http_failure_and_restricted_acquisition(client,tmp_path):
    from app.core.exceptions import StorageError
    pid,refs,ref,svc,adapter,calls,_=prepare(client,tmp_path)
    with pytest.raises(StorageError,match='尚未授权'): svc.acquire(pid,ref['id'],'PMC123','unauthorized')
    with pytest.raises(StorageError): svc.acquire(pid,ref['id'],'PMC999','not-existing',adapter=adapter)
    assert calls==[]
    adapter.client.close()
    adapter.client=httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(503,content=b'')))
    receipt,_=svc.acquire(pid,ref['id'],'PMC123','empty',adapter=adapter)
    assert receipt['status']=='pmc_http_failed'
    assert svc.raw(pid,receipt['id'],0)==b''
    with pytest.raises(StorageError): svc.acquire(pid,refs[0]['id'],'PMC999','empty',adapter=adapter)


@pytest.mark.parametrize('kind',['budget','partial','truncated','excluded'])
def test_review_failure_receipts_remain_readable_auditable_and_cannot_quote(client,tmp_path,kind):
    from tests.domain.test_literature_pmc_review import reserve,Interrupted
    from app.adapters.pmc import MAX_BYTES
    from app.maintenance.literature_pmc_audit import audit_literature_pmc
    pid,refs,ref,svc,adapter,calls,_=prepare(client,tmp_path)
    if kind=='budget': reserve(adapter.ledger,11)
    if kind!='budget':
        adapter.client.close()
        def handle(req):
            if req.url.params['metadataPrefix']=='pmc_fm': return httpx.Response(200,content=xml())
            if kind=='partial': return httpx.Response(200,stream=Interrupted())
            if kind=='truncated': return httpx.Response(200,content=b'x'*(MAX_BYTES+17))
            return httpx.Response(200,content=xml().replace(b'<body>',b'<body><fig>').replace(b'</body>',b'</fig></body>'))
        adapter.client=httpx.Client(transport=httpx.MockTransport(handle))
    receipt,_=svc.acquire(pid,ref['id'],'PMC123','review-failure',adapter=adapter)
    expected=dict(budget='pmc_request_failed',partial='pmc_request_failed',truncated='pmc_response_too_large',excluded='pmc_body_missing')[kind]
    assert receipt['status']==expected and receipt['license']['code']=='CC-BY-4.0'
    response=receipt['responses'][1]
    assert response['capture_status']==dict(budget='not_requested',partial='partial',truncated='truncated',excluded='complete')[kind]
    if kind=='budget':
        assert response['attempted'] is False and response['admission_code']=='live_budget_exhausted'
        assert adapter.ledger.summary()['pmc_attempts']==12 and len(calls)==1
    else:
        raw=svc.raw(pid,receipt['id'],1)
        assert len(raw)==response['retained_bytes']<=MAX_BYTES
    assert svc.source(pid,receipt['id'])['items']==[]
    path=f'/api/v1/projects/{pid}/literature/evidence';c=claim(client,path)
    denied=post(client,path+'/claims/'+c['id']+'/evidence',dict(claim_revision=1,project_reference_id=ref['id'],source_kind='pmc',pmc_receipt_id=receipt['id'],item_id='pmc-item-1',quote='Actual body text.'),'forged')
    assert denied.status_code==422,denied.text
    with database_connection() as db:
        assert all(row['invalid']==0 for row in audit_literature_pmc(db))
    if kind=='partial':
        with database_connection() as db:
            row=db.execute('SELECT * FROM literature_pmc_receipts WHERE id=%s',(receipt['id'],)).fetchone()
        svc.objects.path(row['snapshot_json']['responses'][1]['object']['object_key']).write_bytes(b'changed partial bytes')
        assert client.get(f'/api/v1/projects/{pid}/literature/pmc/receipts/'+receipt['id']+'/source').status_code==409
        with database_connection() as db: assert any(row['invalid'] for row in audit_literature_pmc(db))
