"""Versioned boxplots tied to verified, immutable descriptive-statistics results."""

from app.adapters.storage import ProjectStore
from app.core.config import ExcelSettings


from datetime import datetime, timezone
from fractions import Fraction

from fastapi import HTTPException

from app.domain.analysis import AnalysisSelection, inspect_selection, source
from app.domain.descriptive import ENGINE as STATISTICS_ENGINE, RunRequest, summarize
from app.adapters.excel import fail
from app.adapters.openai_plot import CloudPlot, PROMPT_VERSION, configuration, validate_output
from app.core.exceptions import PlotError
from app.core.exceptions import StorageError
from app.adapters.storage import get_project_store
from app.core.errors import PUBLIC_CODES, job_message, safe_params

RENDERER = PROMPT_VERSION


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


def recover_legacy_boxplot(project_id: str, file_id: str, run_id: str, store: ProjectStore):
    result = result_source(store, project_id, file_id, run_id)
    state = store.figure_state(result, RENDERER, STATISTICS_ENGINE)
    if state['figure']:
        store.figure_png(state['figure'])
    job = store.figure_job(run_id, RENDERER)
    if job and state['figure'] and job['status'] != 'completed':
        job = store.update_figure_job(job['id'], status='completed', message='云端图表已下载并保存。', **job_message('task_completed'))
    if job and job['status'] == 'submitting' and (datetime.now(timezone.utc) - datetime.fromisoformat(job['created_at'])).total_seconds() > 180:
        job = store.update_figure_job(job['id'], status='uncertain', message='提交中断，尚未获得云端任务编号。请联系管理员核对，不能再次自动调用。', **job_message('task_uncertain'))
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
    store = get_project_store()
    for pending in store.pending_figures():
        try:
            recover_legacy_boxplot(pending['project_id'], pending['file_id'], pending['run_id'], store)
        except (HTTPException, StorageError) as exc:
            status = exc.status_code if isinstance(exc, HTTPException) else exc.status
            if status in (404, 409, 410, 422):
                store.update_figure_job(pending['job_id'], status='failed', message='原文件或配置已不可用，后台无法保存图表。请检查项目数据。', **job_message('task_failed'))
            # Temporary network/storage errors keep the response ID for a later poll.






def get_boxplot(project_id: str, file_id: str, run_id: str, store: ProjectStore):
    from app.domain.plot_tasks import get_boxplot as read_plot
    return read_plot(project_id, file_id, run_id, store)


def generate(project_id: str, file_id: str, run_id: str, request: PlotRequest, store: ProjectStore, settings: ExcelSettings):
    from app.domain.plot_tasks import submit_boxplot
    return submit_boxplot(project_id, file_id, run_id, request, store)
