"""Original row identities for immutable raw, prepared v1 and prepared v2 data."""
from app.domain.datasets.contracts import rectangle


def source_rows(sheet):
    """Never infer quality exclusions from missing cells or a bounding rectangle."""
    active = getattr(sheet, 'active_source_rows', None)
    if active is not None:
        return tuple(active)
    area = getattr(sheet, 'data_range', None)
    if area is not None:
        start, end = rectangle(area)
        return range(start[0], end[0] + 1)
    last = max((cell.row for cell in sheet.cells if cell.value not in (None, '')), default=0)
    return range(2, last + 1)
