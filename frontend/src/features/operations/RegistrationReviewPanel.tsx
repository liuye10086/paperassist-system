import { useEffect, useRef, useState, type FormEvent } from 'react'
import useDraftLeaveGuard, { type RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { safeError, useI18n } from '../../shared/i18n'
import { DateValue, ReadState } from './OperationsCommon'
import { accountReviewNames, accountRoleName, accountRoles, operationsRequest, OperationsError, useOperationsRead, type Account, type AccountRegistration } from './operationsApi'

export default function RegistrationReviewPanel({ accountId, active, onBack, onChanged, onForbidden, registerLeaveGuard }: {
  accountId: string
  active: boolean
  onBack: () => void
  onChanged: () => void
  onForbidden: () => void
  registerLeaveGuard?: RegisterLeaveGuard
}) {
  const { t } = useI18n()
  const url = `/api/v1/admin/users/${encodeURIComponent(accountId)}/registration`
  const read = useOperationsRead<AccountRegistration>(url, onForbidden, active)
  const [decision, setDecision] = useState<'approve' | 'reject'>('approve')
  const [role, setRole] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const request = useRef<AbortController | null>(null)
  const application = read.data
  const pending = application?.review_status === 'pending'
  const dirty = pending && (decision === 'reject' || Boolean(role || reason))
  useDraftLeaveGuard(registerLeaveGuard, dirty, busy)
  useEffect(() => () => request.current?.abort(), [])

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!application || !pending || request.current) return
    const trimmed = reason.trim()
    const characters = Array.from(trimmed)
    if (decision === 'approve' && !role) {
      setError('请选择要分配的角色。')
      return
    }
    if ((decision === 'reject' || trimmed) && (characters.length < 5 || characters.length > 500
      || characters.some(character => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127))) {
      setError('请填写 5 至 500 字的审核理由。')
      return
    }
    const controller = new AbortController()
    request.current = controller
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const saved = await operationsRequest<Account>(`${url}/review`, controller.signal, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          decision, expected_revision: application.admin_revision,
          ...(decision === 'approve' && { role }), ...(trimmed && { reason: trimmed }),
        }),
      })
      if (controller.signal.aborted) return
      if (saved.review_status !== 'approved' && saved.review_status !== 'rejected') throw new Error('invalid_review_response')
      setNotice(saved.review_status === 'approved' ? '申请已通过，账号已启用。' : '申请已驳回。')
      read.reload()
      onChanged()
    } catch (cause) {
      if (controller.signal.aborted) return
      if (cause instanceof OperationsError && cause.status === 403) {
        onForbidden()
        return
      }
      setError(safeError(cause, '审核提交失败，请刷新申请后重试。'))
      read.reload()
      onChanged()
    } finally {
      if (request.current === controller) request.current = null
      if (!controller.signal.aborted) setBusy(false)
    }
  }

  return <section aria-label={t('注册申请')} className="operations-detail">
    <button disabled={busy} onClick={() => {
      if (!dirty || window.confirm(t('放弃未保存的审核决定？'))) onBack()
    }}>{t('返回审核列表')}</button>
    <h2>{t('注册申请')}</h2>
    <ReadState {...read} />
    {notice && <p role="status">{t(notice)}</p>}
    {error && <p role="alert">{t(error)}</p>}
    {application && <>
      <dl className="operations-facts">
        <div><dt>{t('邮箱')}</dt><dd>{application.email}</dd></div>
        <div><dt>{t('称呼')}</dt><dd>{application.display_name}</dd></div>
        <div><dt>{t('单位或团队')}</dt><dd>{application.organization || t('未填写')}</dd></div>
        <div><dt>{t('申请时间')}</dt><dd><DateValue value={application.submitted_at}/></dd></div>
        <div><dt>{t('账号审核')}</dt><dd>{t(accountReviewNames[application.review_status])}</dd></div>
      </dl>
      <p className="operations-review-note"><strong>{t('申请说明')}</strong><br />{application.note || t('未填写')}</p>
      {application.decision && <dl className="operations-facts">
        <div><dt>{t('审核人')}</dt><dd>{application.decision.reviewer_email}</dd></div>
        <div><dt>{t('审核时间')}</dt><dd><DateValue value={application.decision.reviewed_at}/></dd></div>
        {application.decision.role && <div><dt>{t('分配角色')}</dt><dd>{t(accountRoleName(application.decision.role))}</dd></div>}
        <div><dt>{t(application.decision.status === 'approved' ? '审核意见' : '驳回原因')}</dt><dd>{t(application.decision.reason)}</dd></div>
      </dl>}
      {pending && <form className="operations-editor" onSubmit={event => void save(event)} aria-busy={busy}>
        <p className="muted">{t('邮箱由申请人填写。请核实申请人身份后分配角色。')}</p>
        <label>{t('审核决定')}<select disabled={busy} value={decision} onChange={event => setDecision(event.target.value === 'reject' ? 'reject' : 'approve')}>
          <option value="approve">{t('通过')}</option>
          <option value="reject">{t('驳回')}</option>
        </select></label>
        {decision === 'approve' && <label>{t('分配角色')}<select value={role} disabled={busy} required onChange={event => setRole(event.target.value)}>
          <option value="">{t('请选择角色')}</option>
          {accountRoles.map(option => <option key={option.value} value={option.value}>{t(option.label)}</option>)}
        </select></label>}
        <label>{t(decision === 'reject' ? '驳回原因' : '审核意见（选填）')}
          <input value={reason} onChange={event => setReason(event.target.value)} required={decision === 'reject'} minLength={5} maxLength={1000} disabled={busy}/>
        </label>
        <button type="submit" disabled={busy}>{t(decision === 'approve' ? '通过并分配角色' : '驳回申请')}</button>
      </form>}
    </>}
  </section>
}
