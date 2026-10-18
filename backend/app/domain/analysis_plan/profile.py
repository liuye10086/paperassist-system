"""Plan-only profile numbers use the fixed process; metadata retains its original scan."""
from app.domain.dataset_profile.scan import ProfileScan
from app.domain.dataset_profile.contracts import NumericProfile
from app.domain.regression.bounded import compute_bounded
from app.domain.regression.common import NumericError


def bounded_numeric_profile(cells):
    if not cells:return None,[],[]
    rows=[dict(row=c.row,column=c.column,value=c.value) for c in cells]
    result=compute_bounded('profile_numeric',rows,{})
    try:
        if type(result) is not dict or set(result)!={'numeric','outlier_rows','precision_rows'}:raise ValueError()
        numeric=NumericProfile.model_validate(result['numeric'],strict=True).model_dump(mode='json')
        lookup={c.row:c for c in cells}
        for key in ('outlier_rows','precision_rows'):
            indices=result[key]
            if not isinstance(indices,list) or len(set(indices))!=len(indices) or any(type(row) is not int or row not in lookup for row in indices):raise ValueError()
        if numeric['n']!=len(cells) or numeric['outlier_count']!=len(result['outlier_rows']):raise ValueError()
        return numeric,[lookup[row] for row in result['outlier_rows']],[lookup[row] for row in result['precision_rows']]
    except (KeyError,TypeError,ValueError):
        raise NumericError('numeric_output_invalid','固定计划数值检查输出无效。') from None

class PlanProfileScan(ProfileScan):
    def __init__(self,sheet,*,selected_columns=None):
        super().__init__(sheet,numeric_calculator=bounded_numeric_profile,selected_columns=selected_columns)
