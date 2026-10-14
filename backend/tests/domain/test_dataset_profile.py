"""Read-only sparse profiles preserve original coordinates and exact typed identities."""
import json
from datetime import date, datetime, time, timedelta
from time import perf_counter
from types import SimpleNamespace

import pytest

from tests.domain.test_dataset_analysis import sheet
from app.domain.dataset_preparation.contracts import PreparedSheet, PreparationField, PreparationUnit, PreparedCell


def scan(value):
    from app.domain.dataset_profile.scan import ProfileScan
    return ProfileScan(value)


def test_iqr_outlier_retains_real_coordinate():
    result = scan(sheet([['Value']] + [[n] for n in [1, 2, 3, 4, 100]]))
    numeric = result.fields[0]['numeric']
    assert (numeric['q1'], numeric['q3'], numeric['iqr']) == (2, 4, 2)
    assert (numeric['lower_fence'], numeric['upper_fence']) == ('-1', '7')
    assert numeric['outlier_count'] == 1
    assert result.issues('outlier', 1, 1)[1][0]['coordinate'] == 'A6'


@pytest.mark.parametrize('values,expected', [([1], 0), ([2, 2, 2], 0), ([0, 0, 0, 100], 1)])
def test_small_or_constant_series_uses_existing_boxplot_rule(values, expected):
    numeric = scan(sheet([['Value']] + [[n] for n in values])).fields[0]['numeric']
    assert numeric['status'] == 'ok' and numeric['outlier_count'] == expected
    assert ('std_insufficient' in numeric['warnings']) == (len(values) == 1)


def test_duplicate_keys_are_typed_exact_and_not_trimmed():
    value = sheet([['Value']] + [[n] for n in [1, 1.0, True, '1', ' 1', '1 ', 'NA', '  ', None, 2]])
    result = scan(value)
    assert result.fields[0]['distinct_count'] == 7
    assert result.blank_row_count == 2
    assert (result.duplicate_groups, result.duplicate_rows, result.duplicate_extra_rows) == (1, 2, 1)
    assert [i['row'] for i in result.issues('duplicate', None, 1)[1]] == [2, 3]
    assert result.fields[0]['missing_count'] == 2
    assert result.fields[0]['issue_counts']['mixed_type'] == 8


def test_duplicates_beyond_preview_group_by_first_row():
    result = scan(sheet([['Value']] + [[n] for n in range(1, 48)] + [[26]]))
    total, items = result.issues('duplicate', None, 1)
    assert total == 2 and [i['row'] for i in items] == [27, 49]
    assert all(i['group_first_row'] == 27 and i['group_size'] == 2 for i in items)


def test_top_ten_is_bounded_and_counts_remaining_observations():
    result = scan(sheet([['Label']] + [[str(n)] for n in range(12)] + [['0']] * 2)).fields[0]
    assert result['categories']['distinct_count'] == 12
    assert len(result['categories']['top']) == 10
    assert result['categories']['top'][0] == {'kind': 'text', 'value': '0', 'count': 3}
    assert result['categories']['other_count'] == 2


def test_temporal_types_and_text_candidates_remain_separate():
    values = [date(2026, 1, 2), datetime(2026, 1, 2, 3), time(12), timedelta(days=2),
              '2026-02-28', '2026/02/28 03:04:05', '2026-02-30', '2026/13/01',
              '01/02/2026', 'plain', '2026-01-01 25:00:00']
    value = sheet([['Time']] + [[n] for n in values])
    # Excel serializers can store a date as midnight datetime. Exercise the
    # persisted date contract explicitly as well as the native parser kinds.
    value = value.model_copy(update={'cells': [c.model_copy(update={'kind': 'date', 'value': '2026-01-02'})
        if c.coordinate == 'A2' else c for c in value.cells]})
    result = scan(value)
    field = result.fields[0]
    assert {v['kind'] for v in field['temporal']} == {'date', 'datetime', 'time', 'duration'}
    assert field['time_candidates'] == dict(valid_count=2, invalid_count=3, ambiguous_count=1)
    assert field['type_counts']['text'] == 7
    assert [i['coordinate'] for i in result.issues('time_invalid', 1, 1)[1]] == ['A8', 'A9', 'A12']


def test_slash_dates_validate_both_orders_without_converting_text():
    invalid = ['99/99/2026', '31/04/2026', '29/02/2025', '0/2/2026',
               '01/02/0000', '01/02/2026 25:00:00', '01/02/2026 12:60:00',
               '01/02/2026 12:00:60']
    ambiguous = ['01/02/2026', '13/02/2026', '02/13/2026', '29/02/2024',
                 '2/29/2024', '1/2/2026 23:59:59']
    values = invalid + ambiguous
    result = scan(sheet([['Time']] + [[value] for value in values]))
    field = result.fields[0]
    assert field['time_candidates'] == dict(valid_count=0, invalid_count=len(invalid),
                                           ambiguous_count=len(ambiguous))
    assert field['type_counts'] == {'text': len(values)}
    assert field['temporal'] == []
    assert [item['value'] for item in result.issues('time_invalid', 1, 1)[1]] == invalid
    assert [item['value'] for item in result.issues('time_ambiguous', 1, 1)[1]] == ambiguous


