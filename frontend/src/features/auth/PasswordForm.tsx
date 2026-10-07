import { useEffect, useLayoutEffect, useRef, useState, type FormEvent } from 'react'
import { apiFetch, captureApiSession, onApiSessionChanged } from '../../shared/api/client'
import { message, useI18n } from '../../shared/i18n'

type Props = { mode: 'change' | 'reset'; onCancel: () => void; onSuccess: () => void }
const passwordRule = '新密码须为12–128个字符。'

async function passwordError(response: Response) {
  if (response.status === 429) {
    const retry = response.headers.get('Retry-After')
    return retry && /^\d{1,6}$/.test(retry) ? message('密码操作尝试过多，请 {seconds} 秒后重试。', { seconds: retry }) : '密码操作尝试过多，请稍后重试。'
  }
  const body = await response.json().catch(() => null)
  switch (body?.detail?.code) {
    case 'invalid_current_password': return '当前密码不正确。'
    case 'invalid_recovery_code': return '恢复码无效或已过期，请联系管理员重新核验并签发。'
    case 'invalid_request': return `输入格式有误，${passwordRule}`
    default: return '密码更新失败，请稍后重试。'
  }
}

export default function PasswordForm({ mode, onCancel, onSuccess }: Props) {
  const { t } = useI18n()
  const [credential, setCredential] = useState('')
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const active = useRef<AbortController | null>(null)
  const timeout = useRef<number | undefined>(undefined)
  const cancelCallback = useRef(onCancel)
  const credentialInput = useRef<HTMLInputElement | null>(null)
  useLayoutEffect(() => { credentialInput.current?.focus() }, [])
  useEffect(() => { cancelCallback.current = onCancel }, [onCancel])

  function clearSecrets() { setCredential(''); setPassword(''); setConfirmation('') }
  function abort() {
    active.current?.abort()
    active.current = null
    window.clearTimeout(timeout.current)
  }
  useEffect(() => {
    const unsubscribe = onApiSessionChanged(() => {
      abort(); clearSecrets(); setBusy(false); setError(''); cancelCallback.current()
    })
    return () => { unsubscribe(); abort() }
  }, [])

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (active.current) return
    setError('')
    const length = Array.from(password).length
    if (length < 12 || length > 128) { setError(passwordRule); return }
    if (password !== confirmation) { setError('两次输入的新密码不一致。'); return }
    if (!credential || (mode === 'reset' && !credential.trim())) {
      setError(mode === 'change' ? '请输入当前密码。' : '请输入恢复码。'); return
    }
    const controller = new AbortController()
    active.current = controller
    const sessionCheck = captureApiSession()
    const check = () => {
      sessionCheck()
      if (active.current !== controller || controller.signal.aborted) throw new DOMException('请求已取消', 'AbortError')
    }
    setBusy(true)
    timeout.current = window.setTimeout(() => {
      if (active.current !== controller) return
      abort(); clearSecrets(); setBusy(false)
      setError('请求超时，尚未确认密码是否更新。请检查连接；如新密码无法登录，请联系管理员。')
    }, 15_000)
    try {
      const response = await apiFetch(`/api/v1/auth/${mode === 'change' ? 'change' : 'reset'}-password`, {
        method: 'POST', signal: controller.signal,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(mode === 'change'
          ? { current_password: credential, new_password: password }
          : { recovery_code: credential.trim(), new_password: password }),
      })
      check()
      if (response.status !== 204) {
        const message = await passwordError(response)
        check(); clearSecrets(); setError(message)
        return
      }
      clearSecrets()
      onSuccess()
    } catch (cause) {
      if (active.current === controller && !controller.signal.aborted && !(cause instanceof DOMException && cause.name === 'AbortError')) {
        clearSecrets(); setError('密码更新失败，请检查连接后重试。')
      }
    } finally {
      if (active.current === controller) {
        window.clearTimeout(timeout.current); active.current = null; setBusy(false)
      }
    }
  }

  return <section className="login-panel">
    <h2>{mode === 'change' ? t("修改密码") : t("恢复密码")}</h2>
    {mode === 'reset' && <p>{t("请联系管理员线下核验身份，获取15分钟有效、仅可使用一次的恢复码，再在此设置新密码。")}</p>}
    <p>{t(passwordRule)}{t("更新成功后全部旧会话失效，请重新登录。")}</p>
    <form onSubmit={event => void submit(event)} aria-busy={busy}>
      <label>{mode === 'change' ? t("当前密码") : t("恢复码")}
        <input ref={credentialInput} type="password" autoComplete={mode === 'change' ? 'current-password' : 'off'} required
          value={credential} disabled={busy} onChange={event => setCredential(event.target.value)} />
      </label>
      <label>{t("新密码")}<input type="password" autoComplete="new-password" required value={password} disabled={busy}
          onChange={event => setPassword(event.target.value)} />
      </label>
      <label>{t("确认新密码")}<input type="password" autoComplete="new-password" required value={confirmation} disabled={busy}
          onChange={event => setConfirmation(event.target.value)} />
      </label>
      <div className="password-actions">
        <button className="button-primary" type="submit" disabled={busy}>{busy ? t("正在更新密码……") : mode === 'change' ? t("确认修改密码") : t("重置密码")}</button>
        <button className="button-quiet" type="button" onClick={() => { abort(); clearSecrets(); onCancel() }}>{mode === 'change' ? t("取消") : t("返回登录")}</button>
      </div>
      {error && <p role="alert">{t(error)}</p>}
    </form>
  </section>
}
