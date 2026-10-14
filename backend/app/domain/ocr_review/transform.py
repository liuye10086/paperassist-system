from app.domain.ocr_review.contracts import (OcrReviewDocument, OcrReviewEdit,
    OcrReviewSummary, OcrReviewedBlock, OcrReviewSource)


def review_document(document, source, edits):
    source = OcrReviewSource.model_validate(source)
    if document.kind != 'ocr_document' or document.parser_version != source.parser_version or document.selected_pages != source.selected_pages:
        raise ValueError('Parent OCR evidence differs from frozen source')
    parsed = [OcrReviewEdit.model_validate(e.model_dump(exclude_unset=True) if isinstance(e,OcrReviewEdit) else e) for e in edits]
    by_id = {e.block_id:e for e in parsed}
    originals = [b for page in document.pages for b in page.text_blocks]
    ids = {b.id for b in originals}
    if not originals or len(ids) != len(originals) or len(by_id) != len(parsed) or not set(by_id) <= ids:
        raise ValueError('Review requires existing unique OCR blocks')
    # Stable parent order keeps candidate identities independent of client ordering.
    parsed = [by_id[b.id] for b in originals if b.id in by_id]
    blocks = []
    counts = dict(accept_original=0, replace_text=0, unreadable=0)
    for original in originals:
        edit = by_id.get(original.id)
        action = edit.action if edit else None
        effective = original.text if action == 'accept_original' else edit.text if action == 'replace_text' else None
        blocks.append(OcrReviewedBlock(original=original.model_copy(deep=True), action=action, effective_text=effective))
        if action: counts[action] += 1
    summary = OcrReviewSummary(total_blocks=len(originals), reviewed_blocks=len(parsed),
        unreviewed_blocks=len(originals)-len(parsed), accepted_blocks=counts['accept_original'],
        corrected_blocks=counts['replace_text'], unreadable_blocks=counts['unreadable'],
        no_text_pages=[p.page_number for p in document.pages if not p.text_blocks])
    return OcrReviewDocument(parent_source=source, edits=parsed, blocks=blocks, summary=summary)
