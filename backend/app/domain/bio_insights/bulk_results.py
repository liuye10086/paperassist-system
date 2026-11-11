"""Read and classify the saved statistics of a reviewed Bulk RNA-seq comparison."""
from collections import Counter
import csv
import math


BULK_DIRECTIONS = frozenset(('up', 'down'))
_REQUIRED_COLUMNS = frozenset((
    'row_key', 'feature_id', 'symbol', 'contrast_id', 'numerator', 'denominator', 'tested', 'test_status',
    'effect_value', 'q_within_contrast', 'q_global_family', 'original_method_adjustment',
))


def is_reviewed_bulk(metadata):
    plan = metadata.get('plan_config')
    return (metadata.get('kind') == 'comparison'
            and isinstance(plan, dict)
            and plan.get('mode') == 'bulk_counts'
            and plan.get('bulk_model') == 'shared_wald_v1')


def finite_metric(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def bulk_row_class(row, selection):
    status = row.get('test_status')
    if status == 'excluded' or str(row.get('tested')).casefold() not in ('true', '1'):
        return 'excluded'
    if status == 'not_computable':
        return 'not_computable'
    q = finite_metric(row.get(selection.q_column))
    effect = finite_metric(row.get('effect_value'))
    if q is None or not 0 <= q <= 1 or effect is None:
        return 'missing_metric'
    if effect == 0 or q > selection.q_threshold or abs(effect) < selection.minimum_absolute_effect:
        return 'not_significant'
    return 'up' if effect > 0 else 'down'


def bulk_rank_key(row, selection):
    q = finite_metric(row.get(selection.q_column))
    effect = finite_metric(row.get('effect_value'))
    return (q if q is not None else math.inf,
            -abs(effect) if effect is not None else math.inf,
            row['feature_id'])


def bulk_contrast_labels(metadata):
    contrasts = metadata['plan_config']['contrasts']
    labels = {
        contrast['contrast_id']: (contrast['groups'][0]['label'], contrast['groups'][1]['label'])
        for contrast in contrasts
    }
    if not labels or len(labels) != len(contrasts):
        raise ValueError('bulk_comparison_contrasts_invalid')
    return labels


def _counts(classes):
    total = classes.total()
    return dict(total=total, tested=total - classes['excluded'], excluded=classes['excluded'],
                not_computable=classes['not_computable'], missing_metric=classes['missing_metric'],
                deg=classes['up'] + classes['down'], up=classes['up'], down=classes['down'])


def bulk_comparison_page(path, contrasts, selection, *, subset, page, page_size, search):
    contrast_id = selection.contrast_id
    query = search.casefold() if search else None
    classes = {cid: Counter() for cid in contrasts}
    items, ranks, feature_matches = [], [], {}
    matched = 0
    start, end = (page - 1) * page_size, page * page_size
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream, delimiter='\t', strict=True)
        columns = reader.fieldnames or []
        if not _REQUIRED_COLUMNS.issubset(columns) or len(columns) != len(set(columns)):
            raise ValueError('bulk_comparison_columns_invalid')
        for number, row in enumerate(reader):
            cid = row['contrast_id']
            if (None in row or None in row.values() or not row['feature_id'] or not row['row_key']
                    or contrasts.get(cid) != (row['numerator'], row['denominator'])):
                raise ValueError('bulk_comparison_row_invalid')
            category = bulk_row_class(row, selection)
            classes[cid][category] += 1
            if search == row['feature_id']:
                feature_matches[cid] = row
            if cid != contrast_id:
                continue
            if subset != 'all' and (category not in BULK_DIRECTIONS or subset not in ('deg', category)):
                continue
            if query and query not in row['feature_id'].casefold() and query not in row['symbol'].casefold():
                continue
            if subset == 'all':
                if start <= matched < end:
                    items.append(row)
            else:
                # Keep only ranks and positions across the full subset, then read the requested page.
                ranks.append((bulk_rank_key(row, selection), number))
            matched += 1
    if any(not counts for counts in classes.values()):
        raise ValueError('bulk_comparison_rows_missing')
    if ranks:
        positions = {number: order for order, (_, number) in enumerate(sorted(ranks)[start:end])}
        if positions:
            items = [None] * len(positions)
            last = max(positions)
            with path.open(encoding='utf-8-sig', newline='') as stream:
                reader = csv.DictReader(stream, delimiter='\t', strict=True)
                for number, row in enumerate(reader):
                    if number in positions:
                        items[positions[number]] = row
                    if number == last:
                        break
    return dict(contrast_id=contrast_id, columns=columns, items=items,
                contrasts=[dict(contrast_id=cid, numerator=left, denominator=right, **_counts(classes[cid]))
                           for cid, (left, right) in contrasts.items()],
                total=classes[contrast_id].total(), matched_total=matched, page=page, page_size=page_size,
                feature_matches=[feature_matches[cid] for cid in contrasts if cid in feature_matches])


def bulk_candidate_data(rows, selection, labels):
    """Keep a full ranked selection and account for every row of the chosen comparison."""
    columns = _REQUIRED_COLUMNS | {'effect_name', 'effect_unit', 'observation_level', 'inference_scope'}
    classes = Counter()
    seen, ranked, exclusions = set(), [], []
    for number, row in rows:
        if row['contrast_id'] != selection.contrast_id:
            continue
        if (not columns.issubset(row) or not row['feature_id'] or not row['row_key']
                or row['feature_id'] in seen or labels != (row['numerator'], row['denominator'])):
            raise ValueError('bulk_comparison_row_invalid')
        feature_id = row['feature_id']
        seen.add(feature_id)
        category = bulk_row_class(row, selection)
        classes[category] += 1
        if category in BULK_DIRECTIONS and selection.direction in ('both', category):
            ranked.append({key: row[key] for key in columns} | {'source_row': number, 'direction': category})
        else:
            reason = 'direction_not_selected' if category in BULK_DIRECTIONS else category
            exclusions.append(dict(step=1, feature_id=feature_id, reason=reason, source_row=number,
                                   source_row_key=row['row_key']))
    if not classes:
        raise ValueError('bulk_comparison_rows_missing')
    ranked.sort(key=lambda row: bulk_rank_key(row, selection))
    return dict(ranked=ranked, counts=_counts(classes), exclusions=exclusions)
