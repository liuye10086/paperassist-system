import BioTaskLinks from './BioTaskLinks'
import useDraftLeaveGuard, { type RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import {reviewHash} from '../reviews/reviewTypes'
import {RecommendationResult} from '../analysisPlan/AnalysisRecommendation'
import PreparationReview from '../datasetPreparation/PreparationReview'
import RequirementReview from '../analysisPlan/RequirementReview'
import AnalysisPlanReview from '../analysisPlan/AnalysisPlanReview'
import OcrReviewWorkspace from '../documents/OcrReviewWorkspace'
import { useEffect, useRef, useState } from 'react'
import { useI18n } from '../../shared/i18n'
import { isTask, sameInputVersion, type TaskOperation, type TaskView, type TaskWorkspace } from './taskTypes'
import { taskErrorMessage, taskRequest } from './taskApi'

// Customer pages explain waits without staff-only wording (NCBI, Worker, frozen inputs, administrators).
const customerChecking = '系统正在核对，请稍后刷新或联系客服。'
const customerLiterature = '文献检索暂不可用，任务已保存。'
export default function TaskPendingAction({ workspace, blocked, onChanged, active: viewActive = true, registerLeaveGuard, customerView = false }: {
  active?: boolean; registerLeaveGuard?: RegisterLeaveGuard; customerView?: boolean;
  workspace: TaskWorkspace; blocked: boolean; onChanged: () => void
}) {
  const { t } = useI18n()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useDraftLeaveGuard(registerLeaveGuard, !!error, busy)
  const request = useRef<AbortController | null>(null)
  const active = useRef(true)
  const replay = useRef<{ signature: string; key: string } | null>(null)
  const { task, wait } = workspace
  // A stale capability list must never turn an unknown submission into a resend.
  const submissionUnknown = task.error_code === 'model_submission_unknown' || task.reason_code === 'submission_unknown'
    || wait?.status === 'open' && (wait.kind === 'submission_unknown' || wait.error_code === 'model_submission_unknown')
  const actions = submissionUnknown ? [] : workspace.allowed_actions.filter(a=>!(task.task_type==='bio_analysis'&&a==='approve'))
  useEffect(() => { active.current = true; return () => { active.current = false; request.current?.abort() } }, [])
  async function perform(operation: TaskOperation) {
    if (task.origin === 'legacy' || task.revision === null || !viewActive || blocked || request.current || !actions.includes(operation)) return
    const controller = new AbortController(); request.current = controller
    const body = operation === 'cancel' ? { expected_revision: task.revision } : { operation, wait_id: wait?.id ?? null, expected_task_revision: task.revision, input_version: task.input_version }
    const signature = JSON.stringify(body)
    if (replay.current?.signature !== signature) replay.current = { signature, key: crypto.randomUUID() }
    setBusy(true); setError('')
    try {
      await taskRequest(`/api/v1/tasks/${encodeURIComponent(task.id)}/${operation === 'cancel' ? 'cancel' : 'resume'}`, controller,
        (value): value is TaskView => isTask(value, task.project_id, task.id) && value.task_type === task.task_type && sameInputVersion(value.input_version, task.input_version), '恢复请求未确认，请先重新读取任务。', {
          method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': replay.current.key }, body: signature,
        })
      if (!active.current || controller.signal.aborted) return
      onChanged()
    } catch (cause) {
      if (!active.current) return
      setError(taskErrorMessage(cause, '恢复请求未确认，请先重新读取任务。', customerView,
        '任务状态已更新，请核对重新读取的内容后再操作。'))
      // Reread after conflict or an ambiguous transport outcome. Repeating the same
      // unchanged operation reuses its key, even when the first response was lost.
      onChanged()
    } finally { if (request.current === controller) request.current = null; if (active.current) setBusy(false) }
  }
  const currentWait = wait?.status === 'open' ? wait : null
  const legacyModelWait = currentWait?.kind === 'budget_confirmation'
  const modelError = currentWait?.error_code ?? task.error_code ?? ''
  const needsModelSetup = !!currentWait && (modelError.endsWith('_not_configured') || modelError === 'model_configuration_disabled')
  const resumeNarrative = task.task_type === 'reader_report_narrative' && actions.includes('resume') && legacyModelWait
  if (task.origin === 'legacy'||task.task_type==='pdf_export') return null
  if(currentWait?.kind==='bio_analysis_confirmation')return <section className="task-pending"><p>{t(customerView?customerChecking:'QC 候选待确认；计算已暂停，不占用 Worker。')}</p>{!customerView&&<BioTaskLinks task={task}/>}</section>
  if(task.task_type==='figure_projection')return <p className="warning-panel">{t('请返回来源文件的图表工作台，核对投影人数与规则后独立确认。')}</p>
  if (task.task_type === 'review_ocr' && task.input_version.kind === 'ocr_review') return <OcrReviewWorkspace active={viewActive} registerLeaveGuard={registerLeaveGuard} projectId={task.project_id} fileId={task.input_version.source.file_id} parseId={task.input_version.source.parse_id} taskId={task.id} filename={workspace.source.filename} onUnavailable={onChanged} onPublished={onChanged}/>
  if (task.task_type === 'prepare_dataset') return <><PreparationReview active={viewActive} registerLeaveGuard={registerLeaveGuard} projectId={task.project_id} taskId={task.id} blocked={blocked} onChanged={onChanged} refreshKey={task.revision ?? 0} />
    {actions.includes('retry') && <button type="button" className="button-primary" disabled={!viewActive || blocked || busy} onClick={() => void perform('retry')}>{t('重试原任务')}</button>}
    {error && <p role="alert" className="error-panel">{t(error)}</p>}</>
  if(task.task_type==='analysis_recommendation'&&task.input_version.kind==='analysis_recommendation'&&task.input_version.source.kind==='prepared_dataset_version') return <RecommendationResult active={viewActive} key={task.id} projectId={task.project_id} taskId={task.id} source={task.input_version.source} disabled={blocked}/>
  if(task.task_type==='analysis_plan'&&task.input_version.kind==='analysis_plan'&&['analysis_plan_v4','analysis_plan_v5'].includes(task.input_version.workflow_version))return <RequirementReview active={viewActive} projectId={task.project_id} taskId={task.id} blocked={blocked} onChanged={onChanged}/>
  if (task.task_type === 'analysis_plan' && task.input_version.kind === 'analysis_plan') return <><AnalysisPlanReview active={viewActive} projectId={task.project_id} taskId={task.id} expectedInputVersion={task.input_version} blocked={blocked} onChanged={onChanged} refreshKey={task.revision ?? 0} />
    {actions.includes('retry') && <button type="button" className="button-primary" disabled={!viewActive || blocked || busy} onClick={() => void perform('retry')}>{t('重试原任务')}</button>}
    {error && <p role="alert" className="error-panel">{t(error)}</p>}</>
  if (customerView) return <section className="task-pending" aria-label={t('任务处理')}>
    {task.input_version.kind==='review_round_plan'&&<a href={reviewHash(task.project_id,task.input_version.round_id)}>{t('返回本轮意见计划')}</a>}
    {currentWait && <p className="warning-panel">{t(currentWait.kind === 'literature_model_authorization' || currentWait.kind === 'literature_configuration' ? customerLiterature : customerChecking)}</p>}
    {actions.length > 0 && <><p className="task-scope-note">{t('使用原资料重新处理；取消后已有成果不变。')}</p>
      <div className="task-actions">{actions.map(operation => <button key={operation} type="button" className="button-primary" disabled={!viewActive || blocked || busy}
        onClick={() => void perform(operation)}>{t(operation === 'cancel' ? '取消任务' : operation === 'retry' ? '重试原任务' : '继续原任务')}</button>)}</div></>}
    {busy && <p role="status">{t('正在提交任务操作……')}</p>}
    {error && <p role="alert" className="error-panel">{t(error)}</p>}
  </section>
  return <section className="task-pending" aria-label={t('任务处理')}>
    {task.input_version.kind==='review_round_plan'&&<><a href={reviewHash(task.project_id,task.input_version.round_id)}>{t('返回本轮意见计划')}</a><p className="warning-panel">{t('计划保存成功仅代表计划已持久保存；待确认、待材料的意见仍未完成。')}</p></>}
    {currentWait?.kind === 'literature_model_authorization'&&<p className="warning-panel">{t('真实文献模型调用关闭；任务已保存并持久等待授权，尚无模型建议。')}</p>}
    {currentWait?.kind === 'literature_configuration'&&<p className="warning-panel">{t('NCBI 配置尚未就绪，检索已保存并持久等待；配置及授权后可继续原任务。')}</p>}
    {needsModelSetup && <p className="warning-panel">{t('模型服务尚未配置。请联系管理员启用模型后，再继续原任务。')}</p>}
    {currentWait?.kind === 'remote_observation' && <p className="warning-panel">{t('云端请求已超过原观察期限，费用与已有回执仍保留。每次继续仅查询原回执一次，不会重新生成。')}</p>}
    {currentWait?.kind === 'submission_unknown' && <p className="warning-panel">{t('提交结果尚未核实，请联系管理员核对；不能重新发送模型请求。')}</p>}
    {!needsModelSetup && (currentWait?.kind === 'unsupported_input' || currentWait?.kind === 'unsupported_confirmation') && <p className="warning-panel">{t('此任务需要的资料或确认暂未提供处理入口，请联系管理员。')}</p>}
    {actions.length > 0 && <><p className="task-scope-note">{t(actions.includes('cancel')?'取消后停止当前计算并保留诊断材料；已有成果不变。':workspace.artifacts.reader_export?'按原报告选材恢复本地导出。':task.task_type==='delivery_package'?'仅恢复原快照封包；复用已有成果，不重新分析、绘图或生成文档。':task.task_type==='bio_analysis'||task.task_type==='bio_figure'?'使用冻结的来源和参数重试；不会新建运行或覆盖历史结果。':task.task_type==='bio_import'?'使用冻结的生信原件重试结构导入；不执行分析或外发资料。':task.task_type==='review_round_plan'?'仅继续本地意见计划核查；不会调用模型、改稿或完成意见。':task.task_type==='journal_adaptation'?'使用冻结的期刊适配、所选动作与父稿重试；不访问外网或调用模型。':task.task_type==='journal_format_check'?'使用冻结的目标、指南要求与稿件版本重试；不访问外网或调用模型。':task.task_type==='journal_recommendation'?'使用冻结的期刊建议输入与来源重试；不访问外网或调用模型。':task.task_type==='school_template_parse'?'使用冻结的学校模板原件重试解析。':task.task_type==='literature_search'?'继续原检索任务，沿用已保存的条件与进度。':task.task_type === 'extract_dataset' ? '使用冻结的原文件输入重试本地结构提取。' : task.task_type === 'parse_file' ? '使用原文件重试本地解析。' : currentWait?.kind === 'remote_observation' ? '授权单次查询原云端回执；不延长原观察期限，也不授权重新生成费用。' : resumeNarrative ? '点击继续，系统会使用已选的分析结果和图表生成详细解读。' : '继续后将使用原任务的资料，已保存的结果会直接复用。')}</p>
      <div className="task-actions">{actions.map(operation => <button key={operation} type="button" className="button-primary" disabled={!viewActive || blocked || busy}
        onClick={() => void perform(operation)}>{t(operation === 'cancel' ? '取消任务' : operation === 'retry' ? '重试原任务'
          : currentWait?.kind === 'remote_observation' ? '查询原回执一次' : resumeNarrative ? '继续生成详细解读' : '继续原任务')}</button>)}</div></>}
    {busy && <p role="status">{t('正在提交任务操作……')}</p>}
    {error && <p role="alert" className="error-panel">{t(error)}</p>}
  </section>
}
