import { useEffect, useRef, useState } from 'react'
import { onApiSessionChanged } from '../../shared/api/client'
import { safeError, useI18n } from '../../shared/i18n'
import { taskRequest } from './taskApi'
import { isTaskPage, phaseNames, statusNames, taskDisplayName, taskNames, type TaskPage } from './taskTypes'
import TaskDetail from './TaskDetail'
import { useDocumentVisible } from './useDocumentVisible'
import './task.css'

type Props = { projectId: string; active: boolean; selectedTaskId: string; onSelectTask: (id: string) => void }
export default function ProjectTasks(props: Props) { return props.active ? <Tasks key={props.projectId} {...props} /> : null }
function Tasks({ projectId, active, selectedTaskId, onSelectTask }: Props) {
  const { t, locale } = useI18n()
  const visible = useDocumentVisible()
  const [data, setData] = useState<TaskPage | null>(null)
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState('')
  const [kind, setKind] = useState('')
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
    let mounted = true; let timer = 0
    const controller = new AbortController(); request.current = controller
    const params = new URLSearchParams({ page: String(page), page_size: '10' })
    if (status) params.set('status', status)
    if (kind) params.set('task_type', kind)
    async function load() {
      try {
        const result = await taskRequest(`/api/v1/projects/${encodeURIComponent(projectId)}/tasks?${params}`, controller,
          (value): value is TaskPage => isTaskPage(value, projectId, page), '项目任务读取失败，请重试。')
        if (!mounted || controller.signal.aborted) return
        const last = Math.max(1, Math.ceil(result.total / 10))
        if (page > last) { setPage(last); return }
        setData(result); setError('')
        timer = window.setTimeout(() => void load(), 5000)
      } catch (cause) { if (mounted) setError(safeError(cause, '项目任务读取失败，请重试。')) }
      finally { if (mounted) setLoading(false) }
    }
    void load()
    return () => { mounted = false; controller.abort(); window.clearTimeout(timer) }
  }, [projectId, active, sessionValid, visible, page, status, kind, attempt])
  function filters(next: string, type: 'status' | 'kind') {
    request.current?.abort(); setData(null); setPage(1); setLoading(true); setError('')
    if (type === 'status') setStatus(next); else setKind(next)
  }
  return <section className="project-tasks" hidden={!active} aria-label={t('项目任务')}>
    <div className="task-page-heading"><div><h2>{t('项目任务')}</h2><p>{t('查看保存的执行状态、待办和成果。')}</p></div>
      <button type="button" disabled={loading || !sessionValid} onClick={() => { setLoading(true); setError(''); setAttempt(value => value + 1) }}>{t('刷新任务列表')}</button></div>
    <p className="task-scope-note">{t('这里展示统一任务及历史绘图、解释任务。')}</p>
    <div className="task-filters"><label>{t('任务类型')}<select value={kind} onChange={event => filters(event.target.value, 'kind')}>
      <option value="">{t('全部类型')}</option>{Object.entries(taskNames).map(([value, label]) => <option key={value} value={value}>{t(label)}</option>)}</select></label>
      <label>{t('任务状态')}<select value={status} onChange={event => filters(event.target.value, 'status')}>
        <option value="">{t('全部状态')}</option>{Object.entries(statusNames).map(([value, label]) => <option key={value} value={value}>{t(label)}</option>)}</select></label></div>
    {!sessionValid && <p role="alert">{t('会话已失效，请重新登录。')}</p>}
    {loading && <p role="status">{t('正在读取项目任务……')}</p>}
    {error && <p role="alert" className="error-panel">{t(error)}</p>}
    {data && <div className="task-list-panel">
      {!data.total ? <p className="task-empty">{t('此筛选下没有任务。')}</p> : <>
        <div className="task-table-scroll"><table><caption className="visually-hidden">{t('项目任务列表')}</caption>
          <thead><tr><th scope="col">{t('任务')}</th><th scope="col">{t('状态与阶段')}</th><th scope="col">{t('输入来源')}</th><th scope="col">{t('更新时间')}</th></tr></thead>
          <tbody>{data.items.map(({ task, source }) => <tr key={task.id} aria-selected={selectedTaskId === task.id}>
            <td><button type="button" className="task-open button-quiet" aria-label={t('查看{type}任务', { type: t(taskNames[task.task_type]) })}
              onClick={() => onSelectTask(task.id)}>{t(taskNames[task.task_type])}</button>{task.origin === 'legacy' && <small>{t('历史任务')}</small>}</td>
            <td><span className={`task-status task-status-${task.status}`}>{t(taskDisplayName(task))}</span><small>{t(phaseNames[task.phase])}</small></td>
            <td><strong>{source.filename}</strong><small>{t('分析配置 v{revision}', { revision: task.input_version.setup_revision })}</small>
              <small>{t(source.is_current ? '当前分析配置' : '历史分析配置')}</small></td>
            <td>{task.updated_at === null ? t('未记录') : <time dateTime={task.updated_at}>{new Date(task.updated_at).toLocaleString(locale)}</time>}</td></tr>)}</tbody></table></div>
        <nav className="task-pagination" aria-label={t('项目任务分页')}>
          <span>{t('共 {total} 项 · 第 {page} / {pages} 页', { total: data.total, page, pages: Math.max(1, Math.ceil(data.total / 10)) })}</span>
          <button type="button" disabled={loading || page <= 1} onClick={() => { setLoading(true); setError(''); setData(null); setPage(value => value - 1) }}>{t('上一页')}</button>
          <button type="button" disabled={loading || page >= Math.ceil(data.total / 10)} onClick={() => { setLoading(true); setError(''); setData(null); setPage(value => value + 1) }}>{t('下一页')}</button>
        </nav></>}
    </div>}
    {active && sessionValid && selectedTaskId ? <TaskDetail projectId={projectId} taskId={selectedTaskId} onChanged={() => setAttempt(value => value + 1)} />
      : sessionValid && <p className="task-empty">{t('选择任务，查看详细记录。')}</p>}
  </section>
}
