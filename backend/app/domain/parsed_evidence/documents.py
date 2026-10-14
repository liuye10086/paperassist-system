"""Flatten persisted document locations and conservative caption candidates."""
import re
from app.domain.parsed_evidence.contracts import Item, Location, Value, Association, Scope, EvidenceWarning, response

CAPTION = re.compile(r'^\s*(?P<label>图|表|Figure|Fig\.?|Table)\s*(?:[0-9]+(?:[.\-][0-9]+)*|[IVX]+)(?=\s|[：:、.．\-]|[^\x00-\x7f]|$)', re.I)


def caption_kind(text):
    match = CAPTION.match(text)
    if not match:
        return None
    return 'table' if match['label'].lower() in ('表', 'table') else 'image'


def location(source, **extra):
    return Location(**source.model_dump(), **extra)


def mark_candidate_caption(items, caption_id):
    caption=next(i for i in items if i.kind=='text' and i.id==caption_id)
    caption.uncertainties=[code for code in caption.uncertainties if code!='caption_unlinked']
    caption.uncertainties.append('caption_association_candidate')


def docx_items(document, image_base):
    items = []
    def container(blocks):
        targets = []
        for position, block in enumerate(blocks):
            loc = location(block.source)
            if block.kind == 'paragraph':
                if block.text:
                    items.append(Item(id=block.id, kind='text', location=loc, text=block.text,
                        uncertainties=['caption_unlinked'] if caption_kind(block.text) else []))
                for image_id in block.image_ids:
                    image = Item(id=block.id+':'+image_id, kind='image', location=loc, image_id=image_id,
                        preview_url=image_base+'/'+image_id, uncertainties=['image_science_not_extracted'])
                    items.append(image); targets.append((position, image))
            else:
                table = Item(id=block.id, kind='table', location=loc, rows=block.rows, columns=block.columns)
                items.append(table); targets.append((position, table))
                for cell in block.cells:
                    cell_location = location(cell.source, row=cell.row, column=cell.column, container_id=block.id)
                    # Original paragraphs remain separate evidence; cell text is an explicit view of them.
                    texts = [p.text for p in cell.blocks if p.kind == 'paragraph']
                    items.append(Item(id=block.id+f':r{cell.row}c{cell.column}', kind='cell',
                        location=cell_location, value=Value(kind='text', typed='\n'.join(texts))))
                    container(cell.blocks)
        for position, target in targets:
            captions = [(i, b) for i, b in enumerate(blocks) if abs(i-position) <= 1
                and b.kind == 'paragraph' and caption_kind(b.text) == target.kind]
            if len(captions) != 1:
                target.uncertainties.append('caption_ambiguous' if captions else 'caption_missing')
                continue
            index, caption = captions[0]
            compatible = [t for i, t in targets if abs(i-index)<=1 and t.kind==target.kind]
            if len(compatible) != 1:
                target.uncertainties.append('caption_ambiguous'); continue
            target.associations.append(Association(basis='adjacent_same_container', caption_id=caption.id,
                caption_text=caption.text, caption_source=location(caption.source),
                target_id=target.id, target_source=target.location))
            mark_candidate_caption(items,caption.id)
    container(document.blocks)
    return items


