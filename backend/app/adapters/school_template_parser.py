"""Passive school-template facts; text requirements remain source-bound proposals."""
from copy import deepcopy
from io import BytesIO
import json
import posixpath
import re
from zipfile import ZipFile

from lxml import etree as E

from app.adapters.docx_parser import parse_docx, props, DOCX_SETTINGS, W, NS
from app.core.exceptions import StorageError

PARSER_VERSION = 'school-template-openxml-v1'
Q = '{' + W + '}'
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
MAX_RESULT_BYTES = 4194304
RESULT_KEYS = frozenset(('parser_version', 'raw_styles', 'defaults', 'sections', 'chapters',
                         'rules', 'notes', 'conflicts', 'missing', 'unsupported', 'identity_fields'))


def _xml(raw):
    if b'<!DOCTYPE' in raw.upper().replace(b'\0', b'') or b'<!ENTITY' in raw.upper().replace(b'\0', b''):
        raise StorageError('invalid_document', '模板包含不支持的XML声明。', 422)
    return E.fromstring(raw, E.XMLParser(resolve_entities=False, no_network=True, load_dtd=False))


def _value(node, name, attribute='val'):
    child = node.find('w:' + name, NS) if node is not None else None
    return child.get(Q + attribute) if child is not None else None


def _text(node):
    return ''.join(node.xpath('.//w:t[not(ancestor::w:txbxContent) and not(ancestor::w:del) and not(ancestor::w:ins)]/text()', namespaces=NS)).strip()


def _source(node, part='word/document.xml', text=None):
    return {'part': part, 'path': node.getroottree().getpath(node), 'text': _text(node) if text is None else text}


def _cm(value):
    return round(int(value) * 2.54 / 1440, 2)


def _interpret_requirements(sections, rules, notes):
    proposed = {}

    def offer(identity, value, source):
        items = proposed.setdefault(identity, [])
        if not any(existing[0] == value for existing in items):
            items.append((value, source))

    sizes = {'小一': 24, '一': 26, '小二': 18, '二': 22, '小三': 15, '三': 16, '小四': 12, '四': 14, '小五': 9, '五': 10.5}
    for note in notes:
        text, source = note['text'], note['source']
        margin_matches = [(m[1], float(m[2])) for m in re.finditer(r'([上下左右][^，。,;\n]{0,15}?)(?:留边|留|边距|[:：])\s*(\d+(?:\.\d+)?)\s*(?:cm|厘米)', text, re.I)]
        margin_matches += [(m[1], float(m[2])) for m in re.finditer(r'([上下左右])(?:边距|侧|方)?\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(?:cm|厘米)', text, re.I)]
        for directions, value in margin_matches:
            for character, key in (('上', 'top'), ('下', 'bottom'), ('左', 'left'), ('右', 'right')):
                if character in directions:
                    for section in sections:
                        offer(section['id'] + '.margin_' + key + '_cm', value, source)
        for clause in re.split(r'[。！？\n]', text):
            for pattern, render in ((r'字数(?:要求|控制在)?\s*(\d+)\s*[-—至~]\s*(\d+)', lambda m: m[1] + '-' + m[2] + '字'),
                                    (r'字数(?:要求)?\s*(\d+)字左右', lambda m: '约' + m[1] + '字')):
                for match in re.finditer(pattern, clause):
                    context = clause[:match.start()]
                    abstract = context.rfind('摘要')
                    other = max(context.rfind(label) for label in ('正文', '全文', '致谢', '结论', '参考文献'))
                    if abstract >= 0 and abstract > other:
                        offer('abstract.word_count', render(match), source)
        for prefix, role in (('一级标题', 'heading1'), ('二级标题', 'heading2'), ('三级标题', 'heading3'),
                             ('正文：', 'body'), ('正文:', 'body'), ('图的题注', 'figure_caption'), ('表的标题', 'table_caption')):
            if prefix in text:
                suffix = re.split(r'[；;。\n]|一级标题|二级标题|三级标题|正文[：:]|图的题注|表的标题', text.split(prefix, 1)[1], maxsplit=1)[0][:180]
                size = re.search(r'(小?[一二三四五])号字?', suffix)
                if size:
                    offer(role + '.font_size_pt', sizes[size[1]], source)
                if '黑体' in suffix:
                    offer(role + '.font_east_asia', '黑体', source)
                elif '宋体' in suffix:
                    offer(role + '.font_east_asia', '宋体', source)
    conflicts = []
    for identity, candidates in proposed.items():
        existing = next((r for r in rules if r['id'] == identity), None)
        actual = existing if existing and existing.get('origin') != 'text_requirement' else None
        options = [{'id': 'openxml', 'value': actual['value'], 'source': actual['source']}] if actual else []
        for value, source in candidates:
            equivalent = lambda old: abs(old-value) <= .02 if isinstance(old, (int, float)) and isinstance(value, (int, float)) else old == value
            if not any(equivalent(option['value']) for option in options):
                options.append({'id': 'text-' + str(len(options)+1), 'value': value, 'source': source})
        if actual is None and options:
            target = existing or {'id': identity, 'category': 'text_requirement',
                                  'label': '摘要字数' if identity == 'abstract.word_count' else identity,
                                  'origin': 'text_requirement'}
            target.update(value=options[0]['value'] if len(options) == 1 else None, source=options[0]['source'])
            if existing is None:
                rules.append(target)
        if len(options) > 1:
            conflicts.append({'id': f'conflict-{len(conflicts)+1}', 'rule_id': identity,
                              'label': actual['label'] if actual else '摘要字数' if identity == 'abstract.word_count' else identity,
                              'message': '实际属性与文字规范或多处文字表述不同，需确认适用要求。', 'options': options})
    return conflicts


