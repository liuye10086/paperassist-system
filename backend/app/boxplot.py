"""Versioned boxplots tied to verified, immutable descriptive-statistics results."""

from datetime import datetime, timezone
from fractions import Fraction
import json
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from .analysis import AnalysisSelection, Settings, Store, inspect_selection, source
from .descriptive import ENGINE as STATISTICS_ENGINE, RunRequest, summarize
from .excel import fail
from .openai_plot import CloudPlot, PlotError, PROMPT_VERSION, configuration, validate_output
from .storage import StorageError, get_project_store
from .errors import PUBLIC_CODES, job_message, safe_params

RENDERER = PROMPT_VERSION
router = APIRouter(prefix='/api/v1/projects/{project_id}/files/{file_id}/analysis-runs/{run_id}', tags=['箱线图'])


class PlotRequest(RunRequest):
    retry: bool = False


def plot_data(result, values, grouped_values):
    def series(label, observations):
        ordered = sorted(observations)
        def quantile(quarter):
            index, remainder = divmod((len(ordered) - 1) * quarter, 4)
            return ((4 - remainder) * Fraction(ordered[index]) + remainder * Fraction(ordered[min(index + 1, len(ordered) - 1)])) / 4
        q1, median, q3 = (quantile(q) for q in (1, 2, 3))
        lower, upper = q1 - (q3 - q1) * Fraction(3, 2), q3 + (q3 - q1) * Fraction(3, 2)
        inside = [v for v in ordered if lower <= v <= upper]
        outside = [v for v in ordered if v < lower or v > upper]
        whislo, whishi = Fraction(inside[0]), Fraction(inside[-1])
        points = sorted(set(outside))
        metrics = {'q1': q1, 'median': median, 'q3': q3, 'whislo': whislo, 'whishi': whishi}
        return {'label': label, 'n': len(ordered), **{k: float(v) for k, v in metrics.items()},
                'fliers': points, 'outlier_count': len(outside)}

    groups = [(('TRUE' if label else 'FALSE') if isinstance(label, bool) else str(label), data)
              for label, data in grouped_values.items()]
    plotted = [series(label, data) for label, data in groups] if groups else [series('总体', values)]
    numeric = result['numeric_name']
    unit = result['selection']['unit'] or '单位未填写'
    x_label = f'{numeric}（{unit}）'
    y_label = result['group_name'] or '分析范围'
    check = result['check']
    caption = (f'图 1. {numeric}箱线图。工作表：{result["selection"]["sheet_name"]}；'
        f'使用 {check["valid_count"]} 行完整记录，排除 {check["excluded_count"]} 行缺失记录。'
        'n 为各组有效记录数；箱体为 Q1–Q3，中线为中位数，分位数按 (n−1)p 线性插值。'
        '须端为 Q1−1.5×IQR 至 Q3+1.5×IQR 范围内最远观测值，IQR = Q3−Q1。'
        '空心圆为范围外观测，重合点可能重叠；这些值仍参与统计，未剔除离群值。'
        '单条或常数数据呈重合线。未进行显著性检验。')
    return {'analysis_run_id': result['id'], 'file_id': result['file_id'], 'source_sha256': result['source_sha256'],
            'setup_revision': result['setup_revision'], 'figure_number': 1, 'language': 'zh-CN',
            'title': f'图 1. {numeric}箱线图', 'x_label': x_label, 'y_label': y_label, 'caption': caption,
            'series': plotted,
            'method': {'whisker_iqr_multiplier': 1.5, 'quantile_method': 'linear_inclusive', 'outliers_removed': False}}


def result_source(store, project_id, file_id, run_id):
    record, _ = source(store, project_id, file_id)
    result = store.analysis_result_by_id(project_id, file_id, run_id)
    if result['source_sha256'] != record['sha256']:
        fail('source_conflict', '统计结果与原文件不一致，请重新保存配置并执行统计。', 409)
    return result


