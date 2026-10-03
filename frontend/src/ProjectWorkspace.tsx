import { apiFetch } from './api'
import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import ExcelPreview from './ExcelPreview'
import AnalysisSetup from './AnalysisSetup'
import ProjectDetails from './ProjectDetails'
import ProjectSummary from './ProjectSummary'
import ProjectDownloadLink from './ProjectDownloadLink'
import ProjectList, { type ProjectListQuery } from './ProjectList'
import useProjectSelection from './useProjectSelection'
import { isProject, type Project, type ProjectPage } from './projectTypes'
type ProjectFile = {
  id: string; filename: string; size_bytes: number; uploaded_at: string
  parse_status: 'parsed' | 'failed'; error: { code: string; message: string } | null
}

async function responseData(response: Response, fallback: string) {
  const data = await response.json().catch(() => null)
  if (!response.ok) throw new Error(typeof data?.detail?.message === 'string' ? data.detail.message : fallback)
  return data
}

function ProjectFiles({ projectId, onSaved }: { projectId: string; onSaved: () => void }) {
  const [files, setFiles] = useState<ProjectFile[]>([])
  const [attempt, setAttempt] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [opened, setOpened] = useState<{ id: string; request: number } | null>(null)
  const openSequence = useRef(0)

  function refresh() {
    setLoading(true)
    setError('')
    setAttempt(value => value + 1)
  }

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    const timeout = window.setTimeout(() => controller.abort(), 15_000)
    async function load() {
      try {
        const response = await apiFetch(`/api/v1/projects/${projectId}/files`, { signal: controller.signal })
        const result = await responseData(response, '文件列表读取失败。')
        if (!Array.isArray(result)) throw new Error('文件列表格式不正确。')
        if (active) setFiles(result)
      } catch {
        if (active) setError('文件列表读取失败，请确认后端服务正常后重试。')
      } finally {
        window.clearTimeout(timeout)
        if (active) setLoading(false)
      }
    }
    void load()
    return () => { active = false; controller.abort(); window.clearTimeout(timeout) }
  }, [projectId, attempt])

  function uploaded() {
    setOpened(null)
    refresh()
    onSaved()
  }

  return <>
    <section className="file-history" aria-labelledby="files-title">
      <div className="preview-heading">
        <h3 id="files-title">项目文件</h3>
        <button type="button" disabled={loading || busy} onClick={refresh}>刷新文件列表</button>
      </div>
      {loading && <p role="status">正在读取文件列表……</p>}
      {error && <p className="error-panel" role="alert">{error}</p>}
      {!loading && !error && files.length === 0 && <p>此项目还没有文件。</p>}
      <ul className="file-list">{files.map(file => <li key={file.id}>
        <div className="file-summary">
          <strong>{file.filename}</strong>
          <span className={file.parse_status === 'failed' ? 'file-failed' : 'file-parsed'}>
            {file.parse_status === 'failed' ? '解析失败' : '可预览'}
          </span>
          <p className="muted">{file.size_bytes.toLocaleString()} 字节 · {new Date(file.uploaded_at).toLocaleString('zh-CN')}</p>
          {file.error && <p className="file-failed">{file.error.message}</p>}
        </div>
        <div className="file-actions">
          {file.parse_status === 'parsed' && <button type="button" disabled={busy}
            aria-label={`预览 ${file.filename}`} onClick={() => setOpened({ id: file.id, request: ++openSequence.current })}>预览</button>}
          <ProjectDownloadLink href={`/api/v1/projects/${projectId}/files/${file.id}/download`} filename={file.filename} ariaLabel={`下载 ${file.filename}`}>下载原文件</ProjectDownloadLink>
        </div>
      </li>)}</ul>
    </section>
    <ExcelPreview projectId={projectId} savedFile={opened} onSaved={uploaded} onBusyChange={setBusy} />
    <AnalysisSetup projectId={projectId} files={files} />
  </>
}

