"""Fixed numerical failure reasons, safe process envelopes and unchanged limits."""
import json
import subprocess
from pathlib import Path

import pytest

from app.domain.regression import bounded, runner
from app.domain.regression.common import NumericError


@pytest.fixture(autouse=True)
def postgres_schema():
    # This suite uses only temporary process files, never a database.
    yield None


@pytest.fixture(autouse=True)
def empty_cache():
    bounded.clear_compute_cache()
    yield
    bounded.clear_compute_cache()


def assert_code(operation, code):
    with pytest.raises(NumericError) as caught:
        operation()
    assert caught.value.code == code
    assert 'private-marker' not in str(caught.value)


@pytest.mark.parametrize('kind,rows,code', [
    ('descriptive', [1.] * 100001, 'numeric_descriptive_limit'),
    ('regression', [{}] * 10001, 'numeric_row_limit'),
    ('roc', [{}] * 10001, 'numeric_row_limit'),
    ('survival', [{}] * 10001, 'numeric_row_limit'),
    ('regression', [], 'numeric_sample_size'),
    ('roc', [], 'numeric_sample_size'),
    ('survival', [], 'numeric_sample_size'),
])
def test_count_limits_identify_the_actual_method(kind, rows, code, monkeypatch):
    monkeypatch.setattr(bounded.subprocess, 'run', lambda *a, **k: pytest.fail('Oversized source spawned'))
    assert_code(lambda: bounded.compute_bounded(kind, rows, {}), code)


@pytest.mark.parametrize('operation', ['cached', 'uncached', 'runner'])
def test_input_byte_limit_is_not_a_row_or_covariate_limit(operation, monkeypatch, tmp_path):
    monkeypatch.setattr(bounded, '_MAX_INPUT_BYTES', 8)
    monkeypatch.setattr(runner, 'MAX_INPUT_BYTES', 8)
    monkeypatch.setattr(bounded.subprocess, 'run', lambda *a, **k: pytest.fail('Oversized input spawned'))
    path = tmp_path / 'input.json'
    path.write_text('x' * 9)
    actions = {
        'cached': lambda: bounded.compute_bounded('descriptive', [1.], {}),
        'uncached': lambda: bounded._compute_uncached('descriptive', [1.], {}),
        'runner': lambda: runner.run(path, tmp_path / 'output.json'),
    }
    assert_code(actions[operation], 'numeric_input_bytes_limit')


@pytest.mark.parametrize('timeout', [0, -1, 31, True, float('nan'), float('inf'), '30'])
def test_invalid_timeout_is_configuration_not_data_volume(timeout):
    assert_code(lambda: bounded.compute_bounded('descriptive', [1.], {}, timeout), 'numeric_timeout_invalid')


def process_response(monkeypatch, body):
    def run(args, **kwargs):
        if body is not None:
            Path(args[-1]).write_bytes(body)
    monkeypatch.setattr(bounded.subprocess, 'run', run)


@pytest.mark.parametrize('body,code', [
    (None, 'numeric_output_missing'),
    (b'{broken', 'numeric_output_invalid'),
    (b'[]', 'numeric_output_invalid'),
    (b'{"status":"ok","result":{}}', 'numeric_output_invalid'),
    (b'{"status":"ok","result":{},"measurement":{"cpu_seconds":-1,"peak_rss_bytes":1}}', 'numeric_output_invalid'),
])
def test_missing_or_corrupt_output_does_not_blame_input(body, code, monkeypatch):
    process_response(monkeypatch, body)
    assert_code(lambda: bounded.compute_bounded('descriptive', [1.], {}), code)
    assert bounded.last_execution_receipt() is None


def test_output_file_limit_is_independent_of_input_limit(monkeypatch):
    monkeypatch.setattr(bounded, '_MAX_OUTPUT_BYTES', 8)
    process_response(monkeypatch, b'x' * 9)
    assert_code(lambda: bounded.compute_bounded('descriptive', [1.], {}), 'numeric_output_limit')


def test_parent_serialized_result_limit_is_also_output_limit(monkeypatch):
    monkeypatch.setattr(bounded, '_MAX_OUTPUT_BYTES', 8)
    monkeypatch.setattr(bounded, '_compute_uncached', lambda *a, **k: {'result': 'large'})
    assert_code(lambda: bounded.compute_bounded('descriptive', [1.], {}), 'numeric_output_limit')


def test_runner_output_limit_uses_output_code(monkeypatch, tmp_path):
    path = tmp_path / 'input.json'
    path.write_text(json.dumps(dict(task_type='descriptive', rows=[1., 2., 3.], selection={})))
    monkeypatch.setattr(runner, 'MAX_OUTPUT_BYTES', 8)
    assert_code(lambda: runner.run(path, tmp_path / 'output.json'), 'numeric_output_limit')


@pytest.mark.parametrize('error,code', [
    (subprocess.TimeoutExpired('fixed', 30), 'numeric_timeout'),
    (subprocess.CalledProcessError(1, 'fixed'), 'numeric_failure'),
    (OSError('private-marker'), 'numeric_failure'),
])
def test_process_failures_do_not_report_input_limits(error, code, monkeypatch):
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(bounded.subprocess, 'run', fail)
    assert_code(lambda: bounded.compute_bounded('descriptive', [1.], {}), code)


