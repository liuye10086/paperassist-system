import { useEffect, useId, useLayoutEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { apiFetch, clearApiSession, onApiSessionChanged, onSessionCookieChanged, onSessionExpired, setApiSession } from '../../shared/api/client'
import './auth.css'
import PasswordForm from './PasswordForm'
import LanguageControl from './LanguageControl'
import { apiError, isLocale, message, setLocale, useI18n, type Locale } from '../../shared/i18n'

type Session = { user: { id: string; email: string; role: string; ui_language?: Locale }; csrf_token: string }
type Status = 'restoring' | 'unavailable' | 'anonymous' | 'authenticated'
type AuthRequest = { kind: 'restore' | 'login' | 'logout'; controller: AbortController; timeout: number }

function validateSession(value: Session) {
  if (!value || typeof value.csrf_token !== 'string' || !value.csrf_token || !value.user
    || typeof value.user.id !== 'string' || !value.user.id || typeof value.user.email !== 'string') {
    throw new Error('invalid_session')
  }
}

async function errorMessage(response: Response, fallback: string) {
  if (response.status === 429) {
    const retry = response.headers.get('Retry-After')
    return retry && /^\d{1,6}$/.test(retry) ? message('登录尝试过多，请 {seconds} 秒后重试。', { seconds: retry }) : '登录尝试过多，请稍后重试。'
  }
  if (response.status === 401) return '账号或密码错误。'
  try {
    return apiError(await response.json(), fallback)
  } catch {
    return fallback
  }
}

export default function AuthBoundary({ children }: { children: ReactNode }) {
  const { t } = useI18n()
  const accountActionsId = useId()
  const [status, setStatus] = useState<Status>('restoring')
  const [session, setSession] = useState<Session | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [passwordMode, setPasswordMode] = useState<'change' | 'reset' | null>(null)
  const [notice, setNotice] = useState('')
  const [accountOpen, setAccountOpen] = useState(false)
  const accountRegion = useRef<HTMLDivElement | null>(null)
  const accountButton = useRef<HTMLButtonElement | null>(null)
  const channel = useRef<BroadcastChannel | null>(null)
  const activeRequest = useRef<AuthRequest | null>(null)
  const sessionCancellation = useRef<number | undefined>(undefined)
  const emailInput = useRef<HTMLInputElement | null>(null)
  const forgotButton = useRef<HTMLButtonElement | null>(null)
  const workspace = useRef<HTMLDivElement | null>(null)
  const [focusTarget, setFocusTarget] = useState<'email' | 'forgot' | 'change' | 'workspace'>('email')

  useLayoutEffect(() => {
    if (passwordMode) return
    if (status === 'anonymous') (focusTarget === 'forgot' ? forgotButton : emailInput).current?.focus()
    if (status === 'authenticated') {
      if (focusTarget === 'change') accountButton.current?.focus()
      else (workspace.current?.querySelector<HTMLElement>('main') ?? workspace.current?.querySelector<HTMLElement>('input:not(:disabled),button:not(:disabled),a[href],select:not(:disabled)') ?? workspace.current)?.focus()
    }
  }, [status, passwordMode, focusTarget])

  useEffect(() => {
    if (!accountOpen) return
    const dismissOutside = (event: Event) => {
      if (event.target instanceof Node && !accountRegion.current?.contains(event.target)) setAccountOpen(false)
    }
    document.addEventListener('pointerdown', dismissOutside, true)
    document.addEventListener('focusin', dismissOutside, true)
    return () => {
      document.removeEventListener('pointerdown', dismissOutside, true)
      document.removeEventListener('focusin', dismissOutside, true)
    }
  }, [accountOpen])

  function cancelRequest() {
    window.clearTimeout(sessionCancellation.current)
    const current = activeRequest.current
    activeRequest.current = null
    if (current) { window.clearTimeout(current.timeout); current.controller.abort() }
  }

  function beginRequest(kind: AuthRequest['kind']) {
    if (activeRequest.current) return null
    const current: AuthRequest = { kind, controller: new AbortController(), timeout: 0 }
    activeRequest.current = current
    current.timeout = window.setTimeout(() => {
      if (activeRequest.current !== current) return
      cancelRequest(); setBusy(false)
      if (kind === 'restore') { setError('会话恢复超时，请检查连接后重试。'); setStatus('unavailable') }
      else if (kind === 'login') { setPassword(''); setError('登录请求超时，尚未确认登录结果，请重试或刷新以核对会话。') }
      else setError('退出请求超时，服务端会话尚未确认撤销，请重试。')
    }, 15_000)
    return current
  }

  function currentRequest(current: AuthRequest) {
    return activeRequest.current === current && !current.controller.signal.aborted
  }

  function finishRequest(current: AuthRequest) {
    if (activeRequest.current !== current) return
    window.clearTimeout(sessionCancellation.current)
    window.clearTimeout(current.timeout); activeRequest.current = null; setBusy(false)
  }

  const reset = () => {
    cancelRequest()
    setFocusTarget('email')
    setAccountOpen(false)
    setLocale('zh-CN')
    window.history.replaceState(null, '', window.location.pathname + window.location.search)
    setSession(null)
    setPassword('')
    setPasswordMode(null)
    setStatus('anonymous')
  }

  useEffect(() => {
    const unsubscribeRequests = onApiSessionChanged(() => {
      // /me's anonymous 401 legitimately clears the generation before returning.
      // Give that response one turn to finish; any still-pending restore belongs
      // to the previous generation and must be cancelled, including body reads.
      const current = activeRequest.current
      if (current?.kind === 'restore') {
        window.clearTimeout(sessionCancellation.current)
        sessionCancellation.current = window.setTimeout(() => {
          if (activeRequest.current !== current) return
          cancelRequest(); setBusy(false); setStatus('unavailable')
          setError('无法恢复会话，请检查连接后重试。')
        }, 0)
      } else { cancelRequest(); setBusy(false) }
    })
    const restoreCookieSession = () => {
      clearApiSession()
      setLocale('zh-CN')
      reset()
      setBusy(false)
      setError('')
      setNotice('')
      setStatus('restoring')
      setAttempt(value => value + 1)
    }
    const unsubscribeCookie = onSessionCookieChanged(() => {
      restoreCookieSession()
      channel.current?.postMessage('session_changed')
    })
    const unsubscribe = onSessionExpired(() => {
      reset()
      setBusy(false)
      setError('会话已失效，请重新登录。')
    })
    if (typeof BroadcastChannel !== 'undefined') {
      const connection = new BroadcastChannel('paperassist-auth')
      channel.current = connection
      connection.onmessage = event => {
        if (event.data !== 'session_changed') return
        restoreCookieSession()
      }
    }
    return () => {
      unsubscribeRequests()
      cancelRequest()
      unsubscribe()
      unsubscribeCookie()
      channel.current?.close()
      channel.current = null
      clearApiSession()
      setLocale('zh-CN')
    }
  }, [])

  useEffect(() => {
    const current = beginRequest('restore')
    if (!current) return
    const controller = current.controller
    async function restore(current: AuthRequest) {
      setStatus('restoring')
      setError('')
      try {
        const response = await apiFetch('/api/v1/auth/me', { signal: controller.signal })
        if (!currentRequest(current)) return
        if (response.status === 401) {
          finishRequest(current)
          setStatus('anonymous')
          return
        }
        if (!response.ok) throw new Error('restore')
        const restored: Session = await response.json()
        if (!currentRequest(current)) return
        validateSession(restored)
        finishRequest(current)
        setFocusTarget('workspace')
        setApiSession(restored.csrf_token)
        setLocale(isLocale(restored.user.ui_language) ? restored.user.ui_language : 'zh-CN')
        setSession(restored)
        setStatus('authenticated')
      } catch {
        if (currentRequest(current)) {
          finishRequest(current)
          setStatus('unavailable')
          setError('无法恢复会话，请检查连接后重试。')
        }
      }
    }
    void restore(current)
    return () => {
      if (activeRequest.current === current) cancelRequest()
      else controller.abort()
    }
  }, [attempt])

  async function login(event: FormEvent) {
    event.preventDefault()
    const current = beginRequest('login')
    if (!current) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const response = await apiFetch('/api/v1/auth/login', {
        method: 'POST',
        signal: current.controller.signal,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      })
      if (!response.ok) {
        const error = await errorMessage(response, '登录失败，请稍后重试。')
        if (currentRequest(current)) setError(error)
        return
      }
      const restored: Session = await response.json()
      if (!currentRequest(current)) return
      validateSession(restored)
      finishRequest(current)
      setFocusTarget('workspace')
      setApiSession(restored.csrf_token)
      setLocale(isLocale(restored.user.ui_language) ? restored.user.ui_language : 'zh-CN')
      setSession(restored)
      setPassword('')
      setStatus('authenticated')
      channel.current?.postMessage('session_changed')
    } catch (cause) {
      if (currentRequest(current) && !(cause instanceof DOMException && cause.name === 'AbortError')) {
        setError('登录失败，请检查连接后重试。')
      }
    } finally {
      finishRequest(current)
    }
  }

  async function logout() {
    const current = beginRequest('logout')
    if (!current) return
    setBusy(true)
    setError('')
    try {
      const response = await apiFetch('/api/v1/auth/logout', { method: 'POST', signal: current.controller.signal })
      if (!currentRequest(current)) return
      if (response.status === 401) return
      if (!response.ok) {
        setError('退出失败，服务端会话尚未确认撤销，请重试。')
        return
      }
      finishRequest(current)
      clearApiSession()
      reset()
      channel.current?.postMessage('session_changed')
    } catch (cause) {
      if (currentRequest(current) && !(cause instanceof DOMException && cause.name === 'AbortError')) {
        setError('退出失败，服务端会话尚未确认撤销，请重试。')
      }
    } finally {
      finishRequest(current)
    }
  }

  function passwordUpdated() {
    clearApiSession()
    reset()
    setError('')
    setNotice('密码已更新，请重新登录。')
    channel.current?.postMessage('session_changed')
  }

  const languageControl = <LanguageControl key={session?.user.id ?? status} userId={status === 'authenticated' ? session?.user.id : undefined} disabled={status === 'restoring'} />
  const brand = <aside className="auth-brand">
    <div className="auth-brand-name"><span className="auth-brand-mark" aria-hidden="true"><i /><i /><i /></span>PaperAssist</div>
    <div className="auth-brand-copy"><p className="auth-eyebrow">{t('科研，从容开始')}</p>
      <h1>{t('让研究更有条理，')}<br />{t('让写作更进一步。')}</h1>
      <p>{t('从文献、数据到论文，把研究中的每一步汇聚在一个清晰的工作空间。')}</p>
      <div className="auth-brand-art" aria-hidden="true"><span /><span /><span /></div>
    </div>
    <p className="auth-brand-footer">{t('专注研究，连接灵感')}</p>
  </aside>
  function anonymousShell(content: ReactNode) {
    return <div className="auth-page">{brand}<main className="auth-form-area">
      <div className="auth-language">{languageControl}</div><div className="auth-form-wrap">{content}</div>
      <p className="auth-copyright">PaperAssist · {t('科研论文辅助系统')}</p>
    </main></div>
  }
  if (status === 'restoring') return anonymousShell(<p role="status">{t('正在恢复会话……')}</p>)
  if (status === 'unavailable') return anonymousShell(<section className="login-panel">
    <h2>{t('暂时无法连接')}</h2><p role="alert">{t(error)}</p>
    <button className="button-primary" onClick={() => setAttempt(value => value + 1)}>{t('重试')}</button>
  </section>)
  if (status === 'authenticated') {
    return <div className="authenticated-app">
      <header className="auth-topbar">{languageControl}
        <div ref={accountRegion} className="auth-account" onKeyDown={event => {
          if (event.key === 'Escape' && accountOpen) { event.preventDefault(); setAccountOpen(false); accountButton.current?.focus() }
        }}>
          <button ref={accountButton} className="auth-account-button" aria-label={t('账号')} aria-expanded={accountOpen}
            aria-controls={accountActionsId} disabled={busy} onClick={() => setAccountOpen(value => !value)}>
            <span className="auth-avatar" aria-hidden="true">{session?.user.email.slice(0, 1).toUpperCase()}</span>
            <span className="auth-account-email">{session?.user.email}</span><span aria-hidden="true">⌄</span>
          </button>
          {accountOpen && <div className="auth-account-actions" id={accountActionsId}>
            <button disabled={busy || passwordMode !== null} onClick={() => { setAccountOpen(false); setError(''); setPasswordMode('change') }}>{t('修改密码')}</button>
            <button disabled={busy} onClick={() => void logout()}>{busy ? t('正在退出……') : t('退出登录')}</button>
          </div>}
        </div>
      </header>
      {error && <p className="auth-session-error" role="alert">{t(error)}</p>}
      {passwordMode === 'change' && <div className="auth-password-region"><PasswordForm mode="change"
        onCancel={() => { setFocusTarget('change'); setPasswordMode(null) }} onSuccess={passwordUpdated} /></div>}
      <div className="auth-workspace" ref={workspace} tabIndex={-1}>{children}</div>
    </div>
  }
  if (passwordMode === 'reset') return anonymousShell(<PasswordForm mode="reset" onCancel={() => { setFocusTarget('forgot'); setPasswordMode(null) }} onSuccess={passwordUpdated} />)
  return anonymousShell(<section className="login-panel">
    <p className="auth-eyebrow">{t('欢迎使用 PaperAssist')}</p><h2>{t('登录')}</h2>
    <p>{t('账号由管理员创建')}</p>
    {notice && <p role="status">{t(notice)}</p>}
    <form onSubmit={event => void login(event)} aria-busy={busy}>
      <label>{t('邮箱')}<input ref={emailInput} type="email" autoComplete="username" required value={email} disabled={busy}
          onChange={event => setEmail(event.target.value)} /></label>
      <label>{t('密码')}<input type="password" autoComplete="current-password" required maxLength={256} value={password}
          disabled={busy} onChange={event => setPassword(event.target.value)} /></label>
      <button className="button-primary auth-login-submit" disabled={busy} type="submit">{busy ? t('正在登录……') : t('登录')}</button>
      <button className="button-quiet auth-forgot" ref={forgotButton} disabled={busy} type="button" onClick={() => { setPassword(''); setError(''); setNotice(''); setPasswordMode('reset') }}>{t('忘记密码')}</button>
      {error && <p role="alert">{t(error)}</p>}
    </form>
    <p className="auth-contact">{t('需要账号？请联系管理员。')}</p>
  </section>)
}
