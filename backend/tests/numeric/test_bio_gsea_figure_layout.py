"""GSEA scientific annotations must not obscure positive or negative curves."""
import copy
import json

import pytest

from test_bio_insight_figures import fixture, member


@pytest.mark.parametrize('language', ['en', 'zh-CN'])
@pytest.mark.parametrize('negative', [False, True])
@pytest.mark.parametrize('size', [(7, 5), (2, 2)])
def test_gsea_annotation_outside_plot_and_empirical_zero_preserved(tmp_path, monkeypatch, language, negative, size):
    from app.adapters.bio_insights_engine import figures
    from app.adapters.bio_engine.manifest import Writer

    payload = fixture(tmp_path)
    payload['config'].update(figure_type='gsea', term_row_key='T1', output_language=language,
                             formats=['png', 'svg'], width_inches=size[0], height_inches=size[1])
    source = payload['sources'][0]
    source['metadata'].update(kind='gsea_prerank', inference_scope='derived',
                              upstream_inference_scopes=['spot_exploratory'], data_driven_grouping=True)
    ranking = b'rank\tfeature_id\tstatistic\n0\tG1\t3\n1\tG2\t2\n2\tG3\t-1\n3\tG4\t-2\n'
    term = dict(row_key='T1', term_id='GO:0022626', hit_indices=[2, 3] if negative else [0, 1],
                weight=1, es=-1 if negative else 1, nes=-5.061925 if negative else 5.061925,
                fdr_q_value=0, nominal_p_value=0, fwer_p_value=0)
    source['members']['gsea_ranking'] = member(tmp_path, 'gsea_ranking', 'tsv', ranking)
    source['members']['gsea_curves'] = member(tmp_path, 'gsea_curves', 'json', json.dumps(
        dict(rank_zero_based=True, rank_member_key='gsea_ranking', terms=[term])).encode())
    original = copy.deepcopy(payload)
    figures_seen = []
    close = figures.plt.close
    monkeypatch.setattr(figures.plt, 'close', lambda fig: figures_seen.append(fig))
    output = tmp_path / 'out'
    output.mkdir()
    try:
        figures.run_figure(payload, Writer(output))
        fig = figures_seen[-1]
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        axes = fig.axes[0]
        texts = [text for text in [*axes.texts, *fig.texts] if text.get_text()]
        annotation = next(text for text in texts if 'GO:0022626' in text.get_text())
        assert not annotation.get_window_extent(renderer).overlaps(axes.get_window_extent(renderer))
        zero_note = next((text for text in texts if ('empirical' in text.get_text().lower()
                                                    or '经验置换' in text.get_text())), None)
        assert zero_note is not None, 'Zero empirical FDR needs its interpretation on the standalone figure'
        for text in (annotation, zero_note):
            bounds = text.get_window_extent(renderer)
            assert not bounds.overlaps(axes.get_window_extent(renderer))
            assert bounds.x0 >= 0 and bounds.y0 >= 0
            assert bounds.x1 <= fig.bbox.width and bounds.y1 <= fig.bbox.height
        assert not annotation.get_window_extent(renderer).overlaps(zero_note.get_window_extent(renderer))
        assert not annotation.get_window_extent(renderer).overlaps(axes.title.get_window_extent(renderer))
        assert not zero_note.get_window_extent(renderer).overlaps(axes.xaxis.label.get_window_extent(renderer))
        data = json.loads((output / 'plot_data.json').read_text())
        assert data['term'] == term
        assert data['running_enrichment'] == figures.running_enrichment([3, 2, -1, -2], term['hit_indices'], 1, term['es'])
        assert payload == original
    finally:
        monkeypatch.setattr(figures.plt, 'close', close)
        for figure in figures_seen:
            if hasattr(figure, 'canvas'):
                close(figure)
