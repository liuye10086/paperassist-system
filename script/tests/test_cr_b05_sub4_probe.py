"""New gate binding only; accepted scientific fits are not re-executed."""
import importlib.util
from pathlib import Path
import pytest


def module():
    path=Path(__file__).parents[1]/'dev/cr_b05_sub4_probe.py'
    spec=importlib.util.spec_from_file_location('sub4_probe',path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def test_incremental_checks_require_exact_runtime_and_parent_proof():
    m=module();runtime={'code_digest':'new-source','environment_digest':'new-env'}
    feature={'runtime_identity':runtime,'checks':{key:True for key in m.FEATURE_CHECKS}}
    parent={'checks':{'feature_parent_validation':True}}
    actual=m.delta_checks(runtime,feature,parent,m.FEATURE_CHECKS,'feature_parent_validation')
    assert actual=={**feature['checks'],**parent['checks']}
    with pytest.raises(ValueError,match='identity'):
        m.delta_checks({**runtime,'code_digest':'different'},feature,parent,m.FEATURE_CHECKS,'feature_parent_validation')
    with pytest.raises(ValueError,match='checks'):
        m.delta_checks(runtime,feature,{'checks':{'feature_parent_validation':False}},m.FEATURE_CHECKS,'feature_parent_validation')
    with pytest.raises(ValueError,match='checks'):
        m.delta_checks(runtime,{**feature,'checks':dict(feature_sequence=1,feature_structure=True,feature_figures=True)},parent,m.FEATURE_CHECKS,'feature_parent_validation')
