"""Freeze small, rectangular manuscript tables from verified original files."""

from decimal import Decimal, ROUND_HALF_UP, localcontext
from operator import eq, ge, gt, le, lt, ne
import re

from app.adapters.task_store import source_conflict
from app.core.exceptions import StorageError
from app.domain.files import require_file


MAX_TABLES = 12
MAX_ROWS = 500
MAX_COLUMNS = 32
MAX_CELLS = 16_000
MAX_TEXT_BYTES = 256 * 1024
INVALID_WORD_TEXT = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]')
NUMBER_FORMAT_TOKEN = re.compile(r'"[^"]*"|\\.|_.|\*.|\[[^]]*\]|.', re.S)
FORMAT_CONDITION = re.compile(r'\[(<=|>=|<>|=|<|>)([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\]')
FORMAT_COLOR = re.compile(r'\[(?:black|blue|cyan|green|magenta|red|white|yellow|color\s*\d+)\]', re.I)
DECIMAL_FORMAT = re.compile(r'([0#]+(?:,[0#]+)*)(?:\.([0#]+))?(,*)')
FORMAT_OPERATORS = {'<': lt, '<=': le, '>': gt, '>=': ge, '=': eq, '<>': ne}
VISIBLE_FORMAT_TEXT = frozenset(' $€£¥¢+-%():^\'{}<>=/!&~\u00a0')
PREVIEW_ROWS = 5


def _limit():
    return StorageError('manuscript_table_limit', '论文表格超过大小限制，请拆分或缩小需要入稿的表格。', 422)


def _values_required():
    return StorageError('manuscript_table_values_required', '请将公式或错误单元格改为核对后的值，并使用普通文本表格。', 422)


def _matrix(height, width):
    if height > MAX_ROWS or width > MAX_COLUMNS:
        raise _limit()
    return [[''] * width for _ in range(height)]


def _word_tables(raw, filename):
    from app.adapters.docx_parser import parse_docx
    from app.domain.documents.contracts import DOCX_SETTINGS

    document = parse_docx(raw, filename, DOCX_SETTINGS).document
    for table in document.blocks:
        if table.kind != 'table' or not table.rows or not table.columns:
            continue
        rows = _matrix(table.rows, table.columns)
        for cell in table.cells:
            if any(block.kind == 'table' for block in cell.blocks):
                raise _values_required()
            # Write merged-cell text once at the source anchor. The cells it
            # spans stay empty so no value is copied to a different row or column.
            rows[cell.row][cell.column] = '\n'.join(block.text for block in cell.blocks)
        yield rows


def _worksheet_selection_required():
    return StorageError('manuscript_table_worksheets_required', '请确认要入稿的 Excel 工作表。', 422)


def _visible_sheets(raw, filename):
    from app.adapters.excel_structure import extract_excel_structure
    from app.core.config import get_excel_settings

    try:
        workbook = extract_excel_structure(raw, filename, get_excel_settings())
    except StorageError as exc:
        if exc.code in ('file_too_large', 'workbook_too_large', 'parse_output_invalid'):
            raise _limit() from exc
        raise StorageError(exc.code, exc.message, 422, params=exc.params) from exc
    return [sheet for sheet in workbook.sheets if sheet.state == 'visible' and sheet.content_range]


def _number_format_section(style, value):
    sections = [[]]
    for token in NUMBER_FORMAT_TOKEN.findall(style):
        if token == ';':
            sections.append([])
        else:
            sections[-1].append(token)
    sections = sections[:3]
    conditions = [next((match for token in section if (match := FORMAT_CONDITION.fullmatch(token))), None)
                  for section in sections]
    if any(conditions):
        for section, condition in zip(sections, conditions):
            if condition is None or FORMAT_OPERATORS[condition[1]](value, Decimal(condition[2])):
                return section, False
        return ['General'], False
    if len(sections) == 3 and value.is_zero():
        return sections[2], False
    if len(sections) > 1 and value < 0:
        return sections[1], True
    return sections[0], False


def _format_text(tokens):
    return ''.join(token[1:-1] if token.startswith('"') else token[1:] if token.startswith('\\') else token
                   for token in tokens)


def _number_text(cell):
    if cell.number_format in ('General', '@'):
        return cell.value
    value = Decimal(cell.value)
    section, negative_section = _number_format_section(cell.number_format, value)
    section = [token for token in section if not (FORMAT_CONDITION.fullmatch(token) or FORMAT_COLOR.fullmatch(token)
               or token.startswith(('_', '*')))]
    # Treat quoted and escaped characters as a single literal when finding the numeric placeholders.
    code = ''.join(token if len(token) == 1 else '\0' for token in section)
    match = DECIMAL_FORMAT.search(code)
    prefix = section[:match.start()] if match else section
    suffix = section[match.end():] if match else []
    literal = all(token in VISIBLE_FORMAT_TEXT or token.startswith(('"', '\\')) for token in prefix + suffix)
    if not match and literal:
        return _format_text(prefix)
    percent = section.count('%')
    if not literal and not percent:
        return cell.value
    with localcontext() as context:
        context.prec = max(28, len(value.as_tuple().digits) + percent * 2)
        context.rounding = ROUND_HALF_UP
        if not match or not literal:
            return str(value.scaleb(percent * 2).normalize()) + '%' * percent
        integer, fraction, scaling = match.groups()
        fraction = fraction or ''
        scaled = value.copy_abs().scaleb(percent * 2 - len(scaling) * 3)
        if not -324 <= scaled.adjusted() <= 310:
            return cell.value
        whole, _, decimals = format(scaled, f'.{len(fraction)}f').partition('.')
        whole = (whole if whole != '0' else '').zfill(integer.count('0'))
        if ',' in integer:
            whole = re.sub(r'(?<=\d)(?=(?:\d{3})+$)', ',', whole)
        decimals = decimals.rstrip('0').ljust(len(fraction.rstrip('#')), '0')
        sign = '-' if value < 0 and not negative_section else ''
        return sign + _format_text(prefix) + whole + ('.' + decimals if decimals else '') + _format_text(suffix)


