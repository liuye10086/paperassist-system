"""Independent review reproductions: changing a measurement zero is not a perfect fit."""
import math
import pytest
from app.domain.regression.kernel import compute_regression
from tests.helpers.modeling import selection


def test_ols_perfect_fit_guard_uses_centered_variation():
    offset=1e10
    rows=[dict(row=i+2,x=[float(x)],y=offset+1+2*x+e)
          for i,(x,e) in enumerate((x,e) for x in range(-3,4) for e in (-.5,.5))]
    result=compute_regression(rows,selection('ols','Synthetic'))
    assert result['coefficients'][1]['beta']==pytest.approx(2,abs=2e-6)
    assert result['residual_sd']==pytest.approx(math.sqrt(3.5/12),abs=2e-6)
