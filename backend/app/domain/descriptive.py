"""A fixed, versioned descriptive-statistics tool over validated original data."""
from app.domain.analysis_plan.context import plan_selection_check
from app.adapters.storage import ProjectStore
from app.core.config import ExcelSettings


from datetime import datetime, timezone
import platform
from typing import Literal

import openpyxl
from pydantic import BaseModel, ConfigDict, Field, model_serializer

from app.domain.analysis import AnalysisSelection, SelectionCheck, inspect_selection, source
from app.adapters.excel import fail

from app.domain.analysis_sources import ENGINE, DATASET_ENGINE, statistics_engine
from app.domain.dataset_analysis import load_dataset, scan_dataset
from app.domain.analysis_plan.references import PlannedAnalysisSource
from app.domain.analysis_plan.service import validate_plan_reference
from app.domain.analysis_plan.context import AnalysisContext, ModernAnalysisContext, result_context


class RunRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_revision: int = Field(ge=1)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128, pattern=r'^[!-~]+$')


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
    openpyxl_version: str | None = None
    parser_version: str | None = None
    std_ddof: Literal[1]
    quantile_method: Literal['linear_inclusive']
    execution_contract: Literal['fixed_statistics_v2'] | None = None


    @model_serializer(mode='wrap')
    def serialize_reader(self, handler):
        value = handler(self)
        for key in ('openpyxl_version', 'parser_version', 'execution_contract'):
            if value[key] is None:
                value.pop(key)
        return value


class AnalysisResult(PlannedAnalysisSource):
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


class ResearchAnalysisResult(AnalysisResult):
    schema_version: Literal[2]
    analysis_context: AnalysisContext


class ModernDescriptiveResult(AnalysisResult):
    schema_version: Literal[3]
    analysis_context: ModernAnalysisContext


from app.domain.correlation.service import CorrelationResult
from app.domain.comparison.service import ComparisonResult
from app.domain.regression.service import RegressionResult
from app.domain.roc.service import RocResult
from app.domain.survival.service import SurvivalResult


def result_model(value):
    modeling={'regression':RegressionResult,'roc':RocResult,'survival':SurvivalResult}
    if value.get('result_type') in modeling:return modeling[value['result_type']]
    if value.get('result_type')=='group_comparison': return ComparisonResult
    if value.get("result_type")=="correlation": return CorrelationResult
    if 'result_type' in value or value.get('schema_version') not in (None,2,3): raise ValueError('Unknown result type or schema.')
    if value.get("schema_version")==3: return ModernDescriptiveResult
    return ResearchAnalysisResult if value.get("schema_version")==2 else AnalysisResult


from app.domain.tasks.contracts import TaskView


class ResultState(BaseModel):
    active_task: TaskView | None = None
    execution_verification: Literal['verified', 'legacy_unverified'] | None = None
    current_revision: int | None
    is_current: bool
    result: RegressionResult | RocResult | SurvivalResult | ComparisonResult | CorrelationResult | ModernDescriptiveResult | ResearchAnalysisResult | AnalysisResult | None


def summarize(values: list[float], *, cache_identity=None) -> dict:
    from app.domain.fixed_statistics import summarize_bounded
    return summarize_bounded(values, cache_identity=cache_identity)



def get_result(project_id: str, file_id: str, store: ProjectStore):
    saved = store.analysis_setup(project_id, file_id)
    engine = statistics_engine(saved or {})
    if engine != ENGINE:
        load_dataset(store, project_id, file_id, saved['source']['dataset_id'], expected_source=saved['source'])
    else:
        source(store, project_id, file_id)
    state = store.latest_analysis_result(project_id, file_id, engine)
    result = state['result']
    if result and statistics_engine(result) != ENGINE:
        load_dataset(store, project_id, file_id, result['source']['dataset_id'], expected_source=result['source'])
    if state['is_current']:
        state['is_current'] = (result.get('source') == (saved or {}).get('source'))
    from app.domain.statistics_execution.verification import require_receipt
    state['execution_verification'] = ('verified' if require_receipt(store,project_id,file_id,result) else 'legacy_unverified') if result else None
    with store.connection() as db:
        task = db.execute("""SELECT * FROM tasks WHERE project_id=%s AND user_id=%s AND task_type='statistics_compute'
            AND input_snapshot->'file'->>'id'=%s AND input_snapshot->'setup'->>'revision'=%s
            ORDER BY created_at DESC,id DESC LIMIT 1""", (project_id,store.owner_id,file_id,str(saved['revision']) if saved else '')).fetchone()
    from app.adapters.task_store import TaskStore
    state['active_task'] = TaskStore.public_task(dict(task)) if task else None
    return state