@router.get('/boxplot')
def get_boxplot(project_id: str, file_id: str, run_id: str, store: Store):
    result = result_source(store, project_id, file_id, run_id)
    state = store.figure_state(result, RENDERER, STATISTICS_ENGINE)
    if state['figure']:
        store.figure_png(state['figure'])
    job = store.figure_job(run_id, RENDERER)
    if job and state['figure'] and job['status'] != 'completed':
        job = store.update_figure_job(job['id'], status='completed', message='云端图表已下载并保存。', **job_message('task_completed'))
    if job and job['status'] == 'submitting' and (datetime.now(timezone.utc) - datetime.fromisoformat(job['created_at'])).total_seconds() > 180:
        job = store.update_figure_job(job['id'], status='uncertain', message='提交中断，尚未获得云端任务编号。无法确认是否已收费；确认后可手动重试。', **job_message('task_uncertain'))
    if job and job['status'] == 'running' and not state['figure']:
        try:
            output = CloudPlot(job['model']).fetch(job)
            if output is not None:
                validate_output(output, job['expected'])
                figure = {**job['expected'], 'file_id': file_id, 'setup_revision': result['setup_revision'],
                    'figure_number': 1, 'language': 'zh-CN', 'created_at': datetime.now(timezone.utc).isoformat(),
                    'engine': {'id': RENDERER, 'provider': 'openai_code_interpreter', 'model': output['provenance']['model']},
                    'method': {'whisker_iqr_multiplier': 1.5, 'quantile_method': 'linear_inclusive', 'outliers_removed': False},
                    'provenance': output['provenance'],
                    'verification': {'status': 'matched', 'note': '结构化数值、标签及图注已核对；图片视觉内容仍需人工确认。'}}
                state['figure'] = store.save_figure(project_id, file_id, figure, output['png'])
                job = store.update_figure_job(job['id'], status='completed', message='云端计算核对通过，图片已下载并保存。', **job_message('task_completed'))
        except PlotError as exc:
            if exc.status == 503 or exc.code == 'openai_request_failed' and exc.status != 404:
                # Keep the response ID for retrying retrieval without submitting another paid run.
                fail(exc.code, exc.message, exc.status, params=exc.params)
            job = store.update_figure_job(job['id'], status='failed', message=exc.message, **job_message(exc.code, exc.params))
        except StorageError as exc:
            if exc.status != 409:
                raise
            job = store.update_figure_job(job['id'], status='failed', message='执行期间配置已修改，云端图片未保存。请执行新配置后生成。', **job_message('setup_conflict'))
    state['job'] = public_job(job)
    return state


def public_job(job):
    if not job:
        return None
    result = {key: job.get(key) for key in ('id', 'status', 'message', 'response_id', 'created_at')}
    code = job.get('message_code')
    if not isinstance(code, str) or code not in PUBLIC_CODES:
        status = job.get('status')
        code = 'task_' + status if status in ('submitting', 'running', 'completed', 'uncertain', 'failed') else 'task_unknown'
    result.update(message_code=code, message_params=safe_params(code, job.get('message_params')))
    return result


def poll_pending_figures():
    """Recover persisted jobs without relying on an open browser; never submit new API work."""
    if not configuration()['configured']:
        return
    store = get_project_store()
    for pending in store.pending_figures():
        try:
            get_boxplot(pending['project_id'], pending['file_id'], pending['run_id'], store)
        except (HTTPException, StorageError) as exc:
            status = exc.status_code if isinstance(exc, HTTPException) else exc.status
            if status in (404, 409, 410, 422):
                store.update_figure_job(pending['job_id'], status='failed', message='原文件或配置已不可用，后台无法保存图表。请检查项目数据。', **job_message('task_failed'))
            # Temporary network/storage errors keep the response ID for a later poll.