def _values_ready(sheet):
    return all(cell.kind not in ('formula', 'error') for cell in sheet.cells)


def _sheet_data(sheet, *, preview=False):
    from app.domain.datasets.contracts import rectangle

    (first_row, first_col), (last_row, last_col) = rectangle(sheet.content_range)
    height, width = last_row - first_row + 1, last_col - first_col + 1
    if preview:
        height, width = min(height, PREVIEW_ROWS + 1), min(width, MAX_COLUMNS)
    rows = _matrix(height, width)
    numeric_cells = []
    for cell in sheet.cells:
        row, column = cell.row - first_row, cell.column - first_col
        if cell.value in (None, '') or not (0 <= row < height and 0 <= column < width):
            continue
        if cell.kind == 'number':
            rows[row][column] = _number_text(cell)
            if not preview:
                numeric_cells.append(dict(row=row, column=column, value=cell.value, number_format=cell.number_format))
        else:
            rows[row][column] = ('TRUE' if cell.value else 'FALSE') if cell.kind == 'boolean' else cell.value
    return rows, numeric_cells


def worksheet_previews(raw, filename):
    previews = []
    for sheet in _visible_sheets(raw, filename):
        rows, _ = _sheet_data(sheet, preview=True)
        previews.append(dict(name=sheet.name, columns=rows[0], preview_rows=rows[1:],
                             row_count=sheet.nonempty_row_count - 1, values_ready=_values_ready(sheet)))
    return previews


def select_worksheets(sheets, names):
    if not sheets:
        raise StorageError('manuscript_table_empty', 'Excel 原件没有可见非空工作表。', 422)
    if names is None and len(sheets) == 1:
        return sheets
    if not names:
        raise _worksheet_selection_required()
    selected = [sheet for sheet in sheets if sheet.name in names]
    if len(selected) != len(names):
        raise _worksheet_selection_required()
    return selected


def validate_worksheets(raw, filename, names):
    selected = select_worksheets(_visible_sheets(raw, filename), names)
    if not all(_values_ready(sheet) for sheet in selected):
        raise _values_required()
    return [sheet.name for sheet in selected]


def _excel_tables(raw, filename, names):
    for sheet in select_worksheets(_visible_sheets(raw, filename), names):
        # Never publish formula caches or error cells as observed results.
        if not _values_ready(sheet):
            raise _values_required()
        rows, numeric_cells = _sheet_data(sheet)
        yield rows, dict(worksheet_name=sheet.name, numeric_cells=numeric_cells)


def freeze_tables(service, project, source, worksheet_names=None):
    """Freeze selected table text and keep the source precision separately."""
    file_id = source['file_id']
    if source['kind'] != 'original' or source['id'] != file_id:
        raise source_conflict()
    with service.store.connection() as db:
        service.store.require_project(db, project)
        file = dict(require_file(db, project, file_id, material_filter=service.assets.material_filter))
    identity = source['content']['source']
    if (source['sha256'] != file['sha256'] or identity['source_sha256'] != file['sha256']
            or identity['file_id'] != file_id or identity['filename'] != file['filename']
            or identity['file_type'] != file['file_type'] or identity['size_bytes'] != file['size_bytes']):
        raise source_conflict()
    kind = file['file_type']
    if kind == 'docx':
        from app.domain.documents.contracts import DOCX_SETTINGS

        if file['size_bytes'] > DOCX_SETTINGS['docx']['max_upload_bytes']:
            raise _limit()
        matrices = ((matrix, {}) for matrix in _word_tables(service.assets.original(file), file['filename']))
    elif kind == 'xlsx':
        from app.core.config import get_excel_settings

        settings = get_excel_settings()
        if file['size_bytes'] > settings.max_upload_bytes:
            raise _limit()
        matrices = _excel_tables(service.assets.original(file), file['filename'], worksheet_names)
    else:
        raise StorageError('unsupported_file_type', '论文表格仅支持 Word 或 Excel 原件。', 422)

    tables = []
    cells = text_bytes = 0
    for matrix, metadata in matrices:
        if not any(value.strip() for row in matrix for value in row):
            continue
        cells += len(matrix) * len(matrix[0])
        if len(tables) >= MAX_TABLES or cells > MAX_CELLS:
            raise _limit()
        for row in matrix:
            for value in row:
                if INVALID_WORD_TEXT.search(value):
                    raise _values_required()
                text_bytes += len(value.encode('utf-8'))
        if text_bytes > MAX_TEXT_BYTES:
            raise _limit()
        tables.append(dict(columns=matrix[0], rows=matrix[1:], **metadata))
    if not tables:
        raise StorageError('manuscript_table_empty', '原件中没有可入稿的正文表格或可见工作表，请检查所选文件。', 422)
    return tables
