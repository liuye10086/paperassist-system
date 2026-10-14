"""Validate persisted Word references without opening asset files."""
import re
from app.adapters.task_store import source_conflict
from app.domain.documents.contracts import Counts, Warning
from app.domain.file_parsing import require_parse_source
from app.core.exceptions import StorageError

def validate_manifest(manifest, parse_id):
    if not isinstance(manifest,dict) or set(manifest)!={'kind','object','images','summary'} or manifest['kind'] not in ('docx_document','pdf_document','ocr_document'):
        raise source_conflict()
    def record(item,suffix):
        if (not isinstance(item,dict) or type(item.get('size_bytes')) is not int or item['size_bytes']<=0
            or not isinstance(item.get('sha256'),str) or not re.fullmatch('[0-9a-f]{64}',item['sha256'])
            or item.get('object_key')!=f"documents/{parse_id}/{item['sha256']}.{suffix}"):
            raise source_conflict()
    record(manifest['object'],'json')
    if manifest['object']['size_bytes']>4194304 or not isinstance(manifest['images'],list) or len(manifest['images'])>100:
        raise source_conflict()
    ids=set();total=0
    for image in manifest['images']:
        record(image,'bin')
        if not isinstance(image.get('id'),str) or image['id'] in ids or type(image.get('inline_preview')) is not bool or not isinstance(image.get('mime'),str) or not isinstance(image.get('part'),str):
            raise source_conflict()
        if image['inline_preview'] and image['mime'] not in ('image/png','image/jpeg'):
            raise source_conflict()
        ids.add(image['id']);total+=image['size_bytes']
    if total>16777216:
        raise source_conflict()
    try:
        from app.domain.documents.pdf_contracts import PdfCounts, PdfCountsV2, PdfWarning
        from app.domain.documents.ocr_contracts import OcrCounts
        pdf = manifest['kind']=='pdf_document'
        pdf_counts=PdfCountsV2 if 'embedded_images' in manifest['summary']['counts'] else PdfCounts
        counts=(OcrCounts if manifest['kind']=='ocr_document' else pdf_counts if pdf else Counts).model_validate(manifest['summary']['counts'])
        warnings=[(PdfWarning if pdf else Warning).model_validate(w) for w in manifest['summary']['warnings']]
        if (pdf and ids) or (not pdf and counts.images!=len(ids)):
            raise ValueError('Wrong image count')
        if manifest['kind']=='ocr_document' and (counts.pages!=len(ids) or counts.pages<1 or counts.pages_without_text>counts.pages):
            raise ValueError('Wrong OCR page counts')
    except (ValueError,KeyError,TypeError) as exc:
        raise source_conflict() from exc

def audit_documents(db):
    rows=db.execute("SELECT r.*,t.input_snapshot,t.workflow_version,t.project_id,t.user_id,t.task_type,t.status FROM file_parse_results r JOIN tasks t ON t.id=r.task_id WHERE t.workflow_version IN ('docx_document_v1','pdf_document_v1','ocr_document_v1') OR r.result_json->>'kind' IN ('docx_document','pdf_document','ocr_document')").fetchall()
    invalid=0
    for row in rows:
        try:
            task=dict(row,id=row['task_id'])
            require_parse_source(db,task)
            owner=db.execute('SELECT owner_id FROM projects WHERE id=%s',(row['project_id'],)).fetchone()
            if not owner or owner['owner_id']!=row['user_id'] or row['workflow_version'] not in ('docx_document_v1','pdf_document_v1','ocr_document_v1'):
                raise source_conflict()
            if row['result_json'] is not None:
                if row['status']!='succeeded':
                    raise source_conflict()
                validate_manifest(row['result_json'],row['id'])
                if row['result_json']['kind'] != row['input_snapshot']['kind']:
                    raise source_conflict()
        except (StorageError,ValueError,TypeError,KeyError):
            invalid+=1
    return [dict(table='file_parse_results',column='document_manifest',rows=len(rows),invalid=invalid)]
