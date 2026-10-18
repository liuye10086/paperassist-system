"""Method-specific errors over the shared, fixed local process boundary."""
from app.domain.regression.bounded import compute_bounded
from app.domain.regression.common import NumericError


def summarize_bounded(values, *, cache_identity=None):
    from app.adapters.excel import fail
    try:
        return compute_bounded('descriptive', values, {}, cache_identity=cache_identity)
    except NumericError as exc:
        fail(exc.code, exc.message, 422)


def correlate_bounded(rows, *, method, mode, seed=1729, cache_identity=None):
    from app.domain.correlation.kernel import CorrelationError
    try:
        return compute_bounded('correlation', rows, dict(method=method, mode=mode, seed=seed), cache_identity=cache_identity)
    except NumericError as exc:
        code = 'correlation_invalid_input' if exc.code == 'numeric_invalid_input' else exc.code
        raise CorrelationError(code, exc.message) from exc


def compare_bounded(groups, *, method, posthoc='none', cache_identity=None):
    from app.domain.comparison.kernel import ComparisonError
    try:
        return compute_bounded('group_comparison', groups, dict(method=method, posthoc=posthoc), cache_identity=cache_identity)
    except NumericError as exc:
        code = 'comparison_invalid_input' if exc.code == 'numeric_invalid_input' else exc.code
        raise ComparisonError(code, exc.message) from exc
