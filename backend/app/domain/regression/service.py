from app.domain.analysis_plan.context import plan_selection_check
from copy import deepcopy
from datetime import datetime,timezone
import importlib,math,platform
import numpy,scipy
from typing import Literal
from pydantic import ConfigDict,model_validator
from app.core.exceptions import StorageError
from app.domain.analysis import SelectionCheck
from app.domain.analysis_plan.references import PlannedAnalysisSource
from app.domain.analysis_plan.context import ModernAnalysisContext,result_context
from app.domain.regression.contracts import RegressionSelection,RegressionStatistics,ENGINE,Variable,RowAudit,StatisticalEngine
from app.domain.dataset_analysis import load_dataset
from app.domain.regression.checks import selected_records
from app.domain.regression.bounded import compute_bounded
from app.domain.regression.common import NumericError

class RegressionResult(PlannedAnalysisSource):
    model_config=ConfigDict(strict=True,extra='forbid',allow_inf_nan=False)
    schema_version:Literal[5]
    result_type:Literal['regression']
    id:str
    file_id:str
    filename:str
    source_sha256:str
    setup_revision:int
    selection:RegressionSelection
    check:SelectionCheck
    engine:StatisticalEngine
    started_at:str
    completed_at:str
    variables:list[Variable]
    statistics:RegressionStatistics
    row_audit:RowAudit
    analysis_context:ModernAnalysisContext
    @model_validator(mode='after')
    def coherent(self):
        if self.engine.id!=self.result_type+'_statistics_dataset_v1':raise ValueError('Engine type mismatch.')
        if self.result_type=='regression' and self.engine.solver!=('qr' if self.selection.method=='ols' else 'newton'):raise ValueError('Solver method mismatch.')
        if self.statistics.n!=len(self.row_audit.included_rows):raise ValueError('Result audit n mismatch.')
        return self

def statistics_match(saved,computed):
    numeric={'beta','se','statistic','p_value','ci_low','ci_high','or_value','or_ci_low','or_ci_high','r_squared','adjusted_r_squared','residual_sd','log_likelihood','deviance','aic','condition_number','gradient_max','auc','variance','low','high','survival','greenwood_variance'}
    arrays={'covariance','residuals','fitted','leverage','cooks_distance'}
    def match(left,right,path):
        floating=bool(path) and (path[-1] in numeric or any(p in arrays for p in path))
        if floating and type(left) is float and type(right) is float:
            if not math.isfinite(left) or not math.isfinite(right):return False
            if left==right:return True
            if left==0 or right==0 or (left<0)!=(right<0):return False
            return abs(left-right)<=256*min(math.ulp(left),math.ulp(right)) and math.isclose(left,right,rel_tol=5e-13,abs_tol=0)
        if type(left) is not type(right):return False
        if isinstance(left,dict):return left.keys()==right.keys() and all(match(left[k],right[k],path+(k,)) for k in left)
        if isinstance(left,list):return len(left)==len(right) and all(match(a,b,path+(i,)) for i,(a,b) in enumerate(zip(left,right)))
        return left==right
    return match(saved,computed,())

def _load_input(kind,assets,project_id,file_id,result):
    from app.domain.analysis_plan.service import validate_plan_reference
    if getattr(assets,'owner_id','scoped') is None:
        from app.adapters.task_store import DatasetTaskAssets
        with assets.connection() as db:
            owner=db.execute('SELECT p.owner_id FROM projects p JOIN files f ON f.project_id=p.id WHERE p.id=%s AND f.id=%s',(project_id,file_id)).fetchone()
        if not owner:raise StorageError('task_source_conflict','Trusted recovery file identity missing.',409)
        assets=DatasetTaskAssets(owner['owner_id'],assets.db_config,assets.directory)
    module=importlib.import_module('app.domain.'+kind+'.service');contracts=importlib.import_module('app.domain.'+kind+'.contracts')
    getattr(module,{'regression':'RegressionResult','roc':'RocResult','survival':'SurvivalResult'}[kind]).model_validate(result,strict=True)
    plan=validate_plan_reference(assets,project_id,file_id,result)
    if plan is None or plan['schema_version'] not in (3,4,5) or plan['selection']['task_type']!=kind:raise StorageError('task_source_conflict','结果必须引用对应已确认分析计划。',409)
    record,source,sheet=load_dataset(assets,project_id,file_id,result['source']['dataset_id'],expected_source=result['source'])
    if result['engine']['parser_version']!=source['parser_version']:
        raise StorageError('task_source_conflict','统计记录与冻结来源的解析器版本不一致。',409)
    chosen=contracts.Selection.model_validate(plan['selection'],strict=True)
    rows,variables,audit=selected_records(sheet,chosen)
    from app.domain.statistics_execution.verification import should_recompute, require_receipt
    try:
        if should_recompute(): computed=compute_bounded(kind,rows,chosen,cache_identity=source)
        else:
            require_receipt(assets,project_id,file_id,result)
            computed=result['statistics']
    except NumericError as exc:raise StorageError('task_source_conflict',exc.message,409) from exc
    if (result['selection']!=plan['selection'] or result['check']!=plan_selection_check(plan) or result['analysis_context']!=result_context(plan) or not statistics_match(result['statistics'],computed) or result['variables']!=variables or result['row_audit']!=audit or result['engine'].get('id')!=contracts.ENGINE or result['filename']!=record['filename'] or result['source_sha256']!=source['source_sha256']):raise StorageError('task_source_conflict','统计结果与冻结数据不一致。',409)
    return dict(rows=rows,variables=variables,statistics=deepcopy(result['statistics']))

