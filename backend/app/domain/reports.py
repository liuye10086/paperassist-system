"""Local Word export of the version-bound analysis, figure and explanation."""

from app.domain.analysis_sources import statistics_engine
from app.adapters.storage import ProjectStore



from docx.image.exceptions import UnrecognizedImageError, UnexpectedEndOfFileError
from pydantic import Field

from app.domain.boxplot import RENDERER, STATISTICS_ENGINE, result_source
from app.domain.descriptive import RunRequest
from app.domain.explanation_content import SECTIONS, VERSION as EXPLANATION_VERSION, build_payload
from app.adapters.explanation_store import ExplanationStore
from app.adapters.report_docx import build_report
from app.adapters.report_store import ReportStore, digest
from app.core.exceptions import StorageError



class ReportRequest(RunRequest):
    figure_id: str = Field(min_length=1, max_length=64)
    explanation_id: str = Field(min_length=1, max_length=64)


def validate_sources(result, figure, explanation):
    def invalid():
        raise StorageError('report_source_changed', '图表、解释与统计结果的来源或核对记录不一致，请恢复数据或重新生成当前版本。', 409)
    try:
        from app.domain.artifact_contracts import (PLOT_V1, PLOT_V2, PLOT_V3, PLOT_V4, EXPLANATION_V1, EXPLANATION_V2,
            artifact_language, figure_kind, section_titles,figure_renderer,saved_explanation_version)
        renderer = figure['engine']['id']
        modern = renderer in (PLOT_V2,PLOT_V3,PLOT_V4)
        comparison=result.get('result_type')=='group_comparison'
        modeling=result.get('result_type') in ('regression','roc','survival')
        artifact_schema=4 if modeling else 3 if comparison else 2
        version = saved_explanation_version(figure)
        language = artifact_language(result) if modern else 'zh-CN'
        titles = section_titles(language)
        if renderer not in (PLOT_V1,PLOT_V2,PLOT_V3,PLOT_V4) or (result.get('schema_version') in (3,4,5) and not modern) or (comparison or modeling) and renderer!=figure_renderer(result):
            invalid()
        if modern and (figure.get('schema_version') != artifact_schema or explanation.get('schema_version') != artifact_schema
                or figure['language'] != language or figure.get('figure_kind') != figure_kind(result)
                or figure.get('plan_sha256') != result.get('analysis_plan',{}).get('sha256')
                or explanation.get('plan_sha256') != result.get('analysis_plan',{}).get('sha256')):
            invalid()
        if modern and result.get('result_type') == 'correlation':
            stats=result['statistics']
            numeric={'n':stats['n'],'coefficient':stats['coefficient']} if stats['mode']=='pair' else {'n':stats['n'],'matrix':stats['matrix']}
            if (figure.get('correlation_method') != stats['method'] or figure.get('mode') != stats['mode']
                    or figure.get('statistics') != numeric or figure['method'].get('id') != stats['method']
                    or figure['method'].get('mode') != stats['mode'] or figure['method'].get('inference_displayed') is not False
                    or figure['plot_config'].get('inference_displayed') is not False
                    or figure['plot_config'].get('regression_line') is not False):
                invalid()
            from app.domain.external_material import contract_labels
            labels=contract_labels(result,None,figure.get('external_processing'),'boxplot')
            variables=[{**variable,'name':labels['field:'+variable['column']],'unit':labels['unit:'+variable['column']]}
                       for variable in result['variables']]
            if figure.get('variables') != variables:
                invalid()
        if modeling:
            from app.domain.external_material import contract_labels
            from app.domain.modeling_material import projection
            labels=contract_labels(result,None,figure.get('external_processing'),'boxplot')
            if figure.get('statistics')!=projection(result,labels) or figure['method']!={'id':result['statistics']['method'],'verification_scope':figure['plot_config']['verification_scope']}: invalid()
        if comparison:
            from app.domain.external_material import contract_labels
            labels=contract_labels(result,None,figure.get('external_processing'),'boxplot')
            variables=[{**variable,'name':labels['field:'+variable['column']],'unit':labels['unit:'+variable['column']]}
                       for variable in result['variables']]
            metrics=('n','mean','std','min','q1','median','q3','max','iqr')
            groups=[{'label':labels[f'group:{index}'],'statistics':{key:group['statistics'][key] for key in metrics}} for index,group in enumerate(result['groups'])]
            if (figure.get('variables')!=variables or figure.get('groups')!=groups
                    or figure.get('statistics')!={'sample_sizes':result['statistics']['sample_sizes']}
                    or figure['method'].get('id')!=result['statistics']['method']
                    or figure['method'].get('design')!=result['statistics']['design']
                    or figure['method'].get('inference_displayed') is not False
                    or figure['plot_config'].get('inference_displayed') is not False): invalid()
            if result['statistics']['design']=='paired' and (figure['paired_summary']['n_pairs']!=result['check']['valid_count']
                    or figure['plot_config'].get('paired_direction')!='before_minus_after'): invalid()
        if (figure.get('source') != result.get('source') or explanation.get('source') != result.get('source')
                or figure['analysis_run_id'] != result['id'] or figure['file_id'] != result['file_id']
                or figure['setup_revision'] != result['setup_revision'] or figure['source_sha256'] != result['source_sha256']
                or figure['verification']['status'] != 'matched'
                or explanation['analysis_run_id'] != result['id'] or explanation['figure_id'] != figure['id']
                or explanation['setup_revision'] != result['setup_revision'] or explanation['source_sha256'] != result['source_sha256']
                or explanation['figure_sha256'] != figure['sha256'] or explanation['engine']['id'] != version
                or explanation['verification']['status'] != 'references_checked' or explanation['language'] != language):
            invalid()
        from app.domain.external_material import explanation_material
        external = explanation['provenance'].get('external_processing')
        payload, _ = explanation_material(result, figure, external)
        if explanation['provenance']['input_sha256'] != digest(payload):
            invalid()
        if [section['key'] for section in explanation['sections']] != list(SECTIONS):
            invalid()
        for section in explanation['sections']:
            if section['title'] != titles[section['key']] or not isinstance(section['text'], str) or not section['text'].strip():
                invalid()
            refs = {evidence['key'] for evidence in section['evidence']}
            if not set(payload['required_references'][section['key']]).issubset(refs):
                invalid()
            for evidence in section['evidence']:
                fact = payload['facts'][evidence['key']]
                if evidence != {'key': evidence['key'], 'label': fact['label'], 'value': fact['value']}:
                    invalid()
    except (KeyError, TypeError, ValueError, StorageError):
        invalid()


