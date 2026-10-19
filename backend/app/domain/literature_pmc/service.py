"""Append-only private receipts and reconstruction from actual saved XML bytes."""
from uuid import uuid4
from datetime import datetime,timezone
from psycopg.types.json import Jsonb
from app.adapters.pmc import PmcAdapter,parse_record,PmcError,MAX_BYTES
from app.adapters.task_store import TaskStore,source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_preparation.service import require_key
from app.domain.literature.service import LiteratureService,digest
from app.domain.literature.objects import LiteratureObjects


def capture_fields(response,raw):
    """Validate transport capture facts; incomplete bytes are never parsed."""
    keys={'attempted','capture_status','received_bytes','retained_bytes','byte_limit','admission_code'}
    if not keys.intersection(response):
        # Pre-review receipts remain readable without modifying their snapshot.
        return dict(attempted=True,capture_status='complete' if raw is not None else 'not_received',
            received_bytes=len(raw) if raw is not None else 0,retained_bytes=len(raw) if raw is not None else 0,
            byte_limit=MAX_BYTES,admission_code=None)
    if not keys<=set(response): raise ValueError()
    capture={key:response[key] for key in keys}
    retained=0 if raw is None else len(raw)
    if (type(capture['attempted']) is not bool or any(type(capture[k]) is not int for k in ('received_bytes','retained_bytes','byte_limit'))
        or capture['byte_limit']!=MAX_BYTES or not 0<=retained<=MAX_BYTES
        or capture['retained_bytes']!=retained or capture['received_bytes']<retained): raise ValueError()
    state=capture['capture_status'];error=response['error'];http=response['http_status']
    if state=='not_requested':
        if (capture['attempted'] or raw is not None or http is not None or capture['received_bytes']!=0
            or error!='pmc_request_failed' or not isinstance(capture['admission_code'],str) or not capture['admission_code']): raise ValueError()
        return capture
    if not capture['attempted'] or capture['admission_code'] is not None: raise ValueError()
    if state=='not_received':
        if raw is not None or http is not None or capture['received_bytes']!=0 or error!='pmc_request_failed': raise ValueError()
        return capture
    if raw is None or type(http) is not int or not 100<=http<=599: raise ValueError()
    if state=='truncated':
        if error!='pmc_response_too_large' or retained!=MAX_BYTES or capture['received_bytes']<=MAX_BYTES: raise ValueError()
    elif state=='partial':
        if error!='pmc_request_failed' or capture['received_bytes']!=retained: raise ValueError()
    elif state=='complete':
        if capture['received_bytes']!=retained or error in ('pmc_request_failed','pmc_response_too_large'): raise ValueError()
    else: raise ValueError()
    return capture


