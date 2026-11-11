"""Bounded raw-text CSV/TSV and OOXML tables; never evaluates cell contents."""
import csv
import io
import posixpath
import re
import stat
import zipfile
from defusedxml.ElementTree import iterparse, fromstring
from .inputs import verify_member
from app.domain.bioinformatics.settings import BioLimits

PARSER_VERSION = 'bio_insight_table_v1'
NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'


def _xlsx_rows(path, sheet, limit):
    if not sheet: raise ValueError('xlsx_explicit_sheet_required')
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist(); names = [item.filename for item in infos]
        if len(infos) > 10000 or len(set(names)) != len(names): raise ValueError('xlsx_archive_invalid')
        total = 0
        for item in infos:
            name = item.filename; total += item.file_size
            if (name.startswith(('/', '\\')) or '\\' in name or '..' in name.split('/')
                    or stat.S_ISLNK(item.external_attr >> 16) or item.flag_bits & 1 or total > limit
                    or 'vbaproject' in name.lower() or 'externallinks/' in name.lower()):
                raise ValueError('xlsx_archive_unsafe')
        # Reject all external relationships, not just worksheet hyperlinks.
        for name in names:
            if name.endswith('.rels'):
                if archive.getinfo(name).file_size > 8 * 1024**2: raise ValueError('xlsx_relationship_limit')
                if any(node.attrib.get('TargetMode') == 'External' for node in fromstring(archive.read(name))):
                    raise ValueError('xlsx_external_relationship')
        workbook = fromstring(archive.read('xl/workbook.xml'))
        descriptors = [n for n in workbook.iter(NS+'sheet') if n.attrib.get('name') == sheet]
        if len(descriptors) != 1: raise ValueError('xlsx_sheet_unknown')
        relations = {r.attrib['Id']:r.attrib for r in fromstring(archive.read('xl/_rels/workbook.xml.rels'))}
        relation = relations[descriptors[0].attrib[REL+'id']]
        if not relation.get('Type','').endswith('/worksheet'): raise ValueError('xlsx_sheet_invalid')
        target = relation['Target']
        worksheet = posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'xl/'+target)
        if not worksheet.startswith('xl/worksheets/'): raise ValueError('xlsx_sheet_path_invalid')
        shared = []
        if 'xl/sharedStrings.xml' in names:
            with archive.open('xl/sharedStrings.xml') as stream:
                for _, node in iterparse(stream, events=['end']):
                    if node.tag == NS+'si':
                        shared.append(''.join(t.text or '' for t in node.iter(NS+'t')))
                        if len(shared) > 2000000: raise ValueError('xlsx_shared_string_limit')
                        node.clear()
        scanned = 0; previous = 0
        with archive.open(worksheet) as stream:
            for _, node in iterparse(stream, events=['end']):
                if node.tag != NS+'row': continue
                number = int(node.attrib.get('r', previous+1))
                if number <= previous or number > 1000001: raise ValueError('xlsx_row_invalid')
                previous = number; values = {}; last_column = 0
                for cell in node.findall(NS+'c'):
                    match = re.fullmatch(r'([A-Z]{1,3})([1-9][0-9]*)',cell.attrib.get('r',''))
                    if not match or int(match[2]) != number: raise ValueError('xlsx_cell_coordinate_invalid')
                    column = 0
                    for char in match[1]: column = column*26 + ord(char)-64
                    scanned += 1
                    if column <= last_column or column > 16384 or scanned > 10000000: raise ValueError('xlsx_cell_limit')
                    last_column = column
                    if cell.find(NS+'f') is not None: raise ValueError('xlsx_formula_rejected')
                    kind = cell.attrib.get('t'); raw = cell.find(NS+'v')
                    text = None if raw is None else raw.text
                    if kind == 's':
                        try:
                            index=int(text)
                            if index<0:raise ValueError('negative_shared_string_index')
                            text = shared[index]
                        except (ValueError,TypeError,IndexError): raise ValueError('xlsx_shared_string_invalid')
                    elif kind == 'inlineStr': text = ''.join(t.text or '' for t in cell.iter(NS+'t'))
                    elif kind not in (None,'n','str','b'): raise ValueError('xlsx_cell_type_rejected')
                    values[column] = text
                yield number, values
                node.clear()


def iter_table(member, format=None, sheet=None, max_uncompressed_bytes=None,
               encoding='utf-8-sig', delimiter=None, header_row=1):
    path = verify_member(member); format = format or member['format']
    max_uncompressed_bytes = BioLimits().max_expanded_bytes if max_uncompressed_bytes is None else max_uncompressed_bytes
    if type(header_row) is not int or not 1 <= header_row <= 10000: raise ValueError('table_header_invalid')
    if not 0 < max_uncompressed_bytes <= 2 * 1024**3: raise ValueError('table_expansion_limit')
    if format in ('csv','tsv'):
        if path.stat().st_size > max_uncompressed_bytes: raise ValueError('table_expansion_limit')
        if encoding not in ('utf-8','utf-8-sig'): raise ValueError('table_encoding_unsupported')
        separator = delimiter or ('\t' if format == 'tsv' else ',')
        if separator not in (',','\t',';'): raise ValueError('table_delimiter_invalid')
        with path.open(encoding=encoding, newline='') as stream:
            reader = csv.reader(stream, delimiter=separator, strict=True)
            headers = None; count = 0
            for number, values in enumerate(reader, 1):
                if number < header_row: continue
                if headers is None:
                    headers = _headers(values); continue
                count += 1
                if count > 1000000 or len(values) != len(headers): raise ValueError('table_row_width_or_limit')
                if any(len(v)>1048576 for v in values): raise ValueError('table_cell_limit')
                yield number, dict(zip(headers, values))
            if headers is None: raise ValueError('table_header_missing')
    elif format == 'xlsx':
        headers = None; width = 0
        for number, values in _xlsx_rows(path,sheet,max_uncompressed_bytes):
            if number < header_row: continue
            if headers is None:
                if number != header_row: raise ValueError('table_header_missing')
                width = max(values,default=0); headers = _headers([values.get(i) for i in range(1,width+1)]); continue
            if any(i>width for i in values): raise ValueError('table_row_width_or_limit')
            yield number, {name:values.get(i) for i,name in enumerate(headers,1)}
        if headers is None: raise ValueError('table_header_missing')
    else: raise ValueError('table_format_unsupported')


def _headers(values):
    if not values or len(values)>16384 or any(not isinstance(v,str) or not v for v in values) or len(values)!=len(set(values)):
        raise ValueError('table_headers_invalid')
    return values
