"""Approved frozen-source correlation execution and bounded result reconstruction."""
from app.domain.analysis_plan.context import plan_selection_check
from copy import deepcopy
from datetime import datetime, timezone
import math
import platform
from typing import Literal
import numpy
import scipy
from pydantic import ConfigDict
from app.core.exceptions import StorageError
from app.domain.analysis import SelectionCheck
from app.domain.analysis_plan.references import PlannedAnalysisSource
from app.domain.analysis_plan.context import ModernAnalysisContext, result_context
from app.domain.correlation.contracts import CorrelationSelection, CorrelationStatistics, ENGINE
from app.domain.correlation.checks import selected_records
from app.domain.dataset_analysis import load_dataset


class CorrelationResult(PlannedAnalysisSource):
    model_config = ConfigDict(strict=True, extra='forbid', allow_inf_nan=False)
    schema_version: Literal[3]
    result_type: Literal['correlation']
    id: str
    file_id: str
    filename: str
    source_sha256: str
    setup_revision: int
    selection: CorrelationSelection
    check: SelectionCheck
    engine: dict
    started_at: str
    completed_at: str
    variables: list[dict]
    statistics: CorrelationStatistics
    row_audit: dict
    analysis_context: ModernAnalysisContext


def statistics_match(saved, computed):
    """Allow only binary64 roundoff in explicit statistic leaves, never metadata.

    A recorded Windows/Linux Pearson P differs by seven ULP. Bound other
    platforms to 32 ULP AND 8e-15 relative error, with no absolute tolerance:
    tiny probabilities must retain their magnitude. Zero, signs and exact
    endpoints retain their meaning. This is validation, never normalization.
    """
    floating_paths = {('coefficient',), ('p_value', 'value'),
        ('confidence_interval', 'low'), ('confidence_interval', 'high')}

    def matches(left, right, path):
        floating = path in floating_paths or (len(path) == 3 and path[0] == 'matrix'
            and type(path[1]) is int and type(path[2]) is int)
        if floating and left is not None and right is not None:
            if type(left) not in (int, float) or type(right) not in (int, float):
                return False
            if not math.isfinite(left) or not math.isfinite(right):
                return False
            if left == right:
                return True
            if left in (-1, 0, 1) or right in (-1, 0, 1) or (left < 0) != (right < 0):
                return False
            return (abs(left - right) <= 32 * min(math.ulp(left), math.ulp(right))
                and math.isclose(left, right, rel_tol=8e-15, abs_tol=0.0))
        if type(left) is not type(right):
            return False
        if isinstance(left, dict):
            return left.keys() == right.keys() and all(matches(left[k], right[k], path + (k,)) for k in left)
        if isinstance(left, list):
            return len(left) == len(right) and all(matches(a, b, path + (i,)) for i, (a, b) in enumerate(zip(left, right)))
        return left == right

    return matches(saved, computed, ())


def load_correlation_input(assets, project_id, file_id, result):
    from app.domain.analysis_plan.service import validate_plan_reference
    from app.domain.fixed_statistics import correlate_bounded as compute_correlation
    CorrelationResult.model_validate(result, strict=True)
    plan = validate_plan_reference(assets, project_id, file_id, result)
    if plan is None or plan['schema_version'] not in (3,4,5):
        raise StorageError('task_source_conflict', '相关分析必须引用已确认分析计划。', 409)
    record, source, sheet = load_dataset(assets, project_id, file_id,
        result['source']['dataset_id'], expected_source=result['source'])
    chosen = CorrelationSelection.model_validate(plan['selection'], strict=True)
    rows, variables, audit = selected_records(sheet, chosen)
    from app.domain.statistics_execution.verification import should_recompute, require_receipt
    if should_recompute():
        computed = compute_correlation(rows, method=chosen.method, mode=chosen.mode, cache_identity=result['source'])
    else:
        require_receipt(assets,project_id,file_id,result)
        computed = result['statistics']
    if (not statistics_match(result['statistics'], computed) or result['variables'] != variables or result['row_audit'] != audit
            or result['engine']['id'] != ENGINE or result['filename'] != record['filename']):
        raise StorageError('task_source_conflict', '统计结果与冻结数据复核不一致。', 409)
    # Downstream facts and material hashes use the original approved result,
    # even if another platform reproduced it with insignificant roundoff.
    return dict(rows=rows, variables=variables, statistics=deepcopy(result['statistics']))


def execute(project_id, file_id, request, store, settings):
    from app.domain.statistics_execution.verification import require_worker
    require_worker()
    from app.domain.analysis_plan.service import validate_plan_reference
    from app.domain.correlation.kernel import CorrelationError
    from app.domain.fixed_statistics import correlate_bounded as compute_correlation
    saved = store.analysis_setup(project_id, file_id)
    if saved is None or saved['revision'] != request.expected_revision:
        raise StorageError('setup_conflict', '分析配置已变化，请重新读取。', 409)
    plan = validate_plan_reference(store, project_id, file_id, saved)
    if plan is None or plan['schema_version'] not in (3,4,5) or plan['selection']['task_type'] != 'correlation':
        raise StorageError('task_source_conflict', '相关分析须经独立计划批准。', 409)
    cached = store.analysis_run(project_id, file_id, request.expected_revision, ENGINE)
    if cached is not None:
        return cached
    record, source, sheet = load_dataset(store, project_id, file_id,
        plan['source']['dataset_id'], expected_source=plan['source'])
    selection = CorrelationSelection.model_validate(plan['selection'], strict=True)
    rows, variables, audit = selected_records(sheet, selection)
    started = datetime.now(timezone.utc).isoformat()
    try: statistics = compute_correlation(rows, method=selection.method, mode=selection.mode, cache_identity=source)
    except CorrelationError as exc:
        raise StorageError(exc.code, getattr(exc, 'message', '相关计算无法完成。'), 422) from exc
    return store.save_analysis_run(project_id, file_id, dict(schema_version=3,result_type='correlation',
        file_id=file_id,filename=record['filename'],source_sha256=source['source_sha256'],source=source,
        setup_revision=saved['revision'],selection=plan['selection'],check=plan_selection_check(plan),
        analysis_plan=saved['analysis_plan'],analysis_context=result_context(plan),variables=variables,
        statistics=statistics,row_audit=audit,started_at=started,completed_at=datetime.now(timezone.utc).isoformat(),
        engine=dict(id=ENGINE,python_version=platform.python_version(),scipy_version=scipy.__version__,
            numpy_version=numpy.__version__,parser_version=source['parser_version'],execution_contract='fixed_statistics_v2')))
