import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { apiFetch } from '../../shared/api/client'
import { STANDARD_REQUEST_TIMEOUT_MS } from '../../shared/api/requestTimeouts'
import { apiError, useI18n } from '../../shared/i18n'

type Submission = { controller: AbortController; timeout: number }

export default function RegistrationForm({ initialEmail, onCancel, onSubmitted }: {
  initialEmail: string
  onCancel: () => void
  onSubmitted: (email: string) => void
}) {
  const { t } = useI18n()
  const passwordHint = useId()
  const nameInput = useRef<HTMLInputElement>(null)
  const current = useRef<Submission | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    nameInput.current?.focus()
    return () => {
      if (!current.current) return
      window.clearTimeout(current.current.timeout)
      current.current.controller.abort()
      current.current = null
    }
  }, [])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (current.current) return
    const fields = new FormData(event.currentTarget)
    const password = String(fields.get('password') ?? '')
    const passwordLength = Array.from(password).length
    if (passwordLength < 12 || passwordLength > 128) {
      setError('密码须为 12–128 个字符。')
      return
    }
    if (password !== fields.get('confirmation')) {
      setError('两次输入的密码不一致。')
      return
    }
    const email = String(fields.get('email') ?? '').trim()
    const body = {
      display_name: String(fields.get('display_name') ?? ''), email, password,
      organization: String(fields.get('organization') ?? ''), note: '',
    }
    const controller = new AbortController()
    const submission = { controller, timeout: window.setTimeout(() => {
      if (current.current?.controller !== controller) return
      current.current = null
      controller.abort()
      setBusy(false)
      setError('尚未确认申请是否提交成功，可以重试。')
    }, STANDARD_REQUEST_TIMEOUT_MS) }
    current.current = submission
    setBusy(true)
    setError('')
    try {
      const response = await apiFetch('/api/v1/auth/register', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body), signal: controller.signal,
      })
      if (response.status === 202) {
        if (current.current === submission) onSubmitted(email)
      } else {
        const message = apiError(await response.json().catch(() => null), '注册申请提交失败，请重试。')
        if (current.current === submission) setError(message)
      }
    } catch {
      if (current.current === submission) setError('注册申请提交失败，请重试。')
    } finally {
      if (current.current === submission) {
        current.current = null
        window.clearTimeout(submission.timeout)
        setBusy(false)
      }
    }
  }

  return <section className="login-panel auth-register-panel">
    <h2>{t('注册账号')}</h2>
    <p className="muted">{t('提交申请后由管理员审核。审核通过后即可登录。')}</p>
    <form onSubmit={event => void submit(event)} aria-busy={busy}>
      <div className="auth-register-identity">
        <label>{t('称呼')}<input ref={nameInput} name="display_name" autoComplete="name" required maxLength={80} disabled={busy}/></label>
        <label>{t('单位或团队（选填）')}<input name="organization" autoComplete="organization" maxLength={160} disabled={busy}/></label>
      </div>
      <label>{t('邮箱')}<input name="email" type="email" autoComplete="username" defaultValue={initialEmail} required maxLength={254} disabled={busy}/></label>
      <label>{t('密码')}<input name="password" type="password" autoComplete="new-password" required minLength={12} maxLength={256} aria-describedby={passwordHint} disabled={busy}/></label>
      <label>{t('确认密码')}<input name="confirmation" type="password" autoComplete="new-password" required minLength={12} maxLength={256} disabled={busy}/></label>
      <p className="muted auth-form-hint" id={passwordHint}>{t('密码须为 12–128 个字符。')}</p>
      {error && <p role="alert">{t(error)}</p>}
      <div className="auth-register-actions">
        <button className="button-quiet" type="button" disabled={busy} onClick={onCancel}>{t('返回登录')}</button>
        <button className="button-primary" disabled={busy} type="submit">
          {t(busy ? '正在提交申请……' : '提交注册申请')}
        </button>
      </div>
    </form>
  </section>
}
