"""Add layout to exact source nodes without rebuilding scientific content."""
from copy import deepcopy
import hashlib
import json
import re

from lxml import etree as E

from app.core.exceptions import StorageError
from app.domain.document_layout import LayoutOptions, parse_expression
from .omml import element, render, width
from .package import NS, W, encode, parse, read_package, write_package

REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
OFFICE_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
CONTENT = 'http://schemas.openxmlformats.org/package/2006/content-types'


def q(tag):
    return '{' + W + '}' + tag


def prop(node, name):
    value = node.find(q(name))
    if value is None:
        value = element('w:' + name)
        node.insert(0, value)
    return value


def text_run(text):
    run = element('w:r')
    value = element('w:t')
    value.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
    value.text = text
    run.append(value)
    return run


def caption_for(node, kind):
    if node is None or node.tag != q('p'):
        return False
    style = node.find('w:pPr/w:pStyle', NS)
    if style is None or style.get(q('val'), '').lower() != 'caption':
        return False
    text = ''.join(node.xpath('.//w:t/text()', namespaces=NS)).lstrip()
    opposite = r'^(?:Figure\b|Fig\.|图)' if kind == 'table' else r'^(?:Table\b|表)'
    return not re.match(opposite, text, re.I)


def figure_label(node):
    if node is None or node.tag != q('p'):
        return False
    text = ''.join(node.xpath('.//w:t/text()', namespaces=NS)).lstrip()
    return bool(re.match(r'^(?:Figure\b|Fig\.|图)\s*\d+', text, re.I))


def _catalog(content, parts):
    root = parse(parts['word/document.xml'])
    body = root.find(q('body'))
    if body is None:
        raise StorageError('layout_source_invalid', '来源 DOCX 缺少正文。', 422)
    digest = hashlib.sha256(content).hexdigest()
    styles = {}
    if 'word/styles.xml' in parts:
        for style in parse(parts['word/styles.xml']).findall(q('style')):
            outline = style.find('w:pPr/w:outlineLvl', NS)
            if outline is not None and outline.get(q('val'), '').isdigit():
                styles[style.get(q('styleId'))] = int(outline.get(q('val'))) + 1
    anchors = []
    for index, node in enumerate(body):
        if node.tag not in (q('p'), q('tbl')):
            continue
        text = ''.join(node.xpath('.//w:t/text()', namespaces=NS))
        style = node.find('w:pPr/w:pStyle', NS)
        style_id = style.get(q('val'), '') if style is not None else ''
        direct = node.find('w:pPr/w:outlineLvl', NS)
        level = styles.get(style_id)
        if direct is not None and direct.get(q('val'), '').isdigit():
            level = int(direct.get(q('val'))) + 1
        if not level:
            match = re.fullmatch(r'Heading([1-9])', style_id, re.I)
            level = int(match[1]) if match else None
        kind = 'table' if node.tag == q('tbl') else 'heading' if level and level <= 9 else 'figure' if node.xpath('.//w:drawing | .//w:pict', namespaces=NS) else 'paragraph'
        bookmark = node.find('.//' + q('bookmarkStart'))
        anchors.append({'id': f'{digest}:{index}', 'position': index, 'type': kind,
                        'text': text[:160], 'heading_level': level if kind == 'heading' else None,
                        'bookmark': bookmark.get(q('name')) if bookmark is not None else None,
                        'is_caption': style_id.lower() == 'caption'})
    return {'source_sha256': digest, 'source_size': len(content), 'anchors': anchors,
            'limits': {'formulas': 40, 'expression_characters': 2000, 'references': 60,
                       'landscape_objects': 16, 'parse_depth': 12, 'matrix_rows': 6,
                       'matrix_columns': 6, 'aligned_lines': 8, 'display_width_units': 56,
                       'inline_width_units': 32}}


def catalog_docx(content: bytes) -> dict:
    return _catalog(content, read_package(content))


