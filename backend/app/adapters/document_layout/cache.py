"""Merge actual office-calculated results into original OOXML field caches."""
import hashlib
import json

from lxml import etree as E

from app.core.exceptions import StorageError
from .engine import element, q, text_run
from .package import NS, encode, parse, read_package, write_package


def failure():
    return StorageError('layout_field_update_failed', '本地目录或引用页码未完成更新；未发布排版文件，请重试。', 503)


def merge_field_cache(content: bytes, cache: dict) -> bytes:
    if not isinstance(cache, dict) or cache.get('source_sha256') != hashlib.sha256(content).hexdigest():
        raise failure()
    parts = read_package(content)
    try:
        meta = parse(parts['customXml/paperassist-layout.xml'])
        manifest = json.loads(meta.text)
        fields = cache['fields']
        root = parse(parts['word/document.xml'])
        completed_begins = []
        for field in manifest['fields']:
            marks = root.xpath('//w:bookmarkStart[@w:name=$name]', namespaces=NS, name=field['bookmark'])
            if len(marks) != 1:
                raise ValueError()
            start = marks[0]
            parent = start.getparent()
            mark_id = start.get(q('id'))
            ends = parent.xpath('./w:bookmarkEnd[@w:id=$id]', namespaces=NS, id=mark_id)
            if len(ends) != 1:
                raise ValueError()
            end = ends[0]
            region = list(parent)[parent.index(start) + 1:parent.index(end)]
            completed_begins.append(next(n.find('w:fldChar', NS) for n in region
                                         if n.find('w:fldChar[@w:fldCharType="begin"]', NS) is not None))
            separator = next(n for n in region if n.find('w:fldChar[@w:fldCharType="separate"]', NS) is not None)
            final = next(n for n in region if n.find('w:fldChar[@w:fldCharType="end"]', NS) is not None)
            for node in list(parent)[parent.index(separator) + 1:parent.index(final)]:
                parent.remove(node)
            if field['role'] == 'toc':
                lines = cache['toc_lines']
                if not lines or len(lines) > 1000 or any(not isinstance(v, str) or len(v) > 2000 for v in lines):
                    raise ValueError()
                # Cached result spans real paragraphs, inside the original TOC
                # field. This is editable/updateable in both Word and Writer.
                lines = [v for v in lines if v.strip()]
                targets = manifest['toc_targets']
                if not lines or len(lines) != len(targets) or any('\t' not in line for line in lines):
                    raise ValueError()
                current = parent
                for line, target in zip(lines, targets):
                    label, page = line.rsplit('\t', 1)
                    if not label.strip() or not page.strip():
                        raise ValueError()
                    paragraph = element('w:p')
                    ppr = element('w:pPr')
                    ppr.append(element('w:ind', left=str((target['level'] - 1) * 240)))
                    tabs = element('w:tabs')
                    tabs.append(element('w:tab', val='right', leader='dot', pos='8800'))
                    ppr.append(tabs)
                    paragraph.append(ppr)
                    link = element('w:hyperlink', anchor=target['bookmark'])
                    link.append(text_run(label))
                    tab_run = element('w:r')
                    tab_run.append(element('w:tab'))
                    link.append(tab_run)
                    link.append(text_run(page))
                    paragraph.append(link)
                    current.addnext(paragraph)
                    current = paragraph
                parent.remove(final)
                parent.remove(end)
                current.append(final)
                current.append(end)
            else:
                value = fields[field['bookmark']]
                if not isinstance(value, str) or not value.strip() or len(value) > 10000 or 'Error!' in value or '错误!' in value:
                    raise ValueError()
                final.addprevious(text_run(value))
        # Only fully merged system-owned fields are clean. Keep real fields
        # editable; neither a lock nor a static text replacement is needed.
        for begin in completed_begins:
            begin.set(q('dirty'), 'false')
        if completed_begins and 'word/settings.xml' in parts:
            # Global updates may also be requested for user fields without
            # dirty attributes. Only manifest-owned fields were calculated here.
            field_nodes = '//w:fldChar[@w:fldCharType="begin"] | //w:fldSimple'
            stories = ('word/document.xml', 'word/footnotes.xml', 'word/endnotes.xml',
                       'word/comments.xml', 'word/glossary/document.xml')
            unprocessed = any(node not in completed_begins
                              for name, value in parts.items()
                              if name.endswith('.xml') and (name in stories or name.startswith(('word/header', 'word/footer')))
                              for node in (root if name == 'word/document.xml' else parse(value)).xpath(field_nodes, namespaces=NS))
            if not unprocessed:
                settings = parse(parts['word/settings.xml'])
                for update in settings.findall('w:updateFields', NS):
                    update.set(q('val'), 'false')
                parts['word/settings.xml'] = encode(settings)
        manifest['cache_status'] = 'complete'
        meta.text = json.dumps(manifest, ensure_ascii=False, separators=(',', ':'))
        parts['customXml/paperassist-layout.xml'] = encode(meta)
        parts['word/document.xml'] = encode(root)
        return write_package(parts)
    except (KeyError, ValueError, StopIteration, TypeError, E.XMLSyntaxError):
        raise failure() from None


def prepare_layout_docx(content, options, *, language):
    """The publication boundary: apply, obtain local field results, merge."""
    from app.adapters.pdf_renderer import update_layout_fields
    from .engine import apply_layout
    pending = apply_layout(content, options, language=language)
    cache = update_layout_fields(pending)
    return merge_field_cache(pending, cache)
