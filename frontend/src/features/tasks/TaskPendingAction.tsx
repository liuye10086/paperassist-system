import {RecommendationResult} from '../analysisPlan/AnalysisRecommendation'
import PreparationReview from '../datasetPreparation/PreparationReview'
import RequirementReview from '../analysisPlan/RequirementReview'
import AnalysisPlanReview from '../analysisPlan/AnalysisPlanReview'
import OcrReviewWorkspace from '../documents/OcrReviewWorkspace'
import { useEffect, useRef, useState } from 'react'
import { safeError, useI18n } from '../../shared/i18n'
import { isTask, sameInputVersion, type TaskOperation, type TaskView, type TaskWorkspace } from './taskTypes'
import { taskRequest, TaskRequestError } from './taskApi'

export default function TaskPendingAction({ workspace, blocked, onChanged }: {
  workspace: TaskWorkspace; blocked: boolean; onChanged: () => void
}) {
  const { t } = useI18n()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const request = useRef<AbortController | null>(null)
  const active = useRef(true)
  const replay = useRef<{ signature: string; key: string } | null>(null)
  const { task, wait } = workspace
  // A stale capability list must never turn an unknown submission into a resend.
  const submissionUnknown = task.error_code === 'model_submission_unknown' || task.reason_code === 'submission_unknown'
    || wait?.status === 'open' && (wait.kind === 'submission_unknown' || wait.error_code === 'model_submission_unknown')
  const actions = submissionUnknown ? [] : workspace.allowed_actions
  useEffect(() => { active.current = true; return () => { active.current = false; request.current?.abort() } }, [])
  async function perform(operation: TaskOperation) {
    if (task.origin === 'legacy' || task.revision === null || blocked || request.current || !actions.includes(operation)) return
    const controller = new AbortController(); request.current = controller
    const body = { operation, wait_id: wait?.id ?? null, expected_task_revision: task.revision, input_version: task.input_version }
    const signature = JSON.stringify(body)
    if (replay.current?.signature !== signature) replay.current = { signature, key: crypto.randomUUID() }
    setBusy(true); setError('')
    try {
      await taskRequest(`/api/v1/tasks/${encodeURIComponent(task.id)}/resume`, controller,
        (value): value is TaskView => isTask(value, task.project_id, task.id) && sameInputVersion(value.input_version, task.input_version), '恢复请求未确认，请先重新读取任务。', {
          method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': replay.current.key }, body: signature,
        })
      if (!active.current || controller.signal.aborted) return
      onChanged()
    } catch (cause) {
      if (!active.current) return
      setError(cause instanceof TaskRequestError && cause.status === 409 ? '任务状态已更新，请核对重新读取的内容后再操作。'
        : safeError(cause, '恢复请求未确认，请先重新读取任务。'))
      // Reread after conflict or an ambiguous transport outcome. Repeating the same
      // unchanged operation reuses its key, even when the first response was lost.
      onChanged()
    } finally { if (request.current === controller) request.current = null; if (active.current) setBusy(false) }
  }
  const currentWait = wait?.status === 'open' ? wait : null
  if (task.origin === 'legacy'||task.task_type==='pdf_export') return null
  if(task.task_type==='figure_projection')return <p className="warning-panel">{t('请返回来源文件的图表工作台，核对投影人数与规则后独立确认。')}</p>
  if (task.task_type === 'review_ocr' && task.input_version.kind === 'ocr_review') return <OcrReviewWorkspace projectId={task.project_id} fileId={task.input_version.source.file_id} parseId={task.input_version.source.parse_id} taskId={task.id} filename={workspace.source.filename} onUnavailable={onChanged} onPublished={onChanged}/>
  if (task.task_type === 'prepare_dataset') return <><PreparationReview projectId={task.project_id} taskId={task.id} blocked={blocked} onChanged={onChanged} refreshKey={task.revision ?? 0} />
    {actions.includes('retry') && <button type="button" className="button-primary" disabled={blocked || busy} onClick={() => void perform('retry')}>{t('重试原任务')}</button>}
    {error && <p role="alert" className="error-panel">{t(error)}</p>}</>
  if(task.task_type==='analysis_recommendation'&&task.input_version.kind==='analysis_recommendation'&&task.input_version.source.kind==='prepared_dataset_version') return <RecommendationResult key={task.id} projectId={task.project_id} taskId={task.id} source={task.input_version.source} disabled={blocked}/>
  if(task.task_type==='analysis_plan'&&task.input_version.kind==='analysis_plan'&&['analysis_plan_v4','analysis_plan_v5'].includes(task.input_version.workflow_version))return <RequirementReview projectId={task.project_id} taskId={task.id} blocked={blocked} onChanged={onChanged}/>
  if (task.task_type === 'analysis_plan' && task.input_version.kind === 'analysis_plan') return <><AnalysisPlanReview projectId={task.project_id} taskId={task.id} expectedInputVersion={task.input_version} blocked={blocked} onChanged={onChanged} refreshKey={task.revision ?? 0} />
    {actions.includes('retry') && <button type="button" className="button-primary" disabled={blocked || busy} onClick={() => void perform('retry')}>{t('重试原任务')}</button>}
    {error && <p role="alert" className="error-panel">{t(error)}</p>}</>
  return <section className="task-pending" aria-label={t('任务处理')}>
    {currentWait?.kind === 'literature_model_authorization'&&<p className="warning-panel">{t('真实文献模型调用关闭；任务已保存并持久等待授权，尚无模型建议。')}</p>}
    {currentWait?.kind === 'literature_configuration'&&<p className="warning-panel">{t('NCBI 配置尚未就绪，检索已保存并持久等待；配置及授权后可继续原任务。')}</p>}
    {currentWait?.kind === 'budget_confirmation' && <p className="warning-panel">{t('任务正在等待预算或模型配置，请联系管理员调整后继续。')}</p>}
    {currentWait?.kind === 'remote_observation' && <p className="warning-panel">{t('云端请求已超过原观察期限，费用与已有回执仍保留。每次继续仅查询原回执一次，不会重新生成。')}</p>}
    {currentWait?.kind === 'submission_unknown' && <p className="warning-panel">{t('提交结果尚未核实，请联系管理员核对；不能重新发送模型请求。')}</p>}
    {(currentWait?.kind === 'unsupported_input' || currentWait?.kind === 'unsupported_confirmation') && <p className="warning-panel">{t('此任务需要的资料或确认暂未提供处理入口，请联系管理员。')}</p>}
    {actions.length > 0 && <><p className="task-scope-note">{t(task.task_type==='journal_adaptation'?'使用冻结的期刊适配、所选动作与父稿重试；不访问外网或调用模型。':task.task_type==='journal_format_check'?'使用冻结的目标、指南要求与稿件版本重试；不访问外网或调用模型。':task.task_type==='journal_recommendation'?'使用冻结的期刊建议输入与来源重试；不访问外网或调用模型。':task.task_type==='school_template_parse'?'使用冻结的学校模板原件重试解析。':task.task_type==='literature_search'?'继续原检索任务，沿用已保存的条件与进度。':task.task_type === 'extract_dataset' ? '使用冻结的原文件输入重试本地结构提取。' : task.task_type === 'parse_file' ? '使用原文件重试本地解析。' : currentWait?.kind === 'remote_observation' ? '授权单次查询原云端回执；不延长原观察期限，也不授权重新生成费用。' : '继续此任务；尚未提交的模型调用会按原策略和预算执行，已有调用沿用已保存结果。')}</p>
      <div className="task-actions">{actions.map(operation => <button key={operation} type="button" className="button-primary" disabled={blocked || busy}
        onClick={() => void perform(operation)}>{t(operation === 'retry' ? '重试原任务'
          : currentWait?.kind === 'remote_observation' ? '查询原回执一次' : currentWait?.kind === 'budget_confirmation' ? '预算或配置已调整，继续任务' : '继续原任务')}</button>)}</div></>}
    {busy && <p role="status">{t('正在提交恢复请求……')}</p>}
    {error && <p role="alert" className="error-panel">{t(error)}</p>}
  </section>
}
