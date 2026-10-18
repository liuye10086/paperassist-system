"""Thirteen methods, five explicit boundary classes; synthetic data, no database.

Descriptive design is N/A for inference: a complete repeated-observation
description remains valid. Constant scores and all-censored KM are legal data.
"""
from copy import deepcopy

import pytest

from app.core.exceptions import StorageError
from app.domain.analysis_plan.checks import build_check, validate_resolutions
from app.domain.correlation.contracts import parse_selection
from app.domain.regression.common import NumericError
from tests.domain.test_correlation_plan_contracts import research
from tests.helpers.modeling import sample, selection as modeling_selection
from tests.integration.test_comparison_plan import selection as comparison_selection
from tests.test_batch04_numeric import prepared


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


COMPARISONS = ('welch_t', 'mann_whitney_u', 'paired_t', 'wilcoxon',
               'welch_anova', 'kruskal_wallis')
METHODS = ('descriptive', 'pearson', 'spearman', *COMPARISONS,
           'ols', 'logistic', 'roc_auc', 'kaplan_meier')


def case(method):
    """Return valid selected source records and the actual selected method."""
    if method == 'descriptive':
        return [[1.], [2.], [4.]], dict(task_type='descriptive_boxplot',
            sheet_name='Data', numeric_column='A', group_column=None, unit='',
            missing_policy='exclude_selected_missing')
    if method in ('pearson', 'spearman'):
        return [[1., 2.], [2., 1.], [3., 3.]], dict(task_type='correlation',
            sheet_name='Data', method=method, mode='pair', columns=['A', 'B'],
            units={'A': '', 'B': ''}, missing_policy='complete_cases',
            assumptions=dict(independent_observations=True,
                relationship_form='linear' if method == 'pearson' else 'monotonic',
                inference_assumptions_confirmed=True))
    if method in COMPARISONS:
        chosen = comparison_selection('Data', method)
        if chosen['design'] == 'paired':
            values = [[f'unit-{i}', float(i), float(i * i + 2)] for i in range(5)]
        else:
            values = [[float(i * i + 2 * g), group['value']]
                      for g, group in enumerate(chosen['groups']) for i in range(5)]
        return values, chosen
    return sample(method)[1:], modeling_selection(method, 'Data')


def numeric_column(method):
    return 1 if method in ('paired_t', 'wilcoxon', 'logistic', 'roc_auc', 'kaplan_meier') else 0


def selected(values, chosen):
    selection = parse_selection(chosen)
    sheet = prepared(values)
    kind = chosen['task_type']
    if kind == 'descriptive_boxplot':
        from app.domain.dataset_analysis import scan_dataset
        profile, scan = scan_dataset(sheet, selection, True)
        return scan.values, scan.check(profile).model_dump(mode='json')
    if kind == 'correlation':
        from app.domain.correlation.checks import selected_records
        rows, _, audit = selected_records(sheet, selection)
    elif kind == 'group_comparison':
        from app.domain.comparison.checks import selected_records
        rows, _, audit, _ = selected_records(sheet, selection)
    else:
        from app.domain.regression.checks import selected_records
        rows, _, audit = selected_records(sheet, selection)
    return rows, audit


def compute(method, rows, chosen):
    if method == 'descriptive':
        from app.domain.descriptive_kernel import summarize
        return summarize(rows)
    if method in ('pearson', 'spearman'):
        from app.domain.correlation.kernel import compute_correlation
        return compute_correlation(rows, method=method, mode='pair')
    if method in COMPARISONS:
        from app.domain.comparison.kernel import compute_comparison
        return compute_comparison(rows, method=method)
    if method in ('ols', 'logistic'):
        from app.domain.regression.kernel import compute_regression
        return compute_regression(rows, chosen)
    if method == 'roc_auc':
        from app.domain.roc.kernel import compute_roc
        return compute_roc(rows, chosen)
    from app.domain.survival.kernel import compute_survival
    return compute_survival(rows, chosen)


@pytest.mark.parametrize('method', METHODS)
def test_each_method_insufficient_sample(method):
    from app.domain.comparison.kernel import ComparisonError
    from app.domain.correlation.kernel import CorrelationError
    values, chosen = case(method)
    rows, _ = selected(values, chosen)
    if method in COMPARISONS:
        rows = [g[:4 if method == 'kruskal_wallis' else 2] for g in rows]
        code = 'comparison_sample_size'
    elif method in ('pearson', 'spearman'):
        rows, code = rows[:2], 'correlation_sample_size'
    elif method == 'descriptive':
        rows, code = [], 'no_valid_records'
    elif method in ('ols', 'logistic'):
        rows, code = rows[:9 if method == 'ols' else 19], 'numeric_sample_size'
    elif method == 'roc_auc':
        rows, code = [r for r in rows if r['outcome'] == 1], 'numeric_sample_size'
    else:
        # Empty observations are insufficient data, not an excess-row limit.
        rows, code = [], 'numeric_sample_size'
    with pytest.raises((NumericError, ComparisonError, CorrelationError)) as caught:
        compute(method, rows, chosen)
    assert caught.value.code == code