@pytest.mark.parametrize('lexical', ['9007199254740992', '9007199254740993', '1e309', '1e-400'])
def test_unsafe_numbers_only_disable_their_numeric_column(lexical):
    value = sheet([['Value', 'Other'], [1, 'NA'], [2, True]])
    value = value.model_copy(update={'cells': [c.model_copy(update={'value': lexical, 'raw_value': lexical})
        if c.coordinate == 'A3' else c for c in value.cells]})
    result = scan(value)
    numeric = result.fields[0]['numeric']
    assert numeric['status'] == 'unavailable' and numeric['n'] == 2
    assert numeric['mean'] is None and 'numeric_precision' in numeric['warnings']
    assert result.fields[1]['categories']['distinct_count'] == 2
    assert result.issues('numeric_precision', 1, 1)[1][0]['coordinate'] == 'A3'
    json.dumps(result.fields, allow_nan=False)


@pytest.mark.parametrize('lexical', ['9007199254740993.0', '9007199254740993e0', '1e308'])
def test_numeric_support_matches_existing_binary64_contract(lexical):
    from decimal import Decimal
    from app.domain.dataset_analysis import binary64
    value = sheet([['Value'], [1]])
    value = value.model_copy(update={'cells': [c.model_copy(update={'value': lexical, 'raw_value': lexical})
        if c.row == 2 else c for c in value.cells]})
    numeric = scan(value).fields[0]['numeric']
    assert numeric['status'] == 'ok'
    assert numeric['mean'] == binary64(Decimal(lexical), 'A', 2, lexical)


def test_extreme_metrics_are_finite_or_null_without_losing_other_metrics():
    value = sheet([['Value'], [1], [2]])
    value = value.model_copy(update={'cells': [c.model_copy(update={'value': '-1e308' if c.row == 2 else '1e308'})
        if c.row > 1 else c for c in value.cells]})
    numeric = scan(value).fields[0]['numeric']
    assert numeric['status'] == 'ok' and numeric['mean'] == 0
    assert numeric['std'] > 0
    json.dumps(numeric, allow_nan=False)


def test_formula_and_error_are_counted_without_reading_formula_cache():
    result = scan(sheet([['Value'], [1], ['=1+1'], ['#DIV/0!']]))
    assert result.fields[0]['numeric']['n'] == 1
    assert result.fields[0]['issue_counts']['formula'] == 1
    assert result.issues('error', 1, 1)[1][0]['value'] == '#DIV/0!'


def test_prepared_rectangle_preserves_rows_columns_and_empty_rows():
    value = PreparedSheet(index=0, name='Data', data_range='C5:F40', merged_ranges=[],
        fields=[PreparationField(column=c, name=f'Field {c}', unit=PreparationUnit(status='confirmed', value='mg')) for c in range(3, 7)],
        cells=[PreparedCell(row=r, column=3, coordinate=f'C{r}', kind='number', value=str(r)) for r in (5, 27, 40)])
    result = scan(value)
    assert result.record_count == 36 and result.blank_row_count == 33
    assert [f['column'] for f in result.fields] == [3, 4, 5, 6]
    assert result.fields[0]['unit'] == {'status': 'confirmed', 'value': 'mg'}
    total, items = result.issues('missing', 3, 2)
    assert total == 33 and [i['row'] for i in items] == list(range(26, 27)) + list(range(28, 40))


def test_sparse_100000_by_256_does_not_materialize_matrix():
    # Only three stored cells; omitted cells must contribute to missing counts.
    cells = [SimpleNamespace(row=1, column=256, kind='text', value='Last'),
        SimpleNamespace(row=2, column=256, kind='number', value='1'),
        SimpleNamespace(row=100000, column=256, kind='number', value='2')]
    started = perf_counter()
    result = scan(SimpleNamespace(name='Sparse', cells=cells))
    elapsed = perf_counter() - started
    assert result.record_count == 99999 and result.blank_row_count == 99997
    assert result.fields[-1]['missing_count'] == 99997
    assert len(result.issues('missing', 256, 5000)[1]) == 17
    assert elapsed < 5
    print(f'sparse rows=100000 columns=256 stored_cells=3 scan_seconds={elapsed:.6f}')


def test_high_cardinality_categories_do_not_truncate_statistics():
    value = SimpleNamespace(name='Distinct', cells=[SimpleNamespace(row=1, column=1, kind='text', value='Label')] +
        [SimpleNamespace(row=r, column=1, kind='text', value=f'label-{r}') for r in range(2, 10002)])
    started = perf_counter()
    result = scan(value)
    elapsed = perf_counter() - started
    assert result.fields[0]['distinct_count'] == 10000
    assert result.fields[0]['categories']['other_count'] == 9990
    assert result.duplicate_rows == 0 and elapsed < 5
    print(f'high_cardinality rows=10000 columns=1 stored_cells=10001 scan_seconds={elapsed:.6f}')
