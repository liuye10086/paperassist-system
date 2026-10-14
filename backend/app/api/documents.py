from typing import Annotated
from urllib.parse import quote
from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BeforeValidator
from app.adapters.storage import ProjectStore, get_request_project_store
from app.api.tasks import decimal_query_integer
from app.domain.documents.service import DocumentService, ReparseRequest, OcrRequest
router=APIRouter(prefix='/api/v1/projects/{project_id}/files/{file_id}/document-versions',tags=['文档版本'])
Store=Annotated[ProjectStore,Depends(get_request_project_store)]
Page=Annotated[int,Query(ge=1,le=1000000),BeforeValidator(decimal_query_integer)]

@router.get('')
def versions(project_id:str,file_id:str,store:Store,page:Page=1):
    return DocumentService(store).list(project_id,file_id,page)

@router.post('',status_code=202)
def reparse(project_id:str,file_id:str,request:ReparseRequest,response:Response,store:Store,
    idempotency_key:Annotated[str,Header(min_length=1,max_length=128,pattern=r'^[\x21-\x7e]+$')]):
    result,status=DocumentService(store).create(project_id,file_id,request,idempotency_key)
    response.status_code=status
    return result

@router.post('/ocr',status_code=202)
def ocr(project_id:str,file_id:str,request:OcrRequest,response:Response,store:Store,
    idempotency_key:Annotated[str,Header(min_length=1,max_length=128,pattern=r'^[\x21-\x7e]+$')]):
    result,status=DocumentService(store).create(project_id,file_id,request,idempotency_key,ocr=True)
    response.status_code=status
    return result

@router.get('/{parse_id}')
def detail(project_id:str,file_id:str,parse_id:str,store:Store):
    return DocumentService(store).detail(project_id,file_id,parse_id)

@router.get('/{parse_id}/blocks')
def blocks(project_id:str,file_id:str,parse_id:str,store:Store,page:Page=1):
    return DocumentService(store).blocks(project_id,file_id,parse_id,page)

@router.get('/{parse_id}/pages')
def pages(project_id:str,file_id:str,parse_id:str,store:Store,page:Page=1):
    return DocumentService(store).pages(project_id,file_id,parse_id,page)

@router.get('/{parse_id}/download')
def download(project_id:str,file_id:str,parse_id:str,store:Store):
    service=DocumentService(store);row=service.load(project_id,file_id,parse_id,True)
    raw,_=service.read(row)
    return Response(raw,media_type='application/json',headers={'Content-Disposition':f'attachment; filename="document-v{row["version"]}.json"','X-Content-Type-Options':'nosniff'})

@router.get('/{parse_id}/images/{image_id}')
def image(project_id:str,file_id:str,parse_id:str,image_id:str,store:Store):
    service=DocumentService(store);row=service.load(project_id,file_id,parse_id,True)
    service.require_format(row,('docx_document_v1','ocr_document_v1'))
    service.read(row)
    content,mime=service.objects().image(row['result_json'],image_id)
    meta=next(i for i in row['result_json']['images'] if i['id']==image_id)
    disposition='inline' if meta['inline_preview'] and mime in ('image/png','image/jpeg') else 'attachment'
    return Response(content,media_type=mime,headers={'Content-Disposition':disposition+'; filename*=UTF-8\'\''+quote(image_id,safe=''),'X-Content-Type-Options':'nosniff'})
