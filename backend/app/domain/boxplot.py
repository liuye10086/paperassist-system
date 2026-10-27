"""Versioned boxplots tied to verified, immutable descriptive-statistics results."""

from app.domain.analysis_sources import statistics_engine
from app.adapters.storage import ProjectStore
from app.core.config import ExcelSettings


from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
from uuid import uuid5,NAMESPACE_URL

from fastapi import HTTPException
from pydantic import Field

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
    external_processing: dict | None = None
    retry: bool = False
    expected_predecessor_id: str | None = Field(default=None, min_length=1, max_length=64, pattern=r'^\S+$')
    expected_predecessor_revision: int | None = Field(default=None, ge=1, le=2_147_483_647)


def plot_data(result, values, grouped_values, *, frozen_series=None):
    def series(label, observations):
        from app.domain.regression.bounded import compute_bounded
        return {'label':label, **compute_bounded('boxplot_series',observations,{})}

    groups = [(('TRUE' if label else 'FALSE') if isinstance(label, bool) else str(label), data)
              for label, data in grouped_values.items()]
    from copy import deepcopy
    plotted = deepcopy(frozen_series) if frozen_series is not None else ([series(label, data) for label, data in groups] if groups else [series('总体', values)])
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
    figure = {'analysis_run_id': result['id'], 'file_id': result['file_id'], 'source_sha256': result['source_sha256'],
            'setup_revision': result['setup_revision'], 'figure_number': 1, 'language': 'zh-CN',
            'title': f'图 1. {numeric}箱线图', 'x_label': x_label, 'y_label': y_label, 'caption': caption,
            'series': plotted,
            'method': {'whisker_iqr_multiplier': 1.5, 'quantile_method': 'linear_inclusive', 'outliers_removed': False}}
    from app.domain.artifact_contracts import artifact_language
    if artifact_language(result) == 'en':
        from app.domain.external_material import plot_labels
        labels = {'numeric_name':result['numeric_name'], 'unit':result['selection']['unit'] or ''}
        if result['group_name']: labels['group_name'] = result['group_name']
        figure.update(plot_labels(result, labels), language='en')
        if not result['groups']: figure['series'][0]['label'] = 'Overall'
    return figure


def result_source(store, project_id, file_id, run_id):
    result = store.analysis_result_by_id(project_id, file_id, run_id)
    if 'source' in result:
        from app.domain.dataset_analysis import load_dataset
        record, _, _ = load_dataset(store, project_id, file_id, result['source']['dataset_id'], expected_source=result['source'])
    else:
        record, _ = source(store, project_id, file_id)
    if result['source_sha256'] != record['sha256']:
        fail('source_conflict', '统计结果与原文件不一致，请重新保存配置并执行统计。', 409)
    return result


