"""Render the bounded AST as editable Office Math, never bitmap equations."""
from lxml import etree as E

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
M = 'http://schemas.openxmlformats.org/officeDocument/2006/math'


def element(tag, **attrs):
    prefix, local = tag.split(':')
    uri = W if prefix == 'w' else M
    node = E.Element(f'{{{uri}}}{local}')
    for key, value in attrs.items():
        node.set(f'{{{uri}}}{key}', str(value))
    return node


def wrapped(name, node):
    result = element('m:' + name)
    result.extend(render(node))
    return result


def render(node):
    kind = node.kind
    if kind == 'seq':
        return [child for part in node.children for child in render(part)]
    if kind == 'text':
        run = element('m:r')
        props = element('w:rPr')
        fonts = element('w:rFonts', ascii='Cambria Math', hAnsi='Cambria Math')
        props.append(fonts)
        run.append(props)
        text = element('m:t')
        text.text = node.value
        run.append(text)
        return [run]
    if kind == 'frac':
        out = element('m:f')
        out.extend([wrapped('num', node.children[0]), wrapped('den', node.children[1])])
    elif kind == 'sqrt':
        out = element('m:rad')
        props = element('m:radPr')
        props.append(element('m:degHide', val='0' if node.children[0].children else '1'))
        out.extend([props, wrapped('deg', node.children[0]), wrapped('e', node.children[1])])
    elif kind == 'scripts':
        base, sub, sup = node.children
        out = element('m:' + ('sSubSup' if sub and sup else 'sSub' if sub else 'sSup'))
        out.append(wrapped('e', base))
        if sub:
            out.append(wrapped('sub', sub))
        if sup:
            out.append(wrapped('sup', sup))
    elif kind == 'nary':
        out = element('m:nary')
        props = element('m:naryPr')
        props.extend([element('m:chr', val=node.value), element('m:limLoc', val='subSup'),
                      element('m:subHide', val='0' if width(node.children[0]) else '1'),
                      element('m:supHide', val='0' if width(node.children[1]) else '1')])
        out.append(props)
        out.extend([wrapped(tag, child) for tag, child in zip(('sub', 'sup', 'e'), node.children)])
    elif kind == 'aligned':
        out = element('m:eqArr')
        for row in node.children:
            out.append(wrapped('e', row[0]))
    elif kind in ('matrix', 'cases'):
        matrix = element('m:m')
        for row in node.children:
            mr = element('m:mr')
            mr.extend(wrapped('e', cell) for cell in row)
            matrix.append(mr)
        out = element('m:d')
        props = element('m:dPr')
        props.extend([element('m:begChr', val='{' if kind == 'cases' else '('),
                      element('m:endChr', val='' if kind == 'cases' else ')')])
        entry = element('m:e')
        entry.append(matrix)
        out.extend([props, entry])
    else:
        raise ValueError(kind)
    return [out]


def width(node):
    """Conservative width in em-like units, used to reject unbreakable input."""
    if node is None:
        return 0
    if node.kind == 'text':
        return len(node.value)
    if node.kind == 'seq':
        return sum(width(n) for n in node.children)
    if node.kind == 'frac':
        return max(map(width, node.children)) + 2
    if node.kind == 'sqrt':
        return width(node.children[1]) + 3
    if node.kind == 'scripts':
        return width(node.children[0]) + max(width(node.children[1]), width(node.children[2])) * .7
    if node.kind == 'nary':
        return max(width(node.children[0]), width(node.children[1]), 2) + width(node.children[2])
    return max(sum(width(cell) + 2 for cell in row) for row in node.children) + 2
