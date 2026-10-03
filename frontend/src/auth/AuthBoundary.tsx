import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { apiFetch, clearApiSession, onSessionCookieChanged, onSessionExpired, setApiSession } from '../api'
import PasswordForm from './PasswordForm'

type Session = { user: { id: string; email: string; role: string }; csrf_token: string }
type Status = 'restoring' | 'unavailable' | 'anonymous' | 'authenticated'

async function errorMessage(response: Response, fallback: string) {
  if (response.status === 429) {
    const retry = response.headers.get('Retry-After')
    return `登录尝试过多，请${retry ? ` ${retry} 秒后` : '稍后'}重试。`
  }
  if (response.status === 401) return '账号或密码错误。'
  try {
    return (await response.json()).detail?.message ?? fallback
  } catch {
    return fallback
  }
}

export default function AuthBoundary({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>('restoring')
  const [session, setSession] = useState<Session | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [passwordMode, setPasswordMode] = useState<'change' | 'reset' | null>(null)
  const [notice, setNotice] = useState('')
  const channel = useRef<BroadcastChannel | null>(null)

  const reset = () => {
    window.history.replaceState(null, '', window.location.pathname + window.location.search)
    setSession(null)
    setPassword('')
    setPasswordMode(null)
    setStatus('anonymous')
  }

  useEffect(() => {
    const restoreCookieSession = () => {
      clearApiSession()
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
      unsubscribe()
      unsubscribeCookie()
      channel.current?.close()
      channel.current = null
      clearApiSession()
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    async function restore() {
      setStatus('restoring')
      setError('')
      try {
        const response = await apiFetch('/api/v1/auth/me', { signal: controller.signal })
        if (controller.signal.aborted) return
        if (response.status === 401) {
          setStatus('anonymous')
          return
        }
        if (!response.ok) throw new Error('restore')
        const restored: Session = await response.json()
        if (controller.signal.aborted) return
        setApiSession(restored.csrf_token)
        setSession(restored)
        setStatus('authenticated')
      } catch {
        if (!controller.signal.aborted) {
          setStatus('unavailable')
          setError('无法恢复会话，请检查连接后重试。')
        }
      }
    }
    void restore()
    return () => controller.abort()
  }, [attempt])

  async function login(event: FormEvent) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const response = await apiFetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      })
      if (!response.ok) {
        setError(await errorMessage(response, '登录失败，请稍后重试。'))
        return
      }
      const restored: Session = await response.json()
      setApiSession(restored.csrf_token)
      setSession(restored)
      setPassword('')
      setStatus('authenticated')
      channel.current?.postMessage('session_changed')
    } catch (cause) {
      if (!(cause instanceof DOMException && cause.name === 'AbortError')) {
        setError('登录失败，请检查连接后重试。')
      }
    } finally {
      setBusy(false)
    }
  }

  async function logout() {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const response = await apiFetch('/api/v1/auth/logout', { method: 'POST' })
      if (response.status === 401) return
      if (!response.ok) {
        setError('退出失败，服务端会话尚未确认撤销，请重试。')
        return
      }
      clearApiSession()
      reset()
      channel.current?.postMessage('session_changed')
    } catch (cause) {
      if (!(cause instanceof DOMException && cause.name === 'AbortError')) {
        setError('退出失败，服务端会话尚未确认撤销，请重试。')
      }
    } finally {
      setBusy(false)
    }
  }

  function passwordUpdated() {
    clearApiSession()
    reset()
    setError('')
    setNotice('密码已更新，请重新登录。')
    channel.current?.postMessage('session_changed')
  }

  if (status === 'restoring') return <p role="status">正在恢复会话……</p>
  if (status === 'unavailable') {
    return <section>
      <p role="alert">{error}</p>
      <button onClick={() => setAttempt(value => value + 1)}>重试</button>
    </section>
  }
  if (status === 'authenticated') {
    return <>
      <p className="connection-status" role="status">后端连接成功</p>
      <div className="session-bar">
        <span>{session?.user.email}</span>
        <button disabled={busy || passwordMode !== null} onClick={() => { setError(''); setPasswordMode('change') }}>修改密码</button>
        <button disabled={busy} onClick={() => void logout()}>{busy ? '正在退出……' : '退出登录'}</button>
      </div>
      {error && <p role="alert">{error}</p>}
      {passwordMode === 'change' && <PasswordForm mode="change" onCancel={() => setPasswordMode(null)} onSuccess={passwordUpdated} />}
      {children}
    </>
  }
  if (passwordMode === 'reset') return <PasswordForm mode="reset" onCancel={() => setPasswordMode(null)} onSuccess={passwordUpdated} />
  return <section className="login-panel">
    <h2>登录</h2>
    <p>账号由管理员创建</p>
    {notice && <p role="status">{notice}</p>}
    <form onSubmit={event => void login(event)} aria-busy={busy}>
      <label>邮箱
        <input type="email" autoComplete="username" required value={email} disabled={busy}
          onChange={event => setEmail(event.target.value)} />
      </label>
      <label>密码
        <input type="password" autoComplete="current-password" required maxLength={256} value={password}
          disabled={busy} onChange={event => setPassword(event.target.value)} />
      </label>
      <button disabled={busy} type="submit">{busy ? '正在登录……' : '登录'}</button>
      <button disabled={busy} type="button" onClick={() => { setPassword(''); setError(''); setNotice(''); setPasswordMode('reset') }}>忘记密码</button>
      {error && <p role="alert">{error}</p>}
    </form>
  </section>
}
