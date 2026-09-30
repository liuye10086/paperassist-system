import { apiFetch } from './api'
import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import ExcelPreview from './ExcelPreview'
import AnalysisSetup from './AnalysisSetup'

type Project = {
  id: string; name: string; research_topic: string; project_type: 'sci' | 'thesis'
  file_count: number; created_at: string; updated_at: string
}
type ProjectFile = {
  id: string; filename: string; size_bytes: number; uploaded_at: string
  parse_status: 'parsed' | 'failed'; error: { code: string; message: string } | null
}
const typeNames = { sci: 'SCI 科研论文', thesis: '毕业论文' }

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
          <a href={`/api/v1/projects/${projectId}/files/${file.id}/download`} aria-label={`下载 ${file.filename}`}>下载原文件</a>
        </div>
      </li>)}</ul>
    </section>
    <ExcelPreview projectId={projectId} savedFile={opened} onSaved={uploaded} onBusyChange={setBusy} />
    <AnalysisSetup projectId={projectId} files={files} />
  </>
}

export default function ProjectWorkspace() {
  const [projects, setProjects] = useState<Project[]>([])
  const [selectedId, setSelectedId] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get('project') ?? '')
  const [attempt, setAttempt] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [createError, setCreateError] = useState('')
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [topic, setTopic] = useState('')
  const [projectType, setProjectType] = useState<'sci' | 'thesis'>('sci')
  const createController = useRef<AbortController | null>(null)
  const project = projects.find(item => item.id === selectedId)

  function refresh() {
    setLoading(true)
    setLoadError('')
    setAttempt(value => value + 1)
  }

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    const timeout = window.setTimeout(() => controller.abort(), 15_000)
    async function load() {
      try {
        const response = await apiFetch('/api/v1/projects', { signal: controller.signal })
        const result = await responseData(response, '项目列表读取失败。')
        if (!Array.isArray(result)) throw new Error('项目列表格式不正确。')
        if (active) {
          setProjects(result)
          setSelectedId(previous => result.some(item => item.id === previous) ? previous : '')
        }
      } catch {
        if (active) setLoadError('项目列表读取失败，请确认后端服务正常后重试。')
      } finally {
        window.clearTimeout(timeout)
        if (active) setLoading(false)
      }
    }
    void load()
    return () => { active = false; controller.abort(); window.clearTimeout(timeout) }
  }, [attempt])

  useEffect(() => {
    window.history.replaceState(null, '', window.location.pathname + window.location.search + (selectedId ? `#project=${encodeURIComponent(selectedId)}` : ''))
  }, [selectedId])
  useEffect(() => () => createController.current?.abort(), [])

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (createController.current) return
    if (!name.trim() || !topic.trim()) { setCreateError('请填写项目名称和研究主题。'); return }
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
        setProjects(previous => [created, ...previous])
        setSelectedId(created.id)
        setName('')
        setTopic('')
        refresh()
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
        <label>项目名称<input value={name} onChange={event => setName(event.target.value)} required maxLength={120} disabled={creating} /></label>
        <label>项目类型<select value={projectType} onChange={event => setProjectType(event.target.value as 'sci' | 'thesis')} disabled={creating}>
          <option value="sci">SCI 科研论文</option><option value="thesis">毕业论文</option>
        </select></label>
      </div>
      <label>研究主题<textarea value={topic} onChange={event => setTopic(event.target.value)} required maxLength={500} rows={2} disabled={creating} /></label>
      <button type="submit" disabled={creating || loading}>{creating ? '正在创建……' : '创建项目'}</button>
      {createError && <p className="error-panel" role="alert">{createError}</p>}
    </form>
    {loading && <p role="status">正在读取项目列表……</p>}
    {loadError && <div className="error-panel" role="alert">{loadError}{' '}
      <button type="button" onClick={refresh}>重试项目列表</button>
    </div>}
    {!loading && !loadError && projects.length === 0 && <p className="empty-preview">还没有项目，请先创建一个项目。</p>}
    {projects.length > 0 && <div className="project-selection">
      <label htmlFor="project-select">当前项目</label>
      <select id="project-select" value={selectedId} onChange={event => setSelectedId(event.target.value)}>
        <option value="">请选择项目</option>
        {projects.map(item => <option key={item.id} value={item.id}>{item.name} · {typeNames[item.project_type]}</option>)}
      </select>
    </div>}
    {project && <>
      <div className="project-details"><h3>{project.name}</h3><p>{project.research_topic}</p>
        <p className="muted">{typeNames[project.project_type]} · {project.file_count} 个文件 · 创建于 {new Date(project.created_at).toLocaleString('zh-CN')}</p>
      </div>
      <ProjectFiles key={project.id} projectId={project.id} onSaved={refresh} />
    </>}
  </section>
}
