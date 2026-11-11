import json
import numpy as np
import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    """The figure worker tests use local frozen members only."""


def _source(root, kind, metadata, writer):
    return dict(source_id=root.name, sha256='a'*64, source_kind=kind, metadata=metadata,
                members={member['key']: member for member in writer.artifacts})


@pytest.fixture
def comparison(tmp_path):
    from app.adapters.bio_engine.manifest import Writer

    root = tmp_path / 'comparison'
    root.mkdir()
    writer = Writer(root)
    direction = dict(contrast_id='AB', numerator='A', denominator='B')
    reverse = dict(contrast_id='BA', numerator='B', denominator='A')
    samples = [dict(processed_version_id='b03', sample_id=sample, condition=group,
                    biological_unit_id=sample, batch='batch', donor=sample)
               for sample, group in [('b1', 'B'), ('a1', 'A'), ('c1', 'C'), ('b2', 'B'), ('a2', 'A')]]
    writer.json('comparison_design', dict(
        actual_units=[{**d, 'n_numerator': 2, 'n_denominator': 2} for d in (direction, reverse)],
        bulk_model=dict(method='shared_wald_v1', contrasts=[direction, reverse], samples=samples)))
    unit_ids = [f'unit{i}' for i in range(len(samples))]
    writer.table('model_sample_metadata', [dict(model_id='model', unit_id=unit, **sample)
                                            for unit, sample in zip(unit_ids, samples)])
    effects = [3., -2., 2., .5, None, -4., 0.]
    within = [0., .01, .01, .1, None, None, .001]
    native = [0., .02, .02, None, None, None, .01]
    raw_values = [(1, 3, 1e4, 1, 5), (1, None, 2e4, 5, 3), (5, 5, 3e4, 5, 5),
                  (4, 3, 4e4, 6, 3), (20, 1, 5e4, 50, 10), (1, 1, 6e4, 1, 1),
                  (1, 1, 7e4, 1, 1)]
    order = [2, 0, 6, 3, 1, 5, 4]
    writer.table('model_normalized_counts', [dict(model_id='model', feature_id=f'G{i+1}', **dict(zip(unit_ids, raw_values[i]))) for i in order])
    result_rows = []
    for comparison_direction, sign in ((direction, 1), (reverse, -1)):
        for i in order:
            status = 'excluded' if i == 4 else 'not_computable' if i == 5 else 'tested'
            result_rows.append(dict(**comparison_direction, row_key=f"{comparison_direction['contrast_id']}-{i+1}",
                feature_id=f'G{i+1}', symbol=f'S{i+1}', effect_value=effects[i] * sign if effects[i] is not None else None,
                effect_name='effect_log2fc', effect_unit='log2 count fold change', base_mean=0 if i == 5 else i+1.,
                p_value=None if within[i] is None else within[i]/2, q_within_contrast=within[i],
                q_global_family=None if within[i] is None else within[i]*2, original_method_adjustment=native[i],
                original_adjustment_reason='independent_filtered_or_undefined_adjustment' if i == 3 else None,
                tested=status != 'excluded', test_status=status, reason=None if status == 'tested' else status,
                n_numerator=2, n_denominator=2))
    writer.table('comparison_results', result_rows)
    contrasts = [dict(contrast_id=d['contrast_id'], groups=[dict(label=d[side]) for side in ('numerator', 'denominator')])
                 for d in (direction, reverse)]
    return _source(root, 'bio_insight_result_version', dict(kind='comparison', provenance='system_computed',
        inference_scope='sample_inference', plan_config=dict(kind='comparison', schema_version=2, mode='bulk_counts',
                                                              bulk_model='shared_wald_v1', contrasts=contrasts)), writer)


def _draw(tmp_path, source, figure_type, *, name='out', **overrides):
    from app.adapters.bio_engine.manifest import Writer
    from app.adapters.bio_insights_engine.figures import run_figure

    output = tmp_path / name
    output.mkdir()
    selection = overrides.pop('selection', {})
    config = dict(kind='figure', result_source_id=source['source_id'], figure_type=figure_type,
                  formats=['png'], dpi=100, width_inches=6, height_inches=4, output_language='en')
    if figure_type not in ('bulk_qc', 'bulk_pca', 'enrichment'):
        config['bulk_selection'] = dict(contrast_id='AB', q_column='q_within_contrast', q_threshold=.05,
                                        minimum_absolute_effect=1., direction='both') | selection
    config.update(overrides)
    payload = dict(config=config, sources=[source])
    writer = Writer(output)
    result = run_figure(payload, writer)
    assert (output / 'figure_png.png').read_bytes().startswith(b'\x89PNG')
    return json.loads((output / 'plot_data.json').read_bytes()), result, payload


