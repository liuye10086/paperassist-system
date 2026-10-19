"""Actual exported XML replayed only in disposable isolated database fixtures."""
import copy
import json
from datetime import datetime,timezone
from uuid import uuid4
import httpx
import pytest
from psycopg.types.json import Jsonb
from tests.api.test_analysis import client
from tests.api.test_literature import project,create
from tests.helpers.literature import SyntheticNcbi
from tests.domain.test_literature_pmc_license_versions import actual,INPUTS
from app.db.database import database_connection,get_database_config
from app.domain.literature.service import digest


def setup(client,identity):
    from app.adapters.ncbi import parse_fetch
    from app.domain.literature.execution import run_literature_task
    from app.core.config import get_data_dir
    from app.adapters.task_store import DatasetTaskAssets
    from app.domain.literature_pmc.service import LiteraturePmcService
    entry,raw=actual(identity)
    class Ncbi(SyntheticNcbi):
        def __init__(self):
            super().__init__(1);self.ids=[entry['pmid']]
        def fetch(self,pmids):
            return parse_fetch((f'<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>{entry["pmid"]}</PMID><Article><ArticleTitle>Synthetic bibliography fixture for exported source replay</ArticleTitle></Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="pmc">{identity}</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>').encode(),pmids)
    pid=project(client);task=create(client,pid).json()
    assert run_literature_task(task['id'],1,client=Ncbi())['status']=='succeeded'
    ref=client.get(f'/api/v1/projects/{pid}/literature/references').json()['items'][0]
    with database_connection() as db: owner=db.execute('SELECT owner_id FROM projects WHERE id=%s',(pid,)).fetchone()['owner_id']
    svc=LiteraturePmcService(DatasetTaskAssets(owner,get_database_config(),get_data_dir()))
    return entry,raw,pid,ref,svc


@pytest.mark.parametrize('identity',['PMC12529328','PMC6827248','PMC12085591'])
@pytest.mark.parametrize('capture_fields_missing',[False,True])
def test_actual_v1_receipt_shape_status_digest_and_bytes_stay_readable(client,identity,capture_fields_missing):
    entry,raw,pid,ref,svc=setup(client,identity)
    exported=json.loads((INPUTS/'historical_receipts.json').read_text(encoding='utf-8'))[identity]
    response=copy.deepcopy(exported['responses'][0])
    if capture_fields_missing:
        for field in ('attempted','capture_status','received_bytes','retained_bytes','byte_limit','admission_code'):
            response.pop(field)
    response['object']=svc.objects.save(raw,'pmc_oai')
    snapshot=dict(status=exported['status'],source_kind=exported['source_kind'],responses=[response],metadata=None,parsed=None)
    original=copy.deepcopy(snapshot);body=dict(project_reference_id=ref['id'],pmcid=identity)
    with svc.store.connection(write=True) as db:
        row=db.execute('''INSERT INTO literature_pmc_receipts(id,project_id,user_id,project_reference_id,reference_id,pmcid,pmid,source_kind,status,idempotency_key,request_digest,request_json,snapshot_json,snapshot_sha256,created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *''',
            (str(uuid4()),pid,svc.store.user_id,ref['id'],ref['reference_id'],identity,entry['pmid'],snapshot['source_kind'],snapshot['status'],'historical',digest(body),Jsonb(body),Jsonb(snapshot),digest(snapshot),datetime.now(timezone.utc))).fetchone()
        before=row['snapshot_sha256']
        assert svc.actual(db,pid,row)==original
        view=svc.view(db,pid,row)
        assert view['status']=='pmc_license_denied' and 'parser_version' not in view
        assert view['responses'][0]['capture_recorded'] is not capture_fields_missing
    assert svc.raw(pid,row['id'],0)==raw
    replay,status=svc.acquire(pid,ref['id'],identity,'historical')
    assert status==200 and replay['status']=='pmc_license_denied' and 'parser_version' not in replay
    api=client.get(f'/api/v1/projects/{pid}/literature/pmc/receipts/'+row['id']+'/source')
    assert api.status_code==200,api.text
    assert api.json()['status']=='pmc_license_denied' and api.json()['items']==[]
    assert api.json()['source']['responses'][0]['capture_recorded'] is not capture_fields_missing
    with database_connection() as db:
        saved=db.execute('SELECT * FROM literature_pmc_receipts WHERE id=%s',(row['id'],)).fetchone()
        assert saved['snapshot_json']==original and saved['snapshot_sha256']==before
        from app.maintenance.literature_pmc_audit import audit_literature_pmc
        assert all(c['invalid']==0 for c in audit_literature_pmc(db))


def test_new_receipt_records_v2_and_rebuilds_article_data_scope(client,tmp_path):
    from app.adapters.pmc import PmcAdapter
    from app.domain.literature_live import Batch06Ledger
    entry,raw,pid,ref,svc=setup(client,'PMC6827248')
    synthetic_body=raw.replace(b'</article>',b'<body><p>Synthetic body for parser version test only.</p></body></article>')
    ledger=Batch06Ledger(tmp_path/'ledger',batch_id='license-v2',schema=get_database_config().schema,public_inputs=[],pmcids=['PMC6827248'])
    adapter=PmcAdapter(ledger,transport=httpx.MockTransport(lambda req:httpx.Response(200,content=raw if req.url.params['metadataPrefix']=='pmc_fm' else synthetic_body)))
    view,_=svc.acquire(pid,ref['id'],'PMC6827248','v2',adapter=adapter)
    assert view['status']=='succeeded' and view['parser_version']==2
    assert view['license']['code']=='CC-BY-4.0' and view['license']['data_licenses'][0]['scope']=='data'
    with database_connection() as db:
        row=db.execute('SELECT * FROM literature_pmc_receipts WHERE id=%s',(view['id'],)).fetchone()
        assert row['snapshot_json']['parser_version']==2
        assert svc.actual(db,pid,row)==row['snapshot_json']
