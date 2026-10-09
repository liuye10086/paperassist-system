"""Local Word export of the version-bound analysis, figure and explanation."""

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
        if (figure['analysis_run_id'] != result['id'] or figure['file_id'] != result['file_id']
                or figure['setup_revision'] != result['setup_revision'] or figure['source_sha256'] != result['source_sha256']
                or figure['engine']['id'] != RENDERER or figure['verification']['status'] != 'matched'
                or explanation['analysis_run_id'] != result['id'] or explanation['figure_id'] != figure['id']
                or explanation['setup_revision'] != result['setup_revision'] or explanation['source_sha256'] != result['source_sha256']
                or explanation['figure_sha256'] != figure['sha256'] or explanation['engine']['id'] != EXPLANATION_VERSION
                or explanation['verification']['status'] != 'references_checked' or explanation['language'] != 'zh-CN'):
            invalid()
        from app.domain.external_material import explanation_material
        external = explanation['provenance'].get('external_processing')
        payload, _ = explanation_material(result, figure, external)
        if explanation['provenance']['input_sha256'] != digest(payload):
            invalid()
        if [section['key'] for section in explanation['sections']] != list(SECTIONS):
            invalid()
        for section in explanation['sections']:
            if section['title'] != SECTIONS[section['key']] or not isinstance(section['text'], str) or not section['text'].strip():
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


def context(store, project_id, file_id, run_id):
    result = result_source(store, project_id, file_id, run_id)
    state = store.figure_state(result, RENDERER, STATISTICS_ENGINE)
    figure = state.pop('figure')
    explanation = ExplanationStore(store).saved(figure['id']) if figure else None
    issues = []
    if not state['is_current']:
        issues.append('当前结果属于旧配置，请先完成当前配置的统计、图表和解释。')
    if not figure:
        issues.append('请先生成当前统计结果的图表。')
    if not explanation:
        issues.append('请先生成当前图表的 AI 分析解释。')
    if figure:
        store.figure_png(figure)
    if figure and explanation:
        validate_sources(result, figure, explanation)
    report = ReportStore(store).saved(explanation['id']) if explanation else None
    if report:
        ReportStore(store).content(report)
    project = store.project(project_id)
    snapshot = {'project': {key: project[key] for key in ('id', 'name', 'research_topic', 'project_type', 'created_at')},
                'result': result, 'figure': figure, 'explanation': explanation}
    return snapshot, {**state, 'ready': not issues, 'issues': issues, 'report': report}


def get_report(project_id: str, file_id: str, run_id: str, store: ProjectStore):
    return context(store, project_id, file_id, run_id)[1]


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
    else:
        metadata = repository.metadata(snapshot)
        try:
            content = build_report(snapshot, metadata, store.figure_png(snapshot['figure']))
        except (ValueError, UnrecognizedImageError, UnexpectedEndOfFileError) as exc:
            raise StorageError('report_render_failed', '无法生成 Word 报告，请检查已保存的图片和文字内容后重试。', 422) from exc
    saved, created = repository.save(snapshot, metadata, content)
    status_code = 201 if created else 200
    return ({**state, 'report': saved}), status_code