def test_b05_volcano_keeps_all_points_zero_q_and_stable_labels(tmp_path, comparison):
    data, result, payload = _draw(tmp_path, comparison, 'bulk_volcano', top_n=2)
    from app.adapters.bio_insights_engine.bulk_figures import validate_bulk_plot

    assert data['direction'] == dict(numerator='A', denominator='B')
    assert data['q_column'] == 'q_within_contrast'
    assert data['displayed_count'] == 5 and data['omitted_count'] == 2
    assert data['labeled_feature_ids'] == ['G1', 'G2']
    rows = {row['feature_id']: row for row in data['rows']}
    assert len(rows) == 7 and rows['G1']['q_value'] == 0 and rows['G1']['display_neg_log10_q'] == 300
    assert rows['G6']['q_value'] is None and rows['G6']['classification'] == 'not_computable'
    assert result['methods']['analysis_recomputed'] is False
    assert {key: result['summary'][key] for key in ('contrast_id', 'numerator', 'denominator', 'requested_top_n', 'displayed_feature_count')} == dict(
        contrast_id='AB', numerator='A', denominator='B', requested_top_n=2, displayed_feature_count=2)
    validate_bulk_plot(payload, data)
    rows['G1']['q_value'] = 1e-300
    with pytest.raises(ValueError, match='bulk_plot_data_mismatch'):
        validate_bulk_plot(payload, data)


def test_b05_ma_retains_plottable_point_missing_selected_q(tmp_path, comparison):
    data, _, _ = _draw(tmp_path, comparison, 'bulk_ma', selection=dict(q_column='original_method_adjustment'))
    rows = {row['feature_id']: row for row in data['rows']}
    assert rows['G4']['base_mean'] == 4 and rows['G4']['effect_value'] == .5
    assert rows['G4']['q_value'] is None and rows['G4']['displayed'] is True
    assert rows['G4']['classification'] == 'missing_metric'
    assert rows['G6']['base_mean'] == 0 and rows['G6']['displayed'] is False
    assert data['displayed_count'] == 5 and data['omitted_count'] == 2


def test_b05_deg_heatmap_uses_frozen_samples_and_keeps_missing_zscore(tmp_path, comparison):
    data, result, _ = _draw(tmp_path, comparison, 'bulk_heatmap', z_score=True, top_n=7)
    assert data['feature_ids'] == ['G1', 'G2', 'G3']
    assert data['requested_top_n'] == 7 and data['selected_feature_count'] == 3
    assert [s['sample_id'] for s in data['samples']] == ['a1', 'a2', 'b1', 'b2']
    assert data['normalized_counts'] == [[3., 5., 1., 1.], [None, 3., 1., 5.], [5., 5., 5., 5.]]
    assert data['display_values'][1][0] is None and data['display_values'][2] == [None]*4
    parameters = {row['feature_id']: row for row in data['z_score_parameters']}
    assert parameters['G2']['mean'] == 3 and parameters['G2']['sample_sd'] == 2 and parameters['G2']['n'] == 3
    assert parameters['G3']['reason'] == 'zero_variance' and parameters['G3']['sample_sd'] == 0
    assert data['missing_count'] == 1 and data['omitted_count'] == 5
    assert result['summary']['displayed_feature_count'] == data['displayed_feature_count'] == 2


def test_b05_zero_deg_is_valid_and_variable_ranking_is_independent(tmp_path, comparison):
    data, result, _ = _draw(tmp_path, comparison, 'bulk_heatmap', name='deg', selection=dict(q_threshold=.001, minimum_absolute_effect=5))
    assert result['methods']['empty_result'] is True and data['feature_ids'] == []
    assert data['empty_reason'] == 'no_selected_degs'
    data, result, _ = _draw(tmp_path, comparison, 'bulk_variable_heatmap', name='variable', top_n=3,
                            selection=dict(q_threshold=.001, minimum_absolute_effect=5, direction='down'))
    assert result['methods']['empty_result'] is False and data['feature_ids'] == ['G5', 'G2', 'G1']
    assert data['ranked_features'][0]['sample_variance'] == pytest.approx(np.var([1, 10, 20, 50], ddof=1))


def test_b05_candidate_expression_and_summary_use_requested_reverse_contrast(tmp_path, comparison):
    selection = dict(contrast_id='BA', q_column='q_global_family', direction='up')
    data, _, _ = _draw(tmp_path, comparison, 'bulk_expression', name='expression', feature_ids=['G2'], selection=selection)
    assert data['direction'] == dict(numerator='B', denominator='A')
    assert [(row['sample_id'], row['normalized_counts']) for row in data['rows']] == [('b1', 1), ('b2', 5), ('a1', None), ('a2', 3)]
    assert data['displayed_count'] == 3 and data['omitted_count'] == 1
    data, _, _ = _draw(tmp_path, comparison, 'bulk_summary', name='summary', selection=selection)
    assert data['counts'] == dict(up=1, down=2, not_significant=2, excluded=1, not_computable=1, missing_metric=0)
    assert data['selected_deg_count'] == 1