def page_items(document):
    items = []
    for page in document.pages:
        if document.kind == 'ocr_document':
            for block in page.text_blocks:
                items.append(Item(id=block.id, kind='text', location=location(block.source), text=block.text,
                    uncertainties=['ocr_unreviewed']))
            items.append(Item(id=page.preview_image_id,kind='image',image_id=page.preview_image_id,
                location=Location(page_number=page.page_number,part=f'page/{page.page_number}',
                    bbox=[0.,0.,page.source_width,page.source_height],coordinate_system=page.source_coordinate_system),
                uncertainties=['image_science_not_extracted','ocr_unreviewed']))
            continue
        targets = []
        for block in page.text_blocks:
            items.append(Item(id=block.id, kind='text', location=location(block.source), text=block.text,
                uncertainties=['reading_order_candidate']+(['caption_unlinked'] if caption_kind(block.text) else [])))
        for table in page.tables:
            target = Item(id=table.id, kind='table', location=location(table.source), rows=table.rows,
                columns=table.columns, uncertainties=['table_candidate'])
            items.append(target); targets.append(target)
            for cell in table.cells:
                loc = Location(page_number=page.page_number, bbox=cell.bbox, row=cell.row,
                    column=cell.column, container_id=table.id)
                items.append(Item(id=table.id+f':r{cell.row}c{cell.column}', kind='cell', location=loc,
                    value=Value(kind='blank' if cell.text is None else 'text', typed=cell.text)))
        for image in getattr(page, 'embedded_images', []):
            target = Item(id=image.id, kind='image', location=location(image.source),
                uncertainties=['image_science_not_extracted', 'image_pixels_not_saved'])
            items.append(target); targets.append(target)
        for target in targets:
            x0, y0, x1, y1 = target.location.bbox
            candidates = []
            for text in page.text_blocks:
                if caption_kind(text.text) != target.kind:
                    continue
                a, b, c, d = text.source.bbox
                gap = max(y0-d, b-y1, 0)
                # Same page, horizontal overlap, within 48 PDF points, outside target.
                if max(x0,a)<min(x1,c) and gap<=48 and (d<=y0 or b>=y1):
                    candidates.append(text)
            if len(candidates) != 1:
                target.uncertainties.append('caption_ambiguous' if candidates else 'caption_missing'); continue
            caption = candidates[0]
            # A caption near multiple same-kind targets is ambiguous, even if distances differ.
            a,b,c,d=caption.source.bbox
            possible = [t for t in targets if t.kind==target.kind and
                max(a,t.location.bbox[0])<min(c,t.location.bbox[2]) and
                max(t.location.bbox[1]-d,b-t.location.bbox[3],0)<=48 and
                (d<=t.location.bbox[1] or b>=t.location.bbox[3])]
            if len(possible)!=1:
                target.uncertainties.append('caption_ambiguous'); continue
            target.associations.append(Association(basis='nearest_same_page', caption_id=caption.id,
                caption_text=caption.text, caption_source=location(caption.source),
                target_id=target.id, target_source=target.location))
            mark_candidate_caption(items,caption.id)
    return items


def project_document(document, origin, image_base, page):
    is_docx = document.kind == 'docx_document'
    items = docx_items(document, image_base) if is_docx else page_items(document)
    if document.kind=='ocr_document':
        for item in items:
            if item.kind=='image':item.preview_url=image_base+'/'+item.image_id
    uncertainties = ['stored_counts_not_research_n']
    if document.kind == 'pdf_document':
        uncertainties += ['vector_figures_not_extracted', 'image_pixels_not_saved']
        if document.parser_version.endswith('text-v1'):
            uncertainties.append('legacy_pdf_images_not_extracted')
    if document.kind == 'ocr_document':
        uncertainties += ['ocr_unreviewed', 'ocr_review_not_projected']
    pages=[] if is_docx else [p.page_number for p in document.pages]
    warnings=[EvidenceWarning(**w.model_dump(),scope='document',pages=pages) for w in document.warnings]
    for physical_page in getattr(document,'pages',[]):
        source=Location(page_number=physical_page.page_number,bbox=physical_page.bbox) if document.kind=='pdf_document' else Location(
            page_number=physical_page.page_number,bbox=[0.,0.,physical_page.source_width,physical_page.source_height],
            coordinate_system=physical_page.source_coordinate_system)
        warnings.extend(EvidenceWarning(**w.model_dump(),scope='page',pages=[physical_page.page_number],location=source)
            for w in physical_page.warnings)
    return response(origin, 'docx' if is_docx else 'ocr' if document.kind=='ocr_document' else 'pdf',
        document.parser_version, Scope(kind='document', pages=[] if is_docx else [p.page_number for p in document.pages]),
        document.counts.model_dump(), items, uncertainties, page,warnings=warnings)
