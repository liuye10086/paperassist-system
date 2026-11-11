"""Render audited views of the frozen B03 QC or B04 shared Wald results."""
from collections import Counter
from heapq import nsmallest
import math
import textwrap

from app.domain.bio_insights.bulk_results import (
    BULK_DIRECTIONS, bulk_contrast_labels, bulk_rank_key, bulk_row_class, finite_metric, is_reviewed_bulk,
)
from app.domain.bio_insights.contracts import BULK_HEATMAPS, BULK_PROCESSED_FIGURES, FigureConfig
from .figure_data import rows
from .inputs import document, iter_table


ZERO_Q_DISPLAY_FLOOR = 1e-300
_CLASSES = ('up', 'down', 'not_significant', 'excluded', 'not_computable', 'missing_metric')
_Q_ADJUSTMENTS = {
    'q_within_contrast': 'BH within the frozen contrast family',
    'q_global_family': 'BH across the frozen family of contrasts',
    'original_method_adjustment': 'Native PyDESeq2 adjustment, including the declared independent filtering policy',
}
_PANEL_AXES = {
    'qc_missing': ('sample_id', 'missing_fraction', 'qc_missing_data'),
    'qc_expression': ('sample_id', 'quantiles', 'expression_distribution_data'),
    'sample_clustering': ('feature_id', 'sample_id', 'sample_clustering_data'),
    'sample_correlation': ('sample_id', 'sample_id', 'sample_correlation'),
    'sample_distance': ('sample_id', 'sample_id', 'sample_distance'),
    'pca_scores': ('pc1', 'pc2', 'pca_scores'),
    'pca_variance': ('component', 'variance_ratio', 'pca_variance_ratio'),
}
_DE_AXES = {
    'bulk_ma': ('base_mean', 'effect_value', 'comparison_results'),
    'bulk_heatmap': ('sample_id', 'feature_id', 'model_normalized_counts'),
    'bulk_variable_heatmap': ('sample_id', 'feature_id', 'model_normalized_counts'),
    'bulk_expression': ('condition', 'normalized_counts', 'model_normalized_counts'),
    'bulk_summary': ('classification', 'count', 'comparison_results'),
}
_PCA_UNAVAILABLE = 'insufficient_complete_nonconstant_features_or_samples'


def bulk_axes(config):
    if config.figure_type in BULK_PROCESSED_FIGURES:
        return _PANEL_AXES[config.bulk_panel]
    if config.figure_type == 'bulk_volcano':
        return 'effect_value', config.bulk_selection.q_column, 'comparison_results'
    return _DE_AXES[config.figure_type]


def _json_member(source, key):
    if key not in source['members']:
        raise ValueError('figure_source_member_missing')
    return document(source['members'][key])


def _member_hashes(source, keys):
    return {key: source['members'][key]['sha256'] for key in keys}


def _comparison_points(source, selection, labels):
    if 'comparison_results' not in source['members']:
        raise ValueError('figure_source_member_missing')
    points = {}
    row_keys = set()
    ranks = []
    for _, row in iter_table(source['members']['comparison_results'], format='tsv'):
        if row['contrast_id'] != selection.contrast_id:
            continue
        feature, key = row['feature_id'], row['row_key']
        if (not feature or not key or feature in points or key in row_keys
                or (row['numerator'], row['denominator']) != labels):
            raise ValueError('bulk_plot_comparison_row_invalid')
        row_keys.add(key)
        category = bulk_row_class(row, selection)
        selected = category in BULK_DIRECTIONS and selection.direction in ('both', category)
        q = finite_metric(row[selection.q_column])
        if q is not None and not 0 <= q <= 1:
            raise ValueError('figure_invalid_q')
        reason = row.get('reason') or None
        adjustment_reason = row.get('original_adjustment_reason') if selection.q_column == 'original_method_adjustment' else reason
        points[feature] = dict(
            feature_id=feature, row_key=key, symbol=row.get('symbol') or feature, classification=category,
            selected=selected, effect_value=finite_metric(row['effect_value']), q_value=q,
            base_mean=finite_metric(row['base_mean']), test_status=row['test_status'], reason=reason,
            q_missing_reason=(adjustment_reason or None) if q is None else None,
        )
        if selected:
            ranks.append(bulk_rank_key(row, selection))
    if not points:
        raise ValueError('figure_contrast_unknown')
    return points, ranks