def merge_template_notes(analysis: dict, notes: list) -> dict:
    """Use the same comparison for frozen supplemental quotes and inline requirements."""
    result = deepcopy(analysis)
    seen = {(n['text'], n['source']['part'], n['source']['path']) for n in result['notes']}
    for note in notes:
        key = (note['text'], note['source']['part'], note['source']['path'])
        if key not in seen:
            result['notes'].append(deepcopy(note))
            seen.add(key)
    result['conflicts'] = _interpret_requirements(result['sections'], result['rules'], result['notes'])
    if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_RESULT_BYTES:
        raise StorageError('parse_output_invalid', '模板及补充规范解析结果超过限制。', 422)
    return result


def inspect_school_template(content: bytes, filename: str) -> dict:
    # Reuse bounded DOCX package/structure validation, without altering its old output contract.
    base = parse_docx(content, filename, DOCX_SETTINGS).document
    with ZipFile(BytesIO(content)) as package:
        parts = {n: package.read(n) for n in package.namelist() if n.endswith(('.xml', '.rels'))}
        has_ole = any('/embeddings/' in n and not n.endswith('/') for n in package.namelist())
    root = _xml(parts['word/document.xml'])
    style_root = _xml(parts['word/styles.xml']) if 'word/styles.xml' in parts else None
    defaults = {'paragraph': {}, 'run': {}}
    if style_root is not None:
        defaults = {'paragraph': props(style_root.find('w:docDefaults/w:pPrDefault/w:pPr', NS)),
                    'run': props(style_root.find('w:docDefaults/w:rPrDefault/w:rPr', NS))}
    raw_styles = [s.model_dump() for s in base.styles]
    styles = {s['id']: s for s in raw_styles}
    style_nodes = {s.get(Q + 'styleId'): s for s in style_root.findall('w:style', NS)} if style_root is not None else {}
    unsupported = [{'id': 'text_rules_manual', 'message': '文字规范按来源引用；仅自动解释确定的页面、字号及字体等规则，其余要求须人工核对。本批不验证论文生成或排版还原。'}]
    style_cache = {}

    def style_properties(identity, seen=()):
        if not identity or identity not in styles:
            return {}
        if identity in seen:
            if not any(i['id'] == 'style_cycle' for i in unsupported):
                unsupported.append({'id': 'style_cycle', 'message': '存在循环样式继承；相关属性不能完整确定。'})
            return {}
        if identity not in style_cache:
            style = styles[identity]
            inherited = style_properties(style.get('based_on'), (*seen, identity))
            style_cache[identity] = {**inherited, **style['properties']}
        return style_cache[identity]

    default_style = None
    if style_root is not None:
        default_style = next((n.get(Q + 'styleId') for n in style_root.findall('w:style', NS)
                              if n.get(Q + 'type') == 'paragraph' and n.get(Q + 'default') in ('1', 'true')), None)

    def property_source(node, prop):
        paragraph = node.find('w:pPr', NS)
        runs = [r for r in node.findall('.//' + Q + 'r') if _text(r)]
        character_style = None
        if prop.startswith('rPr.') and runs:
            run_pr = runs[0].find('w:rPr', NS)
            if prop[4:] in props(run_pr):
                return _source(run_pr, text=f'{prop}；示例：{_text(node)[:120]}'), 'direct'
            character_style = _value(run_pr, 'rStyle')
        if prop.startswith('pPr.') and prop[4:] in props(paragraph):
            return _source(paragraph, text=f'{prop}；示例：{_text(node)[:120]}'), 'direct'
        for identity in (character_style, _value(paragraph, 'pStyle') or default_style):
            seen = set()
            while identity in styles and identity not in seen:
                seen.add(identity)
                style = styles[identity]
                if prop in style['properties']:
                    return _source(style_nodes[identity], 'word/styles.xml', f'样式 {style["name"]}：{prop}={style["properties"][prop]}'), 'style_inheritance'
                identity = style.get('based_on')
        if style_root is not None:
            default_node = style_root.find('w:docDefaults', NS)
            if default_node is not None:
                return _source(default_node, 'word/styles.xml', f'文档默认属性：{prop}'), 'document_default'
        return _source(node), 'unknown'
    settings = _xml(parts['word/settings.xml']) if 'word/settings.xml' in parts else None
    even = settings.find('w:evenAndOddHeaders', NS) if settings is not None else None
    even_enabled = even is not None and even.get(Q + 'val', '1') not in ('0', 'false', 'off')
    relations = {}
    if 'word/_rels/document.xml.rels' in parts:
        for rel in _xml(parts['word/_rels/document.xml.rels']):
            if rel.get('TargetMode', '').lower() != 'external':
                target = rel.get('Target', '')
                name = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join('word', target))
                if name.startswith('word/') and name in parts:
                    relations[rel.get('Id')] = name
    sections, rules, conflicts = [], [], []
    prior_parts = {'headers': {}, 'footers': {}}
    for index, node in enumerate(root.findall('.//' + Q + 'sectPr'), 1):
        page = {}
        for tag, mapping in (('pgSz', {'w': 'width_cm', 'h': 'height_cm'}),
                             ('pgMar', {k: 'margin_' + k + '_cm' for k in ('top', 'bottom', 'left', 'right')})):
            child = node.find('w:' + tag, NS)
            if child is not None:
                for attribute, key in mapping.items():
                    value = child.get(Q + attribute)
                    if value is not None:
                        try:
                            page[key] = _cm(value)
                        except (ValueError, OverflowError):
                            raise StorageError('invalid_document', '模板页面属性无效。', 422) from None
                        rules.append({'id': f'section-{index}.{key}', 'category': 'page',
                                      'label': f'第{index}节 ' + {'width_cm': '页面宽度', 'height_cm': '页面高度', 'margin_top_cm': '上边距', 'margin_bottom_cm': '下边距', 'margin_left_cm': '左边距', 'margin_right_cm': '右边距'}[key] + '（cm）',
                                      'value': page[key], 'source': _source(child, text=f'{attribute}={value} twips')})
        number = node.find('w:pgNumType', NS)
        first = node.find('w:titlePg', NS)
        section = {'id': f'section-{index}', 'page': page, 'source': _source(node, text='分节属性'),
                   'different_first_page': first is not None and first.get(Q + 'val', '1') not in ('0', 'false', 'off'),
                   'different_odd_even_pages': even_enabled,
                   'page_number': {'format': number.get(Q + 'fmt') if number is not None else None,
                                   'start': number.get(Q + 'start') if number is not None else None,
                                   'mode': 'restart' if number is not None and number.get(Q + 'start') is not None else 'continue_or_default'},
                   'break_type': _value(node, 'type')}
        for key, tag in (('headers', 'headerReference'), ('footers', 'footerReference')):
            direct = {n.get(Q + 'type', 'default'): relations.get(n.get(REL + 'id')) for n in node.findall('w:' + tag, NS)}
            section[key] = []
            for kind in ('default', 'first', 'even'):
                part = direct[kind] if kind in direct else prior_parts[key].get(kind)
                text, fields = '', []
                if part:
                    sub = _xml(parts[part])
                    text = _text(sub)
                    fields = sub.xpath('//w:instrText/text() | //w:fldSimple/@w:instr', namespaces=NS)
                section[key].append({'type': kind, 'part': part, 'text': text, 'fields': fields,
                                     'linked_to_previous': index > 1 and kind not in direct,
                                     'source': _source(node, text=tag + ':' + kind)})
                if part:
                    prior_parts[key][kind] = part
        sections.append(section)
    notes, seen_notes, paragraphs = [], set(), []
    normative = re.compile(r'字体|字号|号字|行距|间距|页边距|页面设置|留边|留\d|字数|关键词.{0,10}\d|关键字|编号|图的题注|图的环绕|表的标题|脚注|参考文献\d|签名|注意|全文中|图片缩放|自绘图|截图、照片')
    for node in root.xpath('/w:document/w:body/w:p', namespaces=NS):
        text = _text(node)
        if text:
            paragraphs.append((node, text))
            if normative.search(text) and text not in seen_notes:
                notes.append({'id': f'note-{len(notes)+1}', 'text': text, 'source': _source(node, text=text)})
                seen_notes.add(text)
    # DrawingML Choice and VML Fallback often duplicate the same annotation.
    for box in root.findall('.//' + Q + 'txbxContent'):
        text = ''.join(box.xpath('.//w:t/text()', namespaces=NS)).strip()
        if text and text not in seen_notes:
            notes.append({'id': f'note-{len(notes)+1}', 'text': text, 'source': _source(box, text=text)})
            seen_notes.add(text)
    chapters, exemplars = [], {}
    after_heading = False
    for node, text in paragraphs:
        paragraph = node.find('w:pPr', NS)
        identity = _value(paragraph, 'pStyle') or default_style
        effective = {**{'pPr.' + k: v for k, v in defaults['paragraph'].items()},
                     **{'rPr.' + k: v for k, v in defaults['run'].items()},
                     **style_properties(identity), **{'pPr.' + k: v for k, v in props(paragraph).items()}}
        runs = [r for r in node.findall('.//' + Q + 'r') if _text(r)]
        if runs:
            run = runs[0]
            run_style = _value(run.find('w:rPr', NS), 'rStyle')
            effective.update(style_properties(run_style))
            effective.update({'rPr.' + k: v for k, v in props(run.find('w:rPr', NS)).items()})
        level = effective.get('pPr.outlineLvl.val')
        level = int(level) + 1 if level is not None and str(level).isdigit() and int(level) < 9 else None
        if level is None and identity:
            style_name = styles.get(identity, {}).get('name', identity)
            match = re.match(r'heading\s*([1-9])$', style_name, re.I)
            if match:
                level = int(match[1])
        instructions = ' '.join(node.xpath('.//w:instrText/text() | .//w:fldSimple/@w:instr', namespaces=NS))
        is_toc = bool(identity and re.match(r'toc\s*\d', styles.get(identity, {}).get('name', identity), re.I)) or bool(re.search(r'PAGEREF|HYPERLINK\s+\\l\s+"?_Toc', instructions, re.I))
        role = None
        compact = re.sub(r'\s', '', text)
        named_part = compact in ('摘要', 'Abstract', 'ABSTRACT', '参考文献', '目录', '致谢', '学位论文独创性声明', '学位论文版权使用授权书') or bool(re.match(r'^附录[A-ZＡ-Ｚ][:：]', compact))
        guide = text.startswith(('自绘图', '截图、照片', '注意：', '一级标题：', '二级标题：', '三级标题：'))
        if (level or named_part) and not is_toc and not guide:
            chapters.append({'id': 'chapter-' + str(len(chapters)+1), 'title': text, 'level': level or 1, 'source': _source(node)})
        if level and not is_toc and not guide:
            role = f'heading{level}'
            after_heading = True
        if compact in ('摘要', 'Abstract', 'ABSTRACT', '参考文献', '目录', '致谢'):
            role = {'摘要': 'abstract_heading_zh', 'Abstract': 'abstract_heading_en', 'ABSTRACT': 'abstract_heading_en',
                    '参考文献': 'references_heading', '目录': 'toc_heading', '致谢': 'acknowledgements_heading'}[compact]
        elif re.match(r'^图\s*\d', text):
            role = 'figure_caption'
        elif re.match(r'^表\s*\d', text):
            role = 'table_caption'
        elif compact.startswith('关键词'):
            role = 'keywords_zh'
        elif compact.lower().startswith('keywords:'):
            role = 'keywords_en'
        elif after_heading and not level and len(text) > 30 and not re.match(r'^(?:注意|正文[：:]|一级标题|二级标题|三级标题|图的题注|表的标题)', text):
            role = 'body'
        if role:
            exemplars.setdefault(role, (node, effective))
    # The paragraph immediately before an abstract is a title example, not a research requirement.
    for index, (node, text) in enumerate(paragraphs):
        if re.sub(r'\s', '', text) in ('摘要', 'Abstract', 'ABSTRACT') and index:
            previous = paragraphs[index-1][0]
            role = 'title_zh' if '摘' in text else 'title_en'
            properties = {**{'rPr.' + k: v for k, v in defaults['run'].items()},
                          **style_properties(_value(previous.find('w:pPr', NS), 'pStyle') or default_style)}
            runs = [r for r in previous.findall('.//' + Q + 'r') if _text(r)]
            if runs:
                properties.update({'rPr.' + k: v for k, v in props(runs[0].find('w:rPr', NS)).items()})
            exemplars.setdefault(role, (previous, properties))
    title_paths = {node.getroottree().getpath(node) for role, (node, _) in exemplars.items() if role in ('title_zh', 'title_en')}
    chapters = [chapter for chapter in chapters if chapter['source']['path'] not in title_paths]
    labels = {'body': '正文示例', 'heading1': '一级标题', 'heading2': '二级标题', 'heading3': '三级标题',
              'title_zh': '中文题目示例', 'title_en': '英文题目示例', 'figure_caption': '图题示例', 'table_caption': '表题示例',
              'abstract_heading_zh': '中文摘要标题', 'abstract_heading_en': '英文摘要标题', 'references_heading': '参考文献标题',
              'toc_heading': '目录标题', 'acknowledgements_heading': '致谢标题', 'keywords_zh': '中文关键词', 'keywords_en': '英文关键词'}
    for role, (node, effective) in exemplars.items():
        for key, prop, label in (('font_east_asia', 'rPr.rFonts.eastAsia', '中文字体'),
                                 ('font_latin', 'rPr.rFonts.ascii', '西文字体'), ('font_size_pt', 'rPr.sz.val', '字号（pt）'),
                                 ('alignment', 'pPr.jc.val', '对齐'), ('line_spacing', 'pPr.spacing.line', '行距原始值'),
                                 ('line_rule', 'pPr.spacing.lineRule', '行距方式'), ('first_line_chars', 'pPr.ind.firstLineChars', '首行缩进（百分之一字符）')):
            if prop in effective:
                value = effective[prop]
                if key == 'font_size_pt':
                    try:
                        value = int(value) / 2
                    except ValueError:
                        continue
                source, origin = property_source(node, prop)
                rules.append({'id': role + '.' + key, 'category': role, 'label': labels.get(role, role) + ' ' + label,
                              'value': value, 'source': source, 'origin': origin, 'example_source': _source(node)})
    conflicts = _interpret_requirements(sections, rules, notes)
    if has_ole:
        unsupported.append({'id': 'embedded_objects', 'message': '模板含OLE嵌入对象（如公式）；仅保留原件，不执行或承诺转换还原。'})
    if any('脚注' in n['text'] for n in notes):
        unsupported.append({'id': 'footnote_citations', 'message': '规范含当页脚注引用要求；本批仅保留来源与要求，后续学校导出需单独验证。'})
    for warning in base.warnings:
        if warning.code not in ('other_parts', 'textboxes', 'fields'):
            unsupported.append({'id': warning.code, 'message': warning.message})
    missing = []
    if not chapters:
        missing.append({'id': 'chapters', 'message': '未识别到可靠的标题层级，请在确认前补充学校章节与顺序。'})
    if not any(re.sub(r'\s', '', t).startswith('封面') for _, t in paragraphs):
        missing.append({'id': 'cover_rules', 'message': '未确定完整封面字段和版式；本批不能宣称封面已支持。'})
    if not notes:
        missing.append({'id': 'text_specifications', 'message': '未发现可定位的文字规范；请补充学校要求或保留未知状态。'})
    all_text = '\n'.join(t for _, t in paragraphs)
    identity = [name for name in ('作者姓名', '学号', '作者签名', '指导教师签名', '签字日期') if name in all_text]
    result = dict(parser_version=PARSER_VERSION, raw_styles=raw_styles, defaults=defaults, sections=sections,
                  chapters=chapters, rules=rules, notes=notes, conflicts=conflicts, missing=missing,
                  unsupported=unsupported, identity_fields=identity)
    if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_RESULT_BYTES:
        raise StorageError('parse_output_invalid', '模板结构超出解析结果大小限制。', 422)
    return result
