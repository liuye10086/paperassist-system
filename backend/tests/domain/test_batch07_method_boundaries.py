"""Missing method-by-method boundary characterizations, without database or cloud."""
from copy import deepcopy
import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


COMPARISONS=['welch_t','mann_whitney_u','paired_t','wilcoxon','welch_anova','kruskal_wallis']


@pytest.mark.parametrize('method',COMPARISONS)
def test_comparison_minimum_short_constant_type_and_design(method):
    from app.domain.comparison.kernel import compute_comparison,ComparisonError
    count=5 if method=='kruskal_wallis' else 3
    multiple=method in ('welch_anova','kruskal_wallis')
    groups=[[float(i) for i in range(count)], [float(i*i+2) for i in range(count)]]
    if multiple:groups.append([float(i+4) for i in range(count)])
    assert compute_comparison(groups,method=method)['sample_sizes']==[count]*len(groups)
    with pytest.raises(ComparisonError) as error:
        compute_comparison([g[:-1] for g in groups],method=method)
    assert error.value.code=='comparison_sample_size'
    with pytest.raises(ComparisonError) as error:
        compute_comparison([[1.]*count for _ in groups],method=method)
    assert error.value.code=='comparison_constant'
    invalid=deepcopy(groups);invalid[0][0]='1'
    with pytest.raises(ComparisonError) as error:compute_comparison(invalid,method=method)
    assert error.value.code=='comparison_invalid_input'
    with pytest.raises(ComparisonError) as error:
        compute_comparison(groups[:2] if multiple else groups+[groups[0]],method=method)
    assert error.value.code=='comparison_invalid_input'


@pytest.mark.parametrize('method',['pearson','spearman'])
def test_correlation_minimum_short_constant_and_type(method):
    from app.domain.correlation.kernel import compute_correlation,CorrelationError
    rows=[[1.,2.],[2.,1.],[3.,3.]]
    assert compute_correlation(rows,method=method,mode='pair')['n']==3
    for values,code in [(rows[:2],'correlation_sample_size'),([[1.,1.],[1.,2.],[1.,3.]],'correlation_constant'),([['1',1.],[2.,2.],[3.,3.]],'correlation_invalid_input')]:
        with pytest.raises(CorrelationError) as error:compute_correlation(values,method=method,mode='pair')
        assert error.value.code==code


@pytest.mark.parametrize('method',['ols','logistic'])
def test_regression_minimum_short_constant_and_nonfinite(method):
    from app.domain.regression.kernel import compute_regression
    from app.domain.regression.common import NumericError
    s={'method':method,'covariates':[dict(column='B',type='continuous',unit='',levels=[],reference=None)]}
    if method=='ols':
        rows=[dict(row=i+2,x=[float(i)],y=2+3*i+e) for i,e in enumerate([1,-1,-1,1,0,0,1,-1,-1,1])]
    else:
        rows=[dict(row=2+x*10+i,x=[float(x)],y=float(i<events)) for x,events in [(0,3),(1,7)] for i in range(10)]
    assert compute_regression(rows,s)['n']==len(rows)
    with pytest.raises(NumericError) as error:compute_regression(rows[:-1],s)
    assert error.value.code=='numeric_sample_size'
    constant=[dict(r,x=[1.]) for r in rows]
    with pytest.raises(NumericError) as error:compute_regression(constant,s)
    assert error.value.code=='numeric_rank'
    invalid=deepcopy(rows);invalid[0]['x']=[float('nan')]
    with pytest.raises(NumericError) as error:compute_regression(invalid,s)
    assert error.value.code=='numeric_invalid_input'


def test_roc_one_per_class_constant_score_and_invalid_direction():
    from app.domain.roc.kernel import compute_roc
    from app.domain.regression.common import NumericError
    s=dict(direction='higher_is_positive',evaluation_role='external_validation')
    rows=[dict(row=2,outcome=0,score=.5),dict(row=3,outcome=1,score=.5)]
    result=compute_roc(rows,s)
    assert result['n']==2 and result['auc']==.5
    assert result['confidence_interval']['reason']=='insufficient_class_size'
    with pytest.raises(NumericError) as error:compute_roc(rows[:1],s)
    assert error.value.code=='numeric_sample_size'
    with pytest.raises(NumericError) as error:compute_roc(rows,dict(s,direction='choose_best'))
    assert error.value.code=='numeric_invalid_input'


def test_km_one_observation_constant_time_and_empty_group():
    from app.domain.survival.kernel import compute_survival
    from app.domain.regression.common import NumericError
    s=dict(groups=[],time_unit='day')
    rows=[dict(row=2,time=1.,event=False,group=0)]
    result=compute_survival(rows,s)
    assert result['n']==1 and result['groups'][0]['median'] is None
    assert result['groups'][0]['points'][0]['survival']==1
    with pytest.raises(NumericError) as error:compute_survival([],s)
    assert error.value.code=='numeric_sample_size'
    with pytest.raises(NumericError) as error:
        compute_survival(rows,dict(s,groups=[dict(kind='text',value='A'),dict(kind='text',value='B')]))
    assert error.value.code=='numeric_sample_size'
    with pytest.raises(NumericError) as error:compute_survival([dict(rows[0],event=1)],s)
    assert error.value.code=='numeric_invalid_input'


@pytest.mark.parametrize('method',['ols','logistic','roc_auc','kaplan_meier'])
def test_modeling_missing_numeric_type_and_unconfirmed_design(method):
    from app.domain.regression.checks import selected_records,missing_roles
    from app.domain.correlation.contracts import parse_selection
    from app.core.exceptions import StorageError
    from tests.helpers.modeling import sample,selection
    from tests.test_batch04_numeric import prepared
    values=sample(method)[1:];s=selection(method,'Data')
    col=0 if method=='ols' else 1
    incomplete=deepcopy(values);incomplete[0][col]=None
    _,_,audit=selected_records(prepared(incomplete),parse_selection(s))
    assert audit['excluded_rows']==[dict(row=2,coordinates=[('A' if col==0 else 'B')+'2'],reason='selected_missing')]
    bad=deepcopy(values);bad[0][col]='1.0'
    with pytest.raises(StorageError) as error:selected_records(prepared(bad),parse_selection(s))
    assert error.value.code=='numeric_type'
    s['assumptions']['independent_units']=False
    assert 'independent_units' in missing_roles(parse_selection(s))


def test_descriptive_minimum_empty_constant_and_numeric_type():
    from app.domain.descriptive_kernel import summarize
    from app.domain.regression.common import NumericError
    assert summarize([7.])['std'] is None
    assert summarize([7.,7.,7.])['std']==0
    for values,code in [([],'no_valid_records'),(['7'],'numeric_invalid_input')]:
        with pytest.raises(NumericError) as error:summarize(values)
        assert error.value.code==code