def _sample_axes(source, selection, labels):
    design = _json_member(source, 'comparison_design')
    model = design.get('bulk_model') or {}
    contrast = next((item for item in model.get('contrasts', []) if item['contrast_id'] == selection.contrast_id), None)
    units = next((item for item in design.get('actual_units', []) if item['contrast_id'] == selection.contrast_id), None)
    if (model.get('method') != 'shared_wald_v1' or not contrast or not units
            or any((item['numerator'], item['denominator']) != labels for item in (contrast, units))):
        raise ValueError('bulk_plot_design_mismatch')
    saved = rows(source, 'model_sample_metadata')
    fields = ('processed_version_id', 'sample_id', 'condition', 'biological_unit_id', 'batch', 'donor')
    expected = [tuple(sample[key] for key in fields) for sample in model['samples']]
    actual = [tuple(sample[key] for key in fields) for sample in saved]
    unit_ids = {sample['unit_id'] for sample in saved}
    model_ids = {sample['model_id'] for sample in saved}
    if (actual != expected or len({key[:2] for key in actual}) != len(actual)
            or len(unit_ids) != len(actual) or '' in unit_ids or len(model_ids) != 1 or '' in model_ids):
        raise ValueError('bulk_plot_model_sample_axis_mismatch')
    groups = [[{key: row[key] for key in ('unit_id', *fields)} for row in saved if row['condition'] == label]
              for label in labels]
    if (len(groups[0]), len(groups[1])) != (units['n_numerator'], units['n_denominator']) or not all(groups):
        raise ValueError('bulk_plot_contrast_sample_axis_mismatch')
    return groups[0] + groups[1], unit_ids, model_ids.pop()


def _normalized_values(source, samples, unit_ids, model_id, points, selected=None):
    """Read the shared matrix once, keeping only requested features in memory."""
    seen = set()
    columns = {'model_id', 'feature_id'} | unit_ids
    if 'model_normalized_counts' not in source['members']:
        raise ValueError('figure_source_member_missing')
    for _, row in iter_table(source['members']['model_normalized_counts'], format='tsv'):
        if not seen and row.keys() != columns:
            raise ValueError('bulk_plot_model_count_columns_mismatch')
        feature = row['feature_id']
        if feature not in points or feature in seen or row['model_id'] != model_id:
            raise ValueError('bulk_plot_model_count_axis_mismatch')
        seen.add(feature)
        if selected is None or feature in selected:
            values = [finite_metric(row[sample['unit_id']]) for sample in samples]
            if any(value is not None and value < 0 for value in values):
                raise ValueError('bulk_plot_model_count_invalid')
            yield feature, values
    if seen != points.keys():
        raise ValueError('bulk_plot_model_count_axis_mismatch')


def _moments(values):
    measured = [value for value in values if value is not None]
    n = len(measured)
    mean = math.fsum(measured) / n if n else None
    variance = math.fsum((value - mean)**2 for value in measured) / (n-1) if n > 1 else None
    return n, mean, variance


