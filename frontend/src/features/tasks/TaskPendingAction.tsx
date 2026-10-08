import { useEffect, useRef, useState } from 'react'
import { safeError, useI18n } from '../../shared/i18n'
import { isTask, type TaskOperation, type TaskView, type TaskWorkspace } from './taskTypes'
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
  const { task, wait, allowed_actions: actions } = workspace
  useEffect(() => { active.current = true; return () => { active.current = false; request.current?.abort() } }, [])
  async function perform(operation: TaskOperation) {
    if (blocked || request.current || !actions.includes(operation)) return
    const controller = new AbortController(); request.current = controller
    const body = { operation, wait_id: wait?.id ?? null, expected_task_revision: task.revision, input_version: task.input_version }
    const signature = JSON.stringify(body)
    if (replay.current?.signature !== signature) replay.current = { signature, key: crypto.randomUUID() }
    setBusy(true); setError('')
    try {
      await taskRequest(`/api/v1/tasks/${encodeURIComponent(task.id)}/resume`, controller,
        (value): value is TaskView => isTask(value, task.project_id, task.id), '恢复请求未确认，请先重新读取任务。', {
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
  return <section className="task-pending" aria-label={t('任务处理')}>
    {currentWait?.kind === 'budget_confirmation' && <p className="warning-panel">{t('任务正在等待预算或模型配置，请联系管理员调整后继续。')}</p>}
    {currentWait?.kind === 'submission_unknown' && <p className="warning-panel">{t('提交结果尚未核实，请联系管理员核对；不能重新发送模型请求。')}</p>}
    {(currentWait?.kind === 'unsupported_input' || currentWait?.kind === 'unsupported_confirmation') && <p className="warning-panel">{t('此任务需要的资料或确认暂未提供处理入口，请联系管理员。')}</p>}
    {actions.length > 0 && <><p className="task-scope-note">{t('继续此任务；尚未提交的模型调用会按原策略和预算执行，已有调用沿用已保存结果。')}</p>
      <div className="task-actions">{actions.map(operation => <button key={operation} type="button" className="button-primary" disabled={blocked || busy}
        onClick={() => void perform(operation)}>{t(operation === 'retry' ? '重试原任务'
          : currentWait?.kind === 'budget_confirmation' ? '预算或配置已调整，继续任务' : '继续原任务')}</button>)}</div></>}
    {busy && <p role="status">{t('正在提交恢复请求……')}</p>}
    {error && <p role="alert" className="error-panel">{t(error)}</p>}
  </section>
}
