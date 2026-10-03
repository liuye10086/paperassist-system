import { useEffect, useRef, useState } from 'react'
import { apiFetch, onApiSessionChanged } from './api'
import ProjectDownloadLink from './ProjectDownloadLink'
import { isProjectSummary, type ProjectSummaryData, type SummarySource, type SummaryTask } from './projectSummaryTypes'

type Props = { projectId: string; projectType: 'sci' | 'thesis' }
const taskNames = { statistics: '描述统计', boxplot: '箱线图生成', explanation: 'AI 分析解释', report: 'Word 报告导出' }
const statuses: Record<SummaryTask['status'], string> = {
  submitting: '提交中', running: '运行中', completed: '已完成', failed: '失败', uncertain: '结果不确定', unknown: '状态未知',
}

function Source({ item }: { item: SummarySource }) {
  const revision = item.current_revision === null ? '（当前配置无记录）'
    : item.setup_revision === item.current_revision ? '（当前配置）' : '（历史配置）'
  return <><strong>{item.filename}</strong>
    <p className="muted">配置 v{item.setup_revision} · 当前 {item.current_revision === null ? '未知' : `v${item.current_revision}`}{revision}</p>
    <details><summary>来源信息</summary><dl className="summary-source">
      <dt>记录 ID</dt><dd>{item.id}</dd><dt>文件 ID</dt><dd>{item.file_id}</dd>
      <dt>统计结果 ID</dt><dd>{item.analysis_run_id}</dd>
      {item.figure_id && <><dt>图表 ID</dt><dd>{item.figure_id}</dd></>}
      {item.explanation_id && <><dt>解释 ID</dt><dd>{item.explanation_id}</dd></>}
      <dt>工具版本</dt><dd>{item.engine_version}</dd>
    </dl></details>
  </>
}

function Pagination({ label, page, total, onChange }: { label: string; page: number; total: number; onChange: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / 10))
  return <nav className="summary-pagination" aria-label={`${label}分页`}>
    <span>共 {total} 项 · 第 {page} / {pages} 页</span>
    <button type="button" aria-label={`${label}上一页`} disabled={page <= 1} onClick={() => onChange(page - 1)}>上一页</button>
    <button type="button" aria-label={`${label}下一页`} disabled={page >= pages} onClick={() => onChange(page + 1)}>下一页</button>
  </nav>
}

export default function ProjectSummary(props: Props) {
  return <Summary key={`${props.projectId}:${props.projectType}`} {...props} />
}

function Summary({ projectId, projectType }: Props) {
  const [data, setData] = useState<ProjectSummaryData | null>(null)
  const [pages, setPages] = useState({ tasks: 1, artifacts: 1 })
  const [attempt, setAttempt] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [sessionChanged, setSessionChanged] = useState(false)
  const validSession = useRef(true)
  const request = useRef<AbortController | null>(null)

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

  function refresh(next = pages) {
    if (!validSession.current) return
    request.current?.abort()
    setData(null); setError(''); setLoading(true); setPages(next); setAttempt(value => value + 1)
  }

  return <section className="project-summary" aria-label="项目任务与成果" aria-busy={loading}>
    <div className="preview-heading"><h3>项目任务与成果</h3>
      <button type="button" disabled={loading || sessionChanged} onClick={() => refresh()}>刷新项目摘要</button></div>
    <p className="muted">这里展示已保存的记录，完成分析后可刷新摘要。图表与解释保留每次请求状态；描述统计和 Word 导出仅记录成功结果。</p>
    <p className="muted">任务完成不代表论文已投稿、录用或评审通过。实际进展由后续业务记录。</p>
    {loading && <p role="status">正在读取项目摘要……</p>}
    {error && <><p role="alert" className="error-panel">{error}</p><button type="button" onClick={() => refresh()}>重试项目摘要</button></>}
    {data && <>
      <h4>分析任务记录</h4>
      {data.tasks.total === 0 ? <p>还没有已保存的分析任务记录。</p> : <>
        <div className="summary-table-scroll"><table className="summary-table"><caption className="visually-hidden">分析任务记录</caption>
          <thead><tr><th scope="col">任务</th><th scope="col">已记录状态</th><th scope="col">来源</th><th scope="col">记录时间</th></tr></thead>
          <tbody>{data.tasks.items.map(item => <tr key={`${item.kind}:${item.id}`}>
            <td>{taskNames[item.kind]}</td><td><span className={`summary-status summary-status-${item.status}`}>{statuses[item.status]}</span></td>
            <td><Source item={item} /></td><td>{new Date(item.recorded_at).toLocaleString('zh-CN')}</td>
          </tr>)}</tbody></table></div>
        <Pagination label="任务" page={data.tasks.page} total={data.tasks.total} onChange={tasks => refresh({ ...pages, tasks })} />
      </>}
      <h4>已生成文件</h4>
      <p className="muted">列出已保存的 PNG 与 Word 文件；原始 Excel 见项目文件区。下载时检查访问权限与文件完整性。</p>
      {data.artifacts.total === 0 ? <p>还没有已生成的 PNG 或 Word 文件。</p> : <>
        <ul className="summary-artifacts">{data.artifacts.items.map(item => <li key={`${item.kind}:${item.id}`}>
          <div><strong>{item.download_filename}</strong><p>{item.kind === 'figure' ? 'PNG 图表' : 'Word 分析报告'} · {item.size_bytes.toLocaleString()} 字节 · {new Date(item.recorded_at).toLocaleString('zh-CN')}</p>
            <Source item={item} /></div>
          <ProjectDownloadLink href={item.download_url} filename={item.download_filename} ariaLabel={`下载成果 ${item.download_filename}`}>下载文件</ProjectDownloadLink>
        </li>)}</ul>
        <Pagination label="成果" page={data.artifacts.page} total={data.artifacts.total} onChange={artifacts => refresh({ ...pages, artifacts })} />
      </>}
      <div className="summary-future">
        <section><h4>{projectType === 'sci' ? 'SCI 初稿与稿件版本' : '毕业论文初稿与稿件版本'}</h4><p className="muted">功能未开放</p>
          <p>写作任务：无记录</p><p>当前稿件：无记录</p><p>稿件版本：无记录</p></section>
        {data.future.sci && <section><h4>SCI 期刊与投稿</h4><p className="muted">功能未开放</p>
          <p>期刊建议任务：无记录</p><p>目标期刊：无记录</p><p>期刊建议：无记录</p><p>实际投稿进展：无记录</p></section>}
        {data.future.thesis && <section><h4>学校与毕业论文评审</h4><p className="muted">功能未开放</p>
          <p>学校：无记录</p><p>学位：无记录</p><p>学校模板：无记录</p><p>实际评审进展：无记录</p></section>}
        <section><h4>{projectType === 'sci' ? '审稿修改与待补资料' : '导师及评审修改与待补资料'}</h4><p className="muted">功能未开放</p>
          <p>修改任务：无记录</p><p>当前修改轮次：无记录</p><p>历史修改轮次：无记录</p><p>意见处理状态：无记录</p><p>待补资料：无记录</p></section>
      </div>
    </>}
  </section>
}
