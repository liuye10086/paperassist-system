from typing import Literal
from app.domain.regression.service import RegressionResult,load_input,execute_kind,statistics_match
from app.domain.roc.contracts import RocSelection,RocStatistics
class RocResult(RegressionResult):
    result_type:Literal['roc']
    selection:RocSelection
    statistics:RocStatistics
ROCResult=RocResult
def load_roc_input(assets,project_id,file_id,result):return load_input('roc',assets,project_id,file_id,result)
def execute(project_id,file_id,request,store,settings):return execute_kind('roc',project_id,file_id,request,store,settings)
