from typing import Literal
from app.domain.regression.service import RegressionResult,load_input,execute_kind,statistics_match
from app.domain.survival.contracts import SurvivalSelection,SurvivalStatistics
class SurvivalResult(RegressionResult):
    result_type:Literal['survival']
    selection:SurvivalSelection
    statistics:SurvivalStatistics
def load_survival_input(assets,project_id,file_id,result):return load_input('survival',assets,project_id,file_id,result)
def execute(project_id,file_id,request,store,settings):return execute_kind('survival',project_id,file_id,request,store,settings)