def load_input(kind,assets,project_id,file_id,result):
    try:return _load_input(kind,assets,project_id,file_id,result)
    except (KeyError,TypeError,ValueError) as exc:raise StorageError('task_source_conflict','Result differs from frozen source or fixed metadata.',409) from exc

def load_regression_input(assets,project_id,file_id,result):return load_input('regression',assets,project_id,file_id,result)

def execute_kind(kind,project_id,file_id,request,store,settings):
    from app.domain.statistics_execution.verification import require_worker
    require_worker()
    from app.domain.analysis_plan.service import validate_plan_reference
    contracts=importlib.import_module('app.domain.'+kind+'.contracts');saved=store.analysis_setup(project_id,file_id)
    if saved is None or saved['revision']!=request.expected_revision:raise StorageError('setup_conflict','分析配置已变化。',409)
    plan=validate_plan_reference(store,project_id,file_id,saved)
    if plan is None or plan['schema_version'] not in (3,4,5) or plan['selection']['task_type']!=kind:raise StorageError('task_source_conflict','分析须独立批准。',409)
    cached=store.analysis_run(project_id,file_id,request.expected_revision,contracts.ENGINE)
    if cached is not None:load_input(kind,store,project_id,file_id,cached);return cached
    record,source,sheet=load_dataset(store,project_id,file_id,plan['source']['dataset_id'],expected_source=plan['source'])
    selection=contracts.Selection.model_validate(plan['selection'],strict=True);rows,variables,audit=selected_records(sheet,selection);started=datetime.now(timezone.utc).isoformat()
    try:statistics=compute_bounded(kind,rows,selection,cache_identity=source)
    except NumericError as exc:raise StorageError(exc.code,exc.message,422) from exc
    from importlib.metadata import version
    engine=dict(id=contracts.ENGINE,python_version=platform.python_version(),scipy_version=scipy.__version__,numpy_version=numpy.__version__,parser_version=source['parser_version'],encoding_version='typed_reference_dummy_v1',timeout_seconds=30,execution_contract='fixed_statistics_v2')
    if kind=='regression':engine.update(statsmodels_version=version('statsmodels'),solver='qr' if selection.method=='ols' else 'newton',max_iterations=100 if selection.method=='logistic' else None,tolerance=1e-10 if selection.method=='logistic' else None,scale='center_scale_restored_original_units',separation_solver='highs',separation_timeout_seconds=5)
    engine=StatisticalEngine.model_validate(engine,strict=True).model_dump(mode='json')
    return store.save_analysis_run(project_id,file_id,dict(schema_version=5,result_type=kind,file_id=file_id,filename=record['filename'],source_sha256=source['source_sha256'],source=source,setup_revision=saved['revision'],selection=plan['selection'],check=plan_selection_check(plan),analysis_plan=saved['analysis_plan'],analysis_context=result_context(plan),variables=variables,statistics=statistics,row_audit=audit,started_at=started,completed_at=datetime.now(timezone.utc).isoformat(),engine=engine))
def execute(project_id,file_id,request,store,settings):return execute_kind('regression',project_id,file_id,request,store,settings)