@router.get('/boxplot/image')
def image(project_id: str, file_id: str, run_id: str, store: Store, download: bool = False):
    result = result_source(store, project_id, file_id, run_id)
    state = store.figure_state(result, RENDERER, STATISTICS_ENGINE)
    figure = state['figure']
    if figure is None:
        fail('figure_not_found', '此结果尚未生成箱线图。', 404)
    content = store.figure_png(figure)
    return Response(content, media_type='image/png', headers={
        'Content-Disposition': f'{"attachment" if download else "inline"}; filename="boxplot-{figure["id"]}.png"',
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


@router.get('/figures/{figure_id}/download')
def download_saved_figure(project_id: str, file_id: str, run_id: str, figure_id: str, store: Store):
    result = result_source(store, project_id, file_id, run_id)
    with store.connection() as db:
        row = db.execute('SELECT figure_json FROM figures WHERE id=%s AND analysis_run_id=%s',
                         (figure_id, run_id)).fetchone()
    if row is None:
        fail('figure_not_found', '此统计结果中没有该图表。', 404)
    figure = json.loads(row['figure_json'])
    if (figure['id'] != figure_id or figure['analysis_run_id'] != run_id or figure['file_id'] != file_id
            or figure['source_sha256'] != result['source_sha256']):
        fail('source_conflict', '图表与统计结果的来源不一致。', 409)
    return Response(store.figure_png(figure), media_type='image/png', headers={
        'Content-Disposition': "attachment; filename*=UTF-8''" + quote(f'boxplot-{figure_id}.png', safe=''),
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


@router.post('/boxplot')
def generate(project_id: str, file_id: str, run_id: str, request: PlotRequest, store: Store, settings: Settings, response: Response):
    result = result_source(store, project_id, file_id, run_id)
    state = store.figure_state(result, RENDERER, STATISTICS_ENGINE)
    if not state['is_current'] or request.expected_revision != result['setup_revision']:
        fail('setup_conflict', '配置或统计结果已变化，请重新载入配置并执行统计后生成箱线图。', 409)
    if state['figure']:
        store.figure_png(state['figure'])
        state['job'] = public_job(store.figure_job(run_id, RENDERER))
        return state
    job = store.figure_job(run_id, RENDERER)
    if job and (job['status'] not in ('failed', 'uncertain') or not request.retry):
        state['job'] = public_job(job)
        response.status_code = 202 if job['status'] in ('running', 'submitting') else 200
        return state
    config = configuration()
    if not config['configured']:
        fail('openai_not_configured', config['message'], 503)
    selection = AnalysisSelection(**result['selection'])
    _, profile, scan = inspect_selection(store, project_id, file_id, settings, selection.sheet_name, selection, collect_values=True)
    check = scan.check(profile)
    if not check.ready:
        fail('invalid_analysis_selection', ' '.join(check.issues))
    groups = [{'label': ('TRUE' if label else 'FALSE') if isinstance(label, bool) else str(label),
               'statistics': summarize(data)} for label, data in scan.grouped_values.items()]
    if check.model_dump() != result['check'] or summarize(scan.values) != result['overall'] or groups != result['groups']:
        fail('result_mismatch', '原始数据复算与已保存统计结果不一致，请另存配置并重新执行统计。', 409)
    figure = plot_data(result, scan.values, scan.grouped_values)
    labels = {key: figure[key] for key in ('title', 'x_label', 'y_label', 'caption')}
    # Reject unbounded labels before sending data or creating a billable request.
    if any(len(value) > 160 for value in [result['numeric_name'], result['group_name'] or '', *[g['label'] for g in groups]]):
        fail('plot_label_too_long', '字段名或分组名称超过 160 字符，请简化原文件中的标签后重新上传。', params={'max_chars': 160})
    metrics = ('n', 'mean', 'std', 'min', 'q1', 'median', 'q3', 'max', 'iqr')
    expected = {'analysis_run_id': result['id'], 'source_sha256': result['source_sha256'], **labels,
        'overall': {k: result['overall'][k] for k in metrics},
        'groups': [{'label': g['label'], 'statistics': {k: g['statistics'][k] for k in metrics}} for g in groups],
        'series': figure['series']}
    payload = {'analysis_run_id': result['id'], 'source_sha256': result['source_sha256'], 'labels': labels,
               'values': scan.values, 'groups': [{'label': group['label'], 'values': data}
                    for group, data in zip(groups, scan.grouped_values.values())]}
    job, created = store.begin_figure_job(result, RENDERER, payload, expected, config['model'], request.retry)
    if created:
        try:
            response_id = CloudPlot(config['model']).start(payload, job['id'],
                lambda container_id: store.update_figure_job(job['id'], container_id=container_id))
            job = store.update_figure_job(job['id'], response_id=response_id, status='running', message='OpenAI 正在运行 Python 分析并生成箱线图。', **job_message('task_running'))
        except PlotError as exc:
            job = store.update_figure_job(job['id'], status='uncertain' if exc.uncertain else 'failed', message=exc.message, **job_message(exc.code, exc.params))
    state['job'] = public_job(job)
    response.status_code = 202 if job['status'] in ('running', 'submitting') else 200
    return state
