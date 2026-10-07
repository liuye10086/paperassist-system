import { useCallback, useEffect, useRef, useState } from 'react'
import { apiFetch, onApiSessionChanged } from '../../shared/api/client'
import { artifactFilename } from '../../shared/components/artifactFilename'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import { isProjectSummary, type ProjectSummaryData, type SummarySource, type SummaryTask } from './projectSummaryTypes'
import { useI18n } from '../../shared/i18n'
import './projectSummary.css'

type Props = { projectId: string; projectType: 'sci' | 'thesis'; view?: 'overview' | 'artifacts' | 'all'; active?: boolean }
const taskNames = { statistics: '描述统计', boxplot: '箱线图生成', explanation: 'AI 分析解释', report: 'Word 报告导出' }
const statuses: Record<SummaryTask['status'], string> = {
  submitting: '提交中', running: '运行中', completed: '已完成', failed: '失败', uncertain: '结果不确定', unknown: '状态未知',
}

function Source({ item }: { item: SummarySource }) {
  const { t } = useI18n()
  const context = item.current_revision === null ? '当前设置未记录'
    : item.setup_revision === item.current_revision ? '当前结果' : '历史结果'
  return <div className="summary-readable-source"><strong>{item.filename}</strong>
    <span>{t(context)}</span></div>
}

function SummaryIcon({ kind }: { kind: 'task' | 'figure' | 'report' }) {
  return <svg className="summary-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {kind === 'report' ? <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9Zm0 0v6h6M8 13h8m-8 4h5" />
      : <path d="M4 3v17h17M9 15V9m5 6V5m5 10v-4" />}
  </svg>
}

function Pagination({ label, page, total, onChange }: { label: string; page: number; total: number; onChange: (page: number) => void }) {
  const { t } = useI18n()
  const pages = Math.max(1, Math.ceil(total / 10))
  return <nav className="summary-pagination" aria-label={t('{label}分页', { label })}>
    <span>{t('共 {total} 项 · 第 {page} / {pages} 页', { total, page, pages })}</span>
    <button type="button" aria-label={t('{label}上一页', { label })} disabled={page <= 1} onClick={() => onChange(page - 1)}>{t("上一页")}</button>
    <button type="button" aria-label={t('{label}下一页', { label })} disabled={page >= pages} onClick={() => onChange(page + 1)}>{t("下一页")}</button>
  </nav>
}

export default function ProjectSummary(props: Props) {
  return <Summary key={`${props.projectId}:${props.projectType}`} {...props} />
}

