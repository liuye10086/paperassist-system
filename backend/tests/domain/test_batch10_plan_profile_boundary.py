"""Plan-only numerical routing preserves the existing profile algorithm."""
from contextlib import contextmanager
from types import SimpleNamespace
import pytest
from tests.domain.test_analysis_plan import sample,selection

@pytest.fixture(autouse=True)
def postgres_schema():yield None

def test_plan_profile_uses_fixed_kernel_instead_of_parent_statistics(monkeypatch):
    from app.domain.dataset_profile import scan
    original=scan.numeric_profile;calls=[]
    def fixed(kind,rows,options):
        assert kind=='profile_numeric' and options=={}
        calls.append(rows)
        cells=[SimpleNamespace(**r) for r in rows]
        numeric,outliers,precision=original(cells)
        return dict(numeric=numeric,outlier_rows=[c.row for c in outliers],precision_rows=[c.row for c in precision])
    def forbidden(*a,**k):raise AssertionError('Plan statistics ran in privileged parent')
    monkeypatch.setattr(scan,'numeric_profile',forbidden)
    monkeypatch.setattr('app.domain.regression.bounded.compute_bounded',fixed)
    from app.domain.analysis_plan.checks import build_check
    check=build_check(sample(unit='mg'),selection(unit='mg'))
    assert calls and check['selected_fields'][0]['observed_min']==1.
    assert next(i for i in check['issues'] if i['code']=='selected_missing')['coordinates']==['C6','D10','C10']

def test_new_engine_cannot_downgrade_when_execution_task_is_missing(monkeypatch):
    from app.domain.statistics_execution import verification
    from app.core.exceptions import StorageError
    @contextmanager
    def no_row(*a,**k):yield SimpleNamespace(execute=lambda *a,**k:SimpleNamespace(fetchone=lambda:None))
    monkeypatch.setattr(verification,'_storage_connection',no_row)
    with pytest.raises(StorageError):verification.require_receipt(SimpleNamespace(db_config=None),'p','f',{'id':'r','engine':{'execution_contract':'fixed_statistics_v2'}})
    assert verification.require_receipt(SimpleNamespace(db_config=None),'p','f',{'id':'old','engine':{'id':'legacy'}}) is False
