import { useEffect, useRef, useState } from 'react'
import { apiFetch, captureApiSession } from './api'
import { apiError, isLocale, safeError, useI18n, type Locale } from './i18n'
import { isProject, type Project } from './projectTypes'

export default function ProjectLanguage({ project, onUpdated, disabled, onBusyChange }: {
  project: Project; onUpdated: (value: Project) => void; disabled: boolean; onBusyChange: (value: boolean) => void
}) {
  const { t } = useI18n()
  const saved = project.default_output_language ?? 'zh-CN'
  const [selection, setSelection] = useState<{ saved: Locale; draft: Locale }>({ saved, draft: saved })
  const draft = selection.saved === saved ? selection.draft : saved
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [uncertain, setUncertain] = useState(false)
  const active = useRef<{ controller: AbortController; timeout: number } | null>(null)
  useEffect(() => () => {
    active.current?.controller.abort(); window.clearTimeout(active.current?.timeout); active.current = null
  }, [])

  async function submit(read = false) {
    if (disabled || active.current || (!read && (uncertain || draft === saved))) return
    const checkSession = captureApiSession()
    const request = { controller: new AbortController(), timeout: 0 }
    active.current = request; setBusy(true); onBusyChange(true); setError('')
    request.timeout = window.setTimeout(() => {
      if (active.current !== request) return
      request.controller.abort(); active.current = null; setBusy(false); onBusyChange(false); setUncertain(true)
      setError('输出语言保存超时，请重新读取项目确认。')
    }, 15_000)
    try {
      const response = await apiFetch(`/api/v1/projects/${encodeURIComponent(project.id)}/language`, {
        signal: request.controller.signal,
        ...(!read ? { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ default_output_language: draft }) } : {}),
      })
      const data = await response.json(); checkSession()
      if (active.current !== request || request.controller.signal.aborted) return
      if (!response.ok) throw new Error(apiError(data, '输出语言保存失败，请重试。'))
      if (!isProject(data) || data.id !== project.id || !isLocale(data.default_output_language)) throw new Error('项目响应格式不正确，请重新读取项目。')
      setSelection({ saved: data.default_output_language, draft: data.default_output_language }); setUncertain(false); onUpdated(data)
    } catch (cause) {
      if (active.current !== request || request.controller.signal.aborted || (cause instanceof DOMException && cause.name === 'AbortError')) return
      setError(safeError(cause, '输出语言保存失败，请重试。'))
    } finally {
      window.clearTimeout(request.timeout)
      if (active.current === request) { active.current = null; setBusy(false); onBusyChange(false) }
    }
  }
  return <form className="project-language" aria-busy={busy} onSubmit={event => { event.preventDefault(); void submit() }}>
    <label>{t('项目默认输出语言')}
      <select value={draft} disabled={disabled || busy || uncertain} onChange={event => { if (isLocale(event.target.value)) setSelection({ saved, draft: event.target.value }) }}>
        <option value="zh-CN">{t('简体中文')}</option><option value="en">{t('英语')}</option>
      </select>
    </label>
    <button type="submit" disabled={disabled || busy || uncertain || draft === saved}>{t(busy ? '正在保存……' : '保存输出语言')}</button>
    {uncertain && <button type="button" disabled={busy || disabled} onClick={() => void submit(true)}>{t('重新读取项目')}</button>}
    <p className="muted">{t('默认语言供后续生成任务使用；当前分析流程仍生成中文成果，历史成果及已提交任务保持原文。')}</p>
    {error && <p role="alert">{t(error)}</p>}
  </form>
}
