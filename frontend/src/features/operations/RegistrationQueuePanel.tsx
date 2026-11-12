import { useState } from 'react'
import { useI18n } from '../../shared/i18n'
import type { RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { DateValue, Filters, Pagination, ReadState, Table } from './OperationsCommon'
import RegistrationReviewPanel from './RegistrationReviewPanel'
import { accountReviewNames, queryUrl, useOperationsRead, type AccountReviewStatus, type Page, type RegistrationSummary } from './operationsApi'

const reviewStatuses: AccountReviewStatus[] = ['pending', 'approved', 'rejected']

export default function RegistrationQueuePanel({ active, onForbidden, registerLeaveGuard }: {
  active: boolean
  onForbidden: () => void
  registerLeaveGuard: RegisterLeaveGuard
}) {
  const { t } = useI18n()
  const [status, setStatus] = useState<AccountReviewStatus>('pending')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [page, setPage] = useState(1)
  const [accountId, setAccountId] = useState<string | null>(null)
  const url = queryUrl('/api/v1/admin/registrations', filters, page, { review_status: status })
  const read = useOperationsRead<Page<RegistrationSummary>>(url, onForbidden, active && accountId === null)

  return <section aria-label={t('审核管理')}>
    <div hidden={accountId !== null}>
      <div className="review-status-filters" role="group" aria-label={t('账号审核')}>
        {reviewStatuses.map(value => <button key={value} type="button" aria-pressed={status === value}
          onClick={() => { setStatus(value); setPage(1) }}>{t(accountReviewNames[value])}</button>)}
      </div>
      <div className="review-list-toolbar">
        <Filters fields={[{ key: 'q', label: '申请邮箱', maxLength: 254 }]} onApply={value => { setFilters(value); setPage(1) }} applyLabel="搜索" />
        <button type="button" onClick={read.reload} disabled={read.loading}>{t('刷新')}</button>
      </div>
      <ReadState {...read} empty={read.data?.items.length === 0} />
      {read.data && <>
        {read.data.items.length > 0 && <Table headers={['称呼', '邮箱', '单位或团队', '申请时间', '账号审核', '操作']}>
          {read.data.items.map(item => <tr key={item.user_id}>
            <td>{item.display_name}</td>
            <td>{item.email}</td>
            <td>{item.organization || t('未填写')}</td>
            <td><DateValue value={item.submitted_at} /></td>
            <td><span className="registration-status" data-status={item.review_status}>{t(accountReviewNames[item.review_status])}</span></td>
            <td><button type="button" onClick={() => setAccountId(item.user_id)}>{t(item.review_status === 'pending' ? '审核申请' : '查看申请')}</button></td>
          </tr>)}
        </Table>}
        <Pagination page={page} total={read.data.total} size={read.data.page_size} onChange={setPage} />
      </>}
    </div>
    {accountId && <RegistrationReviewPanel key={accountId} accountId={accountId} active={active}
      onBack={() => setAccountId(null)} onChanged={() => { setPage(1); read.reload() }}
      onForbidden={onForbidden} registerLeaveGuard={registerLeaveGuard} />}
  </section>
}
