import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { clearApiSession } from '../shared/api/client'
import App from './App'

vi.mock('../features/projects/ProjectWorkspace', () => ({ default: () => <main>Existing analyst workspace</main> }))

const dialogMethods = ['showModal', 'close'] as const
const originalDialogMethods = dialogMethods.map(name => Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, name))

beforeEach(() => {
  Object.defineProperties(HTMLDialogElement.prototype, {
    showModal: { configurable: true, value(this: HTMLDialogElement) { this.open = true } },
    close: { configurable: true, value(this: HTMLDialogElement) { this.open = false } },
  })
})

afterEach(() => {
  cleanup()
  dialogMethods.forEach((name, index) => {
    const original = originalDialogMethods[index]
    if (original) Object.defineProperty(HTMLDialogElement.prototype, name, original)
    else Reflect.deleteProperty(HTMLDialogElement.prototype, name)
  })
  clearApiSession()
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', window.location.pathname)
})

it.each([
  ['admin', '审核管理'],
  ['customer', '项目列表区域'],
  ['analyst', 'Existing analyst workspace'],
])('mounts only the workspace available to %s', async (role, visibleText) => {
  const fetch = vi.fn(async (url: string) => url.endsWith('/me')
    ? Response.json({ user: { id: 'account', email: 'role@example.test', role }, csrf_token: 'test-csrf' })
    : Response.json({ items: [], total: 0, page: 1, page_size: 10 }))
  vi.stubGlobal('fetch', fetch)
  render(<App />)
  if (role === 'admin') await screen.findByRole('heading', { name: visibleText })
  else if (role === 'customer') await screen.findByRole('region', { name: visibleText })
  else await screen.findByText(visibleText)
  fireEvent.click(screen.getByRole('button', { name: '账号' }))
  expect(Boolean(screen.queryByRole('button', { name: '项目工作区' }))).toBe(role === 'analyst')
  expect(Boolean(screen.queryByRole('button', { name: '权限管理' }))).toBe(role === 'admin')
  expect(Boolean(screen.queryByRole('button', { name: '新建研究项目' }))).toBe(role === 'customer')
  expect(Boolean(screen.queryByText('Existing analyst workspace'))).toBe(role === 'analyst')
  expect(fetch.mock.calls.some(([url]) => url.includes('/admin/registrations') && url.includes('review_status=all'))).toBe(role === 'admin')
})

it('restores the permissions page and opens approved accounts from the sidebar', async () => {
  const fetch = vi.fn(async (url: string) => url.endsWith('/me')
    ? Response.json({ user: { id: 'account', email: 'admin@example.test', role: 'admin' }, csrf_token: 'test-csrf' })
    : Response.json({ items: [], total: 0, page: 1, page_size: 10 }))
  vi.stubGlobal('fetch', fetch)
  const { unmount } = render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: '权限管理' }))
  expect(screen.getByRole('heading', { name: '权限管理', level: 1 })).toBeTruthy()
  expect(window.location.hash).toBe('#admin=permissions')
  unmount()
  render(<App />)
  await screen.findByRole('heading', { name: '权限管理', level: 1 })
  expect(screen.queryByRole('heading', { name: '角色权限' })).toBeNull()
  expect(screen.getAllByRole('table')).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', { name: '账号管理' }))
  expect(window.location.hash).toBe('#admin=accounts')
  await waitFor(() => expect(fetch.mock.calls.some(([url]) => url.includes('/admin/users') && url.includes('review_status=approved'))).toBe(true))
})

it('allows a reconfirmed administrator to reopen the workspace after a forbidden read', async () => {
  let denied = true
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith('/me')) {
      return Response.json({ user: { id: 'account', email: 'admin@example.test', role: 'admin' }, csrf_token: 'test-csrf' })
    }
    return denied
      ? Response.json({ detail: { code: 'permission_denied' } }, { status: 403 })
      : Response.json({ items: [], total: 0, page: 1, page_size: 10 })
  }))
  render(<App />)
  const retry = await screen.findByRole('button', { name: '重新打开管理页面' })
  expect(screen.queryByRole('button', { name: '审核管理' })).toBeNull()
  denied = false
  fireEvent.click(retry)
  await screen.findByRole('heading', { name: '审核管理' })
  await screen.findByText('没有符合筛选条件的记录。')
})

