import { useEffect, useRef, useState } from 'react'
import { onApiSessionChanged } from '../../shared/api/client'
import { safeError, useI18n } from '../../shared/i18n'
import { taskRequest } from '../tasks/taskApi'
import { useDocumentVisible } from '../tasks/useDocumentVisible'
import { formatMicroUsd, isTaskUsage, type Budget, type TaskUsage } from './modelUsageTypes'
import './modelUsage.css'

type Props = { taskId: string; active?: boolean; refreshKey?: number }
export default function TaskModelUsage(props: Props) { return props.active === false ? null : <Usage key={props.taskId} {...props} /> }
function Usage({ taskId, active = true, refreshKey = 0 }: Props) {
  const { t, locale } = useI18n()
  const visible = useDocumentVisible()
  const [data, setData] = useState<TaskUsage | null>(null)
  const [page, setPage] = useState(1)
  const [attempt, setAttempt] = useState(0)
  const [loading, setLoading] = useState(active)
  const [error, setError] = useState('')
  const [sessionValid, setSessionValid] = useState(true)
  const request = useRef<AbortController | null>(null)
  useEffect(() => onApiSessionChanged(() => {
    request.current?.abort(); setSessionValid(false); setData(null); setError(''); setLoading(false)
  }), [])
  useEffect(() => {
    if (!active || !sessionValid || !visible) return
    const controller = new AbortController(); request.current = controller
    let mounted = true
    void taskRequest(`/api/v1/tasks/${encodeURIComponent(taskId)}/model-usage?page=${page}&page_size=10`, controller,
      (value): value is TaskUsage => isTaskUsage(value, page), '任务用量读取失败，请重试。')
      .then(value => {
        if (!mounted || controller.signal.aborted) return
        const last = Math.max(1, Math.ceil(value.total / 10))
        if (page > last) { setPage(last); return }
        setData(value); setError('')
      }).catch(cause => { if (mounted) setError(safeError(cause, '任务用量读取失败，请重试。')) })
      .finally(() => { if (mounted) setLoading(false) })
    return () => { mounted = false; controller.abort() }
  }, [active, sessionValid, visible, taskId, page, attempt, refreshKey])
  const budgets: [string, Budget][] = data ? [['任务预算', data.task_budget], ['项目预算', data.project_budget], ['用户预算', data.user_budget]] : []
  return <section className="model-usage-panel task-model-usage" aria-label={t('本次任务用量')} hidden={!active} aria-busy={loading}>
    <div className="usage-heading"><div><h3>{t('本次任务用量')}</h3><p>{t('内部估算，不是供应商账单。')}</p></div>
      <button type="button" disabled={loading || !sessionValid} onClick={() => { setLoading(true); setError(''); setAttempt(value => value + 1) }}>{t('刷新任务用量')}</button></div>
    {loading && <p role="status">{t('正在读取模型用量……')}</p>}
    {error && <p role="alert" className="error-panel">{t(error)}</p>}
    {!sessionValid && <p role="alert">{t('会话已失效，请重新登录。')}</p>}
    {data && <>
      <div className="usage-budgets">{budgets.map(([label, budget]) => <div className="usage-budget-card" key={label}>
        <h4>{t(label)}</h4><dl>
          <div><dt>{t('累计上限')}</dt><dd>{budget.limit_micro_usd === null ? t('未配置') : formatMicroUsd(budget.limit_micro_usd)}</dd></div>
          <div><dt>{t('内部估算')}</dt><dd>{formatMicroUsd(budget.estimated_micro_usd)}</dd></div>
          <div><dt>{t('预留金额')}</dt><dd>{formatMicroUsd(budget.reserved_micro_usd)}</dd></div>
          <div><dt>{t('可用额度')}</dt><dd>{budget.available_micro_usd === null ? t('未配置') : formatMicroUsd(budget.available_micro_usd)}</dd></div>
        </dl>{budget.exceeded && <p className="usage-exceeded">{t('已超出额度')}</p>}</div>)}</div>
      <p className="usage-scope-note">{t('待核对调用：{count}', { count: data.pending_count })}</p>
      {data.total === 0 ? <p className="usage-empty">{t('此任务尚无模型调用记录。')}</p> : <>
        <div className="usage-table-scroll"><table><caption className="visually-hidden">{t('本次任务模型调用')}</caption>
          <thead><tr><th scope="col">{t('模型')}</th><th scope="col">{t('内部估算')}</th><th scope="col">{t('记录时间')}</th></tr></thead>
          <tbody>{data.items.map(call => <tr key={call.id}><td>{call.model}</td>
            <td>{call.estimated_cost_micro_usd === null ? t('待核对') : <>{formatMicroUsd(call.estimated_cost_micro_usd)}
              {call.usage_status === 'pending' && <small className="usage-pending">{t('待核对')}</small>}</>}</td>
            <td><time dateTime={call.created_at}>{new Date(call.created_at).toLocaleString(locale)}</time></td></tr>)}</tbody></table></div>
        <nav className="usage-pagination" aria-label={t('任务用量分页')}>
          <span>{t('共 {total} 项 · 第 {page} / {pages} 页', { total: data.total, page, pages: Math.max(1, Math.ceil(data.total / 10)) })}</span>
          <button type="button" disabled={loading || page <= 1} onClick={() => { setLoading(true); setError(''); setPage(value => value - 1) }}>{t('上一页')}</button>
          <button type="button" disabled={loading || page >= Math.ceil(data.total / 10)} onClick={() => { setLoading(true); setError(''); setPage(value => value + 1) }}>{t('下一页')}</button>
        </nav></>}
    </>}
  </section>
}
