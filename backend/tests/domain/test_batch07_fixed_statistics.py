"""Independent fixed-runner outcomes and resource failure contracts; no database."""
import importlib.util
import math
import time

import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def api():
    assert importlib.util.find_spec('app.domain.fixed_statistics') is not None, 'Common fixed numerical boundary is missing'
    from app.domain import fixed_statistics
    return fixed_statistics


def test_descriptive_hand_summary_and_source_capacity_preserved():
    f = api()
    result = f.summarize_bounded([10., 20., 40., 1000., 50., 60.])
    assert result['n'] == 6
    assert result['mean'] == pytest.approx(1180 / 6)
    assert result['median'] == 45
    assert result['q1'] == 25 and result['q3'] == 57.5
    large = f.summarize_bounded([1.] * 10001)
    assert large['n'] == 10001 and large['std'] == 0


@pytest.mark.parametrize('method', ['pearson', 'spearman'])
def test_correlation_fixed_process_preserves_exact_independent_expectation(method):
    result = api().correlate_bounded([[float(i), float(i * 2)] for i in range(1, 6)], method=method, mode='pair')
    assert result['n'] == 5 and result['coefficient'] == pytest.approx(1)
    assert result['p_value']['value'] == pytest.approx(0 if method == 'pearson' else 2 / math.factorial(5))


def test_comparison_independent_welch_expectation():
    result = api().compare_bounded([[1., 2., 3.], [2., 3., 4.]], method='welch_t')
    assert result['sample_sizes'] == [3, 3]
    assert result['estimate']['value'] == -1
    assert result['statistic']['value'] == pytest.approx(-math.sqrt(1.5))
    assert result['statistic']['df_denominator'] == 4


@pytest.mark.parametrize('kind', ['correlation', 'group_comparison'])
def test_method_specific_invalid_input_codes_survive_process_boundary(kind):
    from app.domain.correlation.kernel import CorrelationError
    from app.domain.comparison.kernel import ComparisonError
    f = api()
    if kind == 'correlation':
        with pytest.raises(CorrelationError) as caught:
            f.correlate_bounded([[1., 2.]] * 4, method='pearson', mode='pair')
        assert caught.value.code == 'correlation_constant'
    else:
        with pytest.raises(ComparisonError) as caught:
            f.compare_bounded([[1., 2.], [3., 4.]], method='welch_t')
        assert caught.value.code == 'comparison_sample_size'


def test_new_method_timeout_and_unknown_callable_rejected():
    api()
    from app.domain.regression.bounded import compute_bounded
    from app.domain.regression.common import NumericError
    started = time.monotonic()
    with pytest.raises(NumericError) as caught:
        compute_bounded('descriptive', [1., 2., 3.], {}, timeout_seconds=.00001)
    assert caught.value.code == 'numeric_timeout'
    assert time.monotonic() - started < 2
    with pytest.raises(NumericError):
        compute_bounded('os.system', [1.], {})


def test_group_pair_count_is_not_double_counted_for_input_limit():
    f = api()
    # 10001 complete pairs must be refused, while 10000 is still within the
    # declared count; identical nonzero differences are valid for Wilcoxon.
    result = f.compare_bounded([[1.] * 10000, [2.] * 10000], method='wilcoxon')
    assert result['sample_sizes'] == [10000, 10000]
    from app.domain.comparison.kernel import ComparisonError
    with pytest.raises(ComparisonError) as caught:
        f.compare_bounded([[1.] * 10001, [2.] * 10001], method='wilcoxon')
    assert caught.value.code == 'comparison_input_limit'


def test_execution_receipt_is_bounded_metadata_and_cache_returns_own_copy():
    f = api()
    from app.domain.regression import bounded
    bounded.clear_compute_cache()
    original = f.summarize_bounded([1., 2., 3.])
    receipt = bounded.last_execution_receipt()
    assert receipt['contract_version'] == 'fixed_statistics_v2'
    assert receipt['input_bytes'] > 0 and receipt['output_bytes'] > 0
    assert receipt['timeout_seconds'] == 30 and receipt['cache_hit'] is False
    assert receipt['elapsed_seconds'] >= 0
    assert receipt['child_cpu_seconds'] >= 0
    assert receipt['child_peak_rss_bytes'] > 0
    original['n'] = -1
    assert f.summarize_bounded([1., 2., 3.])['n'] == 3
    assert bounded.last_execution_receipt()['cache_hit'] is True


def test_nonfinite_and_protocol_size_rejected_without_spawning(monkeypatch):
    api()
    from app.domain.regression import bounded
    from app.domain.regression.common import NumericError
    monkeypatch.setattr(bounded.subprocess, 'run', lambda *a, **k: pytest.fail('Invalid payload reached subprocess'))
    with pytest.raises(NumericError):
        bounded.compute_bounded('descriptive', [float('nan')], {})
    with pytest.raises(NumericError) as caught:
        bounded.compute_bounded('descriptive', [1.], {'unexpected': 'x' * (8 * 1024 * 1024)})
    assert caught.value.code in ('numeric_invalid_input', 'numeric_input_limit')


def test_execution_contract_metadata_preserves_legacy_serialization():
    from app.domain.descriptive import EngineInfo
    from app.domain.regression.contracts import StatisticalEngine
    legacy = dict(id='descriptive_statistics_v1', python_version='3.11.4', openpyxl_version='3.1.5',
                  std_ddof=1, quantile_method='linear_inclusive')
    assert EngineInfo.model_validate(legacy).model_dump() == legacy
    assert EngineInfo.model_validate(dict(legacy, execution_contract='fixed_statistics_v2')).model_dump()['execution_contract'] == 'fixed_statistics_v2'
    model = dict(id='roc_statistics_dataset_v1', python_version='3.11.4', scipy_version='1.17.1',
                 numpy_version='2.4.6', parser_version='excel_parser_v1', encoding_version='typed_reference_dummy_v1', timeout_seconds=30)
    old = StatisticalEngine.model_validate(model).model_dump()
    assert 'execution_contract' not in old
    assert StatisticalEngine.model_validate(dict(model, execution_contract='fixed_statistics_v2')).model_dump()['execution_contract'] == 'fixed_statistics_v2'
