"""Deterministic encoding for the reviewed Bulk additive model."""
import math
from collections import Counter

from app.domain.bioinformatics.settings import BioLimits
from .design import _rank


def _levels(values, reference=None):
    ordered = sorted(set(values))
    return ordered if reference is None else [reference, *[value for value in ordered if value != reference]]


def _numeric_rank(rows):
    """Pivot on a bounded, scaled design without a scientific import in the API."""
    matrix = [row.copy() for row in rows]
    rank = 0
    tolerance = max(len(rows), len(rows[0])) * math.ulp(1.0) * 10
    for column in range(len(rows[0])):
        pivot = max(range(rank, len(matrix)), key=lambda i: abs(matrix[i][column]))
        if abs(matrix[pivot][column]) <= tolerance:
            continue
        matrix[rank], matrix[pivot] = matrix[pivot], matrix[rank]
        for i in range(rank + 1, len(matrix)):
            multiplier = matrix[i][column] / matrix[rank][column]
            for j in range(column + 1, len(rows[0])):
                matrix[i][j] -= multiplier * matrix[rank][j]
        rank += 1
        if rank == len(matrix):
            break
    return rank


def contrast_vectors(model):
    levels = model['condition_levels']
    width = len(model['design_columns'])
    vectors = {}
    for contrast in model['contrasts']:
        vector = [0] * width
        for sign, level in ((1, contrast['numerator']), (-1, contrast['denominator'])):
            if level != levels[0]:
                vector[width - len(levels) + levels.index(level)] = sign
        vectors[contrast['contrast_id']] = vector
    return vectors


def describe_bulk_model(config, cohorts, feature_count, block):
    levels = _levels(cohorts, config.condition_reference or config.contrasts[0].groups[1].label)
    if any(level not in cohorts for level in levels):
        block('condition_reference_missing', '模型参考组须是纳入模型的条件。')
        return None
    if config.design == 'multiple' and len(levels) < 3:
        block('multiple_requires_conditions', '多组设计须选择至少三个条件。')
        return None
    if config.design == 'independent' and len(levels) != 2:
        block('two_condition_design_required', '两组设计须使用同一对条件。')
        return None
    rows = [row for level in levels for row in sorted(cohorts[level], key=lambda r: (r['processed_version_id'], r['sample_id']))]
    limits = BioLimits()
    if len(rows) > limits.max_bulk_observations or len(rows) * feature_count > limits.max_bulk_matrix_cells:
        block('bulk_model_budget', '纳入样本数或模型矩阵超过 Bulk 容量。')
        return None
    biological = lambda row: row.get('biological_unit_id') or row.get('donor')
    if config.design == 'paired':
        first_pairs = {row[config.pairing_field] for row in cohorts[levels[0]]}
        if any({row[config.pairing_field] for row in cohorts[level]} != first_pairs for level in levels[1:]):
            block('incomplete_or_duplicate_pairs', '共享模型的各条件须使用同一组完整配对单位。')
            return None
        pair_by_unit = {}
        for row in rows:
            pair = row[config.pairing_field]
            if pair_by_unit.setdefault(biological(row), pair) != pair:
                block('nonindependent_biological_units', '同一生物学单位不能分配到多个独立配对。')
                return None
    elif len({biological(row) for row in rows}) != len(rows):
        block('nonindependent_biological_units', '统一拟合的样本包含重复生物学单位。')
        return None

    terms = []
    if config.design == 'paired':
        terms.append(dict(field=config.pairing_field, term='donor', name='配对单位', kind='categorical', reference_level=None))
    if config.batch_adjustment:
        terms.append(dict(field='batch', term='batch', name='batch', kind='categorical', reference_level=None))
    terms.extend({**covariate.model_dump(), 'term': f'covariate_{i}'} for i, covariate in enumerate(config.covariates, 1))
    terms.append(dict(field='condition', term='condition', name='condition', kind='categorical', reference_level=levels[0]))
    columns = ['Intercept']
    blocks = []
    for term in terms:
        values = [row.get(term['field']) for row in rows]
        if any(value is None or str(value).strip() == '' for value in values):
            block('covariate_missing', f"字段 {term['field']} 存在缺失值。")
            return None
        if term['kind'] == 'categorical':
            values = list(map(str, values))
            reference = term['reference_level']
            if reference is not None and reference not in values:
                block('covariate_reference_missing', f"字段 {term['field']} 的参考水平不存在。")
                return None
            factor_levels = _levels(values, reference)
            if len(factor_levels) < 2:
                block('covariate_constant', f"字段 {term['field']} 少于两个水平。")
                return None
            term.update(levels=factor_levels, reference_level=factor_levels[0])
            if len(columns) + len(factor_levels) - 1 > 100:
                block('design_capacity', '设计超过 100 列。')
                return None
            columns.extend(f"{term['term']}[T.{level}]" for level in factor_levels[1:])
            blocks.append([[int(value == level) for level in factor_levels[1:]] for value in values])
        else:
            try:
                numeric = [float(value) for value in values]
            except (TypeError, ValueError, OverflowError):
                numeric = []
            if not numeric or not all(map(math.isfinite, numeric)):
                block('covariate_invalid', f"连续协变量 {term['field']} 须是有限数值。")
                return None
            if len(set(numeric)) < 2:
                block('covariate_constant', f"连续协变量 {term['field']} 没有变化。")
                return None
            scale = max(map(abs, numeric))
            scaled = [value / scale for value in numeric]
            center = math.fsum(scaled) / len(scaled)
            term.update(divisor=scale, center_after_division=center)
            columns.append(term['term'])
            blocks.append([[value - center] for value in scaled])

    if len(columns) > 100:
        block('design_capacity', '设计超过 100 列。')
        return None
    matrix = [[1, *[value for term in blocks for value in term[i]]] for i in range(len(rows))]
    rank = _numeric_rank(matrix) if any(term['kind'] == 'continuous' for term in terms) else _rank(matrix)
    residual = len(rows) - rank
    if rank != len(columns) or residual <= 0:
        block('rank_deficient_design', '设计混杂、不满列秩或没有正残差自由度。')
    sizes = dict(Counter(row['condition'] for row in rows))
    covariate_fields = [covariate.field for covariate in config.covariates]
    return dict(
        method=config.bulk_model,
        formula='~ ' + ' + '.join(term['term'] for term in terms),
        terms=terms,
        condition_levels=levels,
        condition_reference=levels[0],
        group_sizes=sizes,
        contrasts=[dict(contrast_id=c.contrast_id, numerator=c.groups[0].label, denominator=c.groups[1].label)
                   for c in config.contrasts],
        filter=dict(minimum_total_counts=config.minimum_total_counts, minimum_sample_counts=config.minimum_sample_counts,
                    minimum_expressing_samples=min(sizes.values()), eligible_feature_count=feature_count),
        size_factor_method=config.size_factor_method,
        design_columns=columns,
        design_matrix=matrix,
        rank=rank,
        residual_degrees_freedom=residual,
        samples=[dict(processed_version_id=row['processed_version_id'], sample_id=row['sample_id'],
                      condition=row['condition'], biological_unit_id=biological(row), batch=row.get('batch') or '',
                      donor=row.get(config.pairing_field) or '', covariates={field: row[field] for field in covariate_fields})
                 for row in rows],
    )
