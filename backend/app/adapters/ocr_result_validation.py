"""Validate OCR page provenance and internal counts before saving or reading."""
import math

from app.adapters.task_store import source_conflict


def validate_ocr_document(document,snapshot=None):
    def require(condition):
        if not condition: raise source_conflict()
    pages=document.pages;selected=document.selected_pages;images=document.images
    require(type(document.schema_version) is int)
    require(selected==sorted(set(selected)) and all(type(p) is int and 1<=p<=document.source_pages for p in selected))
    require([p.page_number for p in pages]==selected)
    if snapshot is not None:
        require(document.filename==snapshot['file']['filename'] and document.parser_version==snapshot['parser_version'])
        require(document.source_type==snapshot['file']['file_type'] and selected==snapshot['page_numbers'])
    require(document.source_type=='pdf' or document.source_pages==1 and selected==[1])
    image_ids={i.id for i in images}
    require(len(image_ids)==len(images)==len(pages))
    require({p.preview_image_id for p in pages}==image_ids)
    require(all(i.inline_preview and i.mime=='image/jpeg' for i in images))
    text_ids=set()
    for page in pages:
        expected_system='pdf_points_bottom_left' if document.source_type=='pdf' else 'image_pixels_top_left'
        require(page.source_coordinate_system==expected_system)
        require(page.width*page.height <= (12000000 if document.source_type=='pdf' else 20000000))
        require(page.text_status==('text' if page.text_blocks else 'no_text'))
        a,b,c,d,e,f=page.pixel_to_source
        require(all(math.isfinite(v) for v in page.pixel_to_source))
        require(abs(a*e-b*d)>1e-12)
        for text in page.text_blocks:
            require(bool(text.id) and text.id not in text_ids)
            text_ids.add(text.id)
            require(text.source.page_number==page.page_number and text.source.coordinate_system==expected_system)
            require(text.review_status=='unreviewed')
            for (x,y),(sx,sy) in zip(text.polygon,text.source.polygon):
                require(0<=x<=page.width and 0<=y<=page.height)
                require(math.isclose(sx,a*x+b*y+c,rel_tol=1e-6,abs_tol=1e-4) and math.isclose(sy,d*x+e*y+f,rel_tol=1e-6,abs_tol=1e-4))
    require(document.counts.model_dump()==dict(pages=len(pages),text_blocks=sum(len(p.text_blocks) for p in pages),
        images=len(images),pages_without_text=sum(not p.text_blocks for p in pages)))
