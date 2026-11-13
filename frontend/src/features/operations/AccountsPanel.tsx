import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { safeError, useI18n } from '../../shared/i18n'
import useDraftLeaveGuard, { type RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { DateValue, Filters, Pagination, ReadState, Table } from './OperationsCommon'
import { accountRoleName, accountRoles, OperationsError, operationsRequest, queryUrl, useOperationsRead, type Account, type Page } from './operationsApi'

const headers = ['邮箱', '角色', '账号状态', '更新时间', '操作']

type EditDraft = { account: Account; role: string; enabled: boolean }
type AccountChange = { role: string; active: boolean; reason: string }

function hasChange(draft: EditDraft) {
  return draft.role !== draft.account.role || draft.enabled !== draft.account.active
}

export default function AccountsPanel({ userId, onForbidden, onAudit, active = true, registerLeaveGuard }: {
  active?: boolean
  registerLeaveGuard?: RegisterLeaveGuard
  userId: string
  onForbidden: () => void
  onAudit: (id: string) => void
}) {
  const { t } = useI18n()
  const id = useId()
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [page, setPage] = useState(1)
  const [drafts, setDrafts] = useState(() => new Map<string, EditDraft>())
  const [pendingId, setPendingId] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState<{ id: string; deleted: boolean } | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Account | null>(null)
  const [deleteError, setDeleteError] = useState('')
  const [cleanupPending, setCleanupPending] = useState(false)
  const request = useRef<AbortController | null>(null)
  const panel = useRef<HTMLElement>(null)
  const deleteTrigger = useRef<HTMLButtonElement | null>(null)
  const deleteDialog = useRef<HTMLDialogElement>(null)
  const deleteHeading = useRef<HTMLHeadingElement>(null)
  const cancelDelete = useRef<HTMLButtonElement>(null)
  const busy = pendingId !== null
  const read = useOperationsRead<Page<Account>>(queryUrl('/api/v1/admin/users', filters, page, { review_status: 'approved' }), onForbidden, active)
  const currentDeleteTarget = deleteTarget && read.data?.items.find(item => item.id === deleteTarget.id)
  // Cleanup can disable the account and move it out of the current filters.
  const canConfirmDelete = !read.loading && (currentDeleteTarget
    ? canDelete(currentDeleteTarget) && currentDeleteTarget.admin_revision === deleteTarget?.admin_revision
    : cleanupPending)

  useDraftLeaveGuard(registerLeaveGuard, drafts.size > 0, busy)
  useEffect(() => () => request.current?.abort(), [])
  useLayoutEffect(() => {
    const dialog = deleteDialog.current
    if (!active || !deleteTarget || !dialog) return
    dialog.showModal()
    return () => { if (dialog.open) dialog.close() }
  }, [active, deleteTarget])
  useLayoutEffect(() => {
    if (!active || !deleteTarget) return
    const target = busy ? deleteHeading.current : cancelDelete.current
    target?.focus({ preventScroll: true })
  }, [active, busy, deleteTarget])

  function canEdit(account: Account) {
    return account.role !== null && account.id !== userId && account.allowed_actions.includes('edit')
  }

  function canDelete(account: Account) {
    return account.id !== userId && account.role !== 'admin' && account.allowed_actions.includes('delete')
  }

  function updateDraft(account: Account, patch: Partial<Omit<EditDraft, 'account'>>) {
    if (request.current || account.role === null) return
    const role = account.role
    setDrafts(previous => {
      const next = new Map(previous)
      const original = previous.get(account.id) ?? { account, role, enabled: account.active }
      const draft = { ...original, ...patch }
      if (hasChange(draft)) next.set(account.id, draft)
      else next.delete(account.id)
      return next
    })
    setError('')
    setSuccess(null)
  }

  function clearDraft(accountId: string) {
    setDrafts(previous => {
      if (!previous.has(accountId)) return previous
      const next = new Map(previous)
      next.delete(accountId)
      return next
    })
  }

  function save(account: Account) {
    const draft = drafts.get(account.id)
    if (!draft || !canEdit(account) || request.current) return
    void submit(draft.account, { role: draft.role, active: draft.enabled, reason: '账号管理更新' })
  }

  function openDelete(account: Account, trigger: HTMLButtonElement) {
    if (!canDelete(account) || request.current) return
    deleteTrigger.current = trigger
    setDeleteError('')
    setCleanupPending(false)
    setDeleteTarget(account)
  }

  function closeDelete(restoreTrigger = true) {
    deleteDialog.current?.close()
    setDeleteTarget(null)
    const trigger = deleteTrigger.current
    if (restoreTrigger && trigger?.isConnected) trigger.focus({ preventScroll: true })
    else panel.current?.focus({ preventScroll: true })
    deleteTrigger.current = null
  }

  async function submit(account: Account, change: AccountChange | null) {
    if (request.current) return
    const deleting = change === null
    const controller = new AbortController()
    request.current = controller
    setPendingId(account.id)
    setError('')
    setDeleteError('')
    setSuccess(null)
    try {
      const result = await operationsRequest<{ id: string; deleted?: boolean }>(`/api/v1/admin/users/${encodeURIComponent(account.id)}`, controller.signal, {
        method: deleting ? 'DELETE' : 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...change, expected_revision: account.admin_revision }),
      })
      if (controller.signal.aborted) return
      if (deleting) {
        if (result.id !== account.id || result.deleted !== true) throw new Error('账号删除结果暂无法确认，请刷新后重试。')
        closeDelete(false)
        if (read.data) {
          const removed = read.data.items.some(item => item.id === account.id) ? 1 : 0
          const lastPage = Math.max(1, Math.ceil((read.data.total - removed) / read.data.page_size))
          setPage(Math.min(page, lastPage))
        }
      }
      clearDraft(account.id)
      setSuccess({ id: account.id, deleted: deleting })
      read.reload()
    } catch (cause) {
      if (controller.signal.aborted) return
      if (cause instanceof OperationsError && cause.status === 403) {
        onForbidden()
        return
      }
      const message = safeError(cause, '运营信息读取失败，请重试。')
      if (deleting) {
        setDeleteError(message === '运营信息读取失败，请重试。' ? '账号删除结果暂无法确认，请刷新后重试。' : message)
        const incomplete = cause instanceof OperationsError && cause.status === 503
        setCleanupPending(incomplete)
        if (incomplete) clearDraft(account.id)
        read.reload()
      } else {
        setError(message)
        if (cause instanceof OperationsError && cause.status === 409) {
          clearDraft(account.id)
          read.reload()
        }
      }
    } finally {
      if (request.current === controller) request.current = null
      if (!controller.signal.aborted) setPendingId(null)
    }
  }

  return <section className="admin-account-panel admin-account-list" aria-label={t('账号管理')} ref={panel} tabIndex={-1}>
    <div className="admin-account-toolbar">
      <div className="admin-account-filters">
        <Filters disabled={busy} fields={[
          { key: 'q', label: '账号搜索', maxLength: 254 },
          { key: 'role', label: '角色', options: [{ value: '', label: '全部' }, ...accountRoles] },
          { key: 'active', label: '账号状态', options: [{ value: '', label: '全部' }, { value: 'true', label: '启用' }, { value: 'false', label: '停用' }] },
        ]} onApply={value => { setFilters(value); setPage(1) }} />
        <button type="button" onClick={read.reload} disabled={read.loading || busy}>{t('刷新')}</button>
      </div>
      {success && !success.deleted && <button type="button" className="button-quiet" onClick={() => onAudit(success.id)}>{t('查看操作审计')}</button>}
    </div>
    {error && <p className="error-panel" role="alert">{t(error)}</p>}
    {success?.deleted && <div className="admin-account-notice" role="status"><p>{t('账号已永久删除。')}</p></div>}
    <Table headers={headers}>
      {read.data?.items.map(item => {
        const editable = canEdit(item)
        const deletable = canDelete(item)
        const draft = drafts.get(item.id)
        const role = draft?.role ?? item.role
        const enabled = draft?.enabled ?? item.active
        const emailId = `${id}-email-${item.id}`
        return <tr key={item.id} className={editable && draft ? 'admin-account-row-selected' : undefined}>
          <td id={emailId}>{item.email}</td>
          <td>{editable && role !== null
            ? <select aria-label={t('账号角色')} aria-describedby={emailId} value={role} disabled={busy}
              onChange={event => updateDraft(item, { role: event.target.value })}>
              {!accountRoles.some(option => option.value === role) && <option value={role}>{t(accountRoleName(role))}</option>}
              {accountRoles.map(option => <option key={option.value} value={option.value}>{t(option.label)}</option>)}
            </select>
            : t(item.role === null ? '未分配' : accountRoleName(item.role))}</td>
          <td>{editable
            ? <select aria-label={t('账号状态')} aria-describedby={emailId} value={String(enabled)} disabled={busy}
              onChange={event => updateDraft(item, { enabled: event.target.value === 'true' })}>
              <option value="true">{t('启用')}</option>
              <option value="false">{t('停用')}</option>
            </select>
            : <span className="status-badge account-activity" data-active={item.active}>{t(item.active ? '启用' : '停用')}</span>}</td>
          <td><DateValue value={item.updated_at} /></td>
          <td>{editable || deletable ? <div className="admin-account-actions">
            {editable && <button type="button" className="button-primary" aria-label={t('保存账号变更')}
              aria-describedby={emailId} aria-busy={pendingId === item.id && !deleteTarget} disabled={busy || !draft}
              title={t('保存将撤销该账号已有会话，并追加不可修改的操作审计。')} onClick={() => save(item)}>
              {t('保存')}
            </button>}
            {deletable && <button type="button" className="admin-account-delete-button" aria-haspopup="dialog" aria-describedby={emailId}
              disabled={busy} onClick={event => openDelete(item, event.currentTarget)}>{t('删除')}</button>}
          </div> : <span className="muted">{t('只读')}</span>}</td>
        </tr>
      })}
      {!read.data?.items.length && <tr><td colSpan={headers.length}>
        <ReadState {...read} empty={read.data?.items.length === 0} />
      </td></tr>}
    </Table>
    <div className="admin-account-pager">
      {read.data && <Pagination page={page} total={read.data.total} size={read.data.page_size} onChange={setPage} disabled={busy} />}
    </div>
    {deleteTarget && <dialog ref={deleteDialog} className="admin-account-delete-dialog"
      aria-labelledby={`${id}-delete-title`} aria-describedby={`${id}-delete-scope`} aria-busy={busy}
      onCancel={event => { event.preventDefault(); if (!request.current) closeDelete() }}>
      <h2 ref={deleteHeading} id={`${id}-delete-title`} tabIndex={-1}>{t('永久删除账号')}</h2>
      <div id={`${id}-delete-scope`}>
        <p><strong>{deleteTarget.email}</strong></p>
        <p>{t('此操作将永久删除该账号、其拥有的本机项目和文件，以及关联的本机记录。')}</p>
      </div>
      {deleteError && <p className="error-panel" role="alert">{t(deleteError)}</p>}
      <div className="admin-account-delete-actions">
        <button type="button" ref={cancelDelete} disabled={busy} onClick={() => closeDelete()}>{t('取消')}</button>
        <button type="button" className="button-destructive" disabled={busy || !canConfirmDelete}
          onClick={() => { if (canConfirmDelete) void submit(deleteTarget, null) }}>
          {t(busy ? '正在删除……' : '确认永久删除')}
        </button>
      </div>
    </dialog>}
  </section>
}
