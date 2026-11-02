"""UpSet membership columns and scientific labels stay readable on fixed canvases."""
import copy
import json

import pytest

from test_bio_insight_figures import fixture, member


@pytest.fixture
def render_upset(tmp_path, monkeypatch):
    from app.adapters.bio_insights_engine import figures
    from app.adapters.bio_engine.manifest import Writer

    seen = []
    close = figures.plt.close
    monkeypatch.setattr(figures.plt, 'close', lambda figure: seen.append(figure))

    def render(count=3, mode='all', language='en', size=(7, 5), long_labels=False):
        payload = fixture(tmp_path)
        template = payload['sources'][0]
        payload['sources'] = []
        labels = ['forward', 'same-input', 'reverse'] if count == 3 else [f'Set {i + 1}' for i in range(count)]
        if long_labels:
            labels = [label + ' complete descriptive biological comparison label without truncation' for label in labels]
        selections = []
        for i, label in enumerate(labels):
            source = copy.deepcopy(template)
            source['source_id'] = f'r{i}'
            source['metadata'].update(data_driven_grouping=True, upstream_inference_scopes=['spot_exploratory'])
            # The three-set fixture reproduces the actual 74/74/1258 input shape.
            features = ([f'F{j}' for j in range(74)] if i < 2 else [f'R{j}' for j in range(1258)]) if count == 3 else ['shared', f'only{i}']
            content = 'row_key\tfeature_id\tcontrast_id\teffect_value\tq_within_contrast\n'
            content += ''.join(f'{feature}\t{feature}\tc\t2\t0.01\n' for feature in features)
            source['members']['comparison_results'] = member(tmp_path, f'comparison{i}', 'tsv', content.encode())
            payload['sources'].append(source)
            selections.append(dict(result_source_id=source['source_id'], contrast_id='c', label=label))
        payload['config'].update(figure_type='upset', result_source_id='r0',
            result_source_ids=[s['source_id'] for s in payload['sources']], selected_sets=selections,
            intersection_mode=mode, intersection_k=2 if mode == 'at_least_k' else None,
            output_language=language, width_inches=size[0], height_inches=size[1],
            title='CR-B04 figure-upset', formats=['png', 'tiff', 'svg'])
        original = copy.deepcopy(payload)
        output = tmp_path / f'out-{len(seen)}'
        output.mkdir()
        figures.run_figure(payload, Writer(output))
        figure = seen[-1]
        figure.canvas.draw()
        assert payload == original
        return figure, json.loads((output / 'plot_data.json').read_text()), labels, output

    yield render
    monkeypatch.setattr(figures.plt, 'close', close)
    for figure in seen:
        if hasattr(figure, 'canvas'):
            close(figure)


def panels(figure):
    bar = figure.axes[0]
    matrix = next(axis for axis in [*figure.axes[1:], *bar.child_axes] if axis.collections)
    return bar, matrix


def test_upset_does_not_draw_redundant_combination_labels_over_matrix(render_upset):
    figure, _, labels, _ = render_upset()
    bar, matrix = panels(figure)
    assert not any(text.get_visible() and text.get_text() for text in bar.get_xticklabels())
    assert [text.get_text() for text in matrix.get_yticklabels()] == labels


def test_upset_bar_centers_align_with_membership_columns(render_upset):
    figure, data, _, _ = render_upset()
    bar, matrix = panels(figure)
    for patch, collection in zip(bar.patches, matrix.collections):
        bar_x = bar.transData.transform((patch.get_x() + patch.get_width() / 2, 0))[0]
        dot_x = matrix.transData.transform(collection.get_offsets()[0])[0]
        assert bar_x == pytest.approx(dot_x, abs=.01)
    assert [patch.get_height() for patch in bar.patches] == [1258, 74, 74, 74]
    assert [len(row['feature_ids']) for row in data['definitions']] == [74, 74, 1258]
    assert len(data['intersections']) == 7


@pytest.mark.parametrize('language', ['en', 'zh-CN'])
@pytest.mark.parametrize('mode', ['all', 'exclusive', 'at_least_k'])
def test_upset_axis_states_inclusive_or_exclusive_count(render_upset, language, mode):
    figure, data, _, _ = render_upset(mode=mode, language=language)
    expected = ('包容' if mode == 'all' else '互斥') if language == 'zh-CN' else ('inclusive' if mode == 'all' else 'exclusive')
    assert expected in figure.axes[0].get_ylabel().lower()
    assert data['intersection_mode'] == mode
    field = 'inclusive_count' if mode == 'all' else 'exclusive_count'
    displayed = [row for row in data['intersections'] if row[field] and (mode != 'at_least_k' or sum(row['membership']) >= 2)]
    displayed.sort(key=lambda row: (-row[field], row['membership']))
    assert data['displayed_memberships'] == [row['membership'] for row in displayed[:30]]


