"""Freeze small, rectangular manuscript tables from verified original files."""

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


def _excel_tables(raw, filename, settings):
    from app.adapters.excel_structure import extract_excel_structure
    from app.domain.datasets.contracts import rectangle

    try:
        workbook = extract_excel_structure(raw, filename, settings)
    except StorageError as exc:
        if exc.code in ('file_too_large', 'workbook_too_large', 'parse_output_invalid'):
            raise _limit() from exc
        raise StorageError(exc.code, exc.message, 422, params=exc.params) from exc
    for sheet in workbook.sheets:
        if sheet.state != 'visible' or sheet.content_range is None:
            continue
        # An Excel formula cache is unverified. Require the user to provide
        # fixed values rather than publishing an expression or a stale result.
        if any(cell.kind in ('formula', 'error') for cell in sheet.cells):
            raise _values_required()
        (first_row, first_col), (last_row, last_col) = rectangle(sheet.content_range)
        rows = _matrix(last_row - first_row + 1, last_col - first_col + 1)
        for cell in sheet.cells:
            if cell.value not in (None, ''):
                # Preserve stored numeric precision and text. Workbook styles
                # and spreadsheet formulas are not carried into the manuscript.
                value = ('TRUE' if cell.value else 'FALSE') if cell.kind == 'boolean' else cell.value
                rows[cell.row - first_row][cell.column - first_col] = value
        yield rows


def freeze_tables(service, project, source):
    """Read exact table text from an existing, owner-scoped source selection.

    Each Word body table or visible nonempty worksheet becomes one table;
    its first row supplies column headings. Only text and rectangular blanks
    leave the parser. The caller seals this projection in the manuscript.
    """
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
        matrices = _word_tables(service.assets.original(file), file['filename'])
    elif kind == 'xlsx':
        from app.core.config import get_excel_settings

        configured = get_excel_settings()
        settings = configured.model_copy(update=dict(
            max_rows=min(configured.max_rows, MAX_ROWS),
            max_columns=min(configured.max_columns, MAX_COLUMNS),
            max_cells=min(configured.max_cells, MAX_CELLS),
        ))
        if file['size_bytes'] > settings.max_upload_bytes:
            raise _limit()
        matrices = _excel_tables(service.assets.original(file), file['filename'], settings)
    else:
        raise StorageError('unsupported_file_type', '论文表格仅支持 Word 或 Excel 原件。', 422)

    tables = []
    cells = text_bytes = 0
    for matrix in matrices:
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
        tables.append(dict(columns=matrix[0], rows=matrix[1:]))
    if not tables:
        raise StorageError('manuscript_table_empty', '原件中没有可入稿的正文表格或可见工作表，请检查所选文件。', 422)
    return tables
