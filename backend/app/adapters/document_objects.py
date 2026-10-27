"""Immutable hash-verified JSON and original embedded image objects."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
from uuid import UUID, uuid4
from app.core.exceptions import StorageError
from app.domain.documents.contracts import DocxDocument, DocxParseResult, DocxSettings

def invalid():raise StorageError('document_changed','文档版本对象完整性核验失败。',409)
def validate_result(result):
    payload = result.model_dump() if hasattr(result, 'model_dump') else result
    if payload.get('document', {}).get('kind') == 'pdf_document':
        from app.domain.documents.pdf_contracts import PdfParseResult, PDF_SETTINGS
        result = PdfParseResult.model_validate(payload)
        if len(result.document.model_dump_json().encode()) > PDF_SETTINGS['pdf']['max_json_bytes']:invalid()
        return result, {}
    if payload.get('document', {}).get('kind') == 'ocr_document':
        from app.domain.documents.ocr_contracts import OcrParseResult
        from app.adapters.ocr_result_validation import validate_ocr_document
        result=OcrParseResult.model_validate(payload)
        validate_ocr_document(result.document)
    else:
        result=DocxParseResult.model_validate(payload)
    images=result.document.images
    if len({i.id for i in images})!=len(images) or set(result.image_payloads)!={i.id for i in images}:invalid()
    decoded={}
    for image in images:
        try:raw=base64.b64decode(result.image_payloads[image.id],validate=True)
        except (ValueError,TypeError):invalid()
        if len(raw)!=image.size_bytes or hashlib.sha256(raw).hexdigest()!=image.sha256:invalid()
        if image.inline_preview and not (image.mime=='image/png' and raw.startswith(b'\x89PNG\r\n\x1a\n') or image.mime=='image/jpeg' and raw.startswith(b'\xff\xd8\xff')):invalid()
        decoded[image.id]=raw
    limits=DocxSettings()
    if len(images)>limits.max_images or sum(map(len,decoded.values()))>limits.max_image_bytes:invalid()
    if len(result.document.model_dump_json().encode())>limits.max_json_bytes:invalid()
    return result,decoded
class DocumentObjects:
    def __init__(self,directory):self.root=Path(directory).resolve()
    def path(self,key):
        if type(key) is not str or not re.fullmatch(r'documents/[0-9a-f-]{36}/[0-9a-f]{64}\.(json|bin)',key):invalid()
        path=self.root/key
        for candidate in [self.root,*list(path.parents)[:-1],path]:
            if candidate.is_symlink() or (hasattr(candidate,'is_junction') and candidate.is_junction()):invalid()
        if not path.resolve().is_relative_to(self.root):invalid()
        return path
    def _read(self,record,limit):
        try:
            size=record['size_bytes'];digest=record['sha256'];key=record['object_key']
            if type(size) is not int or not 0<size<=limit or key.rsplit('/',1)[-1].split('.')[0]!=digest:invalid()
            with self.path(key).open('rb') as stream:raw=stream.read(size+1)
        except FileNotFoundError as exc:raise StorageError('document_missing','文档版本对象已缺失。',410) from exc
        except (KeyError,TypeError):invalid()
        if len(raw)!=size or hashlib.sha256(raw).hexdigest()!=digest:invalid()
        return raw
    def _save(self,identifier,raw,suffix):
        digest=hashlib.sha256(raw).hexdigest();key=f'documents/{identifier}/{digest}.{suffix}'
        record=dict(object_key=key,size_bytes=len(raw),sha256=digest);target=self.path(key)
        target.parent.mkdir(parents=True,exist_ok=True);target=self.path(key)
        if target.exists():self._read(record,max(len(raw),1));return record
        temp=target.with_name(target.name+'.'+str(uuid4())+'.part')
        try:
            with temp.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
            try:os.link(temp,target)
            except FileExistsError:self._read(record,max(len(raw),1))
        finally:temp.unlink(missing_ok=True)
        return record
    def plan(self,parse_id,result):
        try:identifier=str(UUID(str(parse_id)))
        except ValueError:invalid()
        result,decoded=validate_result(result)
        raw=result.document.model_dump_json().encode()
        objects=[]
        def describe(content,suffix):
            digest=hashlib.sha256(content).hexdigest()
            record=dict(object_key=f'documents/{identifier}/{digest}.{suffix}',size_bytes=len(content),sha256=digest)
            self.path(record['object_key']);objects.append((record,content))
            return record
        images=[{**i.model_dump(),**describe(decoded[i.id],'bin')} for i in getattr(result.document,'images',[])]
        manifest=dict(kind=result.document.kind,object=describe(raw,'json'),images=images,summary=dict(counts=result.document.counts.model_dump(),warnings=[w.model_dump() for w in result.document.warnings]))
        return manifest,objects
    def save(self,parse_id,result):
        manifest,objects=self.plan(parse_id,result)
        for record,content in objects:
            self._save(str(UUID(str(parse_id))),content,record['object_key'].rsplit('.',1)[1])
        return manifest
    def read(self,manifest):
        raw=self._read(manifest['object'],4194304)
        try:
            from app.domain.documents.pdf_contracts import PdfParseResult
            from app.domain.documents.ocr_contracts import OcrDocument
            document=PdfParseResult.model_validate({'document':json.loads(raw)}).document if manifest['kind']=='pdf_document' else (OcrDocument if manifest['kind']=='ocr_document' else DocxDocument).model_validate(json.loads(raw))
        except (ValueError,TypeError):invalid()
        if document.kind != manifest['kind']:invalid()
        if document.kind=='ocr_document':
            from app.adapters.ocr_result_validation import validate_ocr_document
            validate_ocr_document(document)
        if [i.model_dump() for i in getattr(document,'images',[])]!=[{k:v for k,v in i.items() if k!='object_key'} for i in manifest['images']]:invalid()
        return raw,document
    def image(self,manifest,image_id):
        self.read(manifest)
        matches=[i for i in manifest['images'] if i['id']==image_id]
        if len(matches)!=1:raise StorageError('image_not_found','图片不存在。',404)
        i=matches[0];return self._read(i,16777216),i['mime']
