"""Independent regressions for reviewed prose and legacy-archive failures."""
from copy import deepcopy
import pytest
from app.core.exceptions import PlotError
from tests.domain.test_correlation_artifacts import result


def payload_and_draft():
    from app.domain.explanation_content import build_payload
    payload=build_payload(result(),{'id':'figure','title':'Figure 1','figure_number':1,'sha256':'c'*64})
    draft={key:'Based on '+', '.join('{{'+ref+'}}' for ref in refs)+'.' for key,refs in payload['required_references'].items()}
    return payload,draft


@pytest.mark.parametrize('text', ['The coefficient is twenty.', 'The sample contains thirty observations.',
    'This is the twenty-first sample.', 'Correlation does not establish causation and is statistically significant.',
    'This cannot prove effectiveness, and the association is significant.',
    'The correlation coefficient is {{correlation.p_value}}.', 'The P value is {{correlation.coefficient}}.',
    'The sample size is {{correlation.p_value}}.', '相关系数为{{correlation.p_value}}。'])
def test_modern_unbound_numbers_inference_and_wrong_metric_assertions_rejected(text):
    from app.domain.explanation_content import render_explanation
    payload,draft=payload_and_draft()
    draft['interpretation']+=' '+text
    with pytest.raises(PlotError): render_explanation(draft,payload)


def test_modern_numeric_fact_tokens_render_their_own_metric_label_and_value():
    from app.domain.explanation_content import render_explanation
    payload,draft=payload_and_draft()
    rendered=render_explanation(draft,payload)
    assert 'Two-sided P value: 0.2' in rendered[3]['text']
    assert 'Correlation coefficient: 0.8' in rendered[3]['text']
    assert rendered[0]['title']=='Analysis purpose' and len(rendered)==6


@pytest.mark.parametrize('text',['不能推断因果，但相关性显著。','变量显著相关。','相关性具有显著性。',
    'The observation is the billionth sample.','There are quadrillion samples.',
    'There are dozens of observations.','There are hundreds of observations.',
    'The population contains millions of observations.', 'There are tens of observations.',
    'There are scores of observations.','Participants are in their twenties.'])
def test_rereview_chinese_significance_and_large_english_number_words_rejected(text):
    from app.domain.explanation_content import build_payload,render_explanation
    value=result('zh-CN' if any('\u4e00'<=char<='\u9fff' for char in text) else 'en')
    payload=build_payload(value,{'id':'figure','title':'Figure 1','figure_number':1,'sha256':'c'*64})
    draft={key:('依据' if payload['language']=='zh-CN' else 'Based on ')+', '.join('{{'+ref+'}}' for ref in refs)+'.'
        for key,refs in payload['required_references'].items()}
    draft['interpretation']+=text
    with pytest.raises(PlotError):render_explanation(draft,payload)


@pytest.mark.parametrize('text',['不能据此判断相关性显著。','不能推断因果。','没有计算统计显著性。',
    '不能据此判断显著性。','相关不能证明因果关系。','无法据此推断因果。',
    'Correlation does not establish causation.','These data cannot prove treatment effectiveness.'])
def test_rereview_scoped_cautious_negations_remain_usable(text):
    from app.domain.explanation_content import build_payload,render_explanation
    value=result('zh-CN' if any('\u4e00'<=char<='\u9fff' for char in text) else 'en')
    payload=build_payload(value,{'id':'figure','title':'Figure 1','figure_number':1,'sha256':'c'*64})
    draft={key:('依据' if payload['language']=='zh-CN' else 'Based on ')+', '.join('{{'+ref+'}}' for ref in refs)+'.'
        for key,refs in payload['required_references'].items()}
    draft['interpretation']+=text
    assert render_explanation(draft,payload)[4]['text'].endswith(text)