def _sample_plot(source, config, points, ranks, labels):
    samples, unit_ids, model_id = _sample_axes(source, config.bulk_selection, labels)
    hashes = _member_hashes(source, ('comparison_results', 'comparison_design', 'model_sample_metadata', 'model_normalized_counts'))
    info = dict(samples=samples, model_id=model_id, layer='model_normalized_counts', source_members=hashes)
    figure_type = config.figure_type
    if figure_type == 'bulk_expression':
        feature = config.feature_ids[0]
        if feature not in points:
            raise ValueError('bulk_plot_feature_not_found')
        values = dict(_normalized_values(source, samples, unit_ids, model_id, points, {feature}))[feature]
        displayed = sum(value is not None for value in values)
        return info | dict(feature=points[feature], rows=[sample | dict(normalized_counts=value, missing=value is None)
                                                        for sample, value in zip(samples, values)],
                           displayed_count=displayed, omitted_count=len(samples)-displayed, missing_count=len(samples)-displayed,
                           empty_reason=None if displayed else 'no_display_values')

    if figure_type == 'bulk_variable_heatmap':
        ranked_count = 0

        def candidates():
            nonlocal ranked_count
            for feature, values in _normalized_values(source, samples, unit_ids, model_id, points):
                _, _, variance = _moments(values)
                if variance is not None:
                    ranked_count += 1
                    yield (-variance, feature, values)

        top = nsmallest(config.top_n, candidates(), key=lambda candidate: candidate[:2])
        features = [feature for _, feature, _ in top]
        matrix = [values for _, _, values in top]
        ranked = [dict(feature_id=feature, sample_variance=-score) for score, feature, _ in top]
        sorting = 'sample_variance_desc_then_feature_id'
        unrankable = len(points)-ranked_count
        empty_reason = 'no_rankable_features'
    else:
        features = [feature for _, _, feature in nsmallest(config.top_n, ranks)]
        by_feature = dict(_normalized_values(source, samples, unit_ids, model_id, points, set(features)))
        matrix = [by_feature[feature] for feature in features]
        ranked = [points[feature] for feature in features]
        ranked_count = len(ranks)
        sorting = 'q_asc_then_absolute_effect_desc_then_feature_id'
        unrankable = 0
        empty_reason = 'no_selected_degs'
    parameters = []
    display = matrix
    if config.z_score:
        display = []
        for feature, values in zip(features, matrix):
            n, mean, variance = _moments(values)
            sd = math.sqrt(variance) if variance is not None else None
            reason = 'insufficient_measurements' if sd is None else 'zero_variance' if sd == 0 else None
            parameters.append(dict(feature_id=feature, n=n, mean=mean, sample_sd=sd, reason=reason))
            display.append([(value-mean)/sd if value is not None and reason is None else None for value in values])
    shown = sum(value is not None for values in display for value in values)
    missing = sum(value is None for values in matrix for value in values)
    omitted = len(features)*len(samples)-shown
    return info | dict(feature_ids=features, normalized_counts=matrix, display_values=display,
                       z_score=config.z_score, z_score_parameters=parameters, missing_count=missing, omitted_count=omitted,
                       unscalable_count=omitted-missing, displayed_count=shown, selected_feature_count=len(features),
                       displayed_feature_count=sum(any(value is not None for value in row) for row in display),
                       ranked_feature_count=ranked_count, ranked_features=ranked, sorting=sorting, requested_top_n=config.top_n,
                       top_n_omitted_feature_count=ranked_count-len(features), unrankable_feature_count=unrankable,
                       empty_reason=None if shown else 'no_display_values' if features else empty_reason)


