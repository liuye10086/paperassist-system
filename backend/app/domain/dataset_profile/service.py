"""Authenticate and verify persisted objects before every read-only scan."""
from app.adapters.excel import fail
from app.domain.dataset_analysis import load_dataset
from app.domain.dataset_profile.contracts import RULES_VERSION, PAGE_SIZE
from app.domain.dataset_profile.scan import ProfileScan


class DatasetProfileService:
    def __init__(self, store):
        self.store = store

    def load(self, project_id, file_id, dataset_id):
        record, source, sheet = load_dataset(self.store, project_id, file_id, dataset_id)
        return record, source, ProfileScan(sheet)

    def profile(self, project_id, file_id, dataset_id):
        record, source, scan = self.load(project_id, file_id, dataset_id)
        return dict(schema_version=1, rules_version=RULES_VERSION, source=source,
            filename=record['filename'], sheet_name=scan.sheet.name, data_range=scan.data_range,
            record_count=scan.record_count, blank_row_count=scan.blank_row_count,
            duplicate_groups=scan.duplicate_groups, duplicate_rows=scan.duplicate_rows,
            duplicate_extra_rows=scan.duplicate_extra_rows, fields=scan.fields)

    def issues(self, project_id, file_id, dataset_id, kind, column, page):
        _, source, scan = self.load(project_id, file_id, dataset_id)
        if (kind == 'duplicate' and column is not None) or (kind != 'duplicate' and column not in scan.columns):
            fail('invalid_request', '请选择此数据版本的字段；重复行查看不接受字段号。')
        total, items = scan.issues(kind, column, page)
        return dict(source=source, rules_version=RULES_VERSION, kind=kind, column=column,
            page=page, page_size=PAGE_SIZE, total=total, items=items)
