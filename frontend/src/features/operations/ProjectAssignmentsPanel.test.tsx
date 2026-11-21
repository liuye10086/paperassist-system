import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { clearApiSession, setApiSession } from '../../shared/api/client'
import ProjectAssignmentsPanel from './ProjectAssignmentsPanel'

const base = '/api/v1/admin/project-assignments'
const row = (id: string, name: string, extra: Record<string, unknown> = {}) => ({
  id, name, research_topic: '比较两组', project_type: 'research', customer_email: id + '@example.test',
  analyst_id: null as string | null, analyst_email: null as string | null, revision: 0, submitted_version: 1,
  progress_status: 'pending_assignment', required_analyses: ['single_cell', 'bulk'], updated_at: '2026-11-19T00:00:00Z', ...extra,
})
const analyst = { id: 'analyst-a', email: 'analyst-a@example.test', role: 'analyst', active: true }
let rows: ReturnType<typeof row>[] = []
let fetchMock: ReturnType<typeof vi.fn>
const dialogMethods = ['showModal', 'close'] as const
const originalDialogMethods = dialogMethods.map(name => Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, name))

beforeEach(() => {
  Object.defineProperties(HTMLDialogElement.prototype, {
    showModal: { configurable: true, value(this: HTMLDialogElement) { this.open = true } },
    close: { configurable: true, value(this: HTMLDialogElement) { this.open = false } },
  })
  rows = [row('p1', '第一项目'), row('p2', '第二项目', { required_analyses: [] })]
  setApiSession('csrf', 'admin')
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.startsWith(base + '?')) return Response.json({ items: rows, total: rows.length, page: 1, page_size: 10 })
    if (url.startsWith('/api/v1/admin/users?')) return Response.json({ items: [analyst], total: 1, page: 1, page_size: 10 })
    const id = url.slice(base.length + 1)
    if (init?.method === 'PATCH') {
      const body = JSON.parse(String(init.body))
      const current = rows.find(item => item.id === id)!
      return Response.json({ ...current, analyst_id: body.analyst_id, analyst_email: body.analyst_id ? analyst.email : null,
        revision: current.revision + 1, progress_status: body.analyst_id ? 'assigned' : 'pending_assignment' })
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
})

function mount() {
  render(<ProjectAssignmentsPanel active onForbidden={() => undefined} registerLeaveGuard={() => () => undefined} />)
}
const listUrls = () => fetchMock.mock.calls.map(([url]) => String(url)).filter(url => url.startsWith(base + '?'))
const statuses = (url: string) => new URL(url, 'http://test').searchParams.getAll('status')

it('filters by pending, in-progress and all with repeated status parameters', async () => {
  mount()
  const filter = within(await screen.findByRole('group', { name: '筛选项目' }))
  expect(filter.getByRole('button', { name: '待分配' }).getAttribute('aria-pressed')).toBe('true')
  await screen.findByText('第一项目')
  expect(statuses(listUrls().at(-1)!)).toEqual(['pending_assignment'])

  fireEvent.click(filter.getByRole('button', { name: '处理中' }))
  await waitFor(() => expect(statuses(listUrls().at(-1)!)).toEqual(['assigned', 'analyzing', 'needs_materials', 'materials_submitted']))
  expect(filter.getByRole('button', { name: '处理中' }).getAttribute('aria-pressed')).toBe('true')

  fireEvent.click(filter.getByRole('button', { name: '全部' }))
  await waitFor(() => expect(listUrls().at(-1)).not.toContain('status='))
  expect(new URL(listUrls().at(-1)!, 'http://test').searchParams.get('page')).toBe('1')
})

it('shows the required analyses with the customer requirement labels and the resubmitted status', async () => {
  rows = [row('p1', '第一项目', { progress_status: 'materials_submitted' })]
  mount()
  const table = within(await screen.findByRole('table'))
  expect(table.getByRole('columnheader', { name: '所需分析' })).toBeTruthy()
  expect(await table.findByText('单细胞 RNA 测序数据分析、RNA 转录组学分析')).toBeTruthy()
  expect(table.getByText('已补交，等待核对')).toBeTruthy()
})

it('confirms an assignment in place and moves focus to the next row', async () => {
  mount()
  await screen.findByText('第一项目')
  const [first] = screen.getAllByRole('button', { name: '分配分析员' })
  fireEvent.click(first)
  const dialog = within(await screen.findByRole('dialog', { name: '分配分析员' }))
  expect(dialog.getByText('所需分析：单细胞 RNA 测序数据分析、RNA 转录组学分析')).toBeTruthy()
  fireEvent.click(await dialog.findByRole('radio', { name: 'analyst-a@example.test' }))
  const listReads = listUrls().length
  fireEvent.click(dialog.getByRole('button', { name: '确认分配' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  const table = within(screen.getByRole('table'))
  expect(table.getByText('第一项目')).toBeTruthy()
  expect(table.getByText('analyst-a@example.test')).toBeTruthy()
  const next = within(screen.getByText('第二项目').closest('tr')!).getByRole('button', { name: '分配分析员' })
  expect(document.activeElement).toBe(next)
  expect(listUrls()).toHaveLength(listReads)
  expect(screen.queryByText('待分配项目已处理完。')).toBeNull()

  fireEvent.click(next)
  const second = within(await screen.findByRole('dialog', { name: '分配分析员' }))
  expect(second.getByText('所需分析：—')).toBeTruthy()
  fireEvent.click(await second.findByRole('radio', { name: 'analyst-a@example.test' }))
  fireEvent.click(second.getByRole('button', { name: '确认分配' }))
  expect(await screen.findByText('待分配项目已处理完。')).toBeTruthy()
})

it('labels the revoke field as the revoke reason', async () => {
  rows = [row('p1', '第一项目', { analyst_id: 'analyst-a', analyst_email: analyst.email, revision: 1, progress_status: 'assigned' })]
  mount()
  fireEvent.click(await screen.findByRole('button', { name: '撤回授权' }))
  const dialog = within(await screen.findByRole('dialog', { name: '撤回授权' }))
  expect(dialog.queryByLabelText('分配理由')).toBeNull()
  fireEvent.change(dialog.getByLabelText('撤回理由'), { target: { value: '短' } })
  fireEvent.submit(dialog.getByRole('button', { name: '确认撤回' }).closest('form')!)
  expect(await dialog.findByText('请填写 5 至 500 字的撤回理由。')).toBeTruthy()
})
