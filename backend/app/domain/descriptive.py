"""A fixed, versioned descriptive-statistics tool over validated original data."""

from app.adapters.storage import ProjectStore
from app.core.config import ExcelSettings


from datetime import datetime, timezone
from fractions import Fraction
from math import isfinite
import platform
import statistics
from typing import Literal

import openpyxl
from pydantic import BaseModel, ConfigDict, Field

from app.domain.analysis import AnalysisSelection, SelectionCheck, inspect_selection, source
from app.adapters.excel import fail

ENGINE = 'descriptive_statistics_v1'


class RunRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_revision: int = Field(ge=1)


class Summary(BaseModel):
    n: int
    mean: float
    std: float | None
    min: float
    q1: float
    median: float
    q3: float
    max: float
    iqr: float | None
    warnings: list[str]


class GroupSummary(BaseModel):
    label: str
    statistics: Summary


class EngineInfo(BaseModel):
    id: str
    python_version: str
    openpyxl_version: str
    std_ddof: Literal[1]
    quantile_method: Literal['linear_inclusive']


class AnalysisResult(BaseModel):
    id: str
    file_id: str
    filename: str
    source_sha256: str
    setup_revision: int
    selection: AnalysisSelection
    check: SelectionCheck
    numeric_name: str
    group_name: str | None
    engine: EngineInfo
    started_at: str
    completed_at: str
    overall: Summary
    groups: list[GroupSummary]


class ResultState(BaseModel):
    current_revision: int | None
    is_current: bool
    result: AnalysisResult | None


def summarize(values: list[float]) -> dict:
    ordered = sorted(values)
    count = len(ordered)
    if not count:
        fail('no_valid_records', '没有可计算的有效记录，请检查字段配置。')

    def quartile(quarter):
        index, remainder = divmod((count - 1) * quarter, 4)
        if not remainder:
            return Fraction(ordered[index])
        # Preserve interpolation precision until IQR is calculated. Intermediate
        # arithmetic must neither overflow nor subtract already-rounded quartiles.
        return (Fraction(ordered[index]) * (4 - remainder) + Fraction(ordered[index + 1]) * remainder) / 4

    notes = []

    def finite_metric(name, calculate):
        try:
            value = float(calculate())
            if isfinite(value):
                return value
        except ArithmeticError:
            pass
        notes.append(f'{name}超出可表示的数值范围，结果标记为无法计算。')
        return None

    deviation = None
    if count < 2:
        notes.append('有效记录不足 2 条，样本标准差无法计算。')
    else:
        deviation = finite_metric('样本标准差', lambda: statistics.stdev(ordered))
    q1, median, q3 = (quartile(quarter) for quarter in (1, 2, 3))
    return {'n': count, 'mean': statistics.mean(ordered), 'std': deviation,
            'min': ordered[0], 'q1': float(q1), 'median': float(median), 'q3': float(q3), 'max': ordered[-1],
            'iqr': finite_metric('四分位距', lambda: q3 - q1), 'warnings': notes}


def get_result(project_id: str, file_id: str, store: ProjectStore):
    source(store, project_id, file_id)
    return store.latest_analysis_result(project_id, file_id, ENGINE)


def execute(project_id: str, file_id: str, request: RunRequest, store: ProjectStore, settings: ExcelSettings):
    record, _ = source(store, project_id, file_id)
    saved = store.analysis_setup(project_id, file_id)
    if saved is None or saved['revision'] != request.expected_revision:
        fail('setup_conflict', '分析配置已变化或尚未保存，请重新载入配置后再执行。', 409)
    if saved['source_sha256'] != record['sha256']:
        fail('source_conflict', '配置与原文件不一致，请重新保存分析配置。', 409)
    cached = store.analysis_run(project_id, file_id, request.expected_revision, ENGINE)
    if cached is not None:
        return cached
    started = datetime.now(timezone.utc).isoformat()
    selection = AnalysisSelection(**saved['selection'])
    record, profile, scan = inspect_selection(store, project_id, file_id, settings,
        selection.sheet_name, selection, collect_values=True)
    check = scan.check(profile)
    if not check.ready:
        fail('invalid_analysis_selection', ' '.join(check.issues))
    columns = {column.id: column.name for column in profile.columns}
    overall = summarize(scan.values)
    groups = [{'label': ('TRUE' if group else 'FALSE') if isinstance(group, bool) else str(group),
               'statistics': summarize(values)} for group, values in scan.grouped_values.items()]
    return store.save_analysis_run(project_id, file_id, {
        'file_id': file_id, 'filename': record['filename'], 'source_sha256': record['sha256'],
        'setup_revision': saved['revision'], 'selection': selection.model_dump(), 'check': check.model_dump(),
        'numeric_name': columns[selection.numeric_column], 'group_name': columns.get(selection.group_column),
        'engine': {'id': ENGINE, 'python_version': platform.python_version(), 'openpyxl_version': openpyxl.__version__,
                   'std_ddof': 1, 'quantile_method': 'linear_inclusive'},
        'started_at': started, 'completed_at': datetime.now(timezone.utc).isoformat(),
        'overall': overall, 'groups': groups,
    })