def execute(project_id: str, file_id: str, request: RunRequest, store: ProjectStore, settings: ExcelSettings):
    from app.domain.statistics_execution.verification import require_worker
    require_worker()
    saved = store.analysis_setup(project_id, file_id)
    if saved is None or saved['revision'] != request.expected_revision:
        fail('setup_conflict', '分析配置已变化或尚未保存，请重新载入配置后再执行。', 409)
    if saved['selection']['task_type'] in ('regression','roc','survival'):
        from app.domain.regression.service import execute_kind
        return execute_kind(saved['selection']['task_type'],project_id,file_id,request,store,settings)
    if saved['selection']['task_type']=='correlation':
        from app.domain.correlation.service import execute as execute_correlation
        return execute_correlation(project_id,file_id,request,store,settings)
    if saved['selection']['task_type']=='group_comparison':
        from app.domain.comparison.service import execute as execute_comparison
        return execute_comparison(project_id,file_id,request,store,settings)
    if saved['selection']['task_type']!='descriptive_boxplot':
        fail('invalid_analysis_selection','未知分析类型不能执行描述统计。',422)
    plan = validate_plan_reference(store, project_id, file_id, saved)
    engine = statistics_engine(saved)
    if engine == DATASET_ENGINE:
        record, frozen_source, sheet = load_dataset(store, project_id, file_id, saved['source']['dataset_id'], expected_source=saved['source'])
    else:
        record, _ = source(store, project_id, file_id)
    if saved['source_sha256'] != record['sha256']:
        fail('source_conflict', '配置与原文件不一致，请重新保存分析配置。', 409)
    cached = store.analysis_run(project_id, file_id, request.expected_revision, engine)
    if cached is not None:
        validate_plan_reference(store, project_id, file_id, cached)
        if statistics_engine(cached) != engine or cached.get('source') != saved.get('source'):
            fail('source_conflict', '缓存统计与配置来源不一致。', 409)
        return cached
    started = datetime.now(timezone.utc).isoformat()
    selection = AnalysisSelection(**(plan['selection'] if plan else saved['selection']))
    if engine == DATASET_ENGINE:
        profile, scan = scan_dataset(sheet, selection, collect_values=True)
    else:
        record, profile, scan = inspect_selection(store, project_id, file_id, settings,
            selection.sheet_name, selection, collect_values=True)
    check = scan.check(profile)
    if plan and check.model_dump(mode='json') != plan_selection_check(plan):
        fail('source_conflict', '计划与实际统计检查不一致。', 409)
    if not check.ready:
        fail('invalid_analysis_selection', ' '.join(check.issues))
    columns = {column.id: column.name for column in profile.columns}
    summary_options = {'cache_identity': saved['source']} if saved.get('source') else {}
    overall = summarize(scan.values, **summary_options)
    groups = [{'label': ('TRUE' if group else 'FALSE') if isinstance(group, bool) else str(group),
               'statistics': summarize(values, **summary_options)} for group, values in scan.grouped_values.items()]
    reader = {'parser_version': frozen_source['parser_version']} if engine == DATASET_ENGINE else {'openpyxl_version': openpyxl.__version__}
    frozen = {'source': frozen_source} if engine == DATASET_ENGINE else {}
    if plan:
        frozen['analysis_plan'] = saved['analysis_plan']
        if plan['schema_version'] in (2,3,4,5):
            frozen.update(schema_version=3 if plan['schema_version'] in (4,5) else plan['schema_version'],analysis_context=result_context(plan))
    if engine != ENGINE:
        load_dataset(store, project_id, file_id, frozen_source['dataset_id'], expected_source=frozen_source)
    return store.save_analysis_run(project_id, file_id, {
        **frozen,
        'file_id': file_id, 'filename': record['filename'], 'source_sha256': record['sha256'],
        'setup_revision': saved['revision'], 'selection': selection.model_dump(), 'check': check.model_dump(),
        'numeric_name': columns[selection.numeric_column], 'group_name': columns.get(selection.group_column),
        'engine': {'id': engine, 'python_version': platform.python_version(), **reader,
                   'std_ddof': 1, 'quantile_method': 'linear_inclusive', 'execution_contract': 'fixed_statistics_v2'},
        'started_at': started, 'completed_at': datetime.now(timezone.utc).isoformat(),
        'overall': overall, 'groups': groups,
    })

def verify_result(assets, project_id, file_id, result):
    """Worker-only independent reconstruction of frozen descriptive facts."""
    from app.domain.statistics_execution.verification import should_recompute
    if not should_recompute():
        return
    if result.get('result_type') is not None:
        return
    from app.core.config import get_excel_settings
    from app.adapters.task_store import source_conflict
    selection = AnalysisSelection.model_validate(result['selection'])
    if result.get('source'):
        record, _, sheet = load_dataset(assets,project_id,file_id,result['source']['dataset_id'],expected_source=result['source'])
        profile, scan = scan_dataset(sheet,selection,collect_values=True)
    else:
        record, profile, scan = inspect_selection(assets,project_id,file_id,get_excel_settings(),selection.sheet_name,selection,collect_values=True)
    groups=[{'label':('TRUE' if label else 'FALSE') if isinstance(label,bool) else str(label),'statistics':summarize(values)} for label,values in scan.grouped_values.items()]
    if (scan.check(profile).model_dump()!=result['check'] or summarize(scan.values)!=result['overall']
            or groups!=result['groups'] or record['sha256']!=result['source_sha256']):
        raise source_conflict()
