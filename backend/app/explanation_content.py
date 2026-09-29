"""Bind AI prose to an immutable, bounded catalogue of statistical facts."""

import re

from .openai_plot import PlotError

VERSION = 'analysis_explanation_v1'
SECTIONS = {'purpose': '分析目的', 'data': '使用数据', 'methods': '分析方法',
            'results': '主要结果', 'interpretation': '结果解释', 'paper_text': '论文描述文字'}
METRICS = {'n': '样本数', 'mean': '均值', 'std': '样本标准差', 'min': '最小值', 'q1': '下四分位数',
           'median': '中位数', 'q3': '上四分位数', 'max': '最大值', 'iqr': '四分位距'}
LIMITATIONS = [
    '本步仅进行描述统计，未计算 P 值、置信区间或效应量，不能据此作显著性、因果或疗效判断。',
    '研究设计、样本来源、实验步骤及测量背景尚未提供，具体研究目的与方法细节待补充。',
    '解释依据已保存的统计汇总和图表元数据，不代表对图片像素的核验。AI 初稿仍需人工审阅。',
    '文字中的数值最多显示 6 位有效数字；完整数值以保存的统计结果为准。',
]
METHOD = ('使用所选字段的完整记录，未插补、去重或剔除离群值；样本标准差采用 n−1 分母，'
          '分位数按 (n−1)p 线性插值。箱体为 Q1–Q3，中线为中位数，'
          '须端到 Q1−1.5×IQR 至 Q3+1.5×IQR 范围内最远实际观测，空心点表示范围外观测。')
TOKEN = re.compile(r'\{\{([a-z][a-z0-9_.]*)\}\}')
UNSUPPORTED = re.compile(r'显著(?:高于|低于|增加|减少|改善|升高|降低|差异)|'
    r'(?:具有|有)统计学意义|(?:证明|证实|导致|造成).{0,30}(?:因果|疗效|疾病|改善)|'
    r'因果关系(?:成立|明确)|[pPＰ]\s*(?:[值=<>＜＞]|[- ]?value)', re.IGNORECASE)
# These fixed words contain numeral characters but do not state a quantity.
NON_QUANTITIES = re.compile('四分位|百分位|一致|统一|单一|一般|一定|一些|一样|进一步|'
                           '一方面|另一方面|一同|一并|一概|一律|一一对应|之一|不一')
LIMITATION_PREFIX = re.compile(r'(?:不能|无法|不足以|不应|不宜|尚不能)(?:据此)?'
    r'(?:说明|证明|认定|判断|推断|确定|声称|表明).{0,30}$|'
    r'(?:未|没有|不)(?:进行|开展|计算|提供|报告).{0,16}$')


def unsafe_prose(prose):
    # isnumeric also covers full-width, Chinese/financial and other Unicode numerals.
    if any(char.isnumeric() or char in '两兩俩倆半幺' for char in NON_QUANTITIES.sub('', prose)) or re.search(r'[{}<>]', prose):
        return True
    for match in UNSUPPORTED.finditer(prose):
        clause = re.split(r'[，,。；;！？!?\n]|但是|然而|但|而且|且|却|仍', prose[:match.end()])[-1]
        # A scoped inability-to-infer statement is a limitation, not a positive finding.
        if not LIMITATION_PREFIX.search(clause):
            return True
    return False


def build_payload(result, figure):
    facts = {}
    def add(key, label, value):
        display = '无法计算' if value is None else format(value, '.6g') if isinstance(value, float) else str(value)
        facts[key] = {'label': label, 'value': display, 'raw': value}
    add('variable', '数值字段', result['numeric_name'])
    add('unit', '数值单位', result['selection']['unit'] or '单位未填写')
    add('grouping', '分组字段', result['group_name'] or '不分组')
    add('sheet', '工作表', result['selection']['sheet_name'])
    add('figure.number', '图号', figure['figure_number'])
    add('figure.title', '图标题', figure['title'])
    add('method.summary', '计算及绘图方法', METHOD)
    for key, source, label in [('total', 'row_count', '原始行数'), ('valid', 'valid_count', '完整记录数'),
                               ('excluded', 'excluded_count', '排除行数')]:
        add('data.' + key, label, result['check'][source])
    for key, label in METRICS.items():
        add('overall.' + key, '总体：' + label, result['overall'][key])
    required_results = ['overall.' + key for key in METRICS]
    for index, group in enumerate(result['groups']):
        prefix = f'groups.{index}.'
        add(prefix + 'label', '分组名称', group['label'])
        for key, label in METRICS.items():
            add(prefix + key, group['label'] + '：' + label, group['statistics'][key])
        required_results.extend(prefix + key for key in ('label', 'n', 'median'))
    for index, series in enumerate(figure['series']):
        for key, label in [('outlier_count', '离群观测数量'), ('whislo', '下须端'), ('whishi', '上须端')]:
            add(f'series.{index}.{key}', series['label'] + '：' + label, series[key])
        required_results.append(f'series.{index}.outlier_count')
    return {'language': 'zh-CN', 'analysis_run_id': result['id'], 'figure_id': figure['id'],
            'source_sha256': result['source_sha256'], 'figure_sha256': figure['sha256'],
            'facts': facts, 'required_references': {
                'purpose': ['variable'], 'data': ['sheet', 'data.total', 'data.valid', 'data.excluded'],
                'methods': ['method.summary'], 'results': required_results,
                'interpretation': ['overall.median'], 'paper_text': ['figure.number', 'overall.n', 'overall.mean', 'unit']}}


def render_explanation(draft, payload):
    def invalid(message):
        raise PlotError('explanation_invalid', message + '解释未保存，请重新生成。')
    if not isinstance(draft, dict) or set(draft) != set(SECTIONS):
        invalid('AI 未返回完整的六部分解释。')
    sections = []
    for key, title in SECTIONS.items():
        text = draft[key]
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            invalid('AI 解释为空、格式错误或篇幅超限。')
        refs = list(dict.fromkeys(TOKEN.findall(text)))
        if any(ref not in payload['facts'] for ref in refs):
            invalid('AI 引用了不存在的数据。')
        if not set(payload['required_references'][key]).issubset(refs):
            invalid('AI 解释缺少本段要求的关键数据引用。')
        prose = TOKEN.sub('', text)
        if unsafe_prose(prose):
            invalid('AI 解释包含未绑定的数值、无效引用或不支持的推断性表述。')
        # One substitution pass: user labels are literal data, never another template.
        rendered = TOKEN.sub(lambda match: payload['facts'][match[1]]['value'], text).strip()
        sections.append({'key': key, 'title': title, 'text': rendered,
                         'evidence': [{'key': ref, 'label': payload['facts'][ref]['label'],
                                       'value': payload['facts'][ref]['value']} for ref in refs]})
    return sections