class LiteraturePmcService:
    def __init__(self,assets):
        self.assets=assets
        self.store=TaskStore(assets.owner_id,assets.db_config)
        self.literature=LiteratureService(assets)
        self.objects=LiteratureObjects(assets.directory)

    def bibliography(self,db,project,ref):
        reference=self.literature.require_reference(db,project,ref)
        view=self.literature.reference_view(db,reference)
        hit=db.execute('SELECT * FROM literature_search_hits WHERE receipt_id=%s AND project_reference_id=%s',
            (view['source']['receipt_id'],ref)).fetchone()
        receipt=db.execute('SELECT * FROM literature_fetch_receipts WHERE id=%s',(hit['receipt_id'],)).fetchone()
        from app.adapters.ncbi import parse_fetch
        try:
            records=parse_fetch(self.literature.objects.read(receipt),receipt['request_json']['pmids']).records
            if next((r for r in records if r['pmid']==view['pmid']),None)!=hit['record_json']: raise ValueError()
        except Exception as exc: raise source_conflict() from exc
        return reference,view

    def row(self,db,project,identity):
        self.store.require_project(db,project)
        row=db.execute('SELECT * FROM literature_pmc_receipts WHERE id=%s AND project_id=%s AND user_id=%s',
            (identity,project,self.store.user_id)).fetchone()
        if not row: raise StorageError('literature_not_found','PMC回执不存在。',404)
        return row

    def actual(self,db,project,row):
        try:
            request=row['request_json'];snapshot=row['snapshot_json']
            if (digest(request)!=row['request_digest'] or digest(snapshot)!=row['snapshot_sha256']
                or request!=dict(project_reference_id=row['project_reference_id'],pmcid=row['pmcid'])
                or snapshot['status']!=row['status'] or snapshot['source_kind']!=row['source_kind']): raise ValueError()
            reference,view=self.bibliography(db,project,row['project_reference_id'])
            if (reference['reference_id']!=row['reference_id'] or view['pmid']!=row['pmid']
                or not self.has_pmcid(view['record'],row['pmcid'])): raise ValueError()
            parsed=None; metadata=None; status='succeeded'
            parser_version=snapshot.get('parser_version',1)
            if type(parser_version) is not int or parser_version not in (1,2): raise ValueError()
            responses=snapshot['responses']
            if not 1<=len(responses)<=2: raise ValueError()
            for index,response in enumerate(responses):
                prefix=('pmc_fm','pmc')[index]
                if response['metadata_prefix']!=prefix: raise ValueError()
                raw=self.objects.read(response['object']) if response['object'] else None
                capture=capture_fields(response,raw)
                if response['error'] in ('pmc_request_failed','pmc_response_too_large'):
                    if index!=len(responses)-1: raise ValueError()
                    if not capture['attempted'] and (index!=1 or metadata is None): raise ValueError()
                    status=response['error'];break
                if raw is None: raise ValueError()
                try:
                    if response['http_status']!=200: raise PmcError('pmc_http_failed')
                    current=parse_record(raw,row['pmcid'],row['pmid'],fulltext=index==1,parser_version=parser_version)
                    if index==0: metadata=current
                    if parsed and parsed['license']['code']!=current['license']['code']: raise PmcError('pmc_license_denied')
                    parsed=current
                except PmcError as exc:
                    status=str(exc)
                    if response['error']!=status or index!=len(responses)-1: raise ValueError()
                    break
                if response['error'] is not None: raise ValueError()
            if status=='succeeded' and len(responses)!=2: raise ValueError()
            if status!=row['status'] or snapshot['metadata']!=metadata or snapshot['parsed']!=(parsed if status=='succeeded' else None): raise ValueError()
            return snapshot
        except StorageError: raise
        except Exception as exc: raise source_conflict() from exc

    def view(self,db,project,row):
        snapshot=self.actual(db,project,row)
        parsed=snapshot['parsed']
        metadata=snapshot['metadata']
        return dict(**({'parser_version':snapshot['parser_version']} if 'parser_version' in snapshot else {}),
            id=row['id'],project_reference_id=row['project_reference_id'],pmcid=row['pmcid'],pmid=row['pmid'],
            source_kind=row['source_kind'],status=row['status'],license=metadata['license'] if metadata else None,
            scope=parsed['scope'] if parsed else None,created_at=row['created_at'].astimezone(timezone.utc).isoformat(),
            responses=[dict(metadata_prefix=r['metadata_prefix'],http_status=r['http_status'],error=r['error'],
                capture_recorded='capture_status' in r,
                **capture_fields(r,self.objects.read(r['object']) if r['object'] else None),
                sha256=r['object']['sha256'] if r['object'] else None,
                source_download_url=f'/api/v1/projects/{project}/literature/pmc/receipts/{row["id"]}/raw/{i}') for i,r in enumerate(snapshot['responses'])])

    def acquire(self,project,project_reference_id,pmcid,key,*,adapter=None):
        require_key(key)
        body=dict(project_reference_id=project_reference_id,pmcid=pmcid)
        with self.store.connection(write=True) as db:
            self.store.require_project(db,project)
            db.execute('SELECT id FROM projects WHERE id=%s FOR UPDATE',(project,)).fetchone()
            previous=db.execute('SELECT * FROM literature_pmc_receipts WHERE project_id=%s AND user_id=%s AND idempotency_key=%s',
                (project,self.store.user_id,key)).fetchone()
            if previous:
                if previous['request_digest']!=digest(body): raise StorageError('task_idempotency_conflict','请求标识已用于不同输入。',409)
                return self.view(db,project,previous),200
            if (type(adapter) is not PmcAdapter or self.store.config.environment!='test'
                or self.store.config.url.database!='paperassist_system_test'
                or adapter.ledger.policy['schema']!=self.store.config.schema):
                raise StorageError('literature_pmc_not_authorized','尚未授权PMC获取。',409)
            reference,view=self.bibliography(db,project,project_reference_id)
            if not self.has_pmcid(view['record'],pmcid): raise StorageError('task_input_invalid','PMCID必须来自此项目已取得的书目。',422)
            result=adapter.fetch(pmcid,view['pmid'])
            for response in result['responses']:
                raw=response.pop('raw')
                response['object']=self.objects.save(raw,'pmc_oai') if raw is not None else None
            now=datetime.now(timezone.utc)
            row=db.execute('''INSERT INTO literature_pmc_receipts
                (id,project_id,user_id,project_reference_id,reference_id,pmcid,pmid,source_kind,status,idempotency_key,
                request_digest,request_json,snapshot_json,snapshot_sha256,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *''',
                (str(uuid4()),project,self.store.user_id,reference['id'],reference['reference_id'],pmcid,view['pmid'],
                result['source_kind'],result['status'],key,digest(body),Jsonb(body),Jsonb(result),digest(result),now)).fetchone()
            return self.view(db,project,row),201

    @staticmethod
    def has_pmcid(record,pmcid):
        return dict(url=f'https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/',source='PMC') in record.get('full_text_links',[])

    def list(self,project,page=1,project_reference_id=None):
        with self.store.connection() as db:
            self.store.require_project(db,project)
            args=(project,self.store.user_id,project_reference_id,project_reference_id)
            where='project_id=%s AND user_id=%s AND (%s::text IS NULL OR project_reference_id=%s)'
            total=db.execute('SELECT count(*) AS n FROM literature_pmc_receipts WHERE '+where,args).fetchone()['n']
            rows=db.execute('SELECT * FROM literature_pmc_receipts WHERE '+where+' ORDER BY created_at DESC,id LIMIT 10 OFFSET %s',(*args,(page-1)*10)).fetchall()
            return dict(items=[self.view(db,project,r) for r in rows],total=total,page=page,page_size=10)

    def source(self,project,identity,page=1):
        with self.store.connection() as db:
            row=self.row(db,project,identity);snapshot=self.actual(db,project,row)
            parsed=snapshot['parsed'];items=parsed['items'] if parsed else []
            return dict(source=self.view(db,project,row),status=row['status'],scope=parsed['scope'] if parsed else None,
                items=items[(page-1)*20:page*20],total=len(items),page=page,page_size=20)

    def raw(self,project,identity,index):
        with self.store.connection() as db:
            row=self.row(db,project,identity);snapshot=self.actual(db,project,row)
            if index<0 or index>=len(snapshot['responses']) or not snapshot['responses'][index]['object']:
                raise StorageError('literature_not_found','未取得此原文。',404)
            return self.objects.read(snapshot['responses'][index]['object'])