def _comparison_plot(source, config):
    if source['source_kind'] != 'bio_insight_result_version' or not is_reviewed_bulk(source['metadata']):
        raise ValueError('bulk_comparison_source_required')
    selection = config.bulk_selection
    labels = bulk_contrast_labels(source['metadata']).get(selection.contrast_id)
    if labels is None:
        raise ValueError('figure_contrast_unknown')
    points, ranks = _comparison_points(source, selection, labels)
    counts = Counter(point['classification'] for point in points.values())
    data = dict(contrast_id=selection.contrast_id, direction=dict(zip(('numerator', 'denominator'), labels)),
                effect_unit='log2 count fold change', q_column=selection.q_column, q_adjustment=_Q_ADJUSTMENTS[selection.q_column],
                selection=selection.model_dump(mode='json'), thresholds=dict(q=selection.q_threshold, absolute_effect=selection.minimum_absolute_effect),
                counts={category: counts[category] for category in _CLASSES}, selected_deg_count=len(ranks),
                total_feature_count=len(points))
    if config.figure_type in BULK_HEATMAPS or config.figure_type == 'bulk_expression':
        return data | _sample_plot(source, config, points, ranks, labels)
    data.update(rows=list(points.values()), source_members=_member_hashes(source, ('comparison_results',)))
    if config.figure_type == 'bulk_summary':
        return data | dict(displayed_count=len(points), omitted_count=0, missing_count=counts['missing_metric'], empty_reason=None)
    volcano = config.figure_type == 'bulk_volcano'
    omissions = Counter()
    for point in points.values():
        q, effect, base_mean = point['q_value'], point['effect_value'], point['base_mean']
        if volcano:
            point['display_neg_log10_q'] = -math.log10(max(q, ZERO_Q_DISPLAY_FLOOR)) if q is not None else None
        reason = ('missing_effect' if effect is None else 'missing_q' if volcano and q is None else
                  'missing_base_mean' if not volcano and base_mean is None else
                  'nonpositive_base_mean' if not volcano and base_mean <= 0 else None)
        point.update(displayed=reason is None, omission_reason=reason)
        if reason:
            omissions[reason] += 1
    available_labels = (rank for rank in ranks if points[rank[2]]['displayed'])
    labeled = [feature for _, _, feature in nsmallest(config.top_n, available_labels)]
    shown = len(points)-omissions.total()
    data.update(displayed_count=shown, omitted_count=omissions.total(), omission_reasons=dict(omissions),
                missing_count=sum(point['q_value'] is None or point['effect_value'] is None
                                  or (not volcano and point['base_mean'] is None) for point in points.values()),
                requested_top_n=config.top_n, labeled_feature_ids=labeled,
                empty_reason=None if shown else 'no_plottable_points')
    if volcano:
        data['display_q_floor'] = ZERO_Q_DISPLAY_FLOOR
    else:
        data.update(x_scale='log', base_mean_scope='all samples in the frozen shared fit')
    return data


def _pca_plot(source, panel):
    variance_rows = rows(source, 'pca_variance_ratio')
    variance = [finite_metric(row['variance_ratio']) for row in variance_rows]
    components = [int(row['component']) for row in variance_rows]
    if components != list(range(1, len(components)+1)) or any(value is None or not 0 <= value <= 1 for value in variance):
        raise ValueError('bulk_plot_pca_variance_invalid')
    data = dict(components=components, variance_ratio=variance)
    keys = ['pca_variance_ratio']
    if panel == 'pca_variance':
        return data, keys, len(variance)
    keys.append('pca_scores')
    score_rows = rows(source, 'pca_scores')
    if not score_rows and not variance:
        return data | dict(sample_ids=[], scores=[]), keys, 0
    frozen = _json_member(source, 'pca_data')
    samples = [row['sample_id'] for row in score_rows]
    scores = [[finite_metric(row[f'pc{i}']) for i in components] for row in score_rows]
    if (len(components) < 2 or not samples or len(set(samples)) != len(samples)
            or any(value is None for row in scores for value in row)
            or (samples, scores, variance) != (frozen['sample_ids'], frozen['scores'], frozen['variance_ratio'])
            or len(frozen['condition']) != len(samples) or len(frozen['batch']) != len(samples)):
        raise ValueError('bulk_plot_pca_values_mismatch')
    return frozen | data, keys + ['pca_data'], len(samples)


def _qc_plot(source, panel):
    member = _PANEL_AXES[panel][2]
    if panel == 'sample_clustering' and member not in source['members']:
        if rows(source, 'sample_clustering'):
            raise ValueError('figure_source_member_missing')
        return dict(reason=_PCA_UNAVAILABLE), ['sample_clustering'], 0, 0
    data = _json_member(source, member)
    if data.get('status') == 'not_computable':
        return data, [member], 0, 0
    samples = data['sample_ids']
    if len(samples) != len(set(samples)):
        raise ValueError('bulk_plot_sample_axis_mismatch')
    if panel == 'qc_missing':
        values = data['missing_fraction']
        if len(values) != len(samples):
            raise ValueError('bulk_plot_sample_axis_mismatch')
        return data, [member], sum(value is not None for value in values), len(samples)
    if panel == 'qc_expression':
        if set(data['quantiles']) != set(samples):
            raise ValueError('bulk_plot_sample_axis_mismatch')
        displayed = sum(all(v is not None for v in row.values()) for row in data['quantiles'].values())
        return data | dict(display_statistic='frozen_five_number_summary'), [member], displayed, len(samples)
    columns = data['feature_ids'] if panel == 'sample_clustering' else samples
    values = data['values']
    if len(values) != len(samples) or any(len(row) != len(columns) for row in values):
        raise ValueError('bulk_plot_sample_axis_mismatch')
    return data, [member], sum(value is not None for row in values for value in row), len(samples)*len(columns)


