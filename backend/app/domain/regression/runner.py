"""Private fixed kernel dispatcher. No file protocol or executable input."""
from app.domain.fixed_statistics_contract import validate_request, PROJECTION_REASONS, ERROR_MESSAGES
from app.domain.regression.common import NumericError
from fractions import Fraction
import math

_METHODS = {
    'regression': frozenset(('ols', 'logistic')),
    'correlation': frozenset(('pearson', 'spearman')),
    'group_comparison': frozenset(('welch_t', 'mann_whitney_u', 'paired_t', 'wilcoxon', 'welch_anova', 'kruskal_wallis')),
    'roc': frozenset(('roc_auc',)),
    'survival': frozenset(('kaplan_meier',)),
}


def validate_method(kind, selection):
    methods = _METHODS.get(kind)
    default = 'roc_auc' if kind == 'roc' else 'kaplan_meier' if kind == 'survival' else None
    if methods is not None and (type(selection.get('method', default)) is not str or selection.get('method', default) not in methods):
        raise NumericError('numeric_invalid_input', '固定统计方法不在白名单中。')


def compute_boxplot_series(observations):
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in observations):
        raise NumericError('numeric_invalid_input', ERROR_MESSAGES['numeric_invalid_input'])
    ordered = sorted(observations)
    def quantile(quarter):
        index, remainder = divmod((len(ordered) - 1) * quarter, 4)
        return ((4 - remainder) * Fraction(ordered[index]) + remainder * Fraction(ordered[min(index + 1, len(ordered) - 1)])) / 4
    q1, median, q3 = (quantile(q) for q in (1, 2, 3))
    lower, upper = q1 - (q3 - q1) * Fraction(3, 2), q3 + (q3 - q1) * Fraction(3, 2)
    inside = [v for v in ordered if lower <= v <= upper]
    outside = [v for v in ordered if v < lower or v > upper]
    whislo, whishi = Fraction(inside[0]), Fraction(inside[-1])
    points = sorted(set(outside))
    metrics = {'q1': q1, 'median': median, 'q3': q3, 'whislo': whislo, 'whishi': whishi}
    return {'n': len(ordered), **{k: float(v) for k, v in metrics.items()},
            'fliers': points, 'outlier_count': len(outside)}


def preload_kernels():
    # Dependencies and HiGHS lazy modules load before filesystem access ends.
    import statsmodels.api
    import statsmodels.stats.outliers_influence
    import scipy.stats
    from app.domain.dataset_profile.scan import numeric_profile
    from app.domain.regression.kernel import compute_regression
    from app.domain.roc.kernel import compute_roc
    from app.domain.survival.kernel import compute_survival
    from app.domain.descriptive_kernel import summarize
    from app.domain.correlation.kernel import compute_correlation
    from app.domain.comparison.kernel import compute_comparison
    from app.domain.figure_workbench.kernel import compute_projection
    from scipy.optimize import linprog
    linprog([1.], bounds=[(0., 1.)], method='highs', options={'threads': 1})


def compute_request(request):
    if type(request) is not dict or set(request) != {'task_type', 'rows', 'selection'}:
        raise NumericError('numeric_invalid_input', 'Invalid fixed statistics request.')
    task_type, rows, selection = request['task_type'], request['rows'], request['selection']
    validate_request(task_type, rows, selection)
    validate_method(task_type, selection)
    if task_type == 'profile_numeric':
        from types import SimpleNamespace
        from app.domain.dataset_profile.scan import numeric_profile
        numeric,outliers,precision=numeric_profile([SimpleNamespace(**row) for row in rows])
        return dict(numeric=numeric,outlier_rows=[c.row for c in outliers],precision_rows=[c.row for c in precision])
    if task_type == 'boxplot_series':
        return compute_boxplot_series(rows)
    if task_type == 'figure_projection':
        from app.domain.figure_workbench.kernel import compute_projection, ProjectionError
        try:
            return compute_projection(selection['figure_kind'], rows, selection['projection'])
        except ProjectionError as exc:
            error = NumericError('figure_projection_invalid', ERROR_MESSAGES['figure_projection_invalid'])
            error.reason = str(exc) if str(exc) in PROJECTION_REASONS else 'invalid_rule'
            raise error from None
    if task_type == 'regression':
        from app.domain.regression.kernel import compute_regression
        return compute_regression(rows, selection)
    if task_type == 'roc':
        from app.domain.roc.kernel import compute_roc
        return compute_roc(rows, selection)
    if task_type == 'survival':
        from app.domain.survival.kernel import compute_survival
        return compute_survival(rows, selection)
    if task_type == 'descriptive':
        from app.domain.descriptive_kernel import summarize
        return summarize(rows)
    if task_type == 'correlation':
        from app.domain.correlation.kernel import compute_correlation
        return compute_correlation(rows, **selection)
    from app.domain.comparison.kernel import compute_comparison
    return compute_comparison(rows, **selection)
