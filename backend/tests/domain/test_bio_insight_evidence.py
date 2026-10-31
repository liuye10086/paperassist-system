import pytest
from app.adapters.bio_insights_engine.evidence import numeric

@pytest.fixture(autouse=True)
def postgres_schema():yield None

@pytest.mark.parametrize('marker',['NA','NOT_MEASURED'])
def test_frozen_external_missing_semantics_preserve_zero_and_reject_invalid(marker):
    from app.adapters.bio_insights_engine import evidence
    assert numeric('NA') is None
    source_numeric=evidence.source_numeric
    source={'metadata':{'plan_config':{'kind':'result_import','na_values':['',marker]}}}
    assert source_numeric(source,marker) is None
    assert source_numeric(source,'0')==0
    assert source_numeric(source,False)==0
    with pytest.raises(ValueError):source_numeric(source,'broken')
    with pytest.raises(ValueError):source_numeric(source,'nan')
    assert numeric('NA') is None
