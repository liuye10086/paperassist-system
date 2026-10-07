import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import AuthBoundary from '../../features/auth/AuthBoundary'
import ProjectDetails from '../../features/projects/ProjectDetails'
import { clearApiSession } from '../../shared/api/client'

const session = { user: { id: 'synthetic-a', email: 'a@example.test', role: 'user' }, csrf_token: 'synthetic-token' }
const project = { id: 'synthetic-p', name: 'Synthetic project', research_topic: 'Synthetic topic', project_type: 'sci' as const,
  file_count: 0, created_at: '2026-10-05T00:00:00Z', updated_at: '2026-10-05T00:00:00Z' }
afterEach(() => { cleanup(); clearApiSession(); vi.unstubAllGlobals() })

it('enters login fields with Tab and submits once with Enter', async () => {
  const user = userEvent.setup()
  let complete!: (value: Response) => void
  const fetch = vi.fn((url: string) => url.endsWith('/me') ? Promise.resolve(new Response(null, { status: 401 }))
    : new Promise<Response>(resolve => { complete = resolve }))
  vi.stubGlobal('fetch', fetch)
  render(<AuthBoundary><input aria-label="Synthetic workspace input" /></AuthBoundary>)
  const email = await screen.findByLabelText('邮箱')
  expect(document.activeElement).toBe(email)
  await user.type(email, 'a@example.test')
  await user.tab()
  expect(document.activeElement).toBe(screen.getByLabelText('密码'))
  await user.tab({ shift: true })
  expect(document.activeElement).toBe(email)
  await user.tab()
  await user.keyboard('synthetic-password{Enter}')
  expect(screen.getByRole('button', { name: '正在登录……' }).getAttribute('disabled')).not.toBeNull()
  await user.keyboard('{Enter}')
  expect(fetch.mock.calls.filter(([url]) => url.endsWith('/login'))).toHaveLength(1)
  await act(async () => { complete(Response.json(session)) })
  expect(document.activeElement).toBe(screen.getByLabelText('Synthetic workspace input'))
})

it('enters recovery and returns focus to its login trigger using Space', async () => {
  const user = userEvent.setup()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 401 })))
  render(<AuthBoundary><p>Private content</p></AuthBoundary>)
  await screen.findByLabelText('邮箱')
  screen.getByRole('button', { name: '忘记密码' }).focus()
  await user.keyboard(' ')
  expect(document.activeElement).toBe(screen.getByLabelText('恢复码'))
  await user.tab(); await user.tab(); await user.tab(); await user.tab()
  expect(document.activeElement).toBe(screen.getByRole('button', { name: '返回登录' }))
  await user.keyboard('{Enter}')
  expect(document.activeElement).toBe(screen.getByRole('button', { name: '忘记密码' }))
})

it('enters change-password and cancels back to its trigger without stealing focus on rerender', async () => {
  const user = userEvent.setup()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json(session)))
  const view = render(<AuthBoundary><input aria-label="Synthetic workspace input" /></AuthBoundary>)
  const account = await screen.findByRole('button', { name: '账号' })
  await user.click(account)
  const trigger = screen.getByRole('button', { name: '修改密码' })
  trigger.focus(); await user.keyboard('{Enter}')
  expect(document.activeElement).toBe(screen.getByLabelText('当前密码'))
  await user.tab(); await user.tab(); await user.tab(); await user.tab()
  await user.keyboard(' ')
  expect(document.activeElement).toBe(account)
  screen.getByLabelText('Synthetic workspace input').focus()
  view.rerender(<AuthBoundary><input aria-label="Synthetic workspace input" /></AuthBoundary>)
  expect(document.activeElement).toBe(screen.getByLabelText('Synthetic workspace input'))
})

it('enters project edit with Enter and returns focus after keyboard cancellation or save', async () => {
  const user = userEvent.setup()
  const onUpdated = vi.fn()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ ...project, name: 'Changed' })))
  const view = render(<ProjectDetails project={project} onUpdated={onUpdated} />)
  const trigger = screen.getByRole('button', { name: '编辑项目信息' })
  trigger.focus(); await user.keyboard('{Enter}')
  expect(document.activeElement).toBe(screen.getByLabelText('修改项目名称'))
  await user.tab(); await user.tab(); await user.tab()
  expect(document.activeElement).toBe(screen.getByRole('button', { name: '取消修改' }))
  await user.keyboard(' ')
  expect(document.activeElement).toBe(screen.getByRole('button', { name: '编辑项目信息' }))
  await user.keyboard('{Enter}')
  await user.clear(screen.getByLabelText('修改项目名称'))
  await user.type(screen.getByLabelText('修改项目名称'), 'Changed')
  screen.getByLabelText('修改研究主题').focus()
  view.rerender(<ProjectDetails project={{ ...project, file_count: 1 }} onUpdated={onUpdated} />)
  expect(document.activeElement).toBe(screen.getByLabelText('修改研究主题'))
  await user.tab(); await user.keyboard('{Enter}')
  expect(await screen.findByRole('button', { name: '编辑项目信息' })).toBe(document.activeElement)
  expect(onUpdated).toHaveBeenCalledOnce()
})

it('locks login synchronously for two submits dispatched within one event batch', async () => {
  const fetch = vi.fn((url: string) => url.endsWith('/me') ? Promise.resolve(new Response(null, { status: 401 })) : new Promise<Response>(() => {}))
  vi.stubGlobal('fetch', fetch)
  render(<AuthBoundary><p>Private</p></AuthBoundary>)
  fireEvent.change(await screen.findByLabelText('邮箱'), { target: { value: 'a@example.test' } })
  fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'synthetic-password' } })
  const form = screen.getByLabelText('密码').closest('form')!
  act(() => { form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })) })
  expect(fetch.mock.calls.filter(([url]) => url.endsWith('/login'))).toHaveLength(1)
})

it('locks logout synchronously for two activations dispatched within one event batch', async () => {
  const fetch = vi.fn((url: string) => url.endsWith('/me') ? Promise.resolve(Response.json(session)) : new Promise<Response>(() => {}))
  vi.stubGlobal('fetch', fetch)
  render(<AuthBoundary><input aria-label="Synthetic workspace input" /></AuthBoundary>)
  fireEvent.click(await screen.findByRole('button', { name: '账号' }))
  const button = screen.getByRole('button', { name: '退出登录' })
  act(() => { button.dispatchEvent(new MouseEvent('click', { bubbles: true })); button.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
  expect(fetch.mock.calls.filter(([url]) => url.endsWith('/logout'))).toHaveLength(1)
})

it('opens account actions and closes with Escape returning focus to account', async () => {
  const user = userEvent.setup()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json(session)))
  render(<AuthBoundary><input aria-label="Synthetic workspace input" /></AuthBoundary>)
  const account = await screen.findByRole('button', { name: '账号' })
  expect(screen.queryByRole('button', { name: '退出登录' })).toBeNull()
  await user.click(account)
  expect(screen.getByRole('button', { name: '退出登录' })).toBeTruthy()
  await user.tab()
  await user.keyboard('{Escape}')
  expect(screen.queryByRole('button', { name: '退出登录' })).toBeNull()
  expect(document.activeElement).toBe(account)
})

it('focuses the workspace main before a preceding hidden navigation button after session restore', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json(session)))
  render(<AuthBoundary><button style={{ display: 'none' }}>Navigation</button><main tabIndex={-1}><input aria-label="Research input" /></main></AuthBoundary>)
  await screen.findByRole('button', { name: '账号' })
  expect(document.activeElement).toBe(screen.getByRole('main'))
})