@pytest.fixture
def processed(tmp_path):
    from app.adapters.bio_engine.manifest import Writer

    root = tmp_path / 'b03'
    root.mkdir()
    writer = Writer(root)
    samples = ['a1', 'a2', 'b1']
    quantiles = {sample: dict(min=i, q1=i+1, median=i+2, q3=i+3, max=i+4) for i, sample in enumerate(samples)}
    writer.json('qc_missing_data', dict(sample_ids=samples, missing_fraction=[0., 0., .25]))
    writer.json('expression_distribution_data', dict(sample_ids=samples, quantiles=quantiles))
    matrix = [[1., 2., 3.], [4., 5., 6.]]
    selected = dict(sample_ids=['a1', 'b1'], condition=['A', 'B'], batch=['X', 'Y'], layer='analysis', semantic='log1p')
    writer.json('sample_clustering_data', dict(**selected, feature_ids=['G1', 'G2', 'G3'], values=matrix, method='average_euclidean'))
    writer.json('sample_correlation', dict(**selected, values=[[1., .5], [.5, 1.]], method='pearson_complete_features'))
    writer.json('sample_distance', dict(**selected, values=[[0., 2.], [2., 0.]], method='euclidean_complete_features'))
    scores = [[2., -.3], [-2., .3]]
    variance = [.94, .06]
    writer.json('pca_data', dict(**selected, scores=scores, variance_ratio=variance))
    writer.table('pca_scores', [dict(sample_id=sample, pc1=x, pc2=y) for sample, (x, y) in zip(selected['sample_ids'], scores)])
    writer.table('pca_variance_ratio', [dict(component=i, variance_ratio=v) for i, v in enumerate(variance, 1)])
    return _source(root, 'bio_processed_dataset_version', dict(assay='bulk_rna_counts', observation_level='sample'), writer)


@pytest.mark.parametrize(('figure_type', 'panel', 'member', 'field', 'expected'), [
    ('bulk_qc', 'qc_missing', 'qc_missing_data', 'missing_fraction', [0., 0., .25]),
    ('bulk_qc', 'qc_expression', 'expression_distribution_data', 'quantiles',
        {'a1': dict(min=0, q1=1, median=2, q3=3, max=4), 'a2': dict(min=1, q1=2, median=3, q3=4, max=5),
         'b1': dict(min=2, q1=3, median=4, q3=5, max=6)}),
    ('bulk_qc', 'sample_clustering', 'sample_clustering_data', 'values', [[1., 2., 3.], [4., 5., 6.]]),
    ('bulk_qc', 'sample_correlation', 'sample_correlation', 'values', [[1., .5], [.5, 1.]]),
    ('bulk_qc', 'sample_distance', 'sample_distance', 'values', [[0., 2.], [2., 0.]]),
    ('bulk_pca', 'pca_scores', 'pca_scores', 'scores', [[2., -.3], [-2., .3]]),
    ('bulk_pca', 'pca_variance', 'pca_variance_ratio', 'variance_ratio', [.94, .06]),
])
def test_b05_qc_and_pca_reuse_frozen_plot_values(tmp_path, processed, monkeypatch, figure_type, panel, member, field, expected):
    from app.adapters.bio_engine import tabular_assays

    def forbidden(*args, **kwargs):
        pytest.fail('QC or PCA reran while drawing an immutable result')

    monkeypatch.setattr(tabular_assays, 'run_tabular', forbidden)
    monkeypatch.setattr(np.linalg, 'svd', forbidden)
    data, result, payload = _draw(tmp_path, processed, figure_type, bulk_panel=panel)
    from app.adapters.bio_insights_engine.bulk_figures import validate_bulk_plot

    assert data[field] == expected
    assert data['source_members'][member] == processed['members'][member]['sha256']
    assert result['methods']['analysis_recomputed'] is False
    validate_bulk_plot(payload, data)


