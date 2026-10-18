"""Approved comparison execution with frozen provenance and exact audit checks."""
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
from app.domain.comparison.contracts import ComparisonSelection, ComparisonStatistics, RowAudit, Variable, StrictModel, ENGINE
from app.domain.comparison.checks import selected_records
from app.domain.dataset_analysis import load_dataset


class DescriptiveSummary(StrictModel):
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


class GroupSummary(StrictModel):
    label: str
    statistics: DescriptiveSummary


class ComparisonResult(PlannedAnalysisSource):
    model_config=ConfigDict(strict=True,extra='forbid',allow_inf_nan=False)
    schema_version: Literal[4]
    result_type: Literal['group_comparison']
    id: str
    file_id: str
    filename: str
    source_sha256: str
    setup_revision: int
    selection: ComparisonSelection
    check: SelectionCheck
    engine: dict
    started_at: str
    completed_at: str
    variables: list[Variable]
    groups: list[GroupSummary]
    statistics: ComparisonStatistics
    row_audit: RowAudit
    analysis_context: ModernAnalysisContext


def statistics_match(saved, computed, *, summaries=False):
    """32 ULP and 8e-15 relative tolerance only on declared numeric leaves."""
    numeric={('statistic','value'),('statistic','df_numerator'),('statistic','df_denominator'),
        ('estimate','value'),('p_value','value'),('confidence_interval','low'),('confidence_interval','high')}
    summary_fields={'mean','std','min','q1','median','q3','max','iqr'}
    def matches(left,right,path):
        floating=path in numeric
        if len(path)>=3 and path[0]=='pairwise' and type(path[1]) is int:
            floating=path[2:] in numeric or path[2:]==('adjusted_p_value',)
        if summaries:floating=len(path)==3 and type(path[0]) is int and path[1]=='statistics' and path[2] in summary_fields
        if floating and left is not None and right is not None:
            if type(left) not in (float,int) or type(right) not in (float,int) or not math.isfinite(left) or not math.isfinite(right):return False
            if left==right:return True
            if left in (-1,0,1) or right in (-1,0,1) or (left<0)!=(right<0):return False
            return abs(left-right)<=32*min(math.ulp(left),math.ulp(right)) and math.isclose(left,right,rel_tol=8e-15,abs_tol=0.0)
        if type(left) is not type(right):return False
        if isinstance(left,dict):return left.keys()==right.keys() and all(matches(left[k],right[k],path+(k,)) for k in left)
        if isinstance(left,list):return len(left)==len(right) and all(matches(a,b,path+(i,)) for i,(a,b) in enumerate(zip(left,right)))
        return left==right
    return matches(saved,computed,())


def group_summaries(groups, labels):
    from app.domain.descriptive import summarize
    return [dict(label=label,statistics=summarize(values)) for label,values in zip(labels,groups)]


def load_comparison_input(assets,project_id,file_id,result):
    from app.domain.analysis_plan.service import validate_plan_reference
    from app.domain.comparison.kernel import ComparisonError
    from app.domain.fixed_statistics import compare_bounded as compute_comparison
    try:
        if assets.owner_id is None:
            # Trusted local recovery must reconstruct with the exact file owner's scope.
            from app.adapters.task_store import DatasetTaskAssets
            with assets.connection() as db:
                owner=db.execute('''SELECT p.owner_id FROM projects p JOIN files f ON f.project_id=p.id
                    WHERE p.id=%s AND f.id=%s''',(project_id,file_id)).fetchone()
            if not owner:raise ValueError('Trusted recovery file identity missing.')
            assets=DatasetTaskAssets(owner['owner_id'],assets.db_config,assets.directory)
        ComparisonResult.model_validate(result,strict=True)
        plan=validate_plan_reference(assets,project_id,file_id,result)
        if plan is None or plan['schema_version'] not in (3,4,5) or plan['selection']['task_type']!='group_comparison':raise ValueError('Comparison requires its confirmed v3 plan.')
        record,_,sheet=load_dataset(assets,project_id,file_id,result['source']['dataset_id'],expected_source=result['source'])
        chosen=ComparisonSelection.model_validate(plan['selection'],strict=True)
        groups,variables,audit,labels=selected_records(sheet,chosen)
        from app.domain.statistics_execution.verification import should_recompute, require_receipt
        if should_recompute():
            computed=compute_comparison(groups,method=chosen.method,posthoc=chosen.posthoc,cache_identity=result['source'])
            summaries=group_summaries(groups,labels)
        else:
            require_receipt(assets,project_id,file_id,result)
            computed=result['statistics']; summaries=result['groups']
        if (not statistics_match(result['statistics'],computed) or not statistics_match(result['groups'],summaries,summaries=True)
                or result['variables']!=variables or result['row_audit']!=audit or result['engine']['id']!=ENGINE or result['filename']!=record['filename']):
            raise ValueError('Comparison differs from frozen observations.')
    except (KeyError,TypeError,ValueError,ComparisonError) as exc:
        raise StorageError('task_source_conflict','比较结果与冻结数据、计划或完整来源复核不一致。',409) from exc
    return dict(groups=groups,variables=variables,statistics=deepcopy(result['statistics']))


def execute(project_id,file_id,request,store,settings):
    from app.domain.statistics_execution.verification import require_worker
    require_worker()
    from app.domain.analysis_plan.service import validate_plan_reference
    from app.domain.comparison.kernel import ComparisonError
    from app.domain.fixed_statistics import compare_bounded as compute_comparison
    saved=store.analysis_setup(project_id,file_id)
    if saved is None or saved['revision']!=request.expected_revision:raise StorageError('setup_conflict','分析配置已变化，请重新读取。',409)
    plan=validate_plan_reference(store,project_id,file_id,saved)
    if plan is None or plan['schema_version'] not in (3,4,5) or plan['selection']['task_type']!='group_comparison':raise StorageError('task_source_conflict','比较分析须经独立计划批准。',409)
    cached=store.analysis_run(project_id,file_id,request.expected_revision,ENGINE)
    if cached is not None:return cached
    record,source,sheet=load_dataset(store,project_id,file_id,plan['source']['dataset_id'],expected_source=plan['source'])
    chosen=ComparisonSelection.model_validate(plan['selection'],strict=True)
    groups,variables,audit,labels=selected_records(sheet,chosen)
    started=datetime.now(timezone.utc).isoformat()
    try:statistics=compute_comparison(groups,method=chosen.method,posthoc=chosen.posthoc,cache_identity=source)
    except ComparisonError as exc:raise StorageError(exc.code,exc.message,422) from exc
    return store.save_analysis_run(project_id,file_id,dict(schema_version=4,result_type='group_comparison',file_id=file_id,
        filename=record['filename'],source_sha256=source['source_sha256'],source=source,setup_revision=saved['revision'],
        selection=plan['selection'],check=plan_selection_check(plan),analysis_plan=saved['analysis_plan'],analysis_context=result_context(plan),
        variables=variables,groups=group_summaries(groups,labels),statistics=statistics,row_audit=audit,started_at=started,
        completed_at=datetime.now(timezone.utc).isoformat(),engine=dict(id=ENGINE,python_version=platform.python_version(),
            scipy_version=scipy.__version__,numpy_version=numpy.__version__,parser_version=source['parser_version'],execution_contract='fixed_statistics_v2')))