class Editor:
    def __init__(self, content, options, language):
        self.parts = read_package(content)
        self.catalog = _catalog(content, self.parts)
        self.root = parse(self.parts['word/document.xml'])
        self.body = self.root.find(q('body'))
        self.original = list(self.body)
        self.anchors = {a['id']: a for a in self.catalog['anchors']}
        self.nodes = {a['id']: self.original[a['position']] for a in self.catalog['anchors']}
        self.options, self.language = options, language
        self.mark_id = max([int(n.get(q('id'))) for n in self.root.findall('.//' + q('bookmarkStart'))
                            if n.get(q('id'), '').isdigit()] or [0]) + 1
        self.bookmarks = {}
        self.text_bookmarks = {}
        self.field_id = 0
        self.tails = {}
        self.manifest = {'version': 'paperassist_layout_v1', 'provenance': 'user_input',
                         'source_sha256': self.catalog['source_sha256'],
                         'options': options.model_dump(mode='json'), 'fields': [], 'cache_status': 'pending'}
        if options.source_sha256 and options.source_sha256 != self.catalog['source_sha256']:
            raise StorageError('layout_source_mismatch', '来源 DOCX 已变化，请重新选择精确版本。', 409)

    def target(self, anchor, path, allowed=None):
        value = self.anchors.get(anchor)
        if not value or (allowed and value['type'] not in allowed):
            raise StorageError('layout_target_invalid', '排版目标不属于固定来源或不支持此操作。', 422,
                               params={'path': path, 'anchor_id': anchor})
        return self.nodes[anchor]

    def bookmark(self, node, name=None, *, at_end=False):
        name = name or f'PA{self.mark_id:08d}'
        start, end = element('w:bookmarkStart', id=self.mark_id, name=name), element('w:bookmarkEnd', id=self.mark_id)
        self.mark_id += 1
        if at_end:
            node.append(start)
        else:
            node.insert(1 if len(node) and node[0].tag == q('pPr') else 0, start)
        node.append(end)
        return name, start, end

    def field(self, parent, instruction, cached='', *, role='reference'):
        name = f'PAF{self.field_id:06d}'
        self.field_id += 1
        _, start, end = self.bookmark(parent, name, at_end=True)
        parent.remove(end)
        for typ in ('begin', 'instruction', 'separate', 'result', 'end'):
            run = element('w:r')
            if typ == 'instruction':
                node = element('w:instrText')
                node.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
                node.text = ' ' + instruction + ' '
            elif typ == 'result':
                node = element('w:t')
                node.text = cached
            else:
                node = element('w:fldChar', fldCharType=typ)
                if typ == 'begin':
                    node.set(q('dirty'), 'true')
            run.append(node)
            parent.append(run)
        parent.append(end)
        self.manifest['fields'].append({'bookmark': name, 'instruction': instruction, 'role': role})
        return name

    def after(self, anchor, node):
        tail = self.tails.get(anchor, self.nodes[anchor])
        tail.addnext(node)
        self.tails[anchor] = node

    def headings(self):
        for i, heading in enumerate(self.options.headings):
            node = self.target(heading.anchor_id, f'headings.{i}.anchor_id', {'heading', 'paragraph'})
            ppr = prop(node, 'pPr')
            prop(ppr, 'outlineLvl').set(q('val'), str(heading.level - 1))
            prop(ppr, 'pStyle').set(q('val'), f'Heading{heading.level}')
            self.anchors[heading.anchor_id]['type'] = 'heading'
            self.anchors[heading.anchor_id]['heading_level'] = heading.level
        for anchor, info in self.anchors.items():
            if info['type'] in ('heading', 'figure', 'table'):
                node = self.nodes[anchor]
                if info['type'] == 'table':
                    node = node.find('.//' + q('p'))
                self.bookmarks[anchor] = self.bookmark(node)[0]
                if info['type'] in ('figure', 'table'):
                    adjacent = [self.nodes[anchor].getprevious(), self.nodes[anchor].getnext()]
                    caption = next((n for n in adjacent if caption_for(n, info['type'])), None)
                    if caption is not None:
                        self.text_bookmarks[anchor] = self.bookmark(caption)[0]
                    elif info['type'] == 'table':
                        self.text_bookmarks[anchor] = self.bookmarks[anchor]
                if info['type'] == 'heading':
                    ppr = prop(node, 'pPr')
                    prop(ppr, 'outlineLvl').set(q('val'), str(info['heading_level'] - 1))
                    prop(ppr, 'keepNext')
            if info['type'] == 'table':
                row = self.nodes[anchor].find(q('tr'))
                if row is not None:
                    prop(prop(row, 'trPr'), 'tblHeader')
            if info['type'] == 'figure':
                prop(prop(self.nodes[anchor], 'pPr'), 'keepNext')

    def formulas(self):
        numbered = 0
        prepared = []
        for i, formula in enumerate(self.options.formulas):
            node = self.target(formula.anchor_id, f'formulas.{i}.anchor_id', {'paragraph', 'heading'})
            try:
                ast = parse_expression(formula.expression)
            except StorageError as exc:
                exc.params.update({'path': f'formulas.{i}.expression', 'formula_id': formula.id})
                raise
            if width(ast) > (32 if formula.placement == 'inline' else 56):
                raise StorageError('layout_formula_too_wide', '公式过宽，请使用 aligned 显式拆行或缩短单行。', 422,
                                   params={'path': f'formulas.{i}.expression', 'formula_id': formula.id})
            prepared.append((self.anchors[formula.anchor_id]['position'], i, formula, node, ast))
        for _, _, formula, node, ast in sorted(prepared):
            math = element('m:oMath')
            math.extend(render(ast))
            if formula.placement == 'inline':
                node.append(text_run(' '))
                node.append(math)
            else:
                numbered += 1
                paragraph = element('w:p')
                ppr = element('w:pPr')
                ppr.extend([element('w:keepLines'), element('w:spacing', after='120')])
                paragraph.append(ppr)
                math_para = element('m:oMathPara')
                math_para.append(math)
                paragraph.append(math_para)
                paragraph.append(text_run(' ('))
                name, start, end = self.bookmark(paragraph, at_end=True)
                paragraph.remove(end)
                self.field(paragraph, r'SEQ PAEquation \* ARABIC', str(numbered), role='equation')
                paragraph.append(end)
                paragraph.append(text_run(')'))
                self.bookmarks['formula:' + formula.id] = name
                self.after(formula.anchor_id, paragraph)

    def references(self):
        for i, ref in enumerate(self.options.references):
            self.target(ref.anchor_id, f'references.{i}.anchor_id', {'paragraph', 'heading'})
            if ref.target_id not in self.bookmarks:
                raise StorageError('layout_target_invalid', '引用仅支持来源标题、图表或本次独立公式。', 422,
                                   params={'path': f'references.{i}.target_id', 'anchor_id': ref.target_id})
            if ref.kind == 'number' and not ref.target_id.startswith('formula:'):
                raise StorageError('layout_target_invalid', '编号引用仅支持本次独立公式；标题和图表可引用文字或页码。', 422,
                                   params={'path': f'references.{i}.kind'})
            if (ref.kind == 'text' and self.anchors.get(ref.target_id, {}).get('type') == 'figure'
                    and ref.target_id not in self.text_bookmarks):
                raise StorageError('layout_target_invalid', '该图形没有紧邻的原始图注，请选择页码引用。', 422,
                                   params={'path': f'references.{i}.kind'})
            node = element('w:p')
            node.append(text_run(ref.prefix))
            bookmark = self.text_bookmarks.get(ref.target_id, self.bookmarks[ref.target_id]) if ref.kind == 'text' else self.bookmarks[ref.target_id]
            instruction = ('PAGEREF' if ref.kind == 'page' else 'REF') + ' ' + bookmark + r' \h'
            self.field(node, instruction)
            self.after(ref.anchor_id, node)

    def toc(self):
        if not self.options.toc:
            return
        if not any(a['type'] == 'heading' and a['heading_level'] <= self.options.toc.depth for a in self.anchors.values()):
            raise StorageError('layout_target_invalid', '目录需要至少一个范围内的真实标题。', 422, params={'path': 'toc.depth'})
        self.manifest['toc_targets'] = []
        for anchor in self.anchors.values():
            if anchor['type'] != 'heading' or anchor['heading_level'] > self.options.toc.depth:
                continue
            # Word/WPS own and replace the old TOC hyperlink targets when the
            # index updates. Never share these disposable bookmarks with REF/
            # PAGEREF targets used elsewhere in the scientific document.
            name = self.bookmark(self.nodes[anchor['id']], f'PATOC{self.mark_id:08d}')[0]
            self.manifest['toc_targets'].append({'bookmark': name, 'level': anchor['heading_level']})
        title = element('w:p')
        title.append(text_run('目录' if self.language.startswith('zh') else 'Contents'))
        node = element('w:p')
        self.field(node, f'TOC \\o "1-{self.options.toc.depth}" \\h \\z \\u', role='toc')
        self.body.insert(0, title)
        self.body.insert(1, node)

    def effective_section(self, node, *, clone=True):
        start = self.body.index(node)
        for item in list(self.body)[start:]:
            section = item if item.tag == q('sectPr') else item.find('w:pPr/w:sectPr', NS)
            if section is not None:
                return deepcopy(section) if clone else section
        section = element('w:sectPr')
        section.extend([element('w:pgSz', w='11906', h='16838'),
                        element('w:pgMar', top='1247', bottom='1247', left='1304', right='1304')])
        return section

    def break_before(self, node, section):
        paragraph, ppr = element('w:p'), element('w:pPr')
        prop(section, 'type').set(q('val'), 'nextPage')
        ppr.append(section)
        paragraph.append(ppr)
        node.addprevious(paragraph)
        return section

    def is_heading(self, node):
        return any(self.nodes[a] is node and info['type'] == 'heading'
                   for a, info in self.anchors.items())

    def figure_captions(self, node):
        """Accept adjacent styled captions and the exporters' title/prose pair.

        Only one unstyled prose paragraph may follow the numbered title.
        Never traverse another object, heading, section or empty separator.
        """
        def eligible(paragraph):
            return (paragraph is not None and paragraph.tag == q('p')
                    and not self.is_heading(paragraph)
                    and paragraph.find('w:pPr/w:sectPr', NS) is None
                    and not paragraph.xpath('.//w:drawing | .//w:pict | .//m:oMath', namespaces=NS)
                    and bool(''.join(paragraph.xpath('.//w:t/text()', namespaces=NS)).strip()))

        captions = []
        current = node.getnext()
        while eligible(current) and caption_for(current, 'figure'):
            captions.append(current)
            current = current.getnext()
        if not captions and eligible(current) and figure_label(current):
            captions.append(current)
            current = current.getnext()
        if (len(captions) == 1 and figure_label(captions[0])
                and eligible(current)
                and not re.match(r'^\s*(?:Table\b|表)', ''.join(current.xpath('.//w:t/text()', namespaces=NS)), re.I)):
            captions.append(current)
        return captions

    def object_block(self, node, kind):
        first, last = node, node
        previous = node.getprevious()
        # A paragraph's sectPr terminates its own source section. Its caption
        # text cannot make it part of the object in the following section.
        if caption_for(previous, kind) and previous.find('w:pPr/w:sectPr', NS) is None:
            first = previous
        if kind == 'figure':
            captions = self.figure_captions(node)
            if captions:
                last = captions[-1]
        elif caption_for(node.getnext(), kind):
            last = node.getnext()
        while self.is_heading(first.getprevious()):
            previous = first.getprevious()
            if previous.find('w:pPr/w:sectPr', NS) is not None:
                break
            first = previous
        return first, last

    def object_pagination(self):
        for anchor, info in self.anchors.items():
            if info['type'] != 'figure':
                continue
            node = self.nodes[anchor]
            captions = self.figure_captions(node)
            group = [node, *captions]
            for index, paragraph in enumerate(group):
                ppr = prop(paragraph, 'pPr')
                prop(ppr, 'keepLines').set(q('val'), 'true')
                # Explicit false also overrides inherited Caption keepNext.
                prop(ppr, 'keepNext').set(q('val'), 'true' if index < len(group) - 1 else 'false')

    def sections(self):
        for i, anchor in enumerate(sorted(self.options.landscape_anchor_ids, key=lambda a: self.anchors.get(a, {}).get('position', -1))):
            node = self.target(anchor, f'landscape_anchor_ids.{i}', {'table', 'figure'})
            if node.find('w:pPr/w:sectPr', NS) is not None:
                raise StorageError('layout_target_invalid', '横向对象自身包含现有节边界，请选择独立对象。', 422,
                                   params={'path': f'landscape_anchor_ids.{i}'})
            source_section = self.effective_section(node, clone=False)
            section = deepcopy(source_section)
            first, last = self.object_block(node, self.anchors[anchor]['type'])
            preceding = first
            while preceding is not node:
                prop(prop(preceding, 'pPr'), 'keepNext').set(q('val'), 'true')
                preceding = preceding.getnext()
            previous = first.getprevious()
            has_preceding_content = previous is not None and previous.find('w:pPr/w:sectPr', NS) is None
            if has_preceding_content:
                self.break_before(first, deepcopy(section))
            # The first new fragment owns the original explicit page restart.
            # The old terminating sectPr now describes only the continuation.
            # Other original sections retain their intentional restart settings.
            original_number = source_section.find(q('pgNumType'))
            if original_number is not None:
                original_number.attrib.pop(q('start'), None)
            landscape = deepcopy(section)
            landscape_number = landscape.find(q('pgNumType'))
            if landscape_number is not None and has_preceding_content:
                landscape_number.attrib.pop(q('start'), None)
            size = prop(landscape, 'pgSz')
            a, b = int(size.get(q('w'), '11906')), int(size.get(q('h'), '16838'))
            size.set(q('w'), str(max(a, b)))
            size.set(q('h'), str(min(a, b)))
            size.set(q('orient'), 'landscape')
            ending = last.find('w:pPr/w:sectPr', NS)
            if ending is source_section:
                # A trailing table caption can terminate this original section.
                # Reuse its boundary: an extra terminator after it would put
                # only an empty paragraph in landscape, leaving the table out.
                ending.getparent().replace(ending, landscape)
            else:
                after = element('w:p')
                last.addnext(after)
                self.break_before(after, landscape)
        pagination = self.options.pagination
        if pagination is not None:
            body_node = None
            if pagination.mode == 'roman_front':
                body_node = self.target(pagination.body_anchor_id, 'pagination.body_anchor_id', {'heading'})
                previous = body_node.getprevious()
                # Landscape grouping or the original source may already start
                # this heading in a new section. Reuse that boundary.
                if previous is not None and previous.find('w:pPr/w:sectPr', NS) is None:
                    self.break_before(body_node, self.effective_section(body_node))
            switched = body_node is None
            first_front = first_body = True
            for node in self.body:
                if node is body_node:
                    switched = True
                section = node if node.tag == q('sectPr') else node.find('w:pPr/w:sectPr', NS)
                if section is None:
                    continue
                number = prop(section, 'pgNumType')
                number.set(q('fmt'), 'decimal' if switched else 'lowerRoman')
                number.attrib.pop(q('start'), None)
                if (switched and first_body) or (not switched and first_front):
                    number.set(q('start'), '1')
                if switched:
                    first_body = False
                else:
                    first_front = False
            self.ensure_page_footer()

    def ensure_page_footer(self):
        # A dedicated footer keeps existing headers/footer content and page fields.
        sections = self.root.findall('.//' + q('sectPr'))
        existing = [name for name in self.parts if name.startswith('word/footer') and name.endswith('.xml')]
        for name in existing:
            footer = parse(self.parts[name])
            instructions = footer.xpath('//w:instrText/text() | //w:fldSimple/@w:instr', namespaces=NS)
            if any(re.search(r'\bPAGE\b', value) for value in instructions):
                continue
            paragraph = element('w:p')
            fld = element('w:fldSimple', instr='PAGE')
            fld.append(text_run('1'))
            paragraph.append(fld)
            footer.append(paragraph)
            self.parts[name] = encode(footer)
        settings = parse(self.parts.get('word/settings.xml', encode(element('w:settings'))))
        even_setting = settings.find(q('evenAndOddHeaders'))
        even_enabled = even_setting is not None and even_setting.get(q('val'), 'true') not in ('0', 'false', 'off')
        inherited = {}
        missing = []
        for section in sections:
            for reference in section.findall(q('footerReference')):
                inherited[reference.get(q('type'), 'default')] = reference.get('{' + OFFICE_REL.rstrip('/') + '}id')
            first_setting = section.find(q('titlePg'))
            first_enabled = first_setting is not None and first_setting.get(q('val'), 'true') not in ('0', 'false', 'off')
            required = ['default'] + (['first'] if first_enabled else []) + (['even'] if even_enabled else [])
            for kind in required:
                if kind not in inherited:
                    missing.append((section, kind))
                    # Later omissions must continue this newly established chain.
                    inherited[kind] = 'rIdPALayoutFooter'
        if not missing:
            return
        path = 'word/footer-paperassist-layout.xml'
        footer = element('w:ftr')
        paragraph = element('w:p')
        footer.append(paragraph)
        # Footer PAGE is evaluated by Word/LO and does not need a source anchor.
        fld = element('w:fldSimple', instr='PAGE')
        fld.append(text_run('1'))
        paragraph.append(fld)
        self.parts[path] = encode(footer)
        relpath = 'word/_rels/document.xml.rels'
        rels = parse(self.parts[relpath]) if relpath in self.parts else E.Element('{' + REL + '}Relationships')
        rid = 'rIdPALayoutFooter'
        if any(n.get('Id') == rid for n in rels):
            raise StorageError('layout_source_invalid', '来源已含排版专用关系，请选择原始导出。', 422)
        relation = E.SubElement(rels, '{' + REL + '}Relationship', Id=rid, Type=OFFICE_REL + 'footer', Target=path.removeprefix('word/'))
        self.parts[relpath] = encode(rels)
        types = parse(self.parts['[Content_Types].xml'])
        E.SubElement(types, '{' + CONTENT + '}Override', PartName='/' + path,
                     ContentType='application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml')
        self.parts['[Content_Types].xml'] = encode(types)
        for section, kind in missing:
            reference = element('w:footerReference', type=kind)
            reference.set('{' + OFFICE_REL.rstrip('/') + '}id', rid)
            section.insert(0, reference)

    def finish(self):
        if 'customXml/paperassist-layout.xml' in self.parts:
            raise StorageError('layout_source_invalid', '来源已含排版对象，请选择原始成功 DOCX。', 422)
        self.headings()
        self.formulas()
        self.references()
        self.toc()
        self.object_pagination()
        self.sections()
        self.parts['word/document.xml'] = encode(self.root)
        settings = parse(self.parts.get('word/settings.xml', encode(element('w:settings'))))
        prop(settings, 'updateFields').set(q('val'), 'true')
        self.parts['word/settings.xml'] = encode(settings)
        provenance = E.Element('paperassist-layout')
        provenance.text = json.dumps(self.manifest, ensure_ascii=False, separators=(',', ':'))
        self.parts['customXml/paperassist-layout.xml'] = encode(provenance)
        return write_package(self.parts)


def apply_layout(content: bytes, options: LayoutOptions, *, language: str) -> bytes:
    if not isinstance(options, LayoutOptions):
        raise TypeError('options must be LayoutOptions')
    return Editor(content, options, language).finish()