def _processed_plot(source, config):
    if source['source_kind'] != 'bio_processed_dataset_version' or source['metadata'].get('assay') != 'bulk_rna_counts':
        raise ValueError('bulk_processed_source_required')
    panel = config.bulk_panel
    if config.figure_type == 'bulk_pca':
        data, keys, shown = _pca_plot(source, panel)
        total = shown
    else:
        data, keys, shown, total = _qc_plot(source, panel)
    reason = data.get('reason') or (_PCA_UNAVAILABLE if config.figure_type == 'bulk_pca' else 'no_display_values')
    return data | dict(panel=panel, source_members=_member_hashes(source, keys), displayed_count=shown,
                       omitted_count=total-shown, missing_count=total-shown, empty_reason=None if shown else reason)


def bulk_plot_data(source, config):
    data = _processed_plot(source, config) if config.figure_type in BULK_PROCESSED_FIGURES else _comparison_plot(source, config)
    x, y, member = bulk_axes(config)
    return data | dict(schema_version=1, figure_type=config.figure_type, axes=dict(x=x, y=y), input_member=member,
                       source_id=source['source_id'], source_sha256=source['sha256'])


def validate_bulk_plot(payload, actual):
    config = FigureConfig.model_validate(payload['config'])
    source = next(item for item in payload['sources'] if item['source_id'] == config.result_source_id)
    if actual != bulk_plot_data(source, config):
        raise ValueError('bulk_plot_data_mismatch')


def bulk_title(config, zh):
    titles = {
        'bulk_volcano': ('火山图', 'Volcano plot'), 'bulk_ma': ('MA 图', 'MA plot'),
        'bulk_heatmap': ('差异基因热图', 'DEG heatmap'), 'bulk_variable_heatmap': ('高变基因热图', 'Variable gene heatmap'),
        'bulk_expression': ('候选基因样本表达', 'Candidate gene expression by sample'),
        'bulk_summary': ('比较结果数量汇总', 'Comparison counts'), 'qc_missing': ('样本缺失比例', 'Missing fraction by sample'),
        'qc_expression': ('样本表达五数摘要', 'Five-number expression summaries'),
        'sample_clustering': ('样本聚类', 'Sample clustering'), 'sample_correlation': ('样本相关性', 'Sample correlation'),
        'sample_distance': ('样本距离', 'Sample distances'), 'pca_scores': ('样本 PCA 得分', 'Sample PCA scores'),
        'pca_variance': ('PCA 解释方差', 'PCA explained variance'),
    }
    return titles[config.bulk_panel or config.figure_type][0 if zh else 1]


def _colors(config):
    return {'up': config.palette[-1], 'down': config.palette[0], 'other': '#94a3b8'}


