"""Seed immutable legacy PDF objects in an isolated test schema; never convert."""
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
from psycopg.types.json import Jsonb
from app.db.database import database_connection
from app.core.config import get_data_dir
from app.domain.report_collections.service import scoped_store
from app.domain.docx_sources import DocxSourceReader
from app.domain.pdf_exports.service import PdfExportService
from app.domain.manuscripts.service import now
from app.domain.literature.service import digest
from app.adapters.task_store import TaskStore


def historical_pdf(path,source_kind,source_id,*,raw=b'%PDF-1.7\nsynthetic historical fixture',key=None):
    project=path.split('/projects/',1)[1].split('/',1)[0]
    identifier=str(uuid4());moment=now();key=key or 'historical-'+identifier
    manifest={'contract':'test-v1'}
    with database_connection(write=True) as db:
        assert db.config.schema.startswith('pa_test_')
        owner=db.execute('SELECT owner_id FROM projects WHERE id=%s',(project,)).fetchone()['owner_id']
        assets=scoped_store(owner,db.config,get_data_dir());store=TaskStore(owner,db.config)
        source,docx=DocxSourceReader(assets).source(db,project,source_kind,source_id)
        source_sha=sha256(docx).hexdigest()
        snapshot=dict(project_id=project,source_kind=source_kind,source_id=source_id,source_sha256=source_sha,source=source,renderer_identity=manifest,workflow_version='pdf_export_v1')
        task=dict(id=str(uuid4()),project_id=project,user_id=owner,task_type='pdf_export',idempotency_key='historical-pdf:'+identifier,input_snapshot=dict(export_id=identifier,**snapshot),workflow_version='pdf_export_v1',status='queued',phase='export',revision=1,current_attempt=0,reason_code=None,created_at=moment,updated_at=moment)
        task['input_digest']=digest(task['input_snapshot']);store.insert_task(db,task);store.append_event(db,task,'created')
        task.update(status='succeeded',revision=2)
        db.execute("UPDATE tasks SET status='succeeded',revision=2 WHERE id=%s",(task['id'],));store.append_event(db,task,'succeeded')
        name=identifier+'-'+str(uuid4())+'.pdf'
        metadata=dict(filename=Path(source['metadata']['filename']).stem+'.pdf',sha256=sha256(raw).hexdigest(),size_bytes=len(raw),source_sha256=source_sha,input_sha256=digest(snapshot),renderer_manifest=manifest,object_name=name)
        target=assets.directory/'pdf_exports'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        fields=dict(id=identifier,project_id=project,user_id=owner,source_kind=source_kind,source_id=source_id,task_id=task['id'],parent_export_id=None,request_key=key,request_digest=digest(dict(source_kind=source_kind,source_id=source_id,parent_export_id=None)),input_json=Jsonb(snapshot),input_sha256=digest(snapshot),source_sha256=source_sha,renderer_identity=Jsonb(manifest),metadata_json=Jsonb(metadata),created_at=moment)
        column={'report':'report_id','collection_report':'collection_report_id','manuscript_export':'manuscript_export_id','layout_export':'layout_export_id','review_document_export':'review_document_export_id','research_report':'research_report_member_id'}[source_kind];fields[column]=source_id
        db.execute('INSERT INTO pdf_exports('+','.join(fields)+') VALUES ('+','.join(['%s']*len(fields))+')',tuple(fields.values()))
        return PdfExportService(assets).view(db,PdfExportService(assets).row(db,project,identifier))