@pytest.mark.parametrize('code,expected', [
    ('numeric_sample_size', 'numeric_sample_size'),
    ('correlation_constant', 'correlation_constant'),
    ('comparison_sample_size', 'comparison_sample_size'),
    ('unknown_private_code', 'numeric_output_invalid'),
])
def test_process_error_envelope_never_forwards_arbitrary_text(code, expected, monkeypatch):
    process_response(monkeypatch, json.dumps(dict(status='error', code=code, message='private-marker',
        measurement=dict(cpu_seconds=0, peak_rss_bytes=None))).encode())
    assert_code(lambda: bounded.compute_bounded('descriptive', [1.], {}), expected)


@pytest.mark.parametrize('number', ['NaN', 'Infinity', '-Infinity', '1e400'])
def test_nonfinite_output_is_corrupt_response_not_an_unhandled_exception(number, monkeypatch):
    process_response(monkeypatch, ('{"status":"ok","result":{"value":' + number +
        '},"measurement":{"cpu_seconds":0,"peak_rss_bytes":null}}').encode())
    assert_code(lambda: bounded.compute_bounded('descriptive', [1.], {}), 'numeric_output_invalid')


@pytest.mark.parametrize('body', [
    b'[' * 1100 + b'0' + b']' * 1100,
    ('{"status":"ok","result":{},"measurement":{"cpu_seconds":' + '9' * 1000
     + ',"peak_rss_bytes":null}}').encode(),
], ids=['deep-json', 'overflowing-cpu-measurement'])
def test_extreme_corrupt_output_has_fixed_public_error(body, monkeypatch):
    process_response(monkeypatch, body)
    assert_code(lambda: bounded.compute_bounded('descriptive', [1.], {}), 'numeric_output_invalid')
    assert bounded.last_execution_receipt() is None


def test_huge_timeout_is_invalid_configuration_without_float_overflow():
    assert_code(lambda: bounded.compute_bounded('descriptive', [1.], {}, 10 ** 1000), 'numeric_timeout_invalid')


def test_runner_unexpected_exception_never_writes_raw_text(monkeypatch, tmp_path):
    def fail(*args):
        raise RuntimeError('private-marker')
    output = tmp_path / 'output.json'
    monkeypatch.setattr(runner, 'run', fail)
    monkeypatch.setattr(runner.sys, 'argv', ['runner', str(tmp_path / 'input.json'), str(output)])
    assert runner.main() == 0
    message = json.loads(output.read_text())
    assert message['code'] == 'numeric_failure'
    assert 'private-marker' not in output.read_text()


@pytest.mark.parametrize('code,category', [
    ('numeric_input_limit', 'source'),
    ('numeric_descriptive_limit', 'source'),
    ('numeric_row_limit', 'source'),
    ('numeric_effect_limit', 'source'),
    ('numeric_input_bytes_limit', 'source'),
    ('numeric_sample_size', 'source'),
    ('numeric_output_limit', 'output'),
    ('numeric_output_missing', 'output'),
    ('numeric_output_invalid', 'output'),
    ('numeric_timeout_invalid', 'configuration'),
    ('numeric_timeout', 'temporary'),
    ('numeric_failure', 'temporary'),
    ('result_mismatch', 'output'),
])
def test_new_and_legacy_codes_survive_public_task_and_plan_contracts(code, category):
    from app.core.errors import error_detail
    from app.domain.tasks.errors import error_category, safe_error_code
    from app.domain.analysis_plan.contracts import PlanIssue
    assert error_detail(code, 'safe', {'private': 'private-marker'}) == dict(code=code, message='safe', params={})
    assert safe_error_code(code) == code
    assert error_category(code) == category
    if code != 'result_mismatch':
        assert PlanIssue(id=code, code=code, severity='blocking', field=None, count=1,
            coordinates=[], message='safe', allowed_resolutions=[]).code == code


def test_limit_values_are_unchanged():
    from app.domain.fixed_statistics_contract import MAX_INPUT_BYTES, MAX_OUTPUT_BYTES, TIMEOUT_SECONDS, validate_request
    assert (MAX_INPUT_BYTES, MAX_OUTPUT_BYTES, TIMEOUT_SECONDS) == (8 * 1024 * 1024, 16 * 1024 * 1024, 30)
    validate_request('descriptive', [1.] * 100000, {})
    for kind in ('regression', 'roc', 'survival'):
        validate_request(kind, [{}] * 10000, {})


def test_expanded_effect_limit_has_its_own_reason():
    from app.core.exceptions import StorageError
    from app.domain.regression.checks import selected_records
    from app.domain.regression.contracts import RegressionSelection
    from tests.helpers.modeling import selection
    chosen = selection('ols', 'Data')
    levels = [dict(kind='text', value=str(i)) for i in range(6)]
    chosen['covariates'] = [dict(column=column, type='categorical', unit='', levels=levels, reference=levels[0])
        for column in ['B', 'C', 'D', 'E', 'F']]
    with pytest.raises(StorageError) as caught:
        selected_records(None, RegressionSelection.model_validate(chosen))
    assert caught.value.code == 'numeric_effect_limit'


def test_eight_covariates_remain_a_separate_selection_constraint():
    from pydantic import ValidationError
    from app.domain.regression.contracts import RegressionSelection
    from tests.helpers.modeling import selection
    chosen = selection('ols', 'Data')
    chosen['covariates'] = [dict(column=column, type='continuous', unit='', levels=[], reference=None)
        for column in 'BCDEFGHI']
    assert len(RegressionSelection.model_validate(chosen).covariates) == 8
    chosen['covariates'].append(dict(column='J', type='continuous', unit='', levels=[], reference=None))
    with pytest.raises(ValidationError) as caught:
        RegressionSelection.model_validate(chosen)
    assert any(error['loc'] == ('covariates',) and error['type'] == 'too_long' for error in caught.value.errors())