function Summary({ projectId, projectType, view = 'all', active = true }: Props) {
  const { t, locale } = useI18n()
  const [data, setData] = useState<ProjectSummaryData | null>(null)
  const [pages, setPages] = useState({ tasks: 1, artifacts: 1 })
  const [attempt, setAttempt] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [sessionChanged, setSessionChanged] = useState(false)
  const validSession = useRef(true)
  const request = useRef<AbortController | null>(null)
  const artifactsActive = active && view === 'artifacts'
  const previouslyArtifactsActive = useRef(artifactsActive)

  useEffect(() => onApiSessionChanged(() => {
    validSession.current = false
    setSessionChanged(true)
    request.current?.abort()
    setData(null); setError(''); setLoading(false)
  }), [])

  useEffect(() => {
    if (!validSession.current) return
    const controller = new AbortController()
    request.current = controller
    let active = true
    const valid = () => active && validSession.current && !controller.signal.aborted
    const timeout = window.setTimeout(() => {
      if (!valid()) return
      controller.abort(); setData(null); setError('项目摘要读取超时，请重试。'); setLoading(false)
    }, 15_000)
    async function load() {
      try {
        const params = new URLSearchParams({ task_page: String(pages.tasks), artifact_page: String(pages.artifacts), page_size: '10' })
        const response = await apiFetch(`/api/v1/projects/${encodeURIComponent(projectId)}/summary?${params}`, { signal: controller.signal })
        if (!response.ok) throw new Error('summary_failed')
        const result: unknown = await response.json()
        if (!valid()) return
        if (!isProjectSummary(result, projectId, projectType, pages.tasks, pages.artifacts)) throw new Error('summary_invalid')
        const next = { tasks: Math.min(pages.tasks, Math.max(1, Math.ceil(result.tasks.total / 10))),
          artifacts: Math.min(pages.artifacts, Math.max(1, Math.ceil(result.artifacts.total / 10))) }
        if (next.tasks !== pages.tasks || next.artifacts !== pages.artifacts) {
          setPages(next)
          return
        }
        setData(result); setLoading(false)
      } catch {
        if (valid()) { setData(null); setError('项目摘要读取失败，请重试。'); setLoading(false) }
      } finally {
        window.clearTimeout(timeout)
      }
    }
    void load()
    return () => { active = false; controller.abort(); window.clearTimeout(timeout) }
  }, [projectId, projectType, pages, attempt])

  const refresh = useCallback((next = pages) => {
    if (!validSession.current) return
    request.current?.abort()
    setData(null); setError(''); setLoading(true); setPages(next); setAttempt(value => value + 1)
  }, [pages])

  useEffect(() => {
    const enteringArtifacts = artifactsActive && !previouslyArtifactsActive.current
    previouslyArtifactsActive.current = artifactsActive
    if (enteringArtifacts) refresh()
  }, [artifactsActive, refresh])

  const title = view === 'overview' ? '项目任务概览' : view === 'artifacts' ? '图表与报告' : '项目任务与成果'
  const description = view === 'overview' ? '查看已保存的分析进展与任务状态。'
    : view === 'artifacts' ? '已保存的图表与 Word 报告，可直接下载。' : '查看分析任务与已保存的研究成果。'

  return <section className="project-summary project-summary-panel" aria-label={t(title)} aria-busy={loading}>
    <div className="summary-panel-heading"><div><h3>{t(title)}</h3><p>{t(description)}</p></div>
      <button type="button" disabled={loading || sessionChanged} onClick={() => refresh()}>{t("刷新项目摘要")}</button></div>
    {loading && <p className="summary-empty" role="status">{t("正在读取项目摘要……")}</p>}
    {error && <><p role="alert" className="error-panel">{t(error)}</p><button type="button" onClick={() => refresh()}>{t("重试项目摘要")}</button></>}
    {data && <>
      <div className="summary-task-section" hidden={view === 'artifacts'}>
      <h4 className="summary-section-heading">{t("分析任务记录")}<span>{data.tasks.total}</span></h4>
      {data.tasks.total === 0 ? <p className="summary-empty">{t("还没有已保存的分析任务记录。")}</p> : <>
        <div className="summary-table-scroll"><table className="summary-task-table"><caption className="visually-hidden">{t("分析任务记录")}</caption>
          <thead><tr><th scope="col">{t("任务")}</th><th scope="col">{t("已记录状态")}</th><th scope="col">{t("来源")}</th><th scope="col">{t("记录时间")}</th></tr></thead>
          <tbody>{data.tasks.items.map(item => <tr key={`${item.kind}:${item.id}`}>
            <td><span className="summary-task-name"><SummaryIcon kind={item.kind === 'report' ? 'report' : 'task'} />{t(taskNames[item.kind])}</span></td><td><span className={`summary-status summary-status-${item.status}`}>{t(statuses[item.status])}</span></td>
            <td><Source item={item} /></td><td><time dateTime={item.recorded_at}>{new Date(item.recorded_at).toLocaleString(locale)}</time></td>
          </tr>)}</tbody></table></div>
        <Pagination label={t("任务")} page={data.tasks.page} total={data.tasks.total} onChange={tasks => refresh({ ...pages, tasks })} />
      </>}
      <aside className="summary-upcoming" aria-label={t('后续研究工作')}><span>{t('写作与修改')}</span><span aria-hidden="true">·</span>
        {data.future.sci && <span>{t('SCI 期刊与投稿')}</span>}{data.future.thesis && <span>{t('学校与毕业论文评审')}</span>}
        <span className="summary-unavailable">{t('功能未开放')}</span></aside>
      </div>
      <div className="summary-artifact-section" hidden={view === 'overview'}>
      <h4 className="summary-section-heading">{t("已生成文件")}<span>{data.artifacts.total}</span></h4>
      {data.artifacts.total === 0 ? <p className="summary-empty">{t("还没有已生成的 PNG 或 Word 文件。")}</p> : <>
        <ul className="summary-artifact-list">{data.artifacts.items.map(item => {
        const filename = artifactFilename(item.download_filename, item.kind, item.id, item.setup_revision, locale)
          return <li key={`${item.kind}:${item.id}`}>
          <span className={`summary-artifact-symbol summary-artifact-${item.kind}`}><SummaryIcon kind={item.kind} /></span>
          <div className="summary-artifact-content"><strong className="summary-artifact-title">{filename}</strong><p className="summary-artifact-meta">{t('{type} · {bytes} 字节 · {date}', { type: t(item.kind === 'figure' ? 'PNG 图表' : 'Word 分析报告'), bytes: item.size_bytes.toLocaleString(locale), date: new Date(item.recorded_at).toLocaleString(locale) })}</p>
            <div className="summary-artifact-source"><span>{t('来源文件')}</span><Source item={item} /></div></div>
          <ProjectDownloadLink href={item.download_url} filename={filename} ariaLabel={t('下载成果 {name}', { name: filename })}>{t("下载文件")}</ProjectDownloadLink>
        </li>})}</ul>
        <Pagination label={t("成果")} page={data.artifacts.page} total={data.artifacts.total} onChange={artifacts => refresh({ ...pages, artifacts })} />
      </>}
      </div>
    </>}
  </section>
}
