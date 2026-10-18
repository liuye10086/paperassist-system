class NumericError(ValueError):
    def __init__(self,code,message):
        self.code=code;self.message=message;super().__init__(message)
def require(condition,code,message):
    if not condition: raise NumericError(code,message)
def payload(selection): return selection.model_dump(mode='json') if hasattr(selection,'model_dump') else selection
def bounded_rows(rows):
    require(len(rows)>0,'numeric_sample_size','没有完整样本可供计算。')
    require(len(rows)<=10000,'numeric_row_limit','建模统计最多支持10000行。')
