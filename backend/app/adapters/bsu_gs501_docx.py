"""Copy the GS501 official front forms into a fresh Word package."""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from unicodedata import east_asian_width
from zipfile import ZipFile

from docx.opc.constants import RELATIONSHIP_TYPE
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsmap, qn
from lxml import etree

from app.adapters.task_store import source_conflict
from app.domain.school_templates import bsu_gs501


END_OF_FRONT_MATTER = 63
FORM_STYLES = ('a', 'a0', 'a1', 'a9', 'aa', 'ae', 'af', 'Default')
RELATIONSHIP_NS = '{' + nsmap['r'] + '}'
SPACE = '{http://www.w3.org/XML/1998/namespace}space'
GRAPHICS = {
    'rId7': ('word/media/image1.jpeg', '北京体育大学校徽'),
    'rId8': ('word/media/image2.jpeg', '北京体育大学校名'),
    'rId9': ('word/media/image3.jpeg', '北京体育大学校徽及校名'),
}


def _import_form_styles(document, original):
    styles = document.styles.element
    defaults = qn('w:docDefaults')
    styles.replace(styles.find(defaults), deepcopy(original.find(defaults)))
    for destination in ('Normal', 'DefaultParagraphFont', 'TableNormal'):
        style = styles.get_by_id(destination)
        style.attrib.pop(qn('w:default'), None)
        name = style.find(qn('w:name'))
        name.set(qn('w:val'), 'PaperAssist ' + name.get(qn('w:val')))
    for source in original.findall(qn('w:style')):
        identity = source.get(qn('w:styleId'))
        if identity not in FORM_STYLES:
            continue
        style = deepcopy(source)
        if identity == 'ae':
            style.find(qn('w:name')).set(qn('w:val'), 'GS501 Table Grid')
        styles.append(style)


def _copy_layout_settings(document, original):
    settings = document.settings.element
    keys = ('defaultTabStop', 'drawingGridHorizontalSpacing', 'drawingGridVerticalSpacing',
            'displayHorizontalDrawingGridEvery', 'displayVerticalDrawingGridEvery', 'characterSpacingControl',
            'compat', 'themeFontLang', 'clrSchemeMapping')
    for key in keys:
        tag = qn('w:' + key)
        previous = settings.find(tag)
        replacement = deepcopy(original.find(tag))
        if previous is None:
            settings.find(qn('w:characterSpacingControl')).addprevious(replacement)
        else:
            settings.replace(previous, replacement)


def preserve_generated_body_style(document):
    """Keep the renderer's paragraph default outside the copied pages."""
    for node in document.element.body[END_OF_FRONT_MATTER:]:
        for paragraph in node.iter(qn('w:p')):
            if paragraph.style is None:
                paragraph.style = 'Normal'


def _connect_graphics(document, nodes, archive):
    for parent in nodes:
        for drawing in parent.iter(qn('w:drawing')):
            for bitmap in drawing.iter(qn('a:blip')):
                part, description = GRAPHICS[bitmap.get(qn('r:embed'))]
                rel, _ = document.part.get_or_add_image(BytesIO(archive.read(part)))
                bitmap.set(qn('r:embed'), rel)
                for node in drawing.iter():
                    if 'descr' in node.attrib:
                        node.set('descr', description)
        for node in parent.iter():
            for key in list(node.attrib):
                if key.endswith('}gfxdata'):
                    node.attrib.pop(key)
                if key.startswith(RELATIONSHIP_NS) and node.tag != qn('a:blip'):
                    raise source_conflict()


def _text(node, value):
    node.text = value
    node.set(SPACE, 'preserve')


def _replace(p, value, split=None):
    tokens = list(p.iter(qn('w:t')))
    _text(tokens[0], value if split is None else value[:split])
    for token in tokens[1:]:
        _text(token, '')
    if split is not None:
        line = OxmlElement('w:br')
        tail = OxmlElement('w:t')
        _text(tail, value[split:].lstrip())
        tokens[0].addnext(line)
        line.addnext(tail)


def _slots(paragraph):
    current = None
    slots = []
    for run in paragraph.findall(qn('w:r')):
        tokens = run.findall(qn('w:t'))
        if run.find(qn('w:rPr') + '/' + qn('w:u')) is None or not tokens:
            current = None
            continue
        if current is None:
            current = []
            slots.append(current)
        current.extend(tokens)
    return slots


def _units(text):
    return sum(2 if east_asian_width(char) in ('W', 'F') else 1 for char in text)


def _slot_size(slot):
    return sum(len(token.text or '') for token in slot)


def _fill(slot, value):
    if not value:
        return
    padding = ' ' * max(0, _slot_size(slot) - _units(value))
    _text(slot[0], value + padding)
    for token in slot[1:]:
        _text(token, '')


