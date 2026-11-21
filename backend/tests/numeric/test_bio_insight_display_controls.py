import json

from matplotlib import pyplot as plt
from PIL import Image
import pytest

from app.adapters.bio_engine.manifest import Writer
from app.adapters.bio_insights_engine.figures import _enrichment, _volcano
from app.adapters.bio_insights_engine.topic_figures import draw_topic
from app.domain.bio_insights.contracts import FigureConfig
from app.domain.bio_insights.single_cell_composition_contracts import SingleCellCompositionConfig
from app.domain.bio_insights.single_cell_topic_contracts import SingleCellTopicConfig
from test_bio_insight_figures import fixture, member


def test_redraw_composition_from_frozen_tables_without_model_or_cells(tmp_path):
    from app.adapters.bio_insights_engine.figures import run_figure

    counts = b'unit_id\tcategory\tlabel_id\tcell_count\tdenominator_cells\tproportion\nu1\tlabel\tT\t1\t4\t0.25\nu1\tunknown\t\t3\t4\t0.75\n'
    source=dict(source_id='r', source_kind='bio_insight_result_version', sha256='a'*64,
        metadata=dict(kind='comparison', plan_config=dict(kind='comparison',schema_version=5, method='single_cell_composition')),
        members=dict(composition_counts=member(tmp_path,'counts','tsv',counts),
                     composition_units=member(tmp_path,'units','tsv',b'unit_id\tdonor\tcondition\nu1\tD1\tcontrol\n'),
                     composition_methods=member(tmp_path,'methods','json',b'{"label_names":{"T":"T cells"}}')))
    config=FigureConfig(figure_type='single_cell_composition',result_source_id='r',width_inches=4.,height_inches=3.,dpi=100,formats=['png'])
    output=tmp_path/'render';output.mkdir()
    result=run_figure(dict(config=config.model_dump(mode='json'),sources=[source]),Writer(output))
    with Image.open(output/'figure_png.png') as image:
        assert image.size==(400,300)
    data=json.loads((output/'plot_data.json').read_bytes())
    assert [row['proportion'] for row in data['rows']]==['0.25','0.75']
    assert data['label_names']=={'T':'T cells'}
    assert result['methods']['analysis_recomputed'] is False
    assert (tmp_path/'counts.tsv').read_bytes()==counts
    source['metadata']['plan_config']['schema_version']=1
    with pytest.raises(ValueError, match='composition_figure_source_mismatch'):
        run_figure(dict(config=config.model_dump(mode='json'),sources=[source]),Writer(output))


def test_cellchat_color_scale_uses_user_palette_with_legacy_viridis_default(tmp_path):
    from matplotlib.colors import to_hex

    data = dict(method='cellchat', labels=['A','B'], label_names={}, rows=[
        dict(sender='A',receiver='B',unit_id='1',probability=0.4)])
    source = dict(source_id='r',sha256='a'*64, metadata=dict(kind='integration',plan_config=dict(schema_version=2,method='cellchat')),
        members=dict(topic_plot_data=member(tmp_path,'cellchat','json',json.dumps(data).encode())))
    fig, ax = plt.subplots()
    try:
        old = FigureConfig(figure_type='topic_cellchat',result_source_id='r')
        draw_topic(fig, ax, source, old, False)
        assert ax.images[0].cmap.name == 'viridis'
        ax.clear()
        new = FigureConfig(figure_type='topic_cellchat',result_source_id='r',cellchat_colormap='custom',palette=['#000000','#abcdef'])
        draw_topic(fig, ax, source, new, False)
        assert to_hex(ax.images[0].cmap(1.0)) == '#abcdef'
        assert ax.images[0].get_array()[0,1] == .4
    finally:
        plt.close(fig)


def test_volcano_changes_coloring_and_line_only(tmp_path):
    payload = fixture(tmp_path)
    source = payload['sources'][0]
    old = FigureConfig.model_validate(payload['config'])
    new = FigureConfig.model_validate({**payload['config'], 'q_threshold': 0, 'minimum_absolute_effect': 2})
    fig, ax = plt.subplots()
    try:
        original, _ = _volcano(fig, ax, source, old, False)
        ax.clear()
        plot, _ = _volcano(fig, ax, source, new, False)
        assert plot['rows'] == original['rows']
        assert plot['thresholds'] == {'q': 0, 'absolute_effect': 2}
        assert list(ax.lines[0].get_ydata()) == [300, 300]
        assert ax.get_legend_handles_labels()[1] == ['numerator higher', 'other']
    finally:
        plt.close(fig)


