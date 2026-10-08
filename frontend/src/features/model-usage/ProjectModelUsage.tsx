import { useEffect, useRef, useState } from 'react'
import { apiFetch, onApiSessionChanged } from '../../shared/api/client'
import { apiError, safeError, useI18n } from '../../shared/i18n'
import { formatMicroUsd, isProjectUsage, type Budget, type ModelCall, type ProjectUsage } from './modelUsageTypes'
import './modelUsage.css'

type Props = { projectId: string; active?: boolean }
const purposes = { boxplot: '箱线图生成', explanation: 'AI 分析解释', word_report: 'Word 报告导出' }
const states: Record<ModelCall['status'], string> = { reserved: '已预留', submitting: '提交待确认', submitted: '运行中',
  submission_unknown: '提交结果未知', completed: '已完成', failed: '失败', released: '已释放' }

function BudgetCard({ title, budget }: { title: string; budget: Budget }) {
  const { t } = useI18n()
  return <div className="usage-budget-card"><h4>{t(title)}</h4>
    <dl><div><dt>{t('累计上限')}</dt><dd>{budget.limit_micro_usd === null ? t('未配置') : formatMicroUsd(budget.limit_micro_usd)}</dd></div>
      <div><dt>{t('内部估算')}</dt><dd>{formatMicroUsd(budget.estimated_micro_usd)}</dd></div>
      <div><dt>{t('预留金额')}</dt><dd>{formatMicroUsd(budget.reserved_micro_usd)}</dd></div>
      <div><dt>{t('可用额度')}</dt><dd>{budget.available_micro_usd === null ? t('未配置') : formatMicroUsd(budget.available_micro_usd)}</dd></div></dl>
    {budget.exceeded && <p className="usage-exceeded">{t('已超出额度')}</p>}
  </div>
}

export default function ProjectModelUsage(props: Props) {
  return <Usage key={props.projectId} {...props} />
}

function Usage({ projectId, active = true }: Props) {
  const { t, locale } = useI18n()
  const [data, setData] = useState<ProjectUsage | null>(null)
  const [page, setPage] = useState(1)
  const [attempt, setAttempt] = useState(0)
  const [loading, setLoading] = useState(active)
  const [error, setError] = useState('')
  const [sessionChanged, setSessionChanged] = useState(false)
  const sessionValid = useRef(true)
  const request = useRef<AbortController | null>(null)

  useEffect(() => onApiSessionChanged(() => {
    sessionValid.current = false
    request.current?.abort()
    setSessionChanged(true); setData(null); setError(''); setLoading(false)
  }), [])

  useEffect(() => {
    if (!active || !sessionValid.current) return
    const controller = new AbortController()
    request.current = controller
    let current = true
    const valid = () => current && sessionValid.current && !controller.signal.aborted
    setLoading(true); setData(null); setError('')
    const timeout = window.setTimeout(() => {
      if (!valid()) return
      controller.abort(); setError('模型用量读取超时，请重试。'); setLoading(false)
    }, 15_000)
    async function load() {
      try {
        const params = new URLSearchParams({ page: String(page), page_size: '10' })
        const response = await apiFetch(`/api/v1/projects/${encodeURIComponent(projectId)}/model-usage?${params}`, { signal: controller.signal })
        const result: unknown = await response.json()
        if (!valid()) return
        if (!response.ok) throw new Error(apiError(result, '模型用量读取失败，请重试。'))
        if (!isProjectUsage(result, page)) throw new Error('模型用量读取失败，请重试。')
        const last = Math.max(1, Math.ceil(result.total / 10))
        if (page > last) { setPage(last); return }
        setData(result)
      } catch (cause) {
        if (valid()) setError(safeError(cause, '模型用量读取失败，请重试。'))
      } finally {
        window.clearTimeout(timeout)
        if (valid()) setLoading(false)
      }
    }
    void load()
    return () => { current = false; controller.abort(); window.clearTimeout(timeout) }
  }, [active, projectId, page, attempt])

  function refresh(nextPage = page) {
    if (!active || !sessionValid.current) return
    request.current?.abort()
    setLoading(true); setData(null); setError(''); setPage(nextPage); setAttempt(value => value + 1)
  }
  const pages = data ? Math.max(1, Math.ceil(data.total / 10)) : 1
  return <section hidden={!active} className="model-usage-panel" aria-label={t('模型调用与预算')} aria-busy={loading}>
    <div className="usage-heading"><div><h3>{t('模型调用与预算')}</h3><p>{t('累计额度 · USD')}</p></div>
      <button type="button" disabled={loading || sessionChanged} onClick={() => refresh()}>{t('刷新模型用量')}</button></div>
    <p className="usage-scope-note">{t('历史绘图和历史解释未计入统一账本；本面板统计新绘图和新解释等统一入口的调用。')}</p>
    {sessionChanged && <p role="alert" className="error-panel">{t('会话已失效，请重新登录。')}</p>}
    {loading && <p role="status" className="usage-empty">{t('正在读取模型用量……')}</p>}
    {error && <><p role="alert" className="error-panel">{t(error)}</p>
      <button type="button" onClick={() => refresh()}>{t('重试模型用量')}</button></>}
    {data && <>
      <div className="usage-budgets"><BudgetCard title="项目预算" budget={data.project_budget} /><BudgetCard title="用户预算" budget={data.user_budget} /></div>
      <dl className="usage-totals"><div><dt>{t('项目内部估算')}</dt><dd>{formatMicroUsd(data.estimated_micro_usd)}</dd></div>
        <div><dt>{t('项目预留')}</dt><dd>{formatMicroUsd(data.reserved_micro_usd)}</dd></div>
        <div><dt>{t('待核对调用')}</dt><dd>{data.pending_count}</dd></div></dl>
      <p className="usage-scope-note">{t('内部估算，不是供应商账单。')}</p>
      {data.items.some(item => item.status === 'submitting' || item.status === 'submission_unknown')
        && <p className="usage-scope-note">{t('提交待确认或结果未知的调用保留预留预算，等待核对。')}</p>}
      <h4>{t('最近模型调用')}</h4>
      {data.total === 0 ? <p className="usage-empty">{t('尚无统一模型调用记录。')}</p> : <>
        <div className="usage-table-scroll"><table><caption className="visually-hidden">{t('最近模型调用')}</caption>
          <thead><tr><th scope="col">{t('用途')}</th><th scope="col">{t('模型')}</th><th scope="col">{t('已记录状态')}</th>
            <th scope="col">{t('内部估算')}</th><th scope="col">{t('记录时间')}</th></tr></thead>
          <tbody>{data.items.map(item => <tr key={item.id}><td>{t(purposes[item.task_type])}</td><td>{item.model}</td>
            <td><span className="usage-call-status">{t(states[item.status])}</span></td>
            <td>{item.estimated_cost_micro_usd === null ? t('待核对') : <>{formatMicroUsd(item.estimated_cost_micro_usd)}
              {item.usage_status === 'pending' && <small className="usage-pending">{t('待核对')}</small>}</>}</td>
            <td><time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString(locale)}</time></td></tr>)}</tbody>
        </table></div>
        <nav className="usage-pagination" aria-label={t('模型调用分页')}><span>{t('共 {total} 项 · 第 {page} / {pages} 页', { total: data.total, page, pages })}</span>
          <button type="button" aria-label={t('模型调用上一页')} disabled={page <= 1} onClick={() => refresh(page - 1)}>{t('上一页')}</button>
          <button type="button" aria-label={t('模型调用下一页')} disabled={page >= pages} onClick={() => refresh(page + 1)}>{t('下一页')}</button></nav>
      </>}
    </>}
  </section>
}
