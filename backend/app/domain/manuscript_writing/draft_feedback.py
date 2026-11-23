"""Read an opinion letter without registering it as a manuscript source."""
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from app.adapters.docx_parser import parse_docx
from app.adapters.pdf_process import parse_pdf_isolated
from app.core.exceptions import StorageError
from app.domain.documents.contracts import DOCX_SETTINGS
from app.domain.documents.pdf_contracts import PDF_SETTINGS
from app.domain.parsed_evidence.documents import docx_items


def incomplete():
    return StorageError('draft_feedback_incomplete', '未能完整读取意见，请粘贴原文或上传干净的意见文件。', 422)


def read_feedback(filename, content):
    extension = Path(filename).suffix.lower()
    if extension == '.txt':
        try:
            text = content.decode('utf-8-sig')
        except UnicodeDecodeError as exc:
            raise incomplete() from exc
    elif extension == '.docx':
        document = parse_docx(content, filename, DOCX_SETTINGS).document
        # Tracked or annotated manuscript files can omit the actual reviewer's comments.
        with ZipFile(BytesIO(content)) as archive:
            comments = any(name.lower().startswith('word/comments') for name in archive.namelist())
        if comments or any(w.code in {'unsupported_blocks', 'equations', 'other_parts', 'revisions', 'textboxes'}
                           for w in document.warnings):
            raise incomplete()
        text = '\n'.join(item.text for item in docx_items(document, '') if item.kind == 'text' and item.text)
    elif extension == '.pdf':
        document = parse_pdf_isolated(content, filename, PDF_SETTINGS).document
        if any(not page.text_blocks or any(w.code == 'undecoded_characters' for w in page.warnings)
               for page in document.pages):
            raise incomplete()
        text = '\n'.join(block.text for page in document.pages for block in page.text_blocks)
    else:
        raise incomplete()
    text = text.strip()
    if not text or '\x00' in text:
        raise incomplete()
    if len(text) > 10000:
        raise StorageError('draft_feedback_too_long', '意见超过一万字，请粘贴本次需要处理的内容。', 422)
    return text