@pytest.mark.parametrize('order', [None, 'adjusted_metric_term_id'])
def test_enrichment_threshold_displays_only_matching_rows(tmp_path, order):
    source = fixture(tmp_path)['sources'][0]
    source['metadata']['kind'] = 'ora'
    source['members']['enrichment_results'] = member(tmp_path, 'enrichment', 'tsv',
        b'row_key\tterm_id\tq_value\tgene_ratio\n1\tA\t0.02\t0.4\n2\tB\t0.2\t0.6\n')
    fig, ax = plt.subplots()
    try:
        config = FigureConfig(figure_type='enrichment', result_source_id='r', enrichment_order=order, q_threshold=0.02)
        plot, empty = _enrichment(fig, ax, source, config, False)
        assert not empty and plot['displayed_row_keys'] == ['1'] and len(plot['rows']) == 2
        assert plot['q_threshold'] == .02
    finally:
        plt.close(fig)


def test_original_single_cell_png_sizes_and_default_wire(tmp_path):
    from app.adapters.bio_insights_engine import single_cell_topics, single_cell_composition

    size = dict(width_inches=4, height_inches=3, dpi=100)
    source = dict(processed_source_id='p', root_cluster='1', root_basis='root', method='slingshot')
    assert 'plot_size' not in SingleCellTopicConfig(**source).model_dump()
    topic = SingleCellTopicConfig(**source, plot_size=size)
    with pytest.raises(ValueError):
        SingleCellTopicConfig(**source, plot_size={**size, 'width_inches': 20, 'dpi': 600})
    data = dict(method='slingshot', coordinates=[[0, 0]], clusters=['1'], lineage_ids=[], curves=[],
                representation='pca', root='1')
    writer = Writer(tmp_path)
    single_cell_topics._plot(data, writer, topic)
    comp = dict(processed_source_id='p', annotation_source_id='a', label_ids=['T'], numerator='n', denominator='d')
    assert 'plot_size' not in SingleCellCompositionConfig(**comp).model_dump()
    config = SingleCellCompositionConfig(**comp, plot_size=size)
    single_cell_composition._plot(dict(units=[dict(unit_id='x', donor='d', condition='n')],
        categories=[('label', 'T')], counts=[dict(unit_id='x', category='label', label_id='T', proportion=1.)]),
        writer, {'T':'T'}, config)
    for name in ('topic_plot', 'composition_plot'):
        with Image.open(tmp_path / (name + '.png')) as image:
            assert image.size == (400, 300) and image.info['dpi'][0] == pytest.approx(100, abs=.01)


def test_genie3_redraw_uses_complete_frozen_table_on_explicit_top_n(tmp_path):
    rows = [dict(regulator='TF', target='gene'+str(i), weight=1/i, stability_weight=1/i) for i in range(1, 24)]
    preview = dict(method='genie3', rows=rows[:20])
    fields = list(rows[0])
    table = '\n'.join(['\t'.join(fields), *['\t'.join(str(r[k]) for k in fields) for r in rows]])
    source = dict(source_id='r', sha256='a'*64, metadata=dict(kind='integration',plan_config=dict(schema_version=2, method='genie3')),
        members=dict(topic_plot_data=member(tmp_path, 'preview', 'json', json.dumps(preview).encode()),
                     regulation_results=member(tmp_path, 'edges', 'tsv', table.encode())))
    fig, ax = plt.subplots()
    try:
        config = FigureConfig(figure_type='topic_genie3', result_source_id='r', regulation_top_n=22)
        data, _ = draw_topic(fig, ax, source, config, False)
        assert len(ax.get_yticklabels()) == len(data['rows']) == 22
        assert data['rows'][-1]['target'] == 'gene22'
        ax.clear()
        historical = FigureConfig(figure_type='topic_genie3', result_source_id='r', top_n=30)
        old, _ = draw_topic(fig, ax, source, historical, False)
        assert old['rows'] == preview['rows'] and len(ax.get_yticklabels()) == 20
    finally:
        plt.close(fig)
