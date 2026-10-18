"""Cross-platform roundoff is not permission to change frozen scientific facts."""
from copy import deepcopy
import math
import pytest
from app.domain.correlation import service


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def recorded_statistics():
    # Actual Windows/Linux fixture in cross-platform-5.log, not a production oracle.
    return dict(method='pearson',mode='pair',n=5,coefficient=0.7999999999999998,matrix=None,
        p_value=dict(value=0.10408803866182809,method='pearson_beta_two_sided',reason=None),
        confidence_interval=dict(low=-0.2796400419693556,high=0.9861961933012714,
            level=0.95,method='fisher_z',reason=None),
        inference=dict(alternative='two-sided',rank_method=None,permutation_type=None,
            n_resamples=None,seed=None,exact=None),warnings=['correlation_not_causation','small_sample'])


def test_actual_platform_p_difference_is_accepted_without_mutation():
    saved=recorded_statistics();computed=deepcopy(saved);original=deepcopy(saved)
    computed['p_value']['value']=0.10408803866182799
    assert service.statistics_match(saved,computed)
    assert saved==original and computed['p_value']['value']==0.10408803866182799


@pytest.mark.parametrize('path', [('coefficient',),('p_value','value'),
    ('confidence_interval','low'),('confidence_interval','high')])
def test_bounded_roundoff_only_in_floating_statistics(path):
    saved=recorded_statistics();computed=deepcopy(saved)
    target=computed
    for key in path[:-1]: target=target[key]
    for _ in range(32): target[path[-1]]=math.nextafter(target[path[-1]],0.0)
    assert service.statistics_match(saved,computed)
    target[path[-1]]=math.nextafter(target[path[-1]],0.0)
    assert not service.statistics_match(saved,computed)


def test_matrix_elements_use_the_same_roundoff_boundary():
    saved=recorded_statistics();saved.update(coefficient=None,matrix=[[1.,0.8],[0.8,1.]],mode='matrix')
    computed=deepcopy(saved)
    computed['matrix'][0][1]=computed['matrix'][1][0]=math.nextafter(0.8,0.0)
    assert service.statistics_match(saved,computed)
    computed['matrix'][1][0]=0.79999999
    assert not service.statistics_match(saved,computed)


@pytest.mark.parametrize('path,value', [
    (('n',),6),(('n',),5.0),(('method',),'spearman'),(('mode',),'matrix'),
    (('p_value','reason'),'exploratory_matrix'),(('p_value','method'),'spearman_asymptotic'),
    (('confidence_interval','level'),math.nextafter(0.95,0.0)),
    (('confidence_interval','reason'),'degenerate_correlation'),
    (('inference','seed'),1729),(('inference','exact'),False),
    (('warnings',),['small_sample','correlation_not_causation']),
    (('coefficient',),0.123),(('p_value','value'),0.123),(('confidence_interval','high'),0.97),
])
def test_metadata_and_material_statistic_changes_are_rejected(path,value):
    saved=recorded_statistics();computed=deepcopy(saved);target=computed
    for key in path[:-1]: target=target[key]
    target[path[-1]]=value
    assert not service.statistics_match(saved,computed)


@pytest.mark.parametrize('saved_value,computed_value',[
    (0.0,5e-324),(0.0,1e-300),(1e-300,0.0),(1e-300,2e-300),
    (5e-324,1e-323),(1.0,math.nextafter(1.0,0.0)),
    (-1.0,math.nextafter(-1.0,0.0)),(1e-300,-1e-300),
    (0.1,float('nan')),(0.1,float('inf')),
])
def test_zero_endpoints_signs_and_tiny_probabilities_cannot_be_reinterpreted(saved_value,computed_value):
    saved=recorded_statistics();computed=deepcopy(saved)
    saved['p_value']['value']=saved_value;computed['p_value']['value']=computed_value
    assert not service.statistics_match(saved,computed)


def test_small_probability_accepts_only_relative_roundoff():
    saved=recorded_statistics();computed=deepcopy(saved)
    saved['p_value']['value']=1e-300;computed['p_value']['value']=math.nextafter(1e-300,0.0)
    assert service.statistics_match(saved,computed)


def test_missing_and_additional_keys_and_null_values_are_exact():
    saved=recorded_statistics();computed=deepcopy(saved)
    computed['p_value']['value']=None
    assert not service.statistics_match(saved,computed)
    computed=deepcopy(saved);computed['inference']['unexpected']=None
    assert not service.statistics_match(saved,computed)
    computed=deepcopy(saved);del computed['inference']['seed']
    assert not service.statistics_match(saved,computed)