def _draw_scatter(ax, config, data, zh):
    volcano = config.figure_type == 'bulk_volcano'
    x, y = ('effect_value', 'display_neg_log10_q') if volcano else ('base_mean', 'effect_value')
    colors = _colors(config)
    points = {row['feature_id']: row for row in data['rows'] if row['displayed']}
    labels = dict(up='上调' if zh else 'Up', down='下调' if zh else 'Down', other='其他' if zh else 'Other')
    for category in ('other', 'down', 'up'):
        subset = [row for row in points.values() if (row['classification'] if row['selected'] else 'other') == category]
        if subset:
            ax.scatter([row[x] for row in subset], [row[y] for row in subset], s=11, alpha=.75,
                       color=colors[category], label=labels[category], linewidths=0)
    selection = config.bulk_selection
    effect_axis = ax.axvline if volcano else ax.axhline
    effect_axis(0, lw=.6, color='#94a3b8')
    if selection.minimum_absolute_effect > 0:
        for direction, sign in [('up', 1), ('down', -1)]:
            if selection.direction in ('both', direction):
                effect_axis(sign*selection.minimum_absolute_effect, ls='--', lw=.7, color=colors[direction])
    effect_label = 'MLE log2FC'
    if volcano:
        ax.axhline(-math.log10(max(selection.q_threshold, ZERO_Q_DISPLAY_FLOOR)), ls='--', lw=.7, color='#64748b')
        ax.set(xlabel=effect_label, ylabel=f'-log10({selection.q_column})')
    else:
        ax.set(xscale='log', xlabel='共享拟合的归一化均值（对数轴）' if zh else 'Shared-fit base mean (log scale)', ylabel=effect_label)
    rule = f'{selection.q_column} ≤ {selection.q_threshold:g}\n|MLE log2FC| ≥ {selection.minimum_absolute_effect:g}'
    ax.legend(fontsize=7, title=rule, title_fontsize=7)


