import csv
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def selection(**overrides):
    return SimpleNamespace(**(dict(contrast_id='ab', q_column='q_within_contrast', q_threshold=0.05,
                                   minimum_absolute_effect=1.0, direction='both') | overrides))


def saved_row(feature_id, effect, q, **overrides):
    return dict(row_key=f'ab:{feature_id}', contrast_id='ab', numerator='A', denominator='B',
                feature_id=feature_id, symbol='gene', tested='True', test_status='tested',
                effect_value=effect, effect_name='log2_fold_change', effect_unit='log2',
                q_within_contrast=q, q_global_family='0.2', original_method_adjustment='',
                inference_scope='sample_inference', observation_level='sample',
                provenance='system_computed') | overrides


@pytest.mark.parametrize(('row', 'expected'), [
    (saved_row('zero_q', '1', '0'), 'up'),
    (saved_row('zero_effect', '-0.0', '0'), 'not_significant'),
    (saved_row('boundary', '-1', '0.05'), 'down'),
    (saved_row('excluded', '5', '0', tested='False', test_status='excluded'), 'excluded'),
    (saved_row('failed_model', '5', '0', test_status='not_computable'), 'not_computable'),
    (saved_row('missing_q', '5', 'NA'), 'missing_metric'),
    (saved_row('missing_effect', '', '0'), 'missing_metric'),
    (saved_row('non_finite_effect', 'inf', '0'), 'missing_metric'),
])
def test_fixed_row_class_preserves_zero_na_and_test_status(row, expected):
    from app.domain.bio_insights import bulk_results

    assert hasattr(bulk_results, 'bulk_row_class')
    assert bulk_results.bulk_row_class(row, selection(minimum_absolute_effect=0.0, direction='up')) == expected


def test_bulk_selection_uses_only_its_frozen_q_column_and_stable_tie_breaker():
    from app.domain.bio_insights import bulk_results

    rows = [saved_row('C', '-2', '0'), saved_row('B', '4', '0'),
            saved_row('A', '4', '0'), saved_row('D', '8', '0.01')]
    assert [row['feature_id'] for row in sorted(rows, key=lambda row: bulk_results.bulk_rank_key(row, selection()))] == [
        'A', 'B', 'C', 'D']
    assert bulk_results.bulk_row_class(rows[0], selection(q_column='q_global_family')) == 'not_significant'
    assert bulk_results.bulk_row_class(rows[0], selection(q_column='original_method_adjustment')) == 'missing_metric'


def test_reviewed_bulk_gate_requires_the_saved_kind_mode_and_model_marker():
    from app.domain.bio_insights import bulk_results

    plan = dict(mode='bulk_counts', bulk_model='shared_wald_v1')
    assert bulk_results.is_reviewed_bulk(dict(kind='comparison', plan_config=plan))
    assert not bulk_results.is_reviewed_bulk(dict(kind='candidate', plan_config=plan))
    assert not bulk_results.is_reviewed_bulk(dict(kind='comparison', plan_config={'mode': 'bulk_counts'}))
    assert not bulk_results.is_reviewed_bulk(dict(kind='comparison', plan_config=plan | {'mode': 'continuous'}))


def write_comparisons(path):
    rows = [saved_row('gC', '-2', '0'),
            saved_row('gB', '2', '0'),
            saved_row('gA', '2', '0'),
            saved_row('gNA', '3', 'NA', symbol='Missing Q'),
            saved_row('gZ', '0', '0.04'),
            saved_row('gExcluded', '', '', tested='False', test_status='excluded'),
            saved_row('gFail', '', '', test_status='not_computable'),
            saved_row('gA', '-2', '0', contrast_id='ba', row_key='ba:gA', numerator='B', denominator='A')]
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, rows[0].keys(), delimiter='\t')
        writer.writeheader()
        writer.writerows(rows)
    return rows


def test_fixed_comparison_page_summarizes_all_contrasts_before_search_or_pagination(tmp_path):
    from app.domain.bio_insights import bulk_results

    path = tmp_path / 'comparison_results.tsv'
    write_comparisons(path)
    contrasts = {'ab': ('A', 'B'), 'ba': ('B', 'A')}
    result = bulk_results.bulk_comparison_page(path, contrasts, selection(), subset='all',
                                               page=1, page_size=1, search='missing q')
    assert result['total'] == 7 and result['matched_total'] == 1
    assert result['items'][0]['q_within_contrast'] == 'NA'
    assert result['feature_matches'] == []
    assert result['contrasts'] == [
        dict(contrast_id='ab', numerator='A', denominator='B', total=7, tested=6,
             excluded=1, not_computable=1, missing_metric=1, deg=3, up=2, down=1),
        dict(contrast_id='ba', numerator='B', denominator='A', total=1, tested=1,
             excluded=0, not_computable=0, missing_metric=0, deg=1, up=0, down=1),
    ]


def test_threshold_pages_sort_globally_and_cross_lookup_uses_exact_stable_id(tmp_path):
    from app.domain.bio_insights import bulk_results

    path = tmp_path / 'comparison_results.tsv'
    rows = write_comparisons(path)
    contrasts = {'ab': ('A', 'B'), 'ba': ('B', 'A')}
    def query(subset, page=1, search=None):
        return bulk_results.bulk_comparison_page(path, contrasts, selection(), subset=subset,
                                                 page=page, page_size=2, search=search)

    first = query('deg')
    second = query('deg', page=2)
    assert first['matched_total'] == second['matched_total'] == 3
    assert first['items'] + second['items'] == [rows[2], rows[1], rows[0]]
    assert query('all')['items'] == rows[:2]
    assert query('up')['items'] == [rows[2], rows[1]]
    assert query('down')['items'] == rows[:1]
    assert query('down', search='gA')['feature_matches'] == [rows[2], rows[7]]
    assert query('down', search='gA')['matched_total'] == 0
    assert query('all', search='GA')['feature_matches'] == []