def _legacy_identity(job):
    return hashlib.sha256(json.dumps({k:job[k] for k in ('id','analysis_run_id','response_id','container_id','model','payload','expected')},sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def _legacy_owner(db,store,project_id):
    row=db.execute('SELECT p.owner_id FROM projects p JOIN users u ON u.id=p.owner_id AND u.active WHERE p.id=%s',(project_id,)).fetchone()
    if not row or store.owner_id is not None and row['owner_id']!=store.owner_id:
        raise StorageError('project_not_found','项目不存在或不可访问。',404)


def require_legacy_predecessor(store,project_id,result,job,*,db=None):
    """Same latest-predecessor rule at the HTTP gate and final serialized writer."""
    from app.adapters.task_store import TaskStore,source_conflict
    from app.domain.plot_tasks import matching_task
    owner=store.owner_id
    if owner is None:
        if db is None:raise source_conflict()
        owner=db.execute('SELECT owner_id FROM projects WHERE id=%s',(project_id,)).fetchone()['owner_id']
    modern=matching_task(TaskStore(owner,config=store.db_config),project_id,result,db=db)
    if modern and datetime.fromisoformat(modern['created_at'])>=datetime.fromisoformat(job['created_at']):raise source_conflict()


def _legacy_storage(store,project_id,file_id,result,job,*,explicit=False):
    from app.domain.storage_governance import service as storage
    from app.domain.storage_governance.candidates import FIGURE_CAPACITY,_present,read_descriptor,_disk_guard,candidate_recovery_mode
    identifier=str(uuid5(NAMESPACE_URL,'paperassist:legacy-figure:'+job['id']))
    with store.connection(write=True) as db:
        _legacy_owner(db,store,project_id);store.require_analysis_revision(db,file_id,result['setup_revision'])
        require_legacy_predecessor(store,project_id,result,job,db=db)
        if storage.reconcile_intents(db,store.directory):raise storage.invalid()
        hold=db.execute('SELECT * FROM storage_reservations WHERE project_id=%s AND operation_key=%s',(project_id,'legacy-figure:'+job['id'])).fetchone()
        identity=_legacy_identity(job)
        if hold:
            if hold['task_id']!=job['id'] or hold['candidate_json']['source_identity']!=identity or hold['object_key']!='figures/'+identifier+'.png':raise storage.invalid()
            mode=candidate_recovery_mode(store.directory,hold,business_candidate=job.get('figure_candidate') is not None)
            if mode=='blocked' or mode=='original_response' and hold['sha256'] and (not explicit or not job.get('response_id')):raise storage.invalid()
            if hold['sha256'] and mode=='local_candidate':
                document=read_descriptor(store.directory,hold)
                if document.get('job_id')!=job['id'] or document.get('source_identity')!=identity:raise storage.invalid()
                candidate=document.get('candidate')
                if not isinstance(candidate,dict) or candidate.get('id')!=identifier:raise storage.invalid()
                if job.get('figure_candidate') not in (None,candidate):raise storage.invalid()
                job={**job,'figure_candidate':candidate,'storage_reservation_id':hold['id']}
                db.execute('UPDATE figure_jobs SET job_json=%s WHERE id=%s',(json.dumps(job,ensure_ascii=False,allow_nan=False),job['id']))
            if hold['state']=='unknown' and not explicit:raise storage.invalid()
            if explicit:
                storage._scope_check(db,storage._project(db,project_id),0,allow_attributed_unknown=True)
                if mode=='original_response':_disk_guard(db,store.directory,0)
                if not hold['sha256']:
                    db.execute("UPDATE storage_reservations SET state='reserved' WHERE id=%s",(hold['id'],))
        else:
            hold=storage.admit_candidate(db,store.directory,project_id,'legacy-figure:'+job['id'],store.figures_dir/(identifier+'.png'),FIGURE_CAPACITY,
                task_id=job['id'],source_identity=identity)
        return dict(hold),job,identifier


def _legacy_block(store,job,exc):
    from app.domain.storage_governance import service as storage
    with store.connection(write=True) as db:
        storage.reconcile_intents(db,store.directory)
        saved=json.loads(db.execute('SELECT job_json FROM figure_jobs WHERE id=%s',(job['id'],)).fetchone()['job_json'])
        if saved['status']=='completed':return saved
        hold=db.execute('SELECT * FROM storage_reservations WHERE task_id=%s AND capacity_bytes IS NOT NULL',(job['id'],)).fetchone()
        if hold and hold['sha256'] and hold['candidate_json'].get('descriptor'):
            from app.domain.storage_governance.candidates import read_descriptor
            try:document=read_descriptor(store.directory,hold)
            except StorageError:document={}
            if document.get('job_id')==saved['id'] and document.get('source_identity')==_legacy_identity(saved):
                saved.update(figure_candidate=document['candidate'],storage_reservation_id=hold['id'])
        saved.update(status='failed',message='存储受限或状态待核对，请检查存储后显式恢复原图表。',**job_message(exc.code,exc.params))
        db.execute("UPDATE storage_reservations SET state='unknown' WHERE task_id=%s AND capacity_bytes IS NOT NULL AND state='reserved'",(job['id'],))
        db.execute('UPDATE figure_jobs SET job_json=%s WHERE id=%s',(json.dumps(saved,ensure_ascii=False,allow_nan=False),job['id']))
        return saved


def recover_legacy_boxplot(project_id: str, file_id: str, run_id: str, store: ProjectStore, *, explicit_recovery=False):
    result = result_source(store, project_id, file_id, run_id)
    state = store.figure_state(result, RENDERER, statistics_engine(result))
    if state['figure']:
        store.figure_png(state['figure'])
    job = store.figure_job(run_id, RENDERER)
    if job and state['figure'] and job['status'] != 'completed':
        job = store.update_figure_job(job['id'], status='completed', message='云端图表已下载并保存。', **job_message('task_completed'))
    if job and job['status'] == 'submitting' and (datetime.now(timezone.utc) - datetime.fromisoformat(job['created_at'])).total_seconds() > 180:
        job = store.update_figure_job(job['id'], status='uncertain', message='提交中断，尚未获得云端任务编号。请联系管理员核对，不能再次自动调用。', **job_message('task_uncertain'))
    if job and (job['status'] == 'running' or explicit_recovery and job['status']=='failed' and job.get('message_code','').startswith('storage_')) and not state['figure']:
        try:
            hold,job,figure_id=_legacy_storage(store,project_id,file_id,result,job,explicit=explicit_recovery)
            if job.get('figure_candidate'):
                from app.domain.storage_governance.candidates import _present
                from app.domain.storage_governance.service import invalid
                figure=job['figure_candidate'];provenance=figure.get('provenance') or {}
                if any(figure.get(k)!=v for k,v in job['expected'].items()) or figure.get('setup_revision')!=result['setup_revision'] or any(provenance.get(k)!=job[k] for k in ('response_id','container_id','model')):raise invalid()
                paths=_present(store.directory,hold)
                if len(paths)!=1:raise invalid()
                state['figure']=store.save_figure(project_id,file_id,figure,paths[0].read_bytes(),storage_candidate=hold['id'],explicit_recovery=explicit_recovery)
                job=store.update_figure_job(job['id'],status='completed',message='原图表已从本地候选恢复。',**job_message('task_completed'))
                state['job']=public_job(job,store=store)
                return state
            if explicit_recovery and job['status']=='failed':
                job=store.update_figure_job(job['id'],status='running',message='正在取回原云端回执。',**job_message('task_running'))
            output = CloudPlot(job['model']).fetch(job)
            if output is not None:
                validate_output(output, job['expected'])
                figure = {**job['expected'], 'file_id': file_id, 'setup_revision': result['setup_revision'],
                    'figure_number': 1, 'language': 'zh-CN', 'created_at': job['created_at'],
                    'engine': {'id': RENDERER, 'provider': 'openai_code_interpreter', 'model': output['provenance']['model']},
                    'method': {'whisker_iqr_multiplier': 1.5, 'quantile_method': 'linear_inclusive', 'outliers_removed': False},
                    'provenance': output['provenance'],
                    'verification': {'status': 'matched', 'note': '结构化数值、标签及图注已核对；图片视觉内容仍需人工确认。'}}
                figure.update(id=figure_id,size_bytes=len(output['png']),sha256=hashlib.sha256(output['png']).hexdigest())
                if any(output['provenance'].get(k)!=job[k] for k in ('response_id','container_id','model')):
                    from app.domain.storage_governance.service import invalid
                    raise invalid()
                from app.domain.storage_governance.service import capture_candidate
                from app.domain.storage_governance.candidates import FIGURE_DESCRIPTOR_FORMAT
                candidate_path=store.directory/'task-staging'/(figure_id+'.candidate')
                with store.connection(write=True) as db:
                    _legacy_owner(db,store,project_id);store.require_analysis_revision(db,file_id,result['setup_revision'])
                    current=json.loads(db.execute('SELECT job_json FROM figure_jobs WHERE id=%s',(job['id'],)).fetchone()['job_json'])
                    if _legacy_identity(current)!=_legacy_identity(job):raise StorageError('task_source_conflict','原图表任务已变化。',409)
                    document={'job_id':job['id'],'source_identity':_legacy_identity(job),'candidate':figure}
                    capture_candidate(db,store.directory,hold['id'],output['png'],[store.figures_dir/(figure_id+'.png'),candidate_path],source_identity=_legacy_identity(job),
                        descriptor=json.dumps(document,ensure_ascii=False,allow_nan=False,sort_keys=True).encode(),descriptor_path=store.directory/'task-staging'/(figure_id+'.json'),write_path=candidate_path,descriptor_format=FIGURE_DESCRIPTOR_FORMAT)
                    job={**current,'figure_candidate':figure,'storage_reservation_id':hold['id']}
                    db.execute('UPDATE figure_jobs SET job_json=%s WHERE id=%s',(json.dumps(job,ensure_ascii=False,allow_nan=False),job['id']))
                state['figure'] = store.save_figure(project_id, file_id, figure, output['png'],storage_candidate=hold['id'],explicit_recovery=explicit_recovery)
                job = store.update_figure_job(job['id'], status='completed', message='云端计算核对通过，图片已下载并保存。', **job_message('task_completed'))
        except PlotError as exc:
            from app.domain.plot_response import PlotVerificationError
            if isinstance(exc,PlotVerificationError):
                job=store.record_legacy_plot_mismatch(job['id'],differences=exc.differences,manifest=exc.manifest,provenance=exc.provenance)
                state['job']=public_job(job,store=store)
                return state
            if exc.status == 503 or exc.code == 'openai_request_failed' and exc.status != 404:
                # Keep the response ID for retrying retrieval without submitting another paid run.
                fail(exc.code, exc.message, exc.status, params=exc.params)
            job = store.update_figure_job(job['id'], status='failed', message=exc.message, **job_message(exc.code, exc.params))
        except StorageError as exc:
            if explicit_recovery and exc.code=='task_source_conflict':raise
            if exc.code.startswith('storage_'):
                _legacy_block(store,job,exc)
                raise
            if exc.status != 409 or exc.code.startswith('storage_'):
                raise
            job = store.update_figure_job(job['id'], status='failed', message='执行期间配置已修改，云端图片未保存。请执行新配置后生成。', **job_message('setup_conflict'))
        except OSError as exc:
            error=StorageError('storage_unavailable','图表候选写入失败，已有字节与原回执已保留，请检查存储后显式恢复。')
            _legacy_block(store,job,error)
            raise error from exc
    state['job'] = public_job(job,store=store)
    return state


def public_job(job,*,store=None):
    if not job:
        return None
    result = {key: job.get(key) for key in ('id', 'status', 'message', 'response_id', 'created_at')}
    code = job.get('message_code')
    if not isinstance(code, str) or code not in PUBLIC_CODES:
        status = job.get('status')
        code = 'task_' + status if status in ('submitting', 'running', 'completed', 'uncertain', 'failed') else 'task_unknown'
    result.update(message_code=code, message_params=safe_params(code, job.get('message_params')))
    if job.get('status')=='failed' and code.startswith('storage_') and job.get('response_id'):
        mode='blocked'
        if store is not None:
            from app.domain.storage_governance.candidates import candidate_recovery_mode
            with store.connection() as db:
                hold=db.execute('SELECT * FROM storage_reservations WHERE operation_key=%s AND task_id=%s',('legacy-figure:'+job['id'],job['id'])).fetchone()
                try:mode=candidate_recovery_mode(store.directory,hold,business_candidate=job.get('figure_candidate') is not None) if hold else 'original_response'
                except StorageError:pass
        result.update(recovery_mode=mode,recovery_requires_provider=mode=='original_response')
    else:result.update(recovery_mode=None,recovery_requires_provider=False)
    if isinstance(job.get('differences'),list): result['differences']=job['differences']
    return result


def poll_pending_figures():
    """Recover persisted jobs without relying on an open browser; never submit new API work."""
    store = get_project_store()
    for pending in store.pending_figures():
        try:
            recover_legacy_boxplot(pending['project_id'], pending['file_id'], pending['run_id'], store)
        except (HTTPException, StorageError) as exc:
            status = exc.status_code if isinstance(exc, HTTPException) else exc.status
            if (isinstance(exc, StorageError) and exc.code in PUBLIC_CODES
                    and exc.code.startswith('storage_')):
                # Capacity/accounting blocks do not invalidate the source or
                # authorize another paid job. Keep its original provider IDs.
                store.update_figure_job(pending['job_id'],status='failed',
                    message='存储受限或状态待核对，原云端任务标识已保留，请检查存储后恢复。',
                    **job_message(exc.code, exc.params))
            elif status in (404, 409, 410, 422):
                store.update_figure_job(pending['job_id'], status='failed', message='原文件或配置已不可用，后台无法保存图表。请检查项目数据。', **job_message('task_failed'))
            # Temporary network/storage errors keep the response ID for a later poll.






def get_boxplot(project_id: str, file_id: str, run_id: str, store: ProjectStore):
    from app.domain.plot_tasks import get_boxplot as read_plot
    return read_plot(project_id, file_id, run_id, store)


def generate(project_id: str, file_id: str, run_id: str, request: PlotRequest, store: ProjectStore, settings: ExcelSettings):
    from app.domain.plot_tasks import submit_boxplot
    return submit_boxplot(project_id, file_id, run_id, request, store)