export default function ProjectWorkspace() {
  const [projects, setProjects] = useState<Project[]>([])
  const [total, setTotal] = useState(0)
  const [query, setQuery] = useState<ProjectListQuery>({ page: 1, pageSize: 10, q: '', type: '' })
  const [searchDraft, setSearchDraft] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [createError, setCreateError] = useState('')
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [topic, setTopic] = useState('')
  const [projectType, setProjectType] = useState<'' | 'sci' | 'thesis'>('')
  const createController = useRef<AbortController | null>(null)
  const listRequest = useRef<{ controller: AbortController; timeout: number } | null>(null)
  const listSequence = useRef(0)
  const unavailableIds = useRef(new Set<string>())
  const nameInput = useRef<HTMLInputElement | null>(null)
  const selection = useProjectSelection(id => {
    unavailableIds.current.add(id)
    setProjects(previous => previous.filter(item => item.id !== id))
    refresh()
  }, id => {
    if (unavailableIds.current.delete(id)) refresh()
  })
  const project = selection.project

  function invalidateList() {
    listSequence.current++
    if (listRequest.current) {
      listRequest.current.controller.abort()
      window.clearTimeout(listRequest.current.timeout)
      listRequest.current = null
    }
  }

  function refresh() {
    invalidateList()
    setLoading(true)
    setLoadError('')
    setAttempt(value => value + 1)
  }

  function changeQuery(next: ProjectListQuery) {
    invalidateList()
    setLoading(true)
    setLoadError('')
    setQuery(next)
  }

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    const sequence = ++listSequence.current
    const timeout = window.setTimeout(() => {
      if (!active || sequence !== listSequence.current) return
      controller.abort()
      listSequence.current++
      setLoadError('项目列表读取超时，请稍后重试。')
      setLoading(false)
    }, 15_000)
    listRequest.current = { controller, timeout }
    async function load() {
      try {
        const parameters = new URLSearchParams({ page: String(query.page), page_size: String(query.pageSize) })
        if (query.q) parameters.set('q', query.q)
        if (query.type) parameters.set('type', query.type)
        const response = await apiFetch(`/api/v1/projects?${parameters}`, { signal: controller.signal })
        const result = await responseData(response, '项目列表读取失败。')
        if (!active || sequence !== listSequence.current || controller.signal.aborted) return
        if (!result || !Array.isArray(result.items) || !result.items.every(isProject)
          || !Number.isSafeInteger(result.total) || result.total < 0 || result.page !== query.page || result.page_size !== query.pageSize) {
          throw new Error('项目列表格式不正确。')
        }
        const data: ProjectPage = result
        const lastPage = Math.max(1, Math.ceil(data.total / query.pageSize))
        if (query.page > lastPage) {
          changeQuery({ ...query, page: lastPage })
          return
        }
        setProjects(data.items.filter(item => !unavailableIds.current.has(item.id)))
        setTotal(data.total)
      } catch {
        if (active && sequence === listSequence.current) setLoadError('项目列表读取失败，请确认后端服务正常后重试。')
      } finally {
        window.clearTimeout(timeout)
        if (active && sequence === listSequence.current) setLoading(false)
      }
    }
    void load()
    return () => { active = false; controller.abort(); window.clearTimeout(timeout) }
  }, [query, attempt])

  function updated(result: Project) {
    selection.update(result)
    setProjects(previous => previous.map(item => item.id === result.id ? result : item)
      .sort((a, b) => b.updated_at.localeCompare(a.updated_at)))
    refresh()
  }

  useEffect(() => () => createController.current?.abort(), [])

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (createController.current) return
    if (!name.trim() || !topic.trim()) { setCreateError('请填写项目名称和研究主题。'); return }
    if (!projectType) { setCreateError('请选择项目类型。'); return }
    const controller = new AbortController()
    createController.current = controller
    let timedOut = false
    const timeout = window.setTimeout(() => { timedOut = true; controller.abort() }, 15_000)
    setCreating(true)
    setCreateError('')
    try {
      const response = await apiFetch('/api/v1/projects', { method: 'POST', signal: controller.signal,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim(), research_topic: topic.trim(), project_type: projectType }),
      })
      const created: Project = await responseData(response, '创建项目失败，请检查输入后重试。')
      if (!controller.signal.aborted) {
        if (!isProject(created)) throw new Error('项目响应格式不正确，请刷新项目列表。')
        setProjects([created])
        selection.open(created.id, created)
        setSearchDraft('')
        changeQuery({ ...query, page: 1, q: '', type: '' })
        setName('')
        setTopic('')
        setProjectType('')
      }
    } catch (cause) {
      if (timedOut) setCreateError('创建请求超时，请先刷新项目列表确认是否已创建。')
      else if (!controller.signal.aborted) setCreateError(cause instanceof TypeError ? '无法连接后端，请稍后重试。'
        : cause instanceof Error ? cause.message : '创建项目失败。')
    } finally {
      window.clearTimeout(timeout)
      createController.current = null
      if (!controller.signal.aborted || timedOut) setCreating(false)
    }
  }

  return <section className="project-workspace" aria-labelledby="projects-title">
    <div className="section-heading"><h2 id="projects-title">项目中心</h2><p>按项目保存研究资料，继续查看已上传的数据。</p></div>
    <form className="project-form" onSubmit={create} aria-busy={creating}>
      <h3>新建项目</h3>
      <div className="project-fields">
        <label>项目名称<input ref={nameInput} value={name} onChange={event => setName(event.target.value)} required maxLength={120} disabled={creating} /></label>
        <label>项目类型<select value={projectType} onChange={event => setProjectType(event.target.value as '' | 'sci' | 'thesis')} required disabled={creating}>
          <option value="">请选择项目类型</option><option value="sci">SCI 科研论文</option><option value="thesis">毕业论文</option>
        </select></label>
      </div>
      <label>研究主题<textarea value={topic} onChange={event => setTopic(event.target.value)} required maxLength={500} rows={2} disabled={creating} /></label>
      <button type="submit" disabled={creating}>{creating ? '正在创建……' : '创建项目'}</button>
      {createError && <p className="error-panel" role="alert">{createError}</p>}
    </form>
    <ProjectList items={projects} total={total} query={query} searchDraft={searchDraft} loading={loading} error={loadError}
      onSearchDraftChange={setSearchDraft} onQueryChange={changeQuery} onOpen={selection.open} onRetry={refresh}
      onCreate={() => nameInput.current?.focus()} />
    {selection.unavailableId && <div className="error-panel" role="alert">项目不存在或无权访问。{' '}
      <button type="button" onClick={selection.close}>返回项目列表</button>{' '}
      <button type="button" onClick={() => selection.open(selection.unavailableId)}>重试打开项目</button>
    </div>}
    {selection.instance && <section className="selected-project" aria-label="当前项目工作区">
      <button type="button" onClick={selection.close}>返回项目列表</button>
      {selection.loading && <p role="status">正在读取项目详情……</p>}
      {selection.error && <div className="error-panel" role="alert">{selection.error}{' '}
        <button type="button" onClick={selection.refresh}>重试项目详情</button>
      </div>}
      {project && <div key={selection.instance.key}>
        <ProjectDetails project={project} onUpdated={updated} />
        <ProjectSummary projectId={project.id} projectType={project.project_type} />
        <ProjectFiles projectId={project.id} onSaved={() => { refresh(); selection.refresh() }} />
      </div>}
    </section>}
  </section>
}
