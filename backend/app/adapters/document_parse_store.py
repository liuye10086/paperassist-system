"""Word publication through the existing lease and immutable object store."""
from datetime import timezone
from psycopg.types.json import Jsonb
from app.adapters.file_parse_store import FileParseStore
from app.adapters.task_store import TaskStore, source_conflict
from app.domain.file_parsing import require_parse_source

class DocumentParseStore(FileParseStore):
    def complete(self, lease, snapshot, result):
        from app.adapters.document_objects import DocumentObjects
        from app.domain.documents.contracts import DocxParseResult
        from app.domain.documents.pdf_contracts import PdfParseResult
        from app.core.exceptions import StorageError
        try:
            from app.domain.documents.ocr_contracts import OcrParseResult
            model = OcrParseResult if snapshot['kind']=='ocr_document' else PdfParseResult if snapshot['kind']=='pdf_document' else DocxParseResult
            result = model.model_validate(result.model_dump() if hasattr(result,'model_dump') else result,strict=True)
            if result.document.filename != snapshot['file']['filename'] or result.document.parser_version != snapshot['parser_version']:
                raise ValueError('Wrong document source')
            if snapshot['kind']=='ocr_document':
                from app.adapters.ocr_result_validation import validate_ocr_document
                validate_ocr_document(result.document,snapshot)
        except (ValueError,TypeError,StorageError) as exc:
            raise StorageError('parse_output_invalid','解析结果不完整，请检查文件后重试。',422) from exc
        repo=self.repository
        # Confirm source/lease before saving and again in the publish transaction.
        with repo.connection() as db:
            task=repo.require_lease(db,lease);repo.require_owner(db,task)
            if require_parse_source(db,task) != snapshot:
                raise source_conflict()
        saved=DocumentObjects(repo.assets.directory).save(snapshot['parse_id'],result)
        with repo.connection(write=True) as db:
            task=repo.require_lease(db,lease);repo.require_owner(db,task)
            if require_parse_source(db,task) != snapshot:
                raise source_conflict()
            repo.assets.original(snapshot['file']);repo.require_lease(db,lease)
            now=repo.now(db)
            changed=db.execute('UPDATE file_parse_results SET completed_at=%s,result_json=%s WHERE id=%s AND task_id=%s AND result_json IS NULL',(now,Jsonb(saved),snapshot['parse_id'],task['id']))
            if changed.rowcount != 1:
                raise source_conflict()
            repo._finish(db,task,'succeeded',None)
            db.execute('UPDATE projects SET updated_at=GREATEST(updated_at,%s) WHERE id=%s',
                       (now.astimezone(timezone.utc).isoformat(),task['project_id']))
            return TaskStore.public_task(task)
