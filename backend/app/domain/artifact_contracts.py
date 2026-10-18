"""Immutable artifact routing; archived versions never follow mutable preferences."""
from app.core.exceptions import StorageError

PLOT_V1 = 'openai_boxplot_v1'
PLOT_V2 = 'openai_analysis_plot_v2'
PLOT_V3 = 'openai_comparison_plot_v3'
PLOT_V4 = 'openai_modeling_plot_v4'
EXPLANATION_V1 = 'analysis_explanation_v1'
EXPLANATION_V2 = 'analysis_explanation_v2'
EXPLANATION_V3 = 'analysis_explanation_v3'
EXPLANATION_V4 = 'analysis_explanation_v4'
REPORT_V1 = 'word_analysis_report_v1'
REPORT_V2 = 'word_analysis_report_v2'
REPORT_V3 = 'word_analysis_report_v3'
REPORT_V4 = 'word_analysis_report_v4'
SECTION_TITLES = {
    'zh-CN': dict(purpose='分析目的', data='使用数据', methods='分析方法', results='主要结果',
                  interpretation='结果解释', paper_text='论文描述文字'),
    'en': dict(purpose='Analysis purpose', data='Data used', methods='Analysis methods', results='Main results',
               interpretation='Interpretation', paper_text='Manuscript wording'),
}


def artifact_language(result):
    try:
        language = result.get('analysis_context', {}).get('plan', {}).get('research_request', {}).get('output_language', 'zh-CN')
    except (AttributeError, TypeError) as exc:
        raise StorageError('task_source_conflict', '成果语言来源无效。', 409) from exc
    if language not in SECTION_TITLES:
        raise StorageError('task_source_conflict', '成果语言来源无效。', 409)
    return language


def modern_artifact(result):
    return modeling_artifact(result) or comparison_artifact(result) or result.get('schema_version') == 3 or result.get('schema_version') == 2 and artifact_language(result) == 'en'


def modeling_artifact(result):
    if result.get('result_type') in ('regression','roc','survival'):
        if result.get('schema_version') != 5:
            raise StorageError('task_source_conflict','建模成果版本与结果类型不一致。',409)
        return True
    return False


def comparison_artifact(result):
    if result.get('result_type') == 'group_comparison':
        if result.get('schema_version') != 4:
            raise StorageError('task_source_conflict', '比较成果的保存版本不一致。', 409)
        return True
    return False


def figure_kind(result):
    if modeling_artifact(result):
        return {'regression':'forest','roc':'roc_curve','survival':'kaplan_meier'}[result['result_type']]
    if comparison_artifact(result):
        design = result.get('selection', {}).get('design')
        if design not in ('independent', 'multiple', 'paired'):
            raise StorageError('task_source_conflict', '比较图型与结果路径不一致。', 409)
        return 'paired_connected' if design == 'paired' else 'group_boxplot'
    if result.get('result_type') in (None, 'descriptive'):
        return 'boxplot'
    if result.get('result_type') != 'correlation':
        raise StorageError('task_source_conflict', '成果类型无法识别。', 409)
    mode = result.get('selection', {}).get('mode')
    if mode not in ('pair', 'matrix'):
        raise StorageError('task_source_conflict', '相关图型与结果路径不一致。', 409)
    return 'scatter' if mode == 'pair' else 'correlation_heatmap'


def figure_renderer(result):
    figure_kind(result)
    if modeling_artifact(result): return PLOT_V4
    if comparison_artifact(result): return PLOT_V3
    return PLOT_V2 if modern_artifact(result) else PLOT_V1


def explanation_version(result):
    if modeling_artifact(result): return EXPLANATION_V4
    if comparison_artifact(result): return EXPLANATION_V3
    return EXPLANATION_V2 if modern_artifact(result) else EXPLANATION_V1


def report_version(result):
    if modeling_artifact(result): return REPORT_V4
    if comparison_artifact(result): return REPORT_V3
    return REPORT_V2 if modern_artifact(result) else REPORT_V1


def section_titles(language):
    if language not in SECTION_TITLES:
        raise StorageError('task_source_conflict', '成果语言无效。', 409)
    return SECTION_TITLES[language].copy()


def saved_explanation_version(figure):
    if figure.get('engine',{}).get('id') not in (None,PLOT_V1,PLOT_V2,PLOT_V3,PLOT_V4):
        raise StorageError('source_conflict','已保存图表引擎版本无法识别。',409)
    if figure.get('engine', {}).get('id') == PLOT_V4: return EXPLANATION_V4
    if figure.get('engine', {}).get('id') == PLOT_V3: return EXPLANATION_V3
    return EXPLANATION_V2 if figure.get('engine', {}).get('id') == PLOT_V2 else EXPLANATION_V1


