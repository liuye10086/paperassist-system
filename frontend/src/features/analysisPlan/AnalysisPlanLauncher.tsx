import { useEffect, useRef, useState } from 'react'
import { safeError, useI18n } from '../../shared/i18n'
import { isTask, statusNames, type TaskView } from '../tasks/taskTypes'
import { taskRequest, TaskRequestError } from '../tasks/taskApi'
import { sameSource, type PreparedDatasetAnalysisSource } from '../analysis/datasetSource'
import { type Selection } from '../analysis/AnalysisSetup'
import { isPlanPage, type PlanPage } from './analysisPlanApi'
import AnalysisPlanReview from './AnalysisPlanReview'

type Props = { projectId: string; fileId: string; source: PreparedDatasetAnalysisSource; selection: Selection; setupRevision: number; disabled: boolean; onPublished: (id: string, revision: number) => void }
export default function AnalysisPlanLauncher(props: Props) { return <Launcher key={`${props.projectId}:${props.fileId}:${JSON.stringify(props.source)}`} {...props} /> }

function Launcher({ projectId, fileId, source, selection, setupRevision, disabled, onPublished }: Props) {
  const { t } = useI18n()
  const [page, setPage] = useState(1)
  const [list, setList] = useState<PlanPage | null>(null)
  const [selected, setSelected] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const action = useRef<AbortController | null>(null)
  const replay = useRef<{ signature: string; key: string } | null>(null)
  const base = `/api/v1/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(fileId)}/analysis-plans`
  useEffect(() => () => action.current?.abort(), [])
  useEffect(() => {
    const controller = new AbortController(); let active = true
    taskRequest(`${base}?page=${page}&page_size=5`, controller,
      (v): v is PlanPage => isPlanPage(v, projectId, fileId, page), '分析计划列表读取失败，请重试。')
      .then(value => { if (active && !controller.signal.aborted) { setList(value); setError(''); const first=value.items.find(item=>sameSource(item.source,source)); if (first) setSelected(current => current || first.task.id) } })
      .catch(cause => { if (active && !controller.signal.aborted) setError(safeError(cause, '分析计划列表读取失败，请重试。')) })
    return () => { active = false; controller.abort() }
  }, [base, projectId, fileId, source, page, refresh])

  async function create() {
    if (disabled || busy || action.current) return
    const body = { dataset_id: source.dataset_id, expected_setup_revision: setupRevision, selection }
    const signature = JSON.stringify(body)
    if (replay.current?.signature !== signature) replay.current = { signature, key: crypto.randomUUID() }
    const controller = new AbortController(); action.current = controller; setBusy(true); setError('')
    try {
      const task = await taskRequest(base, controller, (v): v is TaskView => isTask(v, projectId) && v.task_type === 'analysis_plan' && v.input_version.kind === 'analysis_plan' && sameSource(v.input_version.source, source), '计划创建结果尚未确认，请重新读取列表。',
        { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': replay.current.key }, body: signature })
      if (controller.signal.aborted) return
      setSelected(task.id); setPage(1); setRefresh(n => n + 1); replay.current = null
    } catch (cause) {
      if (cause instanceof TaskRequestError && cause.status === 409) replay.current = null
      setError(cause instanceof TaskRequestError && cause.status === 409 ? '分析配置或数据来源已更新，请重新载入配置后重试。' : safeError(cause, '计划创建结果尚未确认，请重新读取列表。'))
      setRefresh(n => n + 1)
    } finally { if (action.current === controller) action.current = null; setBusy(false) }
  }
  const visible = list?.items.filter(item => sameSource(item.source, source)) ?? []
  return <section className="preparation-panel" aria-label={t('分析计划')}>
    <h4>{t('分析计划')}</h4><p className="muted">{t('生成后须逐项处理检查问题并确认发布，才能将该计划用于描述统计。')}</p>
    <div className="analysis-actions"><button type="button" className="button-primary" disabled={disabled || busy} onClick={() => void create()}>{t('生成分析计划')}</button><button type="button" disabled={busy} onClick={() => { setError(''); setRefresh(n => n + 1) }}>{t('刷新分析计划列表')}</button></div>
    {error && <p role="alert" className="error-panel">{t(error)}</p>}
    {list && <><div className="analysis-actions"><button type="button" disabled={page <= 1} onClick={() => setPage(n => n - 1)}>{t('上一页')}</button><span>{t('共 {total} 项 · 第 {page} / {pages} 页', { total: list.total, page, pages: Math.max(1, Math.ceil(list.total / 5)) })}</span><button type="button" disabled={page * 5 >= list.total} onClick={() => setPage(n => n + 1)}>{t('下一页')}</button></div>
      {visible.map(item => <button type="button" key={item.task.id} onClick={() => setSelected(item.task.id)} aria-pressed={selected === item.task.id}>{t('分析计划第 {revision} 版 · {status}', { revision: item.plan_revision, status: t(statusNames[item.task.status]) })}</button>)}</>}
    {selected && <AnalysisPlanReview key={selected} projectId={projectId} taskId={selected} expectedSource={source} onChanged={() => setRefresh(n => n + 1)} onPublished={onPublished} />}
  </section>
}
