"""Build file records and originals for migration rehearsals."""
from hashlib import sha256

from app.adapters.excel import parse_workbook
from app.core.config import ExcelSettings, get_data_dir
from app.db.database import database_connection
from tests.api.test_excel import workbook_bytes
from tests.db.test_task_schema import NOW, insert_row, seed_owner, task_row


def seed_workbook(db):
    seed_owner(db)
    content = workbook_bytes()
    original = get_data_dir() / 'files' / 'f.xlsx'
    original.parent.mkdir(parents=True, exist_ok=True)
    original.write_bytes(content)
    preview = parse_workbook(content, 'original.xlsx', ExcelSettings()).model_dump_json()
    db.execute('''INSERT INTO files(id,project_id,filename,file_type,size_bytes,sha256,uploaded_at,parse_status,preview_json)
        VALUES ('f','p','original.xlsx','xlsx',%s,%s,%s,'parsed',%s)''',
        (len(content), sha256(content).hexdigest(), NOW.isoformat(), preview))
    return original, content


def seed_document_parse(file_type):
    kind = {'xlsx': 'parse_file', 'docx': 'docx_document', 'pdf': 'pdf_document'}[file_type]
    digest = 'a' * 64
    filename = f'original.{file_type}'
    with database_connection(write=True) as db:
        seed_owner(db)
        db.execute('''INSERT INTO file_upload_batches(id,project_id,user_id,idempotency_key,request_digest,created_at)
            VALUES ('batch','p','u','upload',%s,%s)''', (digest, NOW))
        db.execute('''INSERT INTO file_upload_items(id,batch_id,ordinal,filename,size_bytes)
            VALUES ('item','batch',0,%s,32)''', (filename,))
        db.execute('''INSERT INTO files(id,project_id,filename,file_type,size_bytes,sha256,uploaded_at,
            parse_status,uploader_id,object_key,upload_item_id,parse_revision)
            VALUES ('f','p',%s,%s,32,%s,%s,'queued','u',%s,'item',1)''',
            (filename, file_type, digest, NOW.isoformat(), f'files/{filename}'))
        db.execute("UPDATE file_upload_items SET file_id='f' WHERE id='item'")
        insert_row(db, 'tasks', task_row(task_type='parse_file', workflow_version=f'{kind}_v1',
                   input_snapshot={'kind': kind, 'file': {'id': 'f', 'sha256': digest}, 'parse_id': 'parse'}))
        db.execute('''INSERT INTO file_parse_results(id,file_id,task_id,version,source_sha256,
            parser_version,settings_json,created_at) VALUES ('parse','f','t',1,%s,%s,'{}',%s)''',
            (digest, f'{file_type}-legacy', NOW))
