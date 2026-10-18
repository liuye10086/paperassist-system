"""Finite process protocol for trusted numerical kernels, never generated code."""
from app.domain.regression.common import NumericError

CONTRACT_VERSION = 'fixed_statistics_v2'
MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
TIMEOUT_SECONDS = 30
KINDS = frozenset(('descriptive', 'correlation', 'group_comparison', 'regression', 'roc', 'survival'))
# Figure projections are descriptive tools, not additional statistical methods.
EXECUTION_KINDS = KINDS | {'figure_projection', 'boxplot_series', 'profile_numeric'}
PROJECTION_REASONS = frozenset(('missing_fields', 'missing_group', 'invalid_group', 'duplicate_x',
    'invalid_numeric', 'invalid_category', 'invalid_datetime', 'invalid_x_type', 'invalid_row',
    'invalid_rule', 'ordered_x_required', 'projection_empty', 'projection_limit',
    'violin_unsupported_group', 'violin_numeric_range', 'unsupported_projection'))

# This is the entire error vocabulary of the fixed child process. Neither its
# exception text nor its response message is a public diagnostic source.
ERROR_MESSAGES = {
    'figure_projection_invalid': '图表投影检查未通过，请核对字段、缺失与计算规则。',
    'numeric_input_limit': '统计执行达到限制，旧记录未区分具体原因。',
    'numeric_descriptive_limit': '描述统计最多支持100000个值。',
    'numeric_row_limit': '建模统计最多支持10000行。',
    'numeric_effect_limit': '回归最多支持20个展开效应项。',
    'numeric_input_bytes_limit': '固定统计输入超过8 MiB。',
    'numeric_output_limit': '固定统计输出超过16 MiB。',
    'numeric_output_missing': '固定统计未生成输出。',
    'numeric_output_invalid': '固定统计输出无效或损坏。',
    'numeric_timeout_invalid': '固定统计超时配置无效。',
    'numeric_timeout': '固定统计阶段超过硬超时。',
    'numeric_failure': '固定统计进程异常退出，未发布结果。',
    'numeric_invalid_input': '固定统计输入或执行参数无效。',
    'numeric_sample_size': '完整样本或所需结局类别数量不足。',
    'numeric_rank': '设计矩阵秩亏或严重病态。',
    'numeric_constant': '结局没有足够变化。',
    'numeric_perfect_fit': '完美或近完美拟合不能发布经典推断。',
    'numeric_separation_check': '分离检查无法可靠完成。',
    'numeric_separation': '存在完全或准完全分离。',
    'numeric_convergence': 'Logistic模型未可靠收敛。',
    'numeric_unstable': '数值结果不稳定或无法通过核对。',
    'numeric_overflow': 'OR或区间无法有限表达。',
    'no_valid_records': '没有可计算的有效记录，请检查字段配置。',
    'correlation_invalid_input': '相关字段或执行参数无效。',
    'correlation_input_limit': '相关分析最多支持10000条完整观察和10个字段。',
    'correlation_sample_size': '相关分析至少需要3条完整观察。',
    'correlation_constant': '选定字段没有变化。',
    'correlation_near_constant': '选定字段变化过小。',
    'comparison_invalid_input': '比较字段或执行参数无效。',
    'comparison_input_limit': '比较最多支持10000条记录或完整对和6个组。',
    'comparison_sample_size': '比较所需的每组观察数或完整对数不足。',
    'comparison_constant': '比较输入没有足够变化。',
    'comparison_near_constant': '比较输入变化过小。',
}


def validate_request(kind, rows, selection):
    if type(kind) is not str or kind not in EXECUTION_KINDS:
        raise NumericError('numeric_invalid_input', '未知统计类型。')
    if type(rows) is not list or type(selection) is not dict:
        raise NumericError('numeric_invalid_input', 'Invalid fixed statistics input.')
    if kind == 'figure_projection':
        if (set(selection) != {'figure_kind', 'projection'} or type(selection['figure_kind']) is not str
                or selection['figure_kind'] not in ('line', 'bar', 'violin') or type(selection['projection']) is not dict):
            raise NumericError('numeric_invalid_input', 'Invalid fixed figure projection request.')
        if not 1 <= len(rows) <= 10000:
            raise NumericError('numeric_row_limit', ERROR_MESSAGES['numeric_row_limit'])
    elif kind == 'profile_numeric':
        if selection or len(rows)>100000:
            raise NumericError('numeric_descriptive_limit',ERROR_MESSAGES['numeric_descriptive_limit'])
        if any(type(row) is not dict or set(row)!={'row','column','value'} or type(row['row']) is not int or not 1<=row['row']<=1048576 or type(row['column']) is not int or not 1<=row['column']<=16384 or type(row['value']) is not str or not 1<=len(row['value'])<=4000 for row in rows):
            raise NumericError('numeric_invalid_input',ERROR_MESSAGES['numeric_invalid_input'])
        if len({(row['row'],row['column']) for row in rows})!=len(rows):raise NumericError('numeric_invalid_input',ERROR_MESSAGES['numeric_invalid_input'])
    elif kind in ('descriptive', 'boxplot_series'):
        if selection:
            raise NumericError('numeric_invalid_input', 'Descriptive statistics takes no execution options.')
        if len(rows) > 100000:
            raise NumericError('numeric_descriptive_limit', ERROR_MESSAGES['numeric_descriptive_limit'])
        if kind == 'boxplot_series' and not rows:
            raise NumericError('numeric_sample_size', ERROR_MESSAGES['numeric_sample_size'])
    elif kind == 'correlation':
        if set(selection) != {'method', 'mode', 'seed'}:
            raise NumericError('numeric_invalid_input', 'Invalid correlation execution parameters.')
        if len(rows) > 10000:
            raise NumericError('correlation_input_limit', 'At most 10000 complete observations are supported.')
    elif kind == 'group_comparison':
        if set(selection) != {'method', 'posthoc'} or len(rows) > 6 or any(type(group) is not list for group in rows):
            raise NumericError('comparison_invalid_input', 'Invalid comparison execution parameters.')
        count = max(map(len, rows), default=0) if selection['method'] in ('paired_t', 'wilcoxon') else sum(map(len, rows))
        if count > 10000:
            raise NumericError('comparison_input_limit', 'At most 10000 observations or complete pairs are supported.')
    else:
        if not rows:
            raise NumericError('numeric_sample_size', ERROR_MESSAGES['numeric_sample_size'])
        if len(rows) > 10000:
            raise NumericError('numeric_row_limit', ERROR_MESSAGES['numeric_row_limit'])
