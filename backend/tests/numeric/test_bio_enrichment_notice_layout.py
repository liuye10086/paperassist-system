"""Enrichment significance notices must remain readable outside the data area."""
import copy
import json

import pytest
from PIL import Image

from test_bio_insight_figures import fixture, member


@pytest.mark.parametrize('language', ['en', 'zh-CN'])
@pytest.mark.parametrize('style', ['dot', 'bar'])
@pytest.mark.parametrize('kind', ['ora', 'gsea_prerank'])
@pytest.mark.parametrize('significant', [False, True])
def test_enrichment_notice_is_readable_and_preserves_data(tmp_path, monkeypatch, language, style, kind, significant):
    from app.adapters.bio_insights_engine import figures
    from app.adapters.bio_engine.manifest import Writer

    payload = fixture(tmp_path, 'enrichment')
    source = payload['sources'][0]
    source['metadata'].update(kind=kind, inference_scope='derived',
        upstream_inference_scopes=['spot_exploratory'], data_driven_grouping=True)
    q_column = 'fdr_q_value' if kind == 'gsea_prerank' else 'q_value'
    value_column = 'nes' if kind == 'gsea_prerank' else 'gene_ratio'
    q = '0' if significant else '0.5'
    text = f'row_key\tterm_id\tterm_name\tcontrast_id\t{value_column}\t{q_column}\tk\n'
    text += f'T1\tGO:1\tTest term\tc\t0.2\t{q}\t2\n'
    source['members']['enrichment_results'] = member(tmp_path, 'enrichment_results', 'tsv', text.encode())
    payload['config'].update(output_language=language, enrichment_style=style,
        title='CR-B04 enrichment', width_inches=7, height_inches=5, dpi=100,
        formats=['png', 'tiff', 'svg'])
    original = copy.deepcopy(payload)
    seen = []
    close = figures.plt.close
    monkeypatch.setattr(figures.plt, 'close', lambda figure: seen.append(figure))
    output = tmp_path / 'out'
    output.mkdir()
    try:
        result = figures.run_figure(payload, Writer(output))
        figure = seen[-1]
        figure.canvas.draw()
        renderer = figure.canvas.get_renderer()
        axis = figure.axes[0]
        notice = 'q ≤ 0.05 无显著条目' if language == 'zh-CN' else 'No terms with q ≤ 0.05'
        scope = '空间探索; 数据驱动分组' if language == 'zh-CN' else 'Spot exploratory; data-driven grouping'
        texts = [t for t in [axis.title, *axis.texts, *figure.texts] if t.get_visible() and t.get_text()]
        matching = [t for t in texts if notice in t.get_text()]
        if significant:
            assert not matching, 'Significant results must not display the no-significance notice'
            assert axis.get_title() == 'CR-B04 enrichment\n' + scope
        else:
            assert len(matching) == 1, 'The no-significance notice must appear exactly once'
            annotation = matching[0]
            bounds = annotation.get_window_extent(renderer)
            for other in texts:
                if other is not annotation:
                    assert not bounds.overlaps(other.get_window_extent(renderer)), (
                        'No-significance notice overlaps the title or scope text')
            assert notice in annotation.get_text().splitlines(), 'Notice requires its own complete text line'
            assert annotation.get_fontsize() >= 8
        assert 'CR-B04 enrichment' in axis.get_title().splitlines()
        assert scope in axis.get_title().splitlines(), 'Scientific scope must remain unmodified and visible'
        for text_artist in texts:
            bounds = text_artist.get_window_extent(renderer)
            assert bounds.x0 >= 0 and bounds.y0 >= 0
            assert bounds.x1 <= figure.bbox.width and bounds.y1 <= figure.bbox.height
            assert not bounds.overlaps(axis.get_window_extent(renderer)), 'Header must not cover data points'
        data = json.loads((output / 'plot_data.json').read_text())
        assert data['rows'] == [dict(row_key='T1', term_id='GO:1', term_name='Test term',
            contrast_id='c', **{value_column: '0.2', q_column: q}, k='2')]
        assert data['displayed_row_keys'] == ['T1'] and data['q_column'] == q_column
        assert data['style'] == style
        assert result['methods']['raw_values_unchanged'] is True
        assert result['methods']['analysis_recomputed'] is False
        assert result['methods']['upstream_inference_scopes'] == ['spot_exploratory']
        assert result['methods']['data_driven_grouping'] is True
        assert result['summary']['empty_result'] is False
        assert payload == original
        with Image.open(output / 'figure_png.png') as image:
            assert image.size == (700, 500), 'Requested physical size and DPI must be preserved'
    finally:
        monkeypatch.setattr(figures.plt, 'close', close)
        for figure in seen:
            if hasattr(figure, 'canvas'):
                close(figure)


@pytest.mark.parametrize('language', ['en', 'zh-CN'])
@pytest.mark.parametrize('style', ['dot', 'bar'])
def test_empty_enrichment_keeps_its_existing_message_without_significance_notice(tmp_path, monkeypatch, language, style):
    from app.adapters.bio_insights_engine import figures
    from app.adapters.bio_engine.manifest import Writer

    payload = fixture(tmp_path, 'enrichment')
    payload['sources'][0]['metadata'].update(kind='ora', inference_scope='derived')
    payload['sources'][0]['members']['enrichment_results'] = member(tmp_path, 'enrichment_results', 'tsv',
        b'row_key\tterm_id\tterm_name\tcontrast_id\tgene_ratio\tq_value\tk\n')
    payload['config'].update(output_language=language, enrichment_style=style, formats=['png'])
    output = tmp_path / 'out'
    output.mkdir()
    seen = []
    close = figures.plt.close
    monkeypatch.setattr(figures.plt, 'close', lambda figure: seen.append(figure))
    try:
        result = figures.run_figure(payload, Writer(output))
        axis = seen[-1].axes[0]
        message = '没有可计算的富集条目' if language == 'zh-CN' else 'No computable enrichment terms'
        assert [text.get_text() for text in axis.texts] == [message]
        assert len(axis.get_title().splitlines()) == 2
        assert result['summary']['empty_result'] is True
        assert json.loads((output / 'plot_data.json').read_text())['rows'] == []
    finally:
        monkeypatch.setattr(figures.plt, 'close', close)
        for figure in seen:
            if hasattr(figure, 'canvas'):
                close(figure)
