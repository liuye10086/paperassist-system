"""A bounded literal CSV/TSV parser with a real persisted parse identity."""
import csv
import io
import time

from pydantic import Field
from typing import Literal

from app.adapters.bio_insights_store import invalid,identity,now
from app.adapters.task_store import TaskStore
from app.domain.bioinformatics.contracts import digest
from app.domain.bioinformatics.service import append_checkpoint
from .contracts import StrictModel,Identifier,Hash

PARSER_VERSION='bio_insight_table_v1'
LIMITS=dict(max_bytes=10485760,max_rows=100000,max_columns=256,max_cells=1000000,timeout_seconds=20)


class TableParseSnapshot(StrictModel):
    schema_version: Literal[1] = 1
    kind: Literal['parse_file'] = 'parse_file'
    project: 'TableProject'
    file: 'TableFile'
    parse_id: Identifier
    parser_version: Literal['bio_insight_table_v1'] = PARSER_VERSION
    settings: 'TableSettings'


class TableProject(StrictModel):
    id: Identifier


class TableFile(StrictModel):
    id: Identifier
    filename: str = Field(min_length=1,max_length=255)
    sha256: Hash
    size_bytes: int = Field(ge=1,le=10485760)
    file_type: Literal['bio_component']
    storage_backend: Literal['local']
    object_key: str = Field(min_length=1,max_length=1000)


class TableSettings(StrictModel):
    max_bytes: Literal[10485760]
    max_rows: Literal[100000]
    max_columns: Literal[256]
    max_cells: Literal[1000000]
    timeout_seconds: Literal[20]
    delimiter: Literal[',','\t']
    encoding: Literal['utf-8-sig']
    header_row: Literal[1]


TableParseSnapshot.model_rebuild()


def scan(content,filename):
    if not 0<len(content)<=LIMITS['max_bytes']:raise invalid('bio_insight_table_limit_exceeded',422)
    delimiter='\t' if filename.lower().endswith('.tsv') else ','
    started=time.monotonic();cells=0;rows=0
    try:
        reader=csv.reader(io.StringIO(content.decode('utf-8-sig'),newline=''),delimiter=delimiter,strict=True)
        headers=next(reader)
        if not headers or len(headers)>256 or len(set(headers))!=len(headers) or any(not h or len(h)>200 for h in headers):raise ValueError('headers')
        for row in reader:
            if len(row)!=len(headers):raise ValueError('column count')
            rows+=1;cells+=len(row)
            if rows>100000 or cells>1000000 or time.monotonic()-started>20:raise invalid('bio_insight_table_limit_exceeded',422)
    except (UnicodeError,csv.Error,ValueError,StopIteration) as exc:raise invalid('bio_insight_table_invalid',422) from exc
    return dict(schema_version=1,headers=headers,total_rows=rows,total_cells=cells,delimiter=delimiter,
                encoding='utf-8-sig',header_row=1,literal_values=True,source_sha256=__import__('hashlib').sha256(content).hexdigest())


def persist(store,db,project,file,content):
    from psycopg.types.json import Jsonb
    parsed=scan(content,file['filename']);parse_id=identity(project,'table-parse',file['id']);task_id=identity(project,'table-parse-task',file['id']);moment=now()
    snapshot=TableParseSnapshot(project={'id':project},file={key:file[key] for key in ('id','filename','sha256','size_bytes','file_type','storage_backend','object_key')},
        parse_id=parse_id,settings={**LIMITS,'delimiter':parsed['delimiter'],'encoding':'utf-8-sig','header_row':1}).model_dump(mode='json')
    task=dict(id=task_id,project_id=project,user_id=store.user_id,task_type='parse_file',idempotency_key='bio-table:'+file['id'],
        input_digest=digest(snapshot),input_snapshot=snapshot,workflow_version=PARSER_VERSION,status='running',phase='parse',revision=1,
        current_attempt=1,reason_code=None,created_at=moment,updated_at=moment)
    store.insert_task(db,task,validated_file_ids=[file['id']]);store.append_event(db,task,'created');store.start_attempt(db,task)
    cp=append_checkpoint(db,task,'check','check',dict(input_version=dict(kind='parse_file',parse_id=parse_id,source_sha256=file['sha256'],parser_version=PARSER_VERSION),stage='literal_table_scan'))
    db.execute('INSERT INTO file_parse_results(id,file_id,task_id,version,source_sha256,parser_version,settings_json,created_at,completed_at,result_json) VALUES(%s,%s,%s,1,%s,%s,%s,%s,%s,%s)',
        (parse_id,file['id'],task_id,file['sha256'],PARSER_VERSION,Jsonb(snapshot['settings']),moment,moment,Jsonb(parsed)))
    task.update(status='succeeded',phase='verify',revision=2,updated_at=now(),error_code=None)
    append_checkpoint(db,task,'done','done',dict(input_version=dict(kind='parse_file',parse_id=parse_id,source_sha256=file['sha256'],parser_version=PARSER_VERSION),parse_result_id=parse_id),cp)
    TaskStore.finish_attempt(db,task);TaskStore.update_task(db,task,1);TaskStore.append_event(db,task,'succeeded')
    db.execute("UPDATE files SET parse_status='parsed',parse_revision=1 WHERE id=%s",(file['id'],))
    return parse_id
