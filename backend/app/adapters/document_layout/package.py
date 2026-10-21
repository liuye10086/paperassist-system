"""Passive DOCX package access. Untouched parts are copied byte for byte."""
from io import BytesIO
from pathlib import PurePosixPath
import re
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile, ZipInfo

from lxml import etree as E

from app.core.exceptions import StorageError

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': W, 'm': 'http://schemas.openxmlformats.org/officeDocument/2006/math'}


def parse(raw):
    return E.fromstring(raw, E.XMLParser(resolve_entities=False, no_network=True))


def encode(root):
    return E.tostring(root, encoding='UTF-8', xml_declaration=True, standalone=True)


def read_package(content):
    try:
        if not content or len(content) > 50 * 1024 * 1024:
            raise ValueError()
        with ZipFile(BytesIO(content)) as z:
            entries = z.infolist()
            names = [i.filename for i in entries]
            if (len(names) > 2000 or len(names) != len(set(names)) or
                    sum(i.file_size for i in entries) > 200 * 1024 * 1024):
                raise ValueError()
            result = {}
            for info in entries:
                name = info.filename
                lower = name.lower()
                if (PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts
                        or '\\' in name or ':' in name or info.flag_bits & 1
                        or any(p in lower for p in ('vbaproject', 'activex', '/embeddings/'))):
                    raise ValueError()
                raw = z.read(name)
                if lower.endswith(('.xml', '.rels')):
                    if b'<!DOCTYPE' in raw.upper().replace(b'\0', b'') or b'<!ENTITY' in raw.upper().replace(b'\0', b''):
                        raise ValueError()
                    root = parse(raw)
                    fields = []
                    for n in root.iter():
                        local = E.QName(n).localname
                        if local in ('object', 'altChunk', 'oleObject', 'control'):
                            raise ValueError()
                        if local == 'Relationship' and n.get('TargetMode', '').lower() == 'external' and not n.get('Type', '').endswith('/hyperlink'):
                            raise ValueError()
                        if local == 'Override' and 'macroenabled' in n.get('ContentType', '').lower():
                            raise ValueError()
                        if local == 'instrText':
                            fields.append(n.text or '')
                        if local == 'fldSimple':
                            fields.append(n.get(f'{{{W}}}instr', ''))
                    if re.search(r'\b(DDEAUTO|DDE|INCLUDETEXT|INCLUDEPICTURE|LINK|DATABASE)\b', ''.join(fields), re.I):
                        raise ValueError()
                result[name] = raw
            if not {'[Content_Types].xml', 'word/document.xml'}.issubset(result):
                raise ValueError()
            return result
    except (BadZipFile, ValueError, OSError, KeyError, RuntimeError, E.XMLSyntaxError) as exc:
        raise StorageError('layout_source_invalid', '来源 DOCX 无效或包含不支持的活动内容。', 422) from exc


def write_package(parts):
    stream = BytesIO()
    with ZipFile(stream, 'w', compression=ZIP_DEFLATED) as z:
        for name, data in parts.items():
            info = ZipInfo(name, (2000, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            z.writestr(info, data)
    return stream.getvalue()
