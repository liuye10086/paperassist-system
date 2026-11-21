import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { clearApiSession, setApiSession } from '../../shared/api/client'
import { setLocale } from '../../shared/i18n'
import RegistrationQueuePanel from './RegistrationQueuePanel'

const review = '/api/v1/admin/users/pending/registration/review'
const pending = { user_id: 'pending', email: 'pending@example.test', display_name: '待审申请人',
  organization: '示例单位', submitted_at: 1792700000, review_status: 'pending', role: null, admin_revision: 3 }
const approved = { ...pending, user_id: 'done', email: 'done@example.test', review_status: 'approved', role: 'analyst', admin_revision: 5 }
let state: 'pending' | 'rejected' = 'pending'
let reviewResponse: () => Response
let fetchMock: ReturnType<typeof vi.fn>
const dialogMethods = ['showModal', 'close'] as const
const originalDialogMethods = dialogMethods.map(name => Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, name))

beforeEach(() => {
  Object.defineProperties(HTMLDialogElement.prototype, {
    showModal: { configurable: true, value(this: HTMLDialogElement) { this.open = true } },
    close: { configurable: true, value(this: HTMLDialogElement) { this.open = false } },
  })
  state = 'pending'
  reviewResponse = () => { state = 'rejected'; return Response.json({ id: 'pending', email: pending.email, role: null, review_status: 'rejected', active: false, admin_revision: 4, updated_at: 1792700001, allowed_actions: [] }) }
  setApiSession('csrf', 'admin')
  fetchMock = vi.fn(async (url: string) => {
    if (url === review) return reviewResponse()
    if (url.startsWith('/api/v1/admin/registrations?')) {
      const items = state === 'pending' ? [pending, approved] : [{ ...pending, review_status: 'rejected', admin_revision: 4 }, approved]
      return Response.json({ items, total: items.length, page: 1, page_size: 10 })
    }
    return Response.json({ detail: { code: 'invalid_request' } }, { status: 422 })
  })
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => {
  cleanup()
  dialogMethods.forEach((name, index) => {
    const original = originalDialogMethods[index]
    if (original) Object.defineProperty(HTMLDialogElement.prototype, name, original)
    else Reflect.deleteProperty(HTMLDialogElement.prototype, name)
  })
  vi.unstubAllGlobals()
  clearApiSession()
  setLocale('zh-CN')
})

function mount() {
  render(<RegistrationQueuePanel active onForbidden={vi.fn()} registerLeaveGuard={() => () => {}} />)
}
async function row(email = pending.email) { return within((await screen.findByText(email)).closest('tr')!) }
const reviewCalls = () => fetchMock.mock.calls.filter(([url]) => url === review)

it('defaults to pending applications and labels the approve action with the applicant email', async () => {
  mount()
  const item = await row()
  expect(fetchMock.mock.calls[0][0]).toContain('review_status=pending')
  expect(screen.getByRole('button', { name: '待审核' }).getAttribute('aria-pressed')).toBe('true')
  expect(screen.getByRole('columnheader', { name: '审核状态' })).toBeTruthy()
  expect(screen.getByRole('columnheader', { name: '操作' })).toBeTruthy()
  const approve = item.getByRole('button', { name: '通过并分配角色' })
  expect(approve.className).not.toContain('button-destructive')
  const described = document.getElementById(approve.getAttribute('aria-describedby') ?? '')
  expect(described?.textContent).toBe(pending.email)
  expect(item.getByText('待审核')).toBeTruthy()
  const done = await row(approved.email)
  expect(done.getByText('审核通过')).toBeTruthy()
  expect(done.queryByRole('button')).toBeNull()
})

it('returns keyboard focus to the review filters when the approved row disappears', async () => {
  let completed = false
  fetchMock.mockImplementation(async (url: string) => {
    if (url === review) {
      completed = true
      return Response.json({ ...approved, id: pending.user_id })
    }
    const items = completed ? [] : [pending]
    return Response.json({ items, total: items.length, page: 1, page_size: 10 })
  })
  mount()
  const approve = (await row()).getByRole('button', { name: '通过并分配角色' })
  approve.focus()
  fireEvent.click(approve)
  await waitFor(() => expect(screen.queryByText(pending.email)).toBeNull())
  expect(document.activeElement).toBe(screen.getByRole('group', { name: '账号审核' }))
})

it('rejects only after a valid reason and an explicit irreversible confirmation', async () => {
  mount()
  fireEvent.click((await row()).getByRole('button', { name: '驳回' }))
  const dialog = within(await screen.findByRole('dialog'))
  expect(dialog.getByText('驳回后账号会被停用，且无法撤回。')).toBeTruthy()
  expect(dialog.getByText(pending.email)).toBeTruthy()
  const confirm = dialog.getByRole('button', { name: '确认驳回' })
  const reason = dialog.getByLabelText('驳回原因')
  expect(confirm).toHaveProperty('disabled', true)
  fireEvent.change(reason, { target: { value: '  资料 ' } })
  expect(confirm).toHaveProperty('disabled', true)
  fireEvent.change(reason, { target: { value: 'x'.repeat(501) } })
  expect(confirm).toHaveProperty('disabled', true)
  fireEvent.change(reason, { target: { value: '单位信息无法核实' } })
  expect(confirm).toHaveProperty('disabled', false)
  fireEvent.click(confirm)
  fireEvent.click(confirm)
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(reviewCalls()).toHaveLength(1)
  const body = JSON.parse(String(reviewCalls()[0][1].body))
  expect(body).toEqual({ decision: 'reject', expected_revision: 3, reason: '单位信息无法核实' })
  expect('role' in body).toBe(false)
  expect(await (await row()).findByText('审核驳回')).toBeTruthy()
})

it('cancelling the rejection sends nothing and keeps the application pending', async () => {
  mount()
  fireEvent.click((await row()).getByRole('button', { name: '驳回' }))
  const dialog = within(await screen.findByRole('dialog'))
  fireEvent.change(dialog.getByLabelText('驳回原因'), { target: { value: '单位信息无法核实' } })
  fireEvent.click(dialog.getByRole('button', { name: '取消' }))
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(reviewCalls()).toHaveLength(0)
  expect((await row()).getByText('待审核')).toBeTruthy()
})

it('does not trust a rejection response that is not rejected and refreshes on conflict', async () => {
  reviewResponse = () => Response.json({ id: 'pending', review_status: 'pending', role: null, active: true, admin_revision: 4 })
  mount()
  fireEvent.click((await row()).getByRole('button', { name: '驳回' }))
  let dialog = within(await screen.findByRole('dialog'))
  fireEvent.change(dialog.getByLabelText('驳回原因'), { target: { value: '单位信息无法核实' } })
  fireEvent.click(dialog.getByRole('button', { name: '确认驳回' }))
  expect(await dialog.findByRole('alert')).toBeTruthy()
  expect(screen.getByRole('dialog')).toBeTruthy()
  reviewResponse = () => Response.json({ detail: { code: 'admin_revision_conflict', message: 'SECRET' } }, { status: 409 })
  const reads = fetchMock.mock.calls.filter(([url]) => url.startsWith('/api/v1/admin/registrations?')).length
  dialog = within(screen.getByRole('dialog'))
  fireEvent.click(dialog.getByRole('button', { name: '确认驳回' }))
  await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => url.startsWith('/api/v1/admin/registrations?')).length).toBeGreaterThan(reads))
  expect(document.body.textContent).not.toContain('SECRET')
})

it('translates the review actions and rejection confirmation in English', async () => {
  setLocale('en')
  mount()
  const item = await row()
  expect(item.getByRole('button', { name: 'Approve and assign role' })).toBeTruthy()
  fireEvent.click(item.getByRole('button', { name: 'Reject' }))
  const dialog = within(await screen.findByRole('dialog'))
  expect(dialog.getByText('Rejecting disables this account and cannot be undone.')).toBeTruthy()
  expect(dialog.getByLabelText('Reason for rejection')).toBeTruthy()
  expect(dialog.getByRole('button', { name: 'Confirm rejection' })).toBeTruthy()
  expect(screen.getByRole('columnheader', { name: 'Review status' })).toBeTruthy()
})
