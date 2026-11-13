import { useEffect, useRef, useState } from 'react'
import { safeError, useI18n } from '../../shared/i18n'
import useDraftLeaveGuard, { type RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { DateValue, Filters, Pagination, ReadState, Table } from './OperationsCommon'
import {
  accountReviewNames, accountRoleName, accountRoles, OperationsError, operationsRequest, queryUrl, useOperationsRead,
  type Account, type AccountReviewStatus, type Page, type RegistrationSummary,
} from './operationsApi'

const reviewStatuses = ['all', 'pending', 'approved', 'rejected'] as const
const headers = ['称呼', '邮箱', '单位或团队', '申请时间', '角色', '操作']
const defaultReviewRole = 'customer'
type ReviewRole = NonNullable<Account['role']>

export default function RegistrationQueuePanel({ active, onForbidden, registerLeaveGuard }: {
  active: boolean
  onForbidden: () => void
  registerLeaveGuard: RegisterLeaveGuard
}) {
  const { t } = useI18n()
  const [status, setStatus] = useState<AccountReviewStatus | 'all'>('all')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [page, setPage] = useState(1)
  const [roles, setRoles] = useState<Partial<Record<string, ReviewRole>>>({})
  const [saving, setSaving] = useState<string | null>(null)
  const [error, setError] = useState('')
  const request = useRef<AbortController | null>(null)
  const url = queryUrl('/api/v1/admin/registrations', filters, page, { review_status: status })
  const read = useOperationsRead<Page<RegistrationSummary>>(url, onForbidden, active)
  useDraftLeaveGuard(registerLeaveGuard, Object.keys(roles).length > 0, saving !== null)
  useEffect(() => () => request.current?.abort(), [])

  function selectRole(userId: string, role: ReviewRole) {
    setRoles(previous => {
      const next = { ...previous }
      if (role === defaultReviewRole) delete next[userId]
      else next[userId] = role
      return next
    })
  }

  async function approve(item: RegistrationSummary) {
    if (request.current) return
    const role = roles[item.user_id] ?? defaultReviewRole
    const controller = new AbortController()
    request.current = controller
    setSaving(item.user_id)
    setError('')
    try {
      const saved = await operationsRequest<Account>(
        `/api/v1/admin/users/${encodeURIComponent(item.user_id)}/registration/review`, controller.signal,
        { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ decision: 'approve', expected_revision: item.admin_revision, role }) },
      )
      if (controller.signal.aborted) return
      if (saved.review_status !== 'approved') throw new Error('invalid_review_response')
      selectRole(item.user_id, defaultReviewRole)
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
      setError(safeError(cause, '审核提交失败，请刷新申请后重试。'))
      if (cause instanceof OperationsError && (cause.status === 404 || cause.status === 409)) read.reload()
    } finally {
      if (request.current === controller) request.current = null
      if (!controller.signal.aborted) setSaving(null)
    }
  }

  return <section className="admin-account-panel" aria-label={t('审核管理')}>
    <div className="admin-account-toolbar">
      <div className="review-status-filters" role="group" aria-label={t('账号审核')}>
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
        return <tr key={item.user_id}>
          <td>{item.display_name}</td>
          <td>{item.email}</td>
          <td>{item.organization || t('未填写')}</td>
          <td><DateValue value={item.submitted_at} /></td>
          <td>{pending ? <select aria-label={t('为 {email} 分配角色', { email: item.email })}
            value={role} disabled={saving !== null} onChange={event => selectRole(item.user_id, event.target.value as ReviewRole)}>
            {accountRoles.map(option => <option key={option.value} value={option.value}>{t(option.label)}</option>)}
          </select> : t(item.role ? accountRoleName(item.role) : '未分配')}</td>
          <td>{pending ? <button type="button" className="registration-review-action button-destructive"
            disabled={saving !== null} title={t('通过并分配角色')} onClick={() => void approve(item)}>
            {t(saving === item.user_id ? '正在审核……' : '未审核')}
          </button> : <span className="status-badge registration-status" data-status={item.review_status}>{t(accountReviewNames[item.review_status])}</span>}</td>
        </tr>
      })}
      {!read.data?.items.length && <tr><td colSpan={headers.length}>
        <ReadState {...read} empty={read.data?.items.length === 0} />
      </td></tr>}
    </Table>
    <div className="admin-account-pager">
      {read.data && <Pagination page={page} total={read.data.total} size={read.data.page_size} disabled={saving !== null} onChange={setPage} />}
    </div>
  </section>
}