def context(store, project_id, file_id, run_id, *, archive=False):
    result = result_source(store, project_id, file_id, run_id)
    from app.domain.artifact_contracts import read_figure_state, saved_explanation_version, saved_report_version
    state = read_figure_state(store,result,archive=archive)
    figure = state.pop('figure')
    explanation = ExplanationStore(store).saved(figure['id'],saved_explanation_version(figure)) if figure else None
    issues = []
    if not state['is_current']:
        issues.append('当前结果属于旧配置，请先完成当前配置的统计、图表和解释。')
    if not figure:
        issues.append('请先生成当前统计结果的图表。')
    if not explanation:
        issues.append('请先生成当前图表的 AI 分析解释。')
    if figure:
        if result.get('result_type') in ('group_comparison','regression','roc','survival'):
            from app.domain.comparison_material import validate_figure_source
            if result.get('result_type') in ('regression','roc','survival'):
                from app.domain.modeling_material import validate_figure_source
            validate_figure_source(store,project_id,file_id,result,figure)
        store.figure_png(figure)
    if figure and explanation:
        validate_sources(result, figure, explanation)
    report = ReportStore(store).saved(explanation['id'],saved_report_version(explanation)) if explanation else None
    if report:
        if 'source' in result:
            report = ReportStore(store).by_id(project_id, file_id, run_id, report['id'])
        ReportStore(store).content(report)
    project = store.project(project_id)
    snapshot = {'project': {key: project[key] for key in ('id', 'name', 'research_topic', 'project_type', 'created_at')},
                'result': result, 'figure': figure, 'explanation': explanation,
                **({'source': result['source']} if 'source' in result else {})}
    from app.domain.dataset_processing import load_processing
    processing = load_processing(store, project_id, result.get('source', {}))
    if processing is not None: snapshot['processing'] = processing
    return snapshot, {**state, 'ready': not issues, 'issues': issues, 'report': report}


def get_report(project_id: str, file_id: str, run_id: str, store: ProjectStore):
    return context(store, project_id, file_id, run_id,archive=True)[1]


def generate_report(project_id: str, file_id: str, run_id: str, request: ReportRequest, store: ProjectStore):
    status_code = 200
    snapshot, state = context(store, project_id, file_id, run_id)
    if (not state['ready'] or request.expected_revision != snapshot['result']['setup_revision']
            or request.figure_id != snapshot['figure']['id'] or request.explanation_id != snapshot['explanation']['id']):
        raise StorageError('report_source_conflict', '请先保存配置并完成同一版本的统计、图表和解释，再重新读取报告状态。', 409)
    repository = ReportStore(store)
    # The transactional save path also checks cached requests, closing the revision race.
    if state['report']:
        metadata = state['report']
        content = repository.content(metadata)
    elif pending := repository.pending(snapshot):
        metadata, content = pending
    else:
        metadata = repository.metadata(snapshot)
        try:
            content = build_report(snapshot, metadata, store.figure_png(snapshot['figure']))
        except (ValueError, UnrecognizedImageError, UnexpectedEndOfFileError) as exc:
            raise StorageError('report_render_failed', '无法生成 Word 报告，请检查已保存的图片和文字内容后重试。', 422) from exc
    saved, created = repository.save(snapshot, metadata, content)
    status_code = 201 if created else 200
    return ({**state, 'report': saved}), status_code