it('assigns, replaces, and revokes analysts in dialogs on the same permissions page', async () => {
  const base = '/api/v1/admin/project-assignments'
  const candidates = ['analyst-a', 'analyst-b'].map(id => ({ id, email: id + '@example.test', role: 'analyst', active: true }))
  const disabledAnalyst = { id: 'disabled', email: 'disabled@example.test', role: 'analyst', active: false }
  let showEnabledAnalysts = false
  let project = { id: 'project', name: '已提交的客户项目', research_topic: '对照分组', customer_email: 'owner@example.test',
    analyst_id: null as string | null, analyst_email: null as string | null, revision: 0,
    submitted_version: 2, progress_status: 'pending_assignment', updated_at: '2026-11-11T12:00:00Z' }
  const page = <T,>(items: T[]) => Response.json({ items, total: items.length, page: 1, page_size: 10 })
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/me')) return Response.json({
      user: { id: 'admin', email: 'admin@example.test', role: 'admin' }, csrf_token: 'test-csrf',
    })
    if (url.startsWith(base + '?')) return page([project])
    if (url.startsWith('/api/v1/admin/users?')) {
      const params = new URL(url, 'http://testserver').searchParams
      const analysts = showEnabledAnalysts ? [...candidates, disabledAnalyst] : [disabledAnalyst]
      return page(params.get('active') === 'true' ? analysts.filter(analyst => analyst.active) : analysts)
    }
    if (url === base + '/project' && init?.method === 'PATCH') {
      const body = JSON.parse(String(init.body))
      project = { ...project, analyst_id: body.analyst_id, analyst_email: candidates.find(user => user.id === body.analyst_id)?.email ?? null,
        revision: project.revision + 1 }
      return Response.json(project)
    }
    return page([])
  })
  vi.stubGlobal('fetch', fetch)
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: '权限管理' }))
  const assign = await screen.findByRole('button', { name: '分配分析员' })
  const table = screen.getByRole('table')
  expect(screen.queryByRole('button', { name: '查看分配记录' })).toBeNull()
  assign.focus()
  fireEvent.click(assign)
  const firstDialog = await screen.findByRole('dialog', { name: '分配分析员' })
  expect(window.location.hash).toBe('#admin=permissions')
  expect(table.isConnected).toBe(true)
  expect(await within(firstDialog).findByRole('radio', { name: 'disabled@example.test 停用' })).toHaveProperty('disabled', true)
  expect(within(firstDialog).queryByLabelText('搜索分析员邮箱')).toBeNull()
  expect(within(firstDialog).getByText('在账号管理启用分析员后即可分配。')).toBeTruthy()
  expect(within(firstDialog).getByRole('button', { name: '分配' })).toHaveProperty('disabled', true)
  fireEvent(firstDialog, new Event('cancel', { cancelable: true }))
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(document.activeElement).toBe(assign)
  expect(fetch.mock.calls.some(([url]) => url === base + '/project')).toBe(false)

  showEnabledAnalysts = true
  fireEvent.click(assign)
  const assigning = within(await screen.findByRole('dialog', { name: '分配分析员' }))
  expect(assigning.getByRole('button', { name: '分配' })).toHaveProperty('disabled', true)
  fireEvent.click(await assigning.findByRole('radio', { name: 'analyst-a@example.test' }))
  expect(assigning.queryByLabelText('分配理由')).toBeNull()
  fireEvent.click(assigning.getByRole('button', { name: '分配' }))
  await within(table).findByText('analyst-a@example.test')
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(screen.queryByText('项目已分配。')).toBeNull()

  fireEvent.click(await screen.findByRole('button', { name: '更换分析员' }))
  const replacing = within(await screen.findByRole('dialog', { name: '更换分析员' }))
  expect(await replacing.findByRole('radio', { name: 'analyst-a@example.test' })).toHaveProperty('disabled', true)
  fireEvent.click(replacing.getByRole('radio', { name: 'analyst-b@example.test' }))
  fireEvent.click(replacing.getByRole('button', { name: '分配' }))
  await within(table).findByText('analyst-b@example.test')
  expect(screen.queryByText('分析员已更换。')).toBeNull()

  fireEvent.click(await screen.findByRole('button', { name: '撤回授权' }))
  const revoking = within(await screen.findByRole('dialog', { name: '撤回授权' }))
  fireEvent.change(revoking.getByLabelText('分配理由'), { target: { value: '项目需要重新安排处理人员' } })
  fireEvent.click(revoking.getByRole('button', { name: '确认撤回' }))
  await within(table).findByText('未分配')
  expect(screen.queryByText('项目授权已撤回。')).toBeNull()
  expect(window.location.hash).toBe('#admin=permissions')
  expect(fetch.mock.calls.some(([url]) => url.includes('/events'))).toBe(false)
  expect(fetch.mock.calls.some(([url]) => url.startsWith(base + '?') && url.includes('page_size=10'))).toBe(true)
  expect(fetch.mock.calls.some(([url]) => url.includes('role=analyst') && url.includes('review_status=approved') && !url.includes('active=') && !url.includes('q='))).toBe(true)
  expect(fetch.mock.calls.filter(([url]) => url === base + '/project').map(([, init]) => JSON.parse(String(init?.body))))
    .toEqual([
      { analyst_id: 'analyst-a', expected_revision: 0, reason: '权限管理分配分析员' },
      { analyst_id: 'analyst-b', expected_revision: 1, reason: '权限管理更换分析员' },
      { analyst_id: null, expected_revision: 2, reason: '项目需要重新安排处理人员' },
    ])
})
