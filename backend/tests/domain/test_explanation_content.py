import copy

import pytest

from app.domain.explanation_content import build_payload, render_explanation
from app.core.exceptions import PlotError
from tests.api.test_descriptive import configured, run
from tests.api.test_analysis import client  # noqa: F401
from tests.api.test_boxplot import cloud, generate  # noqa: F401


def fixture_payload(client, **changes):
    base, _ = configured(client, **changes)
    result = run(client, base)
    figure = generate(client, base + '/analysis-runs/' + result['id'] + '/boxplot')
    return build_payload(result, figure)


def valid_draft(payload):
    refs = payload['required_references']
    return {key: '依据' + '、'.join('{{' + ref + '}}' for ref in values) + '进行描述。'
            for key, values in refs.items()}


def test_renders_only_trusted_fact_values_with_per_section_evidence(client, cloud):
    payload = fixture_payload(client)
    draft = valid_draft(payload)
    rendered = render_explanation(draft, payload)
    assert len(rendered) == 6
    assert rendered[0]['title'] == '分析目的'
    assert '{{' not in rendered[3]['text']
    evidence = {item['key']: item['value'] for item in rendered[3]['evidence']}
    assert evidence['overall.n'] == str(payload['facts']['overall.n']['raw'])
    assert 'values' not in payload and 'provenance' not in payload


@pytest.mark.parametrize('replacement', ['均值为 999。', '均值为９９９。', '{{unknown.mean}}', '{{overall.mean}',
    '均值为九百九十九。', '均值为九。', '共两组。', '增加三倍。', '均值为壹佰。',
    '治疗显著改善结果。', '证明存在因果关系。', '不存在显著差异。',
    '不能说明原因，但差异具有统计学意义。', '', '<script>bad()</script>'])
def test_rejects_unbound_numbers_unknown_or_broken_refs_and_unsupported_claims(client, cloud, replacement):
    payload = fixture_payload(client)
    draft = valid_draft(payload)
    draft['results'] += replacement
    if not replacement:
        draft['purpose'] = ' '
    with pytest.raises(PlotError):
        render_explanation(draft, payload)


def test_requires_schema_and_important_evidence(client, cloud):
    payload = fixture_payload(client)
    for change in ('missing', 'extra', 'references', 'oversize', 'wrong_type'):
        draft = valid_draft(payload)
        if change == 'missing':
            del draft['data']
        elif change == 'extra':
            draft['p_value'] = '0.01'
        elif change == 'references':
            draft['results'] = '记录显示分布存在差别。'
        elif change == 'oversize':
            draft['purpose'] *= 5000
        else:
            draft['purpose'] = []
        with pytest.raises(PlotError):
            render_explanation(draft, payload)


def test_labels_with_numbers_or_template_like_content_stay_literal(client, cloud):
    payload = fixture_payload(client)
    payload = copy.deepcopy(payload)
    payload['facts']['variable']['value'] = 'IL-6 {{overall.mean}} <b>浓度</b>'
    draft = valid_draft(payload)
    rendered = render_explanation(draft, payload)
    assert 'IL-6 {{overall.mean}} <b>浓度</b>' in rendered[0]['text']
    assert rendered[0]['evidence'][0]['value'] == payload['facts']['variable']['value']


@pytest.mark.parametrize('text', ['不能说明差异具有统计学意义。', '无法据此判断差异具有统计学意义。',
    '总体中位数与下四分位数不一致。', '未计算 P 值，结果需要进一步审核。'])
def test_allows_cautious_limitations_and_non_numeric_technical_terms(client, cloud, text):
    payload = fixture_payload(client)
    draft = valid_draft(payload)
    draft['interpretation'] += text
    assert render_explanation(draft, payload)[4]['text'].endswith(text)
