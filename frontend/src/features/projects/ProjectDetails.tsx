import { STANDARD_REQUEST_TIMEOUT_MS } from '../../shared/api/requestTimeouts'
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { apiFetch, captureApiSession } from '../../shared/api/client'
import type { Project } from './projectTypes'
import { apiError, safeError, useI18n } from '../../shared/i18n'
import ProjectLanguage from './ProjectLanguage'
import useDraftLeaveGuard, { type RegisterLeaveGuard } from './useDraftLeaveGuard'

type Field = 'name' | 'research_topic'
type FieldDraft = { saved: string; value: string; error: string; uncertain: boolean }
type Request = { controller: AbortController; timeout: number; field: Field; kind: 'save' | 'read' }
const fields = [
  { key: 'name', label: '修改项目名称', title: '项目名称', maxLength: 120 },
  { key: 'research_topic', label: '修改研究主题', title: '研究主题', maxLength: 500 },
] as const
const initialDraft = (value: string): FieldDraft => ({ saved: value, value, error: '', uncertain: false })

export default function ProjectDetails({ project, onUpdated, showHeading = true, renderHeader, registerLeaveGuard }: {
  project: Project; onUpdated: (project: Project) => void; showHeading?: boolean
  renderHeader?: (language: ReactNode) => ReactNode; registerLeaveGuard?: RegisterLeaveGuard
}) {
  const { t } = useI18n()
  const [drafts, setDrafts] = useState<Record<Field, FieldDraft>>(() => ({ name: initialDraft(project.name), research_topic: initialDraft(project.research_topic) }))
  const [busy, setBusy] = useState<{ field: Field; kind: 'save' | 'read' } | null>(null)
  const [languageBusy, setLanguageBusy] = useState(false)
  const request = useRef<Request | null>(null)
  const inputs = useRef<Record<Field, HTMLInputElement | HTMLTextAreaElement | null>>({ name: null, research_topic: null })
  const uncertain = fields.some(({ key }) => drafts[key].uncertain)
  useDraftLeaveGuard(registerLeaveGuard, fields.some(({ key }) => drafts[key].value !== drafts[key].saved), busy !== null || uncertain)

  useEffect(() => {
    setDrafts(previous => {
      let next = previous
      for (const { key } of fields) {
        const old = previous[key], saved = project[key]
        if (old.saved !== saved) next = { ...next, [key]: { ...old, saved, value: old.value === old.saved ? saved : old.value } }
      }
      return next
    })
  }, [project.name, project.research_topic])

  useEffect(() => () => {
    if (request.current) {
      window.clearTimeout(request.current.timeout)
      request.current.controller.abort()
      request.current = null
    }
  }, [])

  function change(field: Field, update: Partial<FieldDraft>) {
    setDrafts(previous => ({ ...previous, [field]: { ...previous[field], ...update } }))
  }
  function focus(field: Field) {
    const input = inputs.current[field]
    if (input && !input.closest('[hidden]')) input.focus()
  }

  async function submit(field: Field, kind: 'save' | 'read', value?: string) {
    if (request.current || languageBusy || (kind === 'save' && uncertain)) return
    const current: Request = { controller: new AbortController(), timeout: 0, field, kind }
    const checkSession = captureApiSession()
    request.current = current
    setBusy({ field, kind }); change(field, { error: '' })
    current.timeout = window.setTimeout(() => {
      if (request.current !== current) return
      request.current = null; current.controller.abort(); setBusy(null)
      change(field, kind === 'save'
        ? { uncertain: true, error: '保存请求超时，请先重新读取项目，核对服务端是否已保存。' }
        : { error: '项目读取超时，请稍后重试并核对保存结果。' })
    }, STANDARD_REQUEST_TIMEOUT_MS)
    try {
      const response = await apiFetch('/api/v1/projects/' + encodeURIComponent(project.id), {
        signal: current.controller.signal,
        ...(kind === 'save' ? { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ [field]: value }) } : {}),
      })
      const data = await response.json(); checkSession()
      if (!response.ok) throw new Error(apiError(data, kind === 'save' ? '保存修改失败，请稍后重试。' : '项目读取失败，请稍后重试。'))
      if (!data || data.id !== project.id || typeof data.name !== 'string' || typeof data.research_topic !== 'string') throw new Error('项目响应格式不正确，请重新读取项目。')
      if (request.current !== current || current.controller.signal.aborted) return
      change(field, initialDraft(data[field])); onUpdated(data)
    } catch (cause) {
      if (request.current !== current || current.controller.signal.aborted) return
      change(field, { error: cause instanceof TypeError ? '无法连接后端，请稍后重试。' : safeError(cause, '项目请求失败，请稍后重试。') })
    } finally {
      window.clearTimeout(current.timeout)
      if (request.current === current) { request.current = null; setBusy(null) }
    }
  }

  function save(field: Field, event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (request.current || uncertain || languageBusy) return
    const value = drafts[field].value.trim()
    if (!value) { change(field, { error: '请填写项目名称和研究主题。' }); return }
    if (value.length > (field === 'name' ? 120 : 500)) { change(field, { error: '项目名称最多 120 字，研究主题最多 500 字。' }); return }
    if (value === drafts[field].saved) { change(field, { value, error: '' }); return }
    void submit(field, 'save', value)
  }

  const language = <ProjectLanguage key={project.id} project={project} onUpdated={onUpdated} disabled={busy !== null || uncertain} onBusyChange={setLanguageBusy} registerLeaveGuard={registerLeaveGuard}/>
  return <div className={renderHeader ? 'project-details project-details-with-header' : 'project-details'}>
    {renderHeader ? renderHeader(language) : showHeading && <><h3>{project.name}</h3><p>{project.research_topic}</p></>}
    <div className={renderHeader ? 'project-info-body' : undefined}>
      <div className="project-edit-rows">{fields.map(({ key, label, title, maxLength }) => {
        const draft = drafts[key], blocked = busy !== null || languageBusy
        return <form key={key} className="project-edit-form" aria-label={t(title)} onSubmit={event => save(key, event)} aria-busy={busy?.field === key}>
          <label>{t(label)}{key === 'name'
            ? <input ref={element => { inputs.current[key] = element }} value={draft.value} onChange={event => change(key, { value: event.target.value })} required maxLength={maxLength} disabled={blocked}/>
            : <textarea ref={element => { inputs.current[key] = element }} value={draft.value} onChange={event => change(key, { value: event.target.value })} required maxLength={maxLength} rows={2} disabled={blocked}/>}</label>
          <div className="project-edit-actions">
            <button type="submit" aria-label={t('保存修改：{field}', { field: t(title) })} disabled={blocked || uncertain || draft.value === draft.saved}>{t(busy?.field === key && busy.kind === 'save' ? '正在保存……' : '保存修改')}</button>
            <button type="button" aria-label={t('取消修改：{field}', { field: t(title) })} disabled={blocked || draft.uncertain || (draft.value === draft.saved && !draft.error)} onClick={() => { change(key, { value: draft.saved, error: '' }); focus(key) }}>{t('取消修改')}</button>
            {draft.uncertain && <button type="button" disabled={blocked} onClick={() => void submit(key, 'read')}>{t(busy?.field === key && busy.kind === 'read' ? '正在读取……' : '重新读取项目')}</button>}
          </div>
          {draft.error && <p className="error-panel" role="alert">{t(draft.error)}</p>}
        </form>
      })}</div>
      {!renderHeader && language}
    </div>
  </div>
}
