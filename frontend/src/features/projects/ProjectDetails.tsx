import { useEffect, useLayoutEffect, useRef, useState, type FormEvent } from 'react'
import { apiFetch } from '../../shared/api/client'
import { typeNames, type Project } from './projectTypes'
import { apiError, safeError, useI18n } from '../../shared/i18n'
import ProjectLanguage from './ProjectLanguage'

type Request = { controller: AbortController; timeout: number }

export default function ProjectDetails({ project, onUpdated, showHeading = true }: { project: Project; onUpdated: (project: Project) => void; showHeading?: boolean }) {
  const { t, locale } = useI18n()
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(project.name)
  const [topic, setTopic] = useState(project.research_topic)
  const baseline = useRef({ name: project.name, research_topic: project.research_topic })
  const [busy, setBusy] = useState<'save' | 'read' | null>(null)
  const [error, setError] = useState('')
  const [uncertain, setUncertain] = useState(false)
  const [languageBusy, setLanguageBusy] = useState(false)
  const request = useRef<Request | null>(null)
  const editButton = useRef<HTMLButtonElement | null>(null)
  const nameInput = useRef<HTMLInputElement | null>(null)
  const wasEditing = useRef(false)
  useLayoutEffect(() => {
    if (editing) { wasEditing.current = true; nameInput.current?.focus() }
    else if (wasEditing.current) { wasEditing.current = false; editButton.current?.focus() }
  }, [editing])

  useEffect(() => () => {
    if (request.current) {
      window.clearTimeout(request.current.timeout)
      request.current.controller.abort()
      request.current = null
    }
  }, [])

  function startEditing() {
    if (languageBusy) return
    baseline.current = { name: project.name, research_topic: project.research_topic }
    setName(project.name)
    setTopic(project.research_topic)
    setEditing(true)
    setError('')
    setUncertain(false)
  }

  async function submit(kind: 'save' | 'read', changes?: Partial<Pick<Project, 'name' | 'research_topic'>>) {
    if (request.current) return
    const current: Request = { controller: new AbortController(), timeout: 0 }
    request.current = current
    setBusy(kind)
    setError('')
    current.timeout = window.setTimeout(() => {
      if (request.current !== current) return
      request.current = null
      current.controller.abort()
      setBusy(null)
      if (kind === 'save') {
        setUncertain(true)
        setError('保存请求超时，请先重新读取项目，核对服务端是否已保存。')
      } else setError('项目读取超时，请稍后重试并核对保存结果。')
    }, 15_000)
    try {
      const response = await apiFetch(`/api/v1/projects/${encodeURIComponent(project.id)}`, {
        signal: current.controller.signal,
        ...(kind === 'save' ? { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(changes) } : {}),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(apiError(data, kind === 'save' ? '保存修改失败，请稍后重试。' : '项目读取失败，请稍后重试。'))
      if (!data || data.id !== project.id || typeof data.name !== 'string' || typeof data.research_topic !== 'string') {
        throw new Error('项目响应格式不正确，请重新读取项目。')
      }
      if (request.current !== current || current.controller.signal.aborted) return
      onUpdated(data)
      setEditing(false)
      setUncertain(false)
    } catch (cause) {
      if (request.current !== current || current.controller.signal.aborted) return
      setError(cause instanceof TypeError ? '无法连接后端，请稍后重试。'
        : safeError(cause, '项目请求失败，请稍后重试。'))
    } finally {
      window.clearTimeout(current.timeout)
      if (request.current === current) {
        request.current = null
        setBusy(null)
      }
    }
  }

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (request.current || uncertain) return
    const nextName = name.trim()
    const nextTopic = topic.trim()
    if (!nextName || !nextTopic) { setError('请填写项目名称和研究主题。'); return }
    if (nextName.length > 120 || nextTopic.length > 500) { setError('项目名称最多 120 字，研究主题最多 500 字。'); return }
    const changes: Partial<Pick<Project, 'name' | 'research_topic'>> = {}
    if (nextName !== baseline.current.name) changes.name = nextName
    if (nextTopic !== baseline.current.research_topic) changes.research_topic = nextTopic
    if (Object.keys(changes).length === 0) { setEditing(false); setError(''); return }
    void submit('save', changes)
  }

  return <div className="project-details">
    {showHeading && <><h3>{project.name}</h3><p>{project.research_topic}</p></>}
    <p className="muted">{t('{type}（创建后不可更改） · {count} 个文件 · 创建于 {date}', { type: t(typeNames[project.project_type]), count: project.file_count, date: new Date(project.created_at).toLocaleString(locale) })}</p>
    {editing ? <form className="project-edit-form" onSubmit={save} aria-busy={busy !== null}>
      <p className="muted">{t("修改项目信息不会自动重新生成历史报告；已生成的 Word 保留生成时的项目名称和研究主题。")}</p>
      <label>{t("修改项目名称")}<input ref={nameInput} value={name} onChange={event => setName(event.target.value)} required maxLength={120} disabled={busy !== null} /></label>
      <label>{t("修改研究主题")}<textarea value={topic} onChange={event => setTopic(event.target.value)} required maxLength={500} rows={2} disabled={busy !== null} /></label>
      <div className="project-edit-actions">
        <button type="submit" disabled={busy !== null || uncertain}>{busy === 'save' ? t("正在保存……") : t("保存修改")}</button>
        <button type="button" disabled={busy !== null} onClick={() => { setEditing(false); setError(''); setUncertain(false) }}>{t("取消修改")}</button>
        {uncertain && <button type="button" disabled={busy !== null} onClick={() => void submit('read')}>{busy === 'read' ? t("正在读取……") : t("重新读取项目")}</button>}
      </div>
    </form> : <button ref={editButton} type="button" disabled={languageBusy} onClick={startEditing}>{t("编辑项目信息")}</button>}
    {error && <p className="error-panel" role="alert">{t(error)}</p>}
    <ProjectLanguage key={project.id} project={project} onUpdated={onUpdated} disabled={editing || busy !== null} onBusyChange={setLanguageBusy} />
  </div>
}
