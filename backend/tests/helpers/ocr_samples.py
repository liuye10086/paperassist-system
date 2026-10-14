"""Small deterministic OCR output for business tests; never claims engine accuracy."""
import base64
import hashlib


def ocr_result(content,filename,file_type,page_numbers,settings,*,on_started=None):
    from app.domain.documents.ocr_contracts import OcrParseResult,PARSER_VERSION
    if on_started: on_started()
    raw=b'\xff\xd8\xffsynthetic-preview';polygon=[[0.,0.],[10.,0.],[10.,10.],[0.,10.]]
    system='pdf_points_bottom_left' if file_type=='pdf' else 'image_pixels_top_left'
    images=[];pages=[]
    for p in page_numbers:
        image=dict(id=f'page-{p}',part=f'page/{p}',mime='image/jpeg',size_bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),inline_preview=True)
        images.append(image)
        text=dict(kind='ocr_text',id=f'text-{p}',text='候选 12 mg',score=.9,review_status='unreviewed',polygon=polygon,
            source=dict(page_number=p,polygon=polygon,coordinate_system=system,label=f'Page {p}'))
        pages.append(dict(page_number=p,width=100,height=100,preview_image_id=image['id'],rotation=0,
            source_width=100.,source_height=100.,source_coordinate_system=system,pixel_to_source=[1.,0.,0.,0.,1.,0.],
            transforms=[],text_status='text',text_blocks=[text],warnings=[]))
    return OcrParseResult.model_validate(dict(document=dict(schema_version=1,kind='ocr_document',filename=filename,parser_version=PARSER_VERSION,
        source_type=file_type,source_pages=max(page_numbers) if file_type=='pdf' else 1,selected_pages=page_numbers,pages=pages,images=images,warnings=[],
        counts=dict(pages=len(pages),text_blocks=len(pages),images=len(images),pages_without_text=0)),image_payloads={i['id']:base64.b64encode(raw).decode() for i in images}))
