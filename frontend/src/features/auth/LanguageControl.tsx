import { useEffect, useRef, useState } from 'react'
import { apiFetch, captureApiSession } from '../../shared/api/client'
import { apiError, isLocale, safeError, setLocale, useI18n, type Locale } from '../../shared/i18n'

export default function LanguageControl({ userId, disabled = false }: { userId?: string; disabled?: boolean }) {
  const { locale, t } = useI18n()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [pending, setPending] = useState<Locale | null>(null)
  const active = useRef<{ controller: AbortController; timeout: number } | null>(null)
  useEffect(() => () => {
    active.current?.controller.abort()
    window.clearTimeout(active.current?.timeout)
    active.current = null
  }, [])

  async function save(value: Locale) {
    if (active.current || disabled) return
    setError('')
    if (!userId) { setLocale(value); return }
    const checkSession = captureApiSession()
    const request = { controller: new AbortController(), timeout: 0 }
    active.current = request
    setBusy(true); setPending(value)
    request.timeout = window.setTimeout(() => {
      if (active.current !== request) return
      request.controller.abort(); active.current = null; setBusy(false)
      setError('语言保存超时，请重新登录以确认已保存的偏好。')
    }, 15_000)
    try {
      const response = await apiFetch('/api/v1/auth/preferences', {
        method: 'PATCH', signal: request.controller.signal,
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ui_language: value }),
      })
      const data = await response.json()
      checkSession()
      if (active.current !== request || request.controller.signal.aborted) return
      if (!response.ok) throw new Error(apiError(data, '界面语言保存失败，请重试。'))
      if (!isLocale(data?.ui_language)) throw new Error('界面语言保存失败，请重试。')
      setLocale(data.ui_language); setPending(null)
    } catch (cause) {
      if (active.current !== request || request.controller.signal.aborted || (cause instanceof DOMException && cause.name === 'AbortError')) return
      setError(safeError(cause, '界面语言保存失败，请重试。'))
    } finally {
      window.clearTimeout(request.timeout)
      if (active.current === request) { active.current = null; setBusy(false) }
    }
  }

  return <div className="language-control" aria-busy={busy}>
    <label>{t('界面语言')}
      <select value={locale} disabled={disabled || busy} onChange={event => { if (isLocale(event.target.value)) void save(event.target.value) }}>
        <option value="zh-CN">简体中文</option><option value="en">English</option>
      </select>
    </label>
    {busy && <span role="status">{t('正在保存语言……')}</span>}
    {error && <><span role="alert">{t(error)}</span><button type="button" disabled={busy} onClick={() => { if (pending) void save(pending) }}>{t('重试保存语言')}</button></>}
  </div>
}
