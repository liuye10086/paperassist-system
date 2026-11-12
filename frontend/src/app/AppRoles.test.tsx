import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { clearApiSession } from '../shared/api/client'
import App from './App'

vi.mock('../features/projects/ProjectWorkspace', () => ({ default: () => <main>Existing analyst workspace</main> }))

afterEach(() => {
  cleanup()
  clearApiSession()
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', window.location.pathname)
})

it.each([
  ['admin', '审核管理'],
  ['customer', '我的项目'],
  ['analyst', 'Existing analyst workspace'],
])('mounts only the workspace available to %s', async (role, visibleText) => {
  const fetch = vi.fn(async (url: string) => url.endsWith('/me')
    ? Response.json({ user: { id: 'account', email: 'role@example.test', role }, csrf_token: 'test-csrf' })
    : Response.json({ items: [], total: 0, page: 1, page_size: 10 }))
  vi.stubGlobal('fetch', fetch)
  render(<App />)
  if (role === 'admin' || role === 'customer') await screen.findByRole('heading', { name: visibleText })
  else await screen.findByText(visibleText)
  fireEvent.click(screen.getByRole('button', { name: '账号' }))
  expect(Boolean(screen.queryByRole('button', { name: '项目工作区' }))).toBe(role === 'analyst')
  expect(Boolean(screen.queryByRole('button', { name: '权限管理' }))).toBe(role === 'admin')
  expect(Boolean(screen.queryByRole('button', { name: '新建研究项目' }))).toBe(role === 'customer')
  expect(Boolean(screen.queryByText('Existing analyst workspace'))).toBe(role === 'analyst')
  expect(fetch.mock.calls.some(([url]) => url.includes('/admin/registrations') && url.includes('review_status=pending'))).toBe(role === 'admin')
})

it('keeps the admin page in the address and links role permissions to approved accounts', async () => {
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
  fireEvent.click(screen.getByRole('button', { name: '去账号管理' }))
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

it('assigns, replaces, and revokes an analyst from the permissions page with audited revisions', async () => {
  const base = '/api/v1/admin/project-assignments'
  const candidates = ['analyst-a', 'analyst-b'].map(id => ({ id, email: id + '@example.test', role: 'analyst', active: true }))
  let project = { id: 'project', name: '已提交的客户项目', research_topic: '对照分组', customer_email: 'owner@example.test',
    analyst_id: null as string | null, analyst_email: null as string | null, revision: 0,
    submitted_version: 2, progress_status: 'pending_assignment', updated_at: '2026-11-11T12:00:00Z' }
  const events: { id: string; actor_email: string; previous_analyst_email: string | null; analyst_email: string | null;
    revision: number; reason: string; created_at: string }[] = []
  const page = <T,>(items: T[]) => Response.json({ items, total: items.length, page: 1, page_size: 10 })
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/me')) return Response.json({
      user: { id: 'admin', email: 'admin@example.test', role: 'admin' }, csrf_token: 'test-csrf',
    })
    if (url.startsWith(base + '?')) return page([project])
    if (url.startsWith(base + '/project/events?')) return page(events)
    if (url.startsWith('/api/v1/admin/users?')) return page(candidates)
    if (url === base + '/project' && init?.method === 'PATCH') {
      const body = JSON.parse(String(init.body))
      const before = project.analyst_email
      project = { ...project, analyst_id: body.analyst_id, analyst_email: candidates.find(user => user.id === body.analyst_id)?.email ?? null,
        revision: project.revision + 1 }
      events.unshift({ id: 'event-' + project.revision, actor_email: 'admin@example.test',
        previous_analyst_email: before, analyst_email: project.analyst_email, revision: project.revision,
        reason: body.reason, created_at: project.updated_at })
      return Response.json(project)
    }
    return page([])
  })
  vi.stubGlobal('fetch', fetch)
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: '权限管理' }))
  fireEvent.click(await screen.findByRole('button', { name: '分配分析员' }))
  fireEvent.click(await screen.findByRole('radio', { name: 'analyst-a@example.test' }))
  fireEvent.change(screen.getByLabelText('分配理由'), { target: { value: '首位分析员负责样本核对' } })
  fireEvent.click(screen.getByRole('button', { name: '确认分配' }))
  await screen.findByText('项目已分配。')
  fireEvent.click(await screen.findByRole('button', { name: '更换分析员' }))
  fireEvent.click(await screen.findByRole('radio', { name: 'analyst-b@example.test' }))
  fireEvent.change(screen.getByLabelText('分配理由'), { target: { value: '将后续分析转交值班人员' } })
  fireEvent.click(screen.getByRole('button', { name: '确认更换' }))
  await screen.findByText('分析员已更换。')
  fireEvent.click(await screen.findByRole('button', { name: '撤回授权' }))
  fireEvent.change(screen.getByLabelText('分配理由'), { target: { value: '项目需要重新安排处理人员' } })
  fireEvent.click(screen.getByRole('button', { name: '确认撤回' }))
  await screen.findByText('项目授权已撤回。')
  fireEvent.click(await screen.findByRole('button', { name: '查看分配记录' }))
  await screen.findByText('首位分析员负责样本核对')
  expect(screen.getByText('将后续分析转交值班人员')).toBeTruthy()
  expect(screen.getByText('项目需要重新安排处理人员')).toBeTruthy()
  expect(fetch.mock.calls.filter(([url]) => url === base + '/project').map(([, init]) => JSON.parse(String(init?.body))))
    .toEqual([
      { analyst_id: 'analyst-a', expected_revision: 0, reason: '首位分析员负责样本核对' },
      { analyst_id: 'analyst-b', expected_revision: 1, reason: '将后续分析转交值班人员' },
      { analyst_id: null, expected_revision: 2, reason: '项目需要重新安排处理人员' },
    ])
})