def test_b05_not_computable_pca_and_clustering_keep_empty_frozen_panels(tmp_path):
    from app.adapters.bio_engine.manifest import Writer

    root = tmp_path / 'unavailable'
    root.mkdir()
    writer = Writer(root)
    for key, column in (('pca_scores', 'sample_id'), ('pca_variance_ratio', 'component'), ('sample_clustering', 'sample_id')):
        writer.table(key, [], [column, 'reason'])
    source = _source(root, 'bio_processed_dataset_version', dict(assay='bulk_rna_counts'), writer)
    for figure_type, panel in (('bulk_pca', 'pca_scores'), ('bulk_pca', 'pca_variance'), ('bulk_qc', 'sample_clustering')):
        data, result, _ = _draw(tmp_path, source, figure_type, name=panel, bulk_panel=panel)
        assert result['summary']['empty_result'] is True
        assert data['empty_reason'] == 'insufficient_complete_nonconstant_features_or_samples'
        assert data['displayed_count'] == 0 and data['omitted_count'] == 0


def test_b05_redraw_changes_image_without_refitting_or_changing_points(tmp_path, comparison, monkeypatch):
    from pydeseq2.dds import DeseqDataSet

    def forbidden(*args, **kwargs):
        pytest.fail('DE model refit while rendering a fixed result')

    monkeypatch.setattr(DeseqDataSet, 'deseq2', forbidden)
    initial, _, _ = _draw(tmp_path, comparison, 'bulk_volcano', name='initial', top_n=1)
    redrawn, _, _ = _draw(tmp_path, comparison, 'bulk_volcano', name='redrawn', top_n=3,
                           width_inches=7, palette=['#808000', '#00ffff'])
    assert redrawn['rows'] == initial['rows']
    assert initial['labeled_feature_ids'] == ['G1'] and redrawn['labeled_feature_ids'] == ['G1', 'G2', 'G3']
    assert (tmp_path / 'initial' / 'figure_png.png').read_bytes() != (tmp_path / 'redrawn' / 'figure_png.png').read_bytes()


def test_b05_coincident_points_keep_ranked_scatter_labels_readable(tmp_path, comparison, monkeypatch):
    from matplotlib.text import Text
    from app.adapters.bio_engine.manifest import Writer
    from app.adapters.bio_insights_engine import figures
    from app.adapters.bio_insights_engine.figure_data import rows

    root = tmp_path / 'coincident'
    root.mkdir()
    writer = Writer(root)
    points = rows(comparison, 'comparison_results')
    for row in points:
        if row['feature_id'] in ('G1', 'G2', 'G3'):
            row.update(effect_value='2', base_mean='5', q_within_contrast='0.01')
    writer.table('comparison_results', points)
    comparison['members']['comparison_results'] = writer.artifacts[0]
    seen = []
    close = figures.plt.close
    monkeypatch.setattr(figures.plt, 'close', lambda figure: seen.append(figure))
    try:
        data, _, _ = _draw(tmp_path, comparison, 'bulk_ma', top_n=3)
        assert data['labeled_feature_ids'] == ['G1', 'G2', 'G3']
        figure = seen[-1]
        axis = figure.axes[0]
        figure.canvas.draw()
        renderer = figure.canvas.get_renderer()
        boxes = [Text.get_window_extent(artist, renderer) for artist in axis.texts if artist.get_text() in data['labeled_feature_ids']]
        assert len(boxes) == 3
        assert all(not left.overlaps(right) for i, left in enumerate(boxes) for right in boxes[i+1:])
    finally:
        for figure in seen:
            if hasattr(figure, 'canvas'):
                close(figure)


def test_b05_enrichment_opt_in_uses_term_id_ties_and_actual_count(tmp_path):
    from app.adapters.bio_engine.manifest import Writer

    root = tmp_path / 'ora'
    root.mkdir()
    writer = Writer(root)
    writer.table('enrichment_results', [dict(row_key=row, term_id=term, q_value=q, gene_ratio=ratio)
        for row, term, q, ratio in [('1', 'Z', .01, .3), ('3', 'A', .01, .5), ('2', '0', .001, None)]])
    source = _source(root, 'bio_insight_result_version', dict(kind='ora'), writer)
    legacy, _, _ = _draw(tmp_path, source, 'enrichment', name='legacy')
    options = dict(top_n=10, enrichment_order='adjusted_metric_term_id')
    selected, _, _ = _draw(tmp_path, source, 'enrichment', name='selected', **options)
    recolored, _, _ = _draw(tmp_path, source, 'enrichment', name='recolored', palette=['#00a040'], **options)
    assert legacy['displayed_row_keys'] == ['1', '3']
    assert selected['displayed_row_keys'] == ['3', '1'] and len(selected['rows']) == 3
    assert selected['displayed_count'] == 2 and selected['requested_top_n'] == 10 and selected['omitted_count'] == 1
    assert recolored == selected
    assert (tmp_path/'recolored'/'figure_png.png').read_bytes() != (tmp_path/'selected'/'figure_png.png').read_bytes()