@pytest.mark.parametrize('language', ['en', 'zh-CN'])
@pytest.mark.parametrize('mode', ['all', 'exclusive', 'at_least_k'])
def test_upset_explains_what_light_membership_dots_mean(render_upset, language, mode):
    figure, _, _, _ = render_upset(mode=mode, language=language)
    text = ' '.join(item.get_text() for item in figure.texts).replace('\n', ' ').lower()
    if mode == 'all':
        for phrase in (['必须属于', '不限定', '可重叠'] if language == 'zh-CN' else ['required', 'unrestricted', 'may overlap']):
            assert phrase in text
    else:
        for phrase in (['属于', '排除'] if language == 'zh-CN' else ['included', 'excluded']):
            assert phrase in text


@pytest.mark.parametrize('language', ['en', 'zh-CN'])
@pytest.mark.parametrize('count,size,long_labels', [(3, (2, 2), False), (2, (7, 5), True), (3, (7, 5), True), (8, (7, 5), True)])
def test_upset_labels_fit_fixed_canvas_without_overlap(render_upset, language, count, size, long_labels):
    from PIL import Image

    figure, _, labels, output = render_upset(count=count, language=language, size=size, long_labels=long_labels)
    bar, matrix = panels(figure)
    renderer = figure.canvas.get_renderer()
    row_labels = matrix.get_yticklabels()
    assert [''.join(text.get_text().split()) for text in row_labels] == [''.join(label.split()) for label in labels]
    texts = [*figure.texts, bar.title, bar.yaxis.label, *bar.get_yticklabels(), *row_labels]
    texts = [text for text in texts if text.get_visible() and text.get_text()]
    for text in texts:
        bounds = text.get_window_extent(renderer)
        assert bounds.x0 >= -.5 and bounds.y0 >= -.5, text.get_text()
        assert bounds.x1 <= figure.bbox.width + .5 and bounds.y1 <= figure.bbox.height + .5, text.get_text()
    for i, first in enumerate(texts):
        for second in texts[i + 1:]:
            assert not first.get_window_extent(renderer).overlaps(second.get_window_extent(renderer)), (first.get_text(), second.get_text())
    assert not bar.get_window_extent(renderer).overlaps(matrix.get_window_extent(renderer))
    title_text = ' '.join(text.get_text() for text in [bar.title, *figure.texts] if text.get_visible())
    assert 'CR-B04' in title_text
    assert ('数据驱动分组' if language == 'zh-CN' else 'data-driven grouping') in title_text.replace('\n', ' ')
    for extension in ('png', 'tiff'):
        with Image.open(output / f'figure_{extension}.{extension}') as image:
            assert image.size == (size[0] * 100, size[1] * 100)
            assert image.info['dpi'] == pytest.approx((100, 100), abs=.1)


def test_upset_rejects_canvas_that_cannot_fit_complete_labels(render_upset):
    with pytest.raises(ValueError, match='figure_layout_too_small'):
        render_upset(count=8, size=(2, 2), long_labels=True)


def test_worker_returns_specific_layout_size_error(tmp_path, monkeypatch):
    import io
    import struct
    from types import SimpleNamespace
    from app.adapters.bio_insights_engine import worker

    output = tmp_path / 'worker-output'
    output.mkdir()
    request = json.dumps(dict(kind='bio_insight_figure', output_directory=str(output))).encode()
    response = io.BytesIO()
    monkeypatch.setattr(worker.sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(struct.pack('!I', len(request)) + request)))
    monkeypatch.setattr(worker.sys, 'stdout', SimpleNamespace(buffer=response))
    monkeypatch.setattr(worker.signal, 'signal', lambda *args: None)
    monkeypatch.setattr(worker.signal, 'setitimer', lambda *args: None)
    def cannot_fit(_):
        raise ValueError('figure_layout_too_small')
    monkeypatch.setattr(worker, 'warm_render_environment', cannot_fit)
    worker.main()
    body = json.loads(response.getvalue().split(b'\n', 1)[1])
    code = 'bio_insights_figure_layout_too_small'
    assert body == {'error': {'code': code}}
