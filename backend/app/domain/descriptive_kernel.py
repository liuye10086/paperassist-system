"""The unchanged descriptive formulas, separated from storage and HTTP routes."""
from fractions import Fraction
from math import isfinite
import statistics
from app.domain.regression.common import NumericError


def summarize(values):
    if any(type(value) not in (int, float) or not isfinite(value) for value in values):
        raise NumericError('numeric_invalid_input', 'Every descriptive value must be finite and numeric.')
    ordered = sorted(values)
    count = len(ordered)
    if not count:
        raise NumericError('no_valid_records', '没有可计算的有效记录，请检查字段配置。')

    def quartile(quarter):
        index, remainder = divmod((count - 1) * quarter, 4)
        if not remainder:
            return Fraction(ordered[index])
        return (Fraction(ordered[index]) * (4 - remainder) + Fraction(ordered[index + 1]) * remainder) / 4

    notes = []

    def finite_metric(name, calculate):
        try:
            value = float(calculate())
            if isfinite(value):
                return value
        except ArithmeticError:
            pass
        notes.append(f'{name}超出可表示的数值范围，结果标记为无法计算。')
        return None

    deviation = None
    if count < 2:
        notes.append('有效记录不足 2 条，样本标准差无法计算。')
    else:
        deviation = finite_metric('样本标准差', lambda: statistics.stdev(ordered))
    q1, median, q3 = (quartile(quarter) for quarter in (1, 2, 3))
    return {'n': count, 'mean': statistics.mean(ordered), 'std': deviation,
            'min': ordered[0], 'q1': float(q1), 'median': float(median), 'q3': float(q3), 'max': ordered[-1],
            'iqr': finite_metric('四分位距', lambda: q3 - q1), 'warnings': notes}
