import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { safeError, useI18n } from '../../shared/i18n'
import useDraftLeaveGuard, { type RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { DateValue, Filters, Pagination, ReadState, Table } from './OperationsCommon'
import {
  accountReviewNames, accountRoleName, accountRoles, OperationsError, operationsRequest, queryUrl, useOperationsRead,
  type Account, type AccountReviewStatus, type Page, type RegistrationSummary,
} from './operationsApi'

const reviewStatuses = ['all', 'pending', 'approved', 'rejected'] as const
const headers = ['称呼', '邮箱', '单位或团队', '申请时间', '角色', '审核状态', '操作']
const defaultReviewRole = 'customer'
type ReviewRole = NonNullable<Account['role']>
type Decision = { decision: 'approve'; role: ReviewRole } | { decision: 'reject'; reason: string }

// Mirrors the backend AccountReason: 5–500 characters after trimming, no control characters.
function validReason(value: string) {
  const reason = value.trim()
  return reason.length >= 5 && reason.length <= 500 && ![...reason].some(char => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127)
}

export default function RegistrationQueuePanel({ active, onForbidden, registerLeaveGuard }: {
  active: boolean
  onForbidden: () => void
  registerLeaveGuard: RegisterLeaveGuard
}) {
  const { t } = useI18n()
  const id = useId()
  // Same default as GET /admin/registrations: the queue opens on applications still waiting for review.
  const [status, setStatus] = useState<AccountReviewStatus | 'all'>('pending')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [page, setPage] = useState(1)
  const [roles, setRoles] = useState<Partial<Record<string, ReviewRole>>>({})
  const [saving, setSaving] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [rejectTarget, setRejectTarget] = useState<RegistrationSummary | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [rejectError, setRejectError] = useState('')
  const request = useRef<AbortController | null>(null)
  const reviewFilters = useRef<HTMLDivElement>(null)
  const rejectDialog = useRef<HTMLDialogElement>(null)
  const rejectTrigger = useRef<HTMLButtonElement | null>(null)
  const reasonField = useRef<HTMLTextAreaElement>(null)
  const url = queryUrl('/api/v1/admin/registrations', filters, page, { review_status: status })
  const read = useOperationsRead<Page<RegistrationSummary>>(url, onForbidden, active)
  useDraftLeaveGuard(registerLeaveGuard, Object.keys(roles).length > 0 || rejectReason.trim() !== '', saving !== null)
  useEffect(() => () => request.current?.abort(), [])
  useLayoutEffect(() => {
    const dialog = rejectDialog.current
    if (!active || !rejectTarget || !dialog) return
    dialog.showModal()
    reasonField.current?.focus({ preventScroll: true })
    return () => { if (dialog.open) dialog.close() }
  }, [active, rejectTarget])

  function selectRole(userId: string, role: ReviewRole) {
    setRoles(previous => {
      const next = { ...previous }
      if (role === defaultReviewRole) delete next[userId]
      else next[userId] = role
      return next
    })
  }

  function openReject(item: RegistrationSummary, trigger: HTMLButtonElement) {
    if (request.current) return
    rejectTrigger.current = trigger
    setRejectReason('')
    setRejectError('')
    setRejectTarget(item)
  }

  function closeReject() {
    rejectDialog.current?.close()
    setRejectTarget(null)
    setRejectReason('')
    setRejectError('')
    const trigger = rejectTrigger.current
    if (trigger?.isConnected) trigger.focus({ preventScroll: true })
    rejectTrigger.current = null
  }

  async function review(item: RegistrationSummary, decision: Decision) {
    if (request.current) return
    const rejecting = decision.decision === 'reject'
    const trigger = rejecting ? rejectTrigger.current : document.activeElement
    const controller = new AbortController()
    request.current = controller
    setSaving(item.user_id)
    setError('')
    setRejectError('')
    const body = decision.decision === 'approve'
      ? { decision: 'approve', expected_revision: item.admin_revision, role: decision.role }
      : { decision: 'reject', expected_revision: item.admin_revision, reason: decision.reason }
    try {
      const saved = await operationsRequest<Account>(
        `/api/v1/admin/users/${encodeURIComponent(item.user_id)}/registration/review`, controller.signal,
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
      )
      if (controller.signal.aborted) return
      if (saved.review_status !== (rejecting ? 'rejected' : 'approved')) throw new Error('invalid_review_response')
      if (rejecting) closeReject()
      else selectRole(item.user_id, defaultReviewRole)
      if (document.activeElement === document.body || document.activeElement === trigger) {
        reviewFilters.current?.focus({ preventScroll: true })
      }
      if (status === 'pending' && read.data) {
        setPage(Math.min(page, Math.max(1, Math.ceil((read.data.total - 1) / read.data.page_size))))
      }
      read.reload()
    } catch (cause) {
      if (controller.signal.aborted) return
      if (cause instanceof OperationsError && cause.status === 403) {
        onForbidden()
        return
      }
      const message = safeError(cause, '审核提交失败，请刷新申请后重试。')
      if (rejecting) setRejectError(message)
      else setError(message)
      if (cause instanceof OperationsError && (cause.status === 404 || cause.status === 409)) read.reload()
    } finally {
      if (request.current === controller) request.current = null
      if (!controller.signal.aborted) setSaving(null)
    }
  }

  const reasonValid = validReason(rejectReason)
  return <section className="admin-account-panel" aria-label={t('审核管理')}>
    <div className="admin-account-toolbar">
      <div className="review-status-filters" role="group" aria-label={t('账号审核')} tabIndex={-1} ref={reviewFilters}>
        {reviewStatuses.map(value => <button key={value} type="button" aria-pressed={status === value} disabled={saving !== null}
          onClick={() => { setStatus(value); setPage(1); setError('') }}>
          {t(value === 'all' ? '全部' : accountReviewNames[value])}
        </button>)}
      </div>
      <div className="admin-account-filters">
        <Filters fields={[{ key: 'q', label: '申请邮箱', maxLength: 254 }]} disabled={saving !== null}
          onApply={value => { setFilters(value); setPage(1); setError('') }} applyLabel="搜索" />
        <button type="button" onClick={read.reload} disabled={read.loading || saving !== null}>{t('刷新')}</button>
      </div>
    </div>
    {error && <p className="error-panel" role="alert">{t(error)}</p>}
    <Table headers={headers}>
      {read.data?.items.map(item => {
        const pending = item.review_status === 'pending'
        const role = roles[item.user_id] ?? defaultReviewRole
        const emailId = `${id}-email-${item.user_id}`
        return <tr key={item.user_id}>
          <td>{item.display_name}</td>
          <td id={emailId}>{item.email}</td>
          <td>{item.organization || t('未填写')}</td>
          <td><DateValue value={item.submitted_at} /></td>
          <td>{pending ? <select aria-label={t('为 {email} 分配角色', { email: item.email })}
            value={role} disabled={saving !== null} onChange={event => selectRole(item.user_id, event.target.value as ReviewRole)}>
            {accountRoles.map(option => <option key={option.value} value={option.value}>{t(option.label)}</option>)}
          </select> : t(item.role ? accountRoleName(item.role) : '未分配')}</td>
          <td><span className="status-badge registration-status" data-status={item.review_status}>{t(accountReviewNames[item.review_status])}</span></td>
          <td>{pending ? <div className="admin-account-actions">
            <button type="button" className="button-primary registration-review-action" aria-describedby={emailId}
              aria-busy={saving === item.user_id && !rejectTarget} disabled={saving !== null} onClick={() => void review(item, { decision: 'approve', role })}>
              {t(saving === item.user_id && !rejectTarget ? '正在审核……' : '通过并分配角色')}
            </button>
            <button type="button" className="registration-reject-action" aria-haspopup="dialog" aria-describedby={emailId}
              disabled={saving !== null} onClick={event => openReject(item, event.currentTarget)}>{t('驳回')}</button>
          </div> : <span className="muted">—</span>}</td>
        </tr>
      })}
      {!read.data?.items.length && <tr><td colSpan={headers.length}>
        <ReadState {...read} empty={read.data?.items.length === 0} />
      </td></tr>}
    </Table>
    <div className="admin-account-pager">
      {read.data && <Pagination page={page} total={read.data.total} size={read.data.page_size} disabled={saving !== null} onChange={setPage} />}
    </div>
    {rejectTarget && <dialog ref={rejectDialog} className="admin-account-delete-dialog"
      aria-labelledby={`${id}-reject-title`} aria-describedby={`${id}-reject-scope`} aria-busy={saving !== null}
      onCancel={event => { event.preventDefault(); if (!request.current) closeReject() }}>
      <h2 id={`${id}-reject-title`}>{t('驳回申请')}</h2>
      <div id={`${id}-reject-scope`}>
        <p><strong>{rejectTarget.email}</strong></p>
        <p>{t('驳回后账号会被停用，且无法撤回。')}</p>
      </div>
      <label className="registration-reject-reason">{t('驳回原因')}
        <textarea ref={reasonField} value={rejectReason} maxLength={500} rows={3} disabled={saving !== null}
          aria-describedby={`${id}-reject-hint`} onChange={event => { setRejectReason(event.target.value); setRejectError('') }} />
      </label>
      <p id={`${id}-reject-hint`} className="muted">{t('请填写 5 至 500 字的审核理由。')}</p>
      {rejectError && <p className="error-panel" role="alert">{t(rejectError)}</p>}
      <div className="admin-account-delete-actions">
        <button type="button" disabled={saving !== null} onClick={closeReject}>{t('取消')}</button>
        <button type="button" className="button-destructive" disabled={saving !== null || !reasonValid}
          onClick={() => { if (reasonValid) void review(rejectTarget, { decision: 'reject', reason: rejectReason.trim() }) }}>
          {t(saving !== null ? '正在驳回……' : '确认驳回')}
        </button>
      </div>
    </dialog>}
  </section>
}
