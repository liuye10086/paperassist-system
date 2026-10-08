"""Explain saved statistics and figure metadata without inventing new calculations."""

from app.adapters.storage import ProjectStore


from datetime import datetime, timezone
import hashlib
import json

from fastapi import HTTPException
from pydantic import Field

from app.domain.boxplot import RENDERER, STATISTICS_ENGINE, public_job, result_source
from app.domain.descriptive import RunRequest
from app.adapters.excel import fail
from app.domain.explanation_content import LIMITATIONS, VERSION, build_payload, render_explanation
from app.adapters.explanation_store import ExplanationStore
from app.adapters.openai_explanation import CloudExplanation
from app.core.exceptions import PlotError
from app.core.exceptions import StorageError
from app.adapters.storage import get_project_store
from app.core.errors import job_message



class ExplanationRequest(RunRequest):
    figure_id: str = Field(min_length=1, max_length=64)
    retry: bool = False


def context(store, project_id, file_id, run_id):
    result = result_source(store, project_id, file_id, run_id)
    state = store.figure_state(result, RENDERER, STATISTICS_ENGINE)
    figure = state.pop('figure')
    if figure:
        store.figure_png(figure)
    state['figure_id'] = figure['id'] if figure else None
    state['explanation'] = ExplanationStore(store).saved(figure['id']) if figure else None
    return result, figure, state


def recover_legacy_explanation(project_id: str, file_id: str, run_id: str, store: ProjectStore):
    result, figure, state = context(store, project_id, file_id, run_id)
    repository = ExplanationStore(store)
    job = repository.job(figure['id']) if figure else None
    if job and state['explanation'] and job['status'] != 'completed':
        job = repository.update_job(job['id'], status='completed', message='解释及事实引用已保存。', **job_message('task_completed'))
    if job and job['status'] == 'submitting' and (datetime.now(timezone.utc) - datetime.fromisoformat(job['created_at'])).total_seconds() > 180:
        job = repository.update_job(job['id'], status='uncertain', message='提交中断，尚未获得云端任务编号。无法确认是否已收费，请联系管理员核对，不能再次自动调用。', **job_message('task_uncertain'))
    if job and job['status'] == 'running' and not state['explanation']:
        try:
            if not state['is_current']:
                raise StorageError('setup_conflict', '配置已变化，请使用当前统计结果和图表生成解释。', 409)
            output = CloudExplanation(job['model']).fetch(job)
            if output is not None:
                payload = build_payload(result, figure)
                if payload != job['payload']:
                    raise StorageError('source_conflict', '生成期间数据或图表已变化，请重新读取结果。', 409)
                sections = render_explanation(output['draft'], payload)
                explanation = {'analysis_run_id': run_id, 'figure_id': figure['id'], 'figure_sha256': figure['sha256'],
                    'source_sha256': result['source_sha256'], 'setup_revision': result['setup_revision'],
                    'language': 'zh-CN', 'created_at': datetime.now(timezone.utc).isoformat(),
                    'sections': sections, 'limitations': LIMITATIONS,
                    'engine': {'id': VERSION, 'provider': 'openai', 'model': output['provenance']['model']},
                    'verification': {'status': 'references_checked',
                        'note': '数值与事实引用已由程序填入并核对；语义和研究适用性仍需人工审阅。'},
                    'provenance': {**output['provenance'], 'prompt_version': VERSION,
                        'input_sha256': hashlib.sha256(json.dumps(payload, ensure_ascii=False, allow_nan=False,
                            sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()}}
                state['explanation'] = repository.save(project_id, file_id, explanation)
                job = repository.update_job(job['id'], status='completed', message='解释及事实引用已核对并保存，请人工审阅初稿。', **job_message('task_completed'))
        except PlotError as exc:
            if exc.status == 503 or exc.code == 'openai_request_failed' and exc.status != 404:
                fail(exc.code, exc.message, exc.status, params=exc.params)
            job = repository.update_job(job['id'], status='failed', message=exc.message, **job_message(exc.code, exc.params))
        except StorageError as exc:
            if exc.status != 409:
                raise
            job = repository.update_job(job['id'], status='failed', message=exc.message, **job_message(exc.code, exc.params))
    state['job'] = public_job(job)
    return state


def get_explanation(project_id: str, file_id: str, run_id: str, store: ProjectStore):
    """Reading an explanation never contacts a model or advances a task."""
    from app.domain.explanation_tasks import get_explanation as read
    return read(project_id, file_id, run_id, store)


def generate(project_id: str, file_id: str, run_id: str, request: ExplanationRequest, store: ProjectStore):
    from app.domain.explanation_tasks import submit_explanation
    return submit_explanation(project_id, file_id, run_id, request, store)


def poll_pending_explanations():
    """Retrieve existing responses after restart; never start or retry a paid request."""
    store = get_project_store()
    repository = ExplanationStore(store)
    for pending in repository.pending():
        try:
            recover_legacy_explanation(pending['project_id'], pending['file_id'], pending['run_id'], store)
        except (HTTPException, StorageError) as exc:
            status = exc.status_code if isinstance(exc, HTTPException) else exc.status
            if status in (404, 409, 410, 422):
                repository.update_job(pending['job_id'], status='failed', message='原文件、图表或配置已不可用，后台无法保存解释。请检查项目数据。', **job_message('task_failed'))