def _set_cover_title(first, second, title):
    first_slot, = _slots(first)
    second_slot, = _slots(second)
    # The first line also contains the label at 16 pt. Word wraps earlier
    # than the original space count when those spaces become Chinese glyphs.
    length = 32
    split = next((index for index in range(1, len(title) + 1) if _units(title[:index]) > length), len(title) + 1) - 1
    if 0 < split < len(title) and _ascii_word_char(title[split]):
        word_start = split
        while word_start and _ascii_word_char(title[word_start - 1]):
            word_start -= 1
        if word_start:
            split = word_start
    _fill(first_slot, title[:split].rstrip())
    _fill(second_slot, title[split:].lstrip())


def _ascii_word_char(char):
    return char.isascii() and char.isalnum()


def _compact_title_page_spacers(forms, title, english_title):
    # Longer titles can add two lines at the template's original font sizes.
    # Recover that height from the two empty lines above the date.
    if _units(title) <= 46 and _units(english_title) <= 60:
        return
    for paragraph in forms[36:38]:
        spacing = paragraph.get_or_add_pPr().get_or_add_spacing()
        spacing.set(qn('w:line'), '20')
        spacing.set(qn('w:lineRule'), 'exact')


def _balanced_title_break(title):
    width = _units(title)
    if width <= 46:
        return None
    spaces = (i for i, char in enumerate(title) if char == ' ')
    candidates = [(abs(width / 2 - _units(title[:i])), i) for i in spaces
                  if width * .35 <= _units(title[:i]) <= width * .65]
    return min(candidates)[1] if candidates else None


def _set_student_number(table, value):
    label, cell = table.findall(qn('w:tr'))[1].findall(qn('w:tc'))[2:]
    p = cell.find(qn('w:p'))
    if value:
        run = deepcopy(label.find(qn('w:p')).findall(qn('w:r'))[-1])
        _text(run.find(qn('w:t')), value)
        p.append(run)
    return p


def _fill_known_values(forms, title, english_title, values):
    # The positions come from the SHA-pinned appendix. They are direct body
    # children, including the native page breaks in the last paragraph of each page.
    _set_cover_title(forms[4], forms[5], title)
    _replace(forms[25], title, _balanced_title_break(title))
    _replace(forms[26], english_title)
    _compact_title_page_spacers(forms, title, english_title)
    for index, keys in (
        (10, ('college',)), (11, ('discipline',)), (12, ('specialty',)),
        (13, ('author',)), (14, ('supervisor',)), (28, ('author', 'supervisor')),
        (29, ('degree', 'college')), (30, ('discipline', 'specialty')),
    ):
        for slot, key in zip(_slots(forms[index]), keys, strict=True):
            _fill(slot, values.get(key))
    for index, role in enumerate(bsu_gs501.COMMITTEE_ROLES, 32):
        for slot, column in zip(_slots(forms[index]), bsu_gs501.COMMITTEE_COLUMNS, strict=True):
            _fill(slot, values.get(f'committee:{role}:{column}'))
    month = bsu_gs501.submission_month(values.get('submission_date'))
    if month:
        _replace(forms[17], month)
        _replace(forms[38], month)
    student = _set_student_number(forms[0], values.get('student_id'))
    return {student, *(forms[index] for index in (13, 14, 17, 28, 32, 33, 34, 35, 38))}


def insert_submission_forms(document, template, snapshot, plan):
    if template is None or sha256(template).hexdigest() != plan['submission_forms_source_sha256']:
        raise source_conflict()
    with ZipFile(BytesIO(template)) as archive:
        original = parse_xml(archive.read('word/document.xml'))
        forms = [deepcopy(node) for node in original.body[:END_OF_FRONT_MATTER]]
        _import_form_styles(document, parse_xml(archive.read('word/styles.xml')))
        _copy_layout_settings(document, parse_xml(archive.read('word/settings.xml')))
        document.part.part_related_by(RELATIONSHIP_TYPE.THEME)._blob = archive.read('word/theme/theme1.xml')
        _connect_graphics(document, forms, archive)
    protected_nodes = _fill_known_values(forms, snapshot['title'], plan['options'].get('english_title', ''),
                                         bsu_gs501.submission_values(plan))
    for node in forms:
        for cached_break in list(node.iter(qn('w:lastRenderedPageBreak'))):
            cached_break.getparent().remove(cached_break)
        for choice in node.iter('{http://schemas.openxmlformats.org/markup-compatibility/2006}Choice'):
            # The namespace prefix in the Requires value must be in scope.
            prefixes = {prefix: original.nsmap[prefix] for prefix in choice.get('Requires').split()}
            if not prefixes.items() <= choice.nsmap.items():
                replacement = etree.Element(choice.tag, nsmap=prefixes, attrib=choice.attrib)
                replacement.extend(choice)
                choice.getparent().replace(choice, replacement)
        document.element.body.sectPr.addprevious(node)
    return forms, protected_nodes, {forms[8], forms[26]}
