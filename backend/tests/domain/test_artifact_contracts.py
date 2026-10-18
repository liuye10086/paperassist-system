"""Artifact routing expectations independent of any production statistics."""
import pytest


def research_result(language='en', *, schema=3, correlation=False, mode='pair'):
    value = {'schema_version': schema, 'analysis_context': {'plan': {
        'schema_version': schema, 'research_request': {'output_language': language}}}}
    if correlation:
        value.update(result_type='correlation', selection={'task_type': 'correlation', 'mode': mode})
    return value


def test_old_contract_constants_and_chinese_routes_remain_unchanged():
    from app.domain.artifact_contracts import artifact_language, figure_renderer, explanation_version, report_version
    legacy = {}
    assert artifact_language(legacy) == 'zh-CN'
    assert figure_renderer(legacy) == 'openai_boxplot_v1'
    assert explanation_version(legacy) == 'analysis_explanation_v1'
    assert report_version(legacy) == 'word_analysis_report_v1'


@pytest.mark.parametrize('language', ['zh-CN', 'en'])
@pytest.mark.parametrize('correlation,mode,kind', [(False, 'pair', 'boxplot'),
    (True, 'pair', 'scatter'), (True, 'matrix', 'correlation_heatmap')])
def test_new_results_route_language_and_single_figure_path(language, correlation, mode, kind):
    from app.domain.artifact_contracts import artifact_language, figure_kind, figure_renderer, explanation_version, report_version
    result = research_result(language, correlation=correlation, mode=mode)
    assert artifact_language(result) == language
    assert figure_kind(result) == kind
    assert figure_renderer(result) == 'openai_analysis_plot_v2'
    assert explanation_version(result) == 'analysis_explanation_v2'
    assert report_version(result) == 'word_analysis_report_v2'


def test_new_generation_of_v2_english_task_uses_english():
    from app.domain.artifact_contracts import artifact_language, figure_renderer
    assert artifact_language(research_result(schema=2)) == 'en'
    assert figure_renderer(research_result(schema=2)) == 'openai_analysis_plot_v2'


def test_unsupported_result_language_and_correlation_mode_rejected():
    from app.domain.artifact_contracts import artifact_language, figure_kind
    from app.core.exceptions import StorageError
    with pytest.raises(StorageError):
        artifact_language(research_result('fr'))
    with pytest.raises(StorageError):
        figure_kind(research_result(correlation=True, mode='unknown'))


def test_six_section_titles_correspond_to_output_language():
    from app.domain.artifact_contracts import section_titles
    assert list(section_titles('zh-CN')) == ['purpose', 'data', 'methods', 'results', 'interpretation', 'paper_text']
    assert section_titles('zh-CN')['purpose'] == '分析目的'
    assert section_titles('en')['purpose'] == 'Analysis purpose'
    assert all(not any('\u4e00' <= char <= '\u9fff' for char in title) for title in section_titles('en').values())