def saved_report_version(explanation):
    if explanation.get('engine',{}).get('id') not in (None,EXPLANATION_V1,EXPLANATION_V2,EXPLANATION_V3,EXPLANATION_V4):
        raise StorageError('source_conflict','已保存解释引擎版本无法识别。',409)
    if explanation.get('engine', {}).get('id') == EXPLANATION_V4: return REPORT_V4
    if explanation.get('engine', {}).get('id') == EXPLANATION_V3: return REPORT_V3
    return REPORT_V2 if explanation.get('engine', {}).get('id') == EXPLANATION_V2 else REPORT_V1


def read_figure_state(store, result, *, archive=False):
    """Read archived v1 artifacts without making them modern generation cache hits."""
    from app.domain.analysis_sources import statistics_engine
    renderer=figure_renderer(result)
    state=store.figure_state(result,renderer,statistics_engine(result))
    state['generation_compatible']=True
    if (archive and state['figure'] is None and result.get('schema_version')==2 and renderer==PLOT_V2):
        previous=store.figure_state(result,PLOT_V1,statistics_engine(result))
        if previous['figure'] is not None:
            if previous['figure'].get('engine',{}).get('id')!=PLOT_V1:
                raise StorageError('source_conflict','历史图表的保存版本不一致。',409)
            state={**previous,'generation_compatible':False}
    return state


def verification_note(language, *, explanation=False):
    if explanation:
        return ('数值与事实引用已由程序填入并核对；语义和研究适用性仍需人工审阅。' if language == 'zh-CN' else
                'Values and fact references were inserted and checked locally; meaning and research applicability require review.')
    return ('结构化数值、标签及图注已核对；图片视觉内容仍需人工确认。' if language == 'zh-CN' else
            'Structured values, labels and captions were checked; image pixels still require visual review.')


def figure_metadata(result, expected, provenance, *, external=None, created_at=None):
    from datetime import datetime, timezone
    language = artifact_language(result)
    saved = {**expected, 'analysis_run_id': result['id'], 'file_id': result['file_id'],
        'source_sha256': result['source_sha256'], 'setup_revision': result['setup_revision'],
        'figure_number': 1, 'language': language, 'created_at': created_at or datetime.now(timezone.utc).isoformat(),
        'engine': {'id': figure_renderer(result), 'provider': 'openai_code_interpreter', 'model': provenance['model']},
        'method': ({'id':result['statistics']['method'],'verification_scope':expected['plot_config']['verification_scope']} if modeling_artifact(result) else
                  {'id':result['statistics']['method'], 'design':result['statistics']['design'],
                    'inference_displayed':False} if comparison_artifact(result) else
                  {'id': result['statistics']['method'], 'mode': result['statistics']['mode'],
                    'inference_displayed': False} if result.get('result_type') == 'correlation' else
                   {'whisker_iqr_multiplier': 1.5, 'quantile_method': 'linear_inclusive', 'outliers_removed': False}),
        'verification': {'status': 'matched', 'note': verification_note(language)}, 'provenance': provenance}
    if modern_artifact(result):
        saved.update(schema_version=4 if modeling_artifact(result) else 3 if comparison_artifact(result) else 2, figure_kind=figure_kind(result), plan_sha256=result.get('analysis_plan', {}).get('sha256'))
    if external is not None:
        saved['external_processing'] = external
    if 'source' in result:
        saved['source'] = result['source']
    return saved


def explanation_metadata(result, figure, sections, payload, provenance, *, created_at=None):
    from datetime import datetime, timezone
    from app.domain.explanation_content import limitations_for
    from app.domain.external_processing import digest
    language = payload['language']
    version = saved_explanation_version(figure)
    saved = {'analysis_run_id': result['id'], 'file_id': result['file_id'], 'figure_id': figure['id'],
        'figure_sha256': figure['sha256'], 'source_sha256': result['source_sha256'],
        'setup_revision': result['setup_revision'], 'language': language,
        'created_at': created_at or datetime.now(timezone.utc).isoformat(), 'sections': sections,
        'limitations': limitations_for(result, language), 'engine': {'id': version, 'provider': 'openai', 'model': provenance['model']},
        'verification': {'status': 'references_checked', 'note': verification_note(language, explanation=True)},
        'provenance': {**provenance, 'prompt_version': version, 'input_sha256': digest(payload)}}
    if version in (EXPLANATION_V2, EXPLANATION_V3, EXPLANATION_V4):
        saved.update(schema_version=4 if version==EXPLANATION_V4 else 3 if version == EXPLANATION_V3 else 2, plan_sha256=result.get('analysis_plan', {}).get('sha256'))
    if 'source' in result:
        saved['source'] = result['source']
    return saved
