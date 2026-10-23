"""Presentation only. Actual changes and independent texts are already frozen."""
from app.adapters.manuscript_docx import _document, _save_document
from app.domain.review_rounds.document_display import change_text,evidence_text

RENDERER_VERSION='review_docx_v3'

def render_review_document(snapshot):
    document=_document();en=snapshot['language']=='en'
    document.add_heading(snapshot['title'],0)
    if snapshot['synthetic']:document.add_paragraph('Synthetic engineering material; scientific quality is not validated.' if en else '合成工程材料；不代表真实科研质量验收。')
    document.add_paragraph(('Final manuscript version: ' if en else '最终稿件版本：')+str(snapshot['output']['revision']))
    if snapshot.get('document_version'):
        document.add_paragraph(('Document version: ' if en else '独立文档版本：')+str(snapshot['document_version']))
        if snapshot.get('confirmed_at'):
            document.add_paragraph(('Confirmed at export: ' if en else '导出时已确认：')+snapshot['confirmed_at'])
        else:
            document.add_paragraph('Unconfirmed draft at export.' if en else '导出时为尚未确认的草稿。')
    document.add_paragraph(snapshot['location_notice'])
    for item in snapshot['items']:
        label=item.get('source_label') or item.get('source_id') or ''
        document.add_heading(f"{label} · {item.get('original_number') or item.get('number') or ''}",1)
        document.add_paragraph(('Original comment: ' if en else '原意见：')+item['original_text'])
        if item.get('translation'):
            document.add_paragraph(('Saved manual translation: ' if en else '独立保存的人工译文：')+item['translation']['text'])
        document.add_paragraph(('Status: ' if en else '处理状态：')+item['status'])
        document.add_paragraph(item['text'])
        if item.get('reason'):document.add_paragraph(('Reason: ' if en else '原因：')+item['reason'])
        for change in item['actual_changes']:
            document.add_heading('Actual change' if en else '实际改动',2)
            document.add_paragraph(('Before: ' if en else '修改前：')+change_text(change,'before',snapshot['language']))
            document.add_paragraph(('After: ' if en else '修改后：')+change_text(change,'after',snapshot['language']))
            document.add_paragraph(('Basis: ' if en else '修改依据：')+change.get('reason',''))
        for location in item['locations']:
            values=[location.get('section_title'),location.get('section_id'),location.get('kind'),location.get('id')]
            for field,label in (('paragraph_number','paragraph' if en else '段落'),('figure_number','Figure' if en else '图'),('table_number','Table' if en else '表')):
                if location.get(field) is not None:values.append(label+' '+str(location[field]))
            prefix=('Parent location (removed from this manuscript): ' if en else '父稿位置（本稿已移出）：') if location.get('removed_from_output') else ('Final location: ' if en else '最终稳定位置：')
            document.add_paragraph(prefix+' / '.join(str(v) for v in values if v))
        for evidence in item['evidence']:
            document.add_paragraph(('Evidence: ' if en else '依据：')+evidence_text(evidence))
            document.add_paragraph(('Source / SHA-256: ' if en else '来源 / SHA-256：')+str(evidence.get('id',''))+' / '+str(evidence.get('sha256','')))
    return _save_document(document)
