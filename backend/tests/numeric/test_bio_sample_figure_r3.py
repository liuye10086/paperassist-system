import builtins
import hashlib

import pytest
import matplotlib

matplotlib.use('Agg')

from test_bio_insight_figures import fixture


def test_ranked_sample_features_do_not_import_renderer(tmp_path, monkeypatch):
    from app.adapters.bio_insights_engine.quantitative_figures import selected_features
    from app.domain.bio_insights.contracts import FigureConfig
    payload = fixture(tmp_path)
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == 'figures' or name.startswith('matplotlib'):
            raise ModuleNotFoundError('parent has no plotting dependency')
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', guarded)
    assert selected_features(payload['sources'][0], FigureConfig.model_validate(payload['config'])) == ['G1', 'G2', 'G3']


@pytest.mark.parametrize('zh', [True, False])
@pytest.mark.parametrize('effect,expected', [('mean_difference', ('均值差', 'Mean difference')), ('effect_log2fc', ('log2倍数变化', 'log2 fold change')), ('rank_biserial', ('秩二列效应', 'Rank-biserial effect'))])
def test_sample_volcano_labels_preserve_plot_data(tmp_path, zh, effect, expected):
    from matplotlib import pyplot as plt
    from app.adapters.bio_insights_engine.figures import _volcano
    from app.domain.bio_insights.contracts import FigureConfig
    payload = fixture(tmp_path)
    source = payload['sources'][0]
    path = source['members']['comparison_results']['path']
    from pathlib import Path
    content = Path(path).read_text().replace('effect_log2_normalized', effect).replace('log2 ratio', 'original unit')
    Path(path).write_text(content)
    raw = Path(path).read_bytes()
    source['members']['comparison_results'].update(sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
    config = FigureConfig.model_validate(payload['config'])
    fig, ax = plt.subplots()
    old_data, _ = _volcano(fig, ax, source, config, zh)
    assert ax.get_xlabel() == 'original unit'
    assert ax.get_legend_handles_labels()[1] == ['numerator higher', 'denominator higher']
    plt.close(fig)
    source['metadata']['plan_config'] = {'kind': 'comparison', 'schema_version': 2}
    fig, ax = plt.subplots()
    new_data, _ = _volcano(fig, ax, source, config, zh)
    assert new_data == old_data
    label = ax.get_xlabel()
    assert expected[0 if zh else 1] in label and 'original unit' in label
    assert ('A/B' if effect == 'effect_log2fc' else 'A - B' if effect == 'mean_difference' else 'A' ) in label
    assert ax.get_legend_handles_labels()[1] == (['A较高', 'B较高'] if zh else ['A higher', 'B higher'])
    plt.close(fig)


@pytest.mark.parametrize('zh', [True, False])
def test_sample_volcano_first_untestable_feature_does_not_erase_effect_axis(tmp_path, zh):
    from pathlib import Path
    from matplotlib import pyplot as plt
    from app.adapters.bio_insights_engine.figures import _volcano
    from app.domain.bio_insights.contracts import FigureConfig
    payload = fixture(tmp_path)
    source = payload['sources'][0]
    member = source['members']['comparison_results']
    path = Path(member['path'])
    content = path.read_text().replace('2\teffect_log2_normalized\tlog2 ratio\t0\t', '\t\t\t\t', 1)
    content = content.replace('effect_log2_normalized', 'mean_difference').replace('log2 ratio', 'AU')
    path.write_text(content)
    raw = path.read_bytes()
    member.update(sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
    config = FigureConfig.model_validate(payload['config'])
    fig, ax = plt.subplots()
    old_data, _ = _volcano(fig, ax, source, config, zh)
    plt.close(fig)
    source['metadata']['plan_config'] = {'kind': 'comparison', 'schema_version': 2}
    fig, ax = plt.subplots()
    data, _ = _volcano(fig, ax, source, config, zh)
    assert data == old_data and len(data['rows']) == 3
    assert data['rows'][0]['effect_value'] is None and data['rows'][0]['q_value'] is None
    assert ('均值差' if zh else 'Mean difference') in ax.get_xlabel()
    assert '(A - B)' in ax.get_xlabel() and 'AU' in ax.get_xlabel()
    plt.close(fig)


@pytest.mark.parametrize('zh', [True, False])
def test_sample_volcano_explains_double_color_threshold_without_changing_points(tmp_path, zh):
    from pathlib import Path
    from matplotlib import pyplot as plt
    from app.adapters.bio_insights_engine.figures import _volcano
    from app.domain.bio_insights.contracts import FigureConfig
    payload = fixture(tmp_path)
    source = payload['sources'][0]
    member = source['members']['comparison_results']
    header = 'row_key\tfeature_id\tcontrast_id\tnumerator\tdenominator\teffect_value\teffect_name\teffect_unit\tq_within_contrast\n'
    values = [('positive', '1', '.05'), ('negative', '-1', '.05'), ('small', '.99', '.05'), ('large_q', '2', '.051'), ('zero', '0', '0'), ('missing', '', '')]
    text = header + ''.join(f'{key}\t{key}\tc\tA\tB\t{effect}\tmean_difference\toriginal unit\t{q}\n' for key, effect, q in values)
    raw = text.encode();Path(member['path']).write_bytes(raw)
    member.update(sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
    config = FigureConfig.model_validate(payload['config'])
    def capture(ax):
        return [(item.get_offsets().tolist(), item.get_facecolors().tolist()) for item in ax.collections]
    fig, ax = plt.subplots()
    before, _ = _volcano(fig, ax, source, config, zh)
    colors = capture(ax)
    assert ax.get_legend().get_title().get_text() == ''
    assert ax.get_legend_handles_labels()[1] == ['numerator higher', 'denominator higher', 'other']
    plt.close(fig)
    source['metadata']['plan_config'] = {'kind': 'comparison', 'schema_version': 2}
    fig, ax = plt.subplots()
    after, _ = _volcano(fig, ax, source, config, zh)
    assert after == before and capture(ax) == colors
    assert [len(points) for points, _ in colors] == [1, 1, 3]
    assert after['rows'][-1]['effect_value'] is None and after['rows'][-2]['q_value'] == 0
    assert after['thresholds'] == {'q': .05, 'absolute_effect': 1}
    title = ax.get_legend().get_title().get_text()
    assert 'q <= 0.05' in title and ('且 |效应| >= 1' if zh else 'and |effect| >= 1') in title
    assert ('效应单位同横轴' if zh else 'effect unit as on x-axis') in title.replace('\n', ' ')
    assert ax.get_legend_handles_labels()[1][-1].replace('\n', ' ') == ('未同时满足阈值' if zh else 'Does not meet both thresholds')
    plt.close(fig)


def test_small_sample_legend_uses_actual_geometry_to_avoid_hiding_points():
    from matplotlib import pyplot as plt
    from app.adapters.bio_insights_engine import figures
    fig, ax = plt.subplots(figsize=(4, 3))
    ax.set(xlim=(0, 1), ylim=(0, 1))
    points = ax.scatter([.9, .8, .75], [.9, .85, .75], label='Does not meet both\nthresholds')
    legend = ax.legend(loc='upper right', title='q <= 0.05\nand |effect| >= 1', fontsize=7, title_fontsize=7)
    fig.tight_layout();fig.canvas.draw()
    positions = points.get_offset_transform().transform(points.get_offsets())
    assert any(legend.get_window_extent().contains(*point) for point in positions)
    before = points.get_offsets().tolist()
    figures._place_small_sample_volcano_legend(fig, ax)
    fig.canvas.draw()
    box = legend.get_window_extent()
    assert not any(box.contains(*point) for point in positions)
    assert ax.bbox.contains(box.x0, box.y0) and ax.bbox.contains(box.x1, box.y1)
    assert points.get_offsets().tolist() == before
    plt.close(fig)