def place_bulk_labels(fig, ax, data):
    """Place ranked labels using the settled axes and font geometry."""
    from matplotlib.text import Text
    from matplotlib.transforms import Bbox

    features = data['labeled_feature_ids']
    if not features:
        return
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    point = renderer.points_to_pixels(1)
    pad = 2*point
    bounds = ax.bbox
    occupied = [ax.get_legend().get_window_extent(renderer)]
    keys = set(features)
    rows_by_feature = {row['feature_id']: row for row in data['rows'] if row['feature_id'] in keys}
    x, y = ('effect_value', 'display_neg_log10_q') if data['figure_type'] == 'bulk_volcano' else ('base_mean', 'effect_value')
    for feature in features:
        row = rows_by_feature[feature]
        origin = (row[x], row[y])
        px, py = ax.transData.transform(origin)
        label = textwrap.fill(feature, width=24)
        text = Text(text=label, fontsize=7, parse_math=False)
        text.set_figure(fig)
        size = text.get_window_extent(renderer)
        width, height = size.width+2*pad, size.height+2*pad
        if width > bounds.width or height > bounds.height:
            raise ValueError('figure_layout_too_small')
        xs = [min(max(px+pad, bounds.x0), bounds.x1-width), min(max(px-width-pad, bounds.x0), bounds.x1-width)]
        ys = [min(max(py, bounds.y0), bounds.y1-height)]
        xs.extend(bounds.x0+i*width for i in range(int(bounds.width//width)))
        ys.extend(bounds.y0+i*height for i in range(int(bounds.height//height)))
        positions = sorted(((a, b) for a in xs for b in ys), key=lambda pos: abs(pos[0]-px)+abs(pos[1]-py))
        for a, b in positions:
            box = Bbox.from_bounds(a, b, width, height)
            if any(box.overlaps(other) for other in occupied):
                continue
            occupied.append(box)
            ax.annotate(label, origin, xytext=((a+pad-px)/point, (b+pad-py)/point), textcoords='offset points',
                        fontsize=7, ha='left', va='bottom', parse_math=False, annotation_clip=True,
                        arrowprops={'arrowstyle': '-', 'color': '#475569', 'lw': .5, 'shrinkA': 2, 'shrinkB': 2})
            break
        else:
            raise ValueError('figure_layout_too_small')


def _ticks(ax, axis, labels, limit=24):
    step = max(1, math.ceil(len(labels) / limit))
    positions = range(0, len(labels), step)
    visible = [textwrap.fill(str(labels[i]), 20) for i in positions]
    if axis == 'x':
        ax.set_xticks(positions, visible, rotation=55, ha='right', fontsize=7)
    else:
        ax.set_yticks(positions, visible, fontsize=7)


def _heatmap(fig, ax, config, values, xlabels, ylabels, label, *, symmetric=False, correlation=False):
    import numpy as np
    from matplotlib.colors import LinearSegmentedColormap

    colors = [config.palette[0], '#f8fafc', config.palette[-1]] if symmetric else ['#f8fafc', *config.palette]
    cmap = LinearSegmentedColormap.from_list('bulk', colors)
    cmap.set_bad('#cbd5e1')
    matrix = np.ma.masked_invalid(np.asarray(values, dtype=float))
    extent = 1 if correlation else float(np.ma.max(np.ma.abs(matrix))) if symmetric else None
    image = ax.imshow(matrix, cmap=cmap, aspect='auto', interpolation='nearest',
                      vmin=-extent if extent is not None else None, vmax=extent)
    _ticks(ax, 'x', xlabels)
    _ticks(ax, 'y', ylabels, 40)
    fig.colorbar(image, ax=ax, label=label)


def _draw_expression(ax, config, data, zh):
    labels = [data['direction'][side] for side in ('numerator', 'denominator')]
    ticks = []
    colors = _colors(config)
    for i, (label, color) in enumerate(zip(labels, (colors['up'], colors['down']))):
        rows = [row for row in data['rows'] if row['condition'] == label]
        values = [row['normalized_counts'] for row in rows if row['normalized_counts'] is not None]
        n = len(values)
        if n:
            offsets = [i + .28*(j/(n-1)-.5) for j in range(n)] if n > 1 else [i]
            ax.scatter(offsets, values, color=color, s=22, alpha=.8)
        missing = '缺失' if zh else 'missing'
        ticks.append(f'{textwrap.fill(label, 18)}\nn={n}, {missing}={len(rows)-n}')
    ax.set_xticks(range(len(ticks)), ticks)
    ax.set(xlabel=data['feature']['feature_id'], ylabel='模型归一化 counts' if zh else 'Model-normalized counts')


def _draw_summary(ax, config, data, zh):
    categories = ('上调', '下调', '未达阈值', '未纳入', '不可计算', '缺指标') if zh else (
        'Up', 'Down', 'Below threshold', 'Excluded', 'Not computable', 'Missing metric')
    counts = [data['counts'][category] for category in _CLASSES]
    colors = _colors(config)
    direction = config.bulk_selection.direction
    bars = ax.bar(range(len(counts)), counts, color=[colors[category] if category in BULK_DIRECTIONS and direction in ('both', category)
                                                     else colors['other'] for category in _CLASSES])
    ax.bar_label(bars, padding=2, fontsize=7)
    ax.margins(y=.14)
    _ticks(ax, 'x', categories)
    ax.set_ylabel('基因数' if zh else 'Gene count')


def _draw_processed(fig, ax, config, data, zh):
    panel = config.bulk_panel
    if panel == 'pca_scores':
        labels = list(zip(data['condition'], data['batch']))
        markers = ('o', 's', '^', 'v', 'D', 'P', 'X')
        for i, (condition, batch) in enumerate(dict.fromkeys(labels)):
            points = [score for label, score in zip(labels, data['scores']) if label == (condition, batch)]
            legend = ' / '.join(filter(None, (condition, batch))) or ('样本' if zh else 'Samples')
            ax.scatter([p[0] for p in points], [p[1] for p in points], color=config.palette[i%len(config.palette)],
                       marker=markers[i%len(markers)], label=textwrap.fill(legend, 22), s=24)
        if len(data['sample_ids']) <= 20:
            for sample, (x, y, *_) in zip(data['sample_ids'], data['scores']):
                ax.annotate(textwrap.shorten(sample, width=24, placeholder='…'), (x, y), xytext=(3, 3),
                            textcoords='offset points', fontsize=7, clip_on=True)
        ax.set(xlabel=f"PC1 ({data['variance_ratio'][0]:.1%})", ylabel=f"PC2 ({data['variance_ratio'][1]:.1%})")
        if 1 < len(set(labels)) <= 12:
            ax.legend(fontsize=7, title='条件 / 批次' if zh else 'Condition / batch', title_fontsize=7)
    elif panel == 'pca_variance':
        from matplotlib.ticker import PercentFormatter

        ax.bar(data['components'], data['variance_ratio'], color=config.palette[0])
        ax.yaxis.set_major_formatter(PercentFormatter(xmax=1))
        ax.set(xlabel='主成分' if zh else 'Principal component', ylabel='解释方差比例' if zh else 'Explained variance ratio')
    elif panel == 'qc_missing':
        for i, value in enumerate(data['missing_fraction']):
            if value is not None:
                ax.bar(i, value, color=config.palette[0])
        _ticks(ax, 'x', data['sample_ids'])
        ax.set(ylim=(0, 1), ylabel='缺失比例' if zh else 'Missing fraction')
    elif panel == 'qc_expression':
        boxes, positions = [], []
        for i, sample in enumerate(data['sample_ids']):
            quantiles = data['quantiles'][sample]
            if all(value is not None for value in quantiles.values()):
                boxes.append({key: quantiles[field] for key, field in zip(('whislo', 'q1', 'med', 'q3', 'whishi'),
                                                                         ('min', 'q1', 'median', 'q3', 'max'))})
                positions.append(i)
        ax.bxp(boxes, positions=positions, showfliers=False, patch_artist=True,
               boxprops={'facecolor': config.palette[0], 'alpha': .5}, medianprops={'color': '#111827'})
        _ticks(ax, 'x', data['sample_ids'])
        ax.set_ylabel('原始 counts 分位数' if zh else 'Raw count quantiles')
    else:
        samples = data['sample_ids']
        features = data['feature_ids'] if panel == 'sample_clustering' else samples
        labels = {'sample_clustering': ('保存的中心化/缩放值', 'Saved centered/scaled values'),
                  'sample_correlation': ('Pearson 相关系数', 'Pearson correlation'),
                  'sample_distance': ('欧氏距离', 'Euclidean distance')}
        correlation = panel == 'sample_correlation'
        _heatmap(fig, ax, config, data['values'], features, samples, labels[panel][0 if zh else 1],
                 symmetric=correlation, correlation=correlation)


def draw_bulk(fig, ax, source, config, zh):
    data = bulk_plot_data(source, config)
    if config.bulk_selection:
        labels = data['direction']
        notice = textwrap.fill(f"{labels['numerator']} vs {labels['denominator']}", 50)
        if config.figure_type in ('bulk_heatmap', 'bulk_summary'):
            selection = config.bulk_selection
            notice += f'\n{selection.q_column} ≤ {selection.q_threshold:g}, |log2FC| ≥ {selection.minimum_absolute_effect:g}'
        ax.set_title(notice)
    empty = data['empty_reason'] is not None
    if empty:
        message = {
            'no_selected_degs': ('当前阈值下没有差异基因', 'No DEG meets the selected thresholds'),
            'no_rankable_features': ('没有方差可计算的基因', 'No gene has computable variance'),
            _PCA_UNAVAILABLE: ('固定结果中该面板不可计算', 'Panel unavailable in this fixed result'),
        }.get(data['empty_reason'], ('没有可绘制的固定数值', 'No plottable fixed values'))
        ax.text(.5, .5, message[0 if zh else 1], ha='center', va='center', transform=ax.transAxes, wrap=True)
        ax.set(xticks=[], yticks=[])
    elif config.figure_type in BULK_PROCESSED_FIGURES:
        _draw_processed(fig, ax, config, data, zh)
    elif config.figure_type in BULK_HEATMAPS:
        label = ('逐基因 z-score' if zh else 'Per-gene z-score') if config.z_score else (
            '模型归一化 counts' if zh else 'Model-normalized counts')
        _heatmap(fig, ax, config, data['display_values'], [sample['sample_id'] for sample in data['samples']],
                 data['feature_ids'], label, symmetric=config.z_score)
    elif config.figure_type == 'bulk_expression':
        _draw_expression(ax, config, data, zh)
    elif config.figure_type == 'bulk_summary':
        _draw_summary(ax, config, data, zh)
    else:
        _draw_scatter(ax, config, data, zh)
    return data, empty