@pytest.mark.parametrize('method', METHODS)
def test_each_method_constant_semantics(method):
    from app.domain.comparison.kernel import ComparisonError
    from app.domain.correlation.kernel import CorrelationError
    values, chosen = case(method)
    rows, _ = selected(values, chosen)
    if method == 'descriptive':
        result = compute(method, [7.] * 3, chosen)
        assert result['mean'] == 7 and result['std'] == 0
        assert compute(method, [7.], chosen)['std'] is None
        return
    if method == 'roc_auc':
        result = compute(method, [dict(r, score=.5) for r in rows], chosen)
        assert result['auc'] == .5
        minimal = compute(method, [dict(row=2, outcome=0, score=.5),
                                   dict(row=3, outcome=1, score=.5)], chosen)
        assert minimal['confidence_interval']['reason'] == 'insufficient_class_size'
        return
    if method == 'kaplan_meier':
        result = compute(method, [dict(r, time=1., event=False) for r in rows], chosen)
        group = result['groups'][0]
        assert group['median'] is None and all(p['survival'] == 1 for p in group['points'])
        assert compute(method, [dict(rows[0], time=1., event=False)], chosen)['n'] == 1
        return
    if method in COMPARISONS:
        rows, code = [[1.] * len(g) for g in rows], 'comparison_constant'
    elif method in ('pearson', 'spearman'):
        rows, code = [[1., r[1]] for r in rows], 'correlation_constant'
    else:
        rows, code = [dict(r, x=[1.]) for r in rows], 'numeric_rank'
    with pytest.raises((NumericError, ComparisonError, CorrelationError)) as caught:
        compute(method, rows, chosen)
    assert caught.value.code == code


@pytest.mark.parametrize('method', METHODS)
def test_each_method_missing_preserves_original_row_audit(method):
    values, chosen = case(method)
    original = deepcopy(values)
    column = numeric_column(method)
    values[0][column] = None
    _, audit = selected(values, chosen)
    if method == 'descriptive':
        assert audit['valid_count'] == len(values) - 1 and audit['excluded_count'] == 1
    else:
        assert audit['included_rows'] == list(range(3, len(values) + 2))
        assert audit['excluded_rows'] == [dict(row=2, coordinates=[f'{chr(65 + column)}2'], reason='selected_missing')]
    assert original[0][column] is not None and values[0][column] is None


@pytest.mark.parametrize('method', METHODS)
def test_each_method_text_number_is_not_silently_coerced(method):
    values, chosen = case(method)
    values[0][numeric_column(method)] = '1.0'
    if method == 'descriptive':
        check = build_check(prepared(values), parse_selection(chosen))
        assert not check['selection_check']['ready']
        assert any(i['code'] == 'numeric_type' and i['severity'] == 'blocking' for i in check['issues'])
    else:
        with pytest.raises(StorageError) as caught:
            selected(values, chosen)
        assert caught.value.code == 'numeric_type'


@pytest.mark.parametrize('method', METHODS)
def test_each_method_research_design_boundary(method):
    values, chosen = case(method)
    declaration = research()
    if method == 'descriptive':
        # N/A for inferential independence; complete descriptive research is valid.
        declaration.update(observation_structure='repeated', relationship_description='Three repeated measurements')
    else:
        declaration.update(observation_structure='independent' if chosen.get('design') == 'paired' else 'paired',
                           relationship_description='Explicitly mismatched research design')
    check = build_check(prepared(values), parse_selection(chosen), declaration, schema_version=3)
    resolutions = {i['id']: i['allowed_resolutions'][0] for i in check['issues'] if i['allowed_resolutions']}
    if method == 'descriptive':
        assert check['research_missing'] == []
        validate_resolutions(check, resolutions)
    else:
        assert 'observation_structure' in check['research_missing']
        with pytest.raises(StorageError) as caught:
            validate_resolutions(check, resolutions)
        assert caught.value.code == 'task_input_invalid'


@pytest.mark.parametrize('boundary', ['independence', 'paired', 'repeated', 'unknown', 'linear_relationship'])
def test_spearman_explicit_independence_and_research_design_reject_approval(boundary):
    values, chosen = case('spearman')
    declaration = research()
    if boundary == 'independence':
        chosen['assumptions']['independent_observations'] = False
        missing = 'independent_observations'
    elif boundary == 'linear_relationship':
        chosen['assumptions']['relationship_form'] = 'linear'
        missing = 'relationship_form'
    else:
        declaration.update(observation_structure=boundary, relationship_description='Explicit source relationship')
        missing = 'observation_structure'
    selection = parse_selection(chosen)
    assert selection.method == 'spearman'
    check = build_check(prepared(values), selection, declaration, schema_version=3)
    assert missing in check['research_missing']
    with pytest.raises(StorageError) as caught:
        validate_resolutions(check, {i['id']: i['allowed_resolutions'][0] for i in check['issues'] if i['allowed_resolutions']})
    assert caught.value.code == 'task_input_invalid'
