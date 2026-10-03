import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import AuthBoundary from './AuthBoundary'
import { apiFetch, clearApiSession, setApiSession } from '../api'

const session = { user: { id: 'a', email: 'a@example.com', role: 'user' }, csrf_token: 'a-csrf' }
const newPassword = 'new-password-123'
afterEach(() => { cleanup(); clearApiSession(); vi.unstubAllGlobals(); vi.useRealTimers(); window.location.hash = '' })
async function open(mode: 'change' | 'reset', mutation: (init: RequestInit) => Promise<Response> = async () => new Response(null, { status: 204 })) {
  const send = vi.fn()
  class Channel { onmessage = null; postMessage = send; close() {} }
  vi.stubGlobal('BroadcastChannel', Channel)
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/me')) return mode === 'change' ? Response.json(session) : new Response(null, { status: 401 })
    if (url.endsWith('-password')) return mutation(init!)
    return new Response(null, { status: 204 })
  })
  vi.stubGlobal('fetch', fetchMock)
  render(<AuthBoundary><p>私有工作区</p></AuthBoundary>)
  fireEvent.click(await screen.findByRole('button', { name: mode === 'change' ? '修改密码' : '忘记密码' }))
  return { fetchMock, send }
}
function fill(mode: 'change' | 'reset', password = newPassword, confirmation = password) {
  fireEvent.change(screen.getByLabelText(mode === 'change' ? '当前密码' : '恢复码'), { target: { value: mode === 'change' ? 'old-password-123' : 'one-use-code' } })
  fireEvent.change(screen.getByLabelText('新密码'), { target: { value: password } })
  fireEvent.change(screen.getByLabelText('确认新密码'), { target: { value: confirmation } })
}
function submit() { fireEvent.submit(screen.getByLabelText('新密码').closest('form')!) }

it.each(['change', 'reset'] as const)('completes %s, clears workspace/hash/secrets and broadcasts login requirement', async mode => {
  const { fetchMock, send } = await open(mode)
  if (mode === 'reset') expect(screen.getByText(/管理员.*线下.*15.*分钟.*一次/)).toBeTruthy()
  window.location.hash = '#private-project'
  fill(mode); submit()
  await screen.findByLabelText('邮箱')
  expect(screen.getByRole('status').textContent).toContain('密码已更新，请重新登录')
  expect(screen.queryByText('私有工作区')).toBeNull()
  expect((screen.getByLabelText('密码') as HTMLInputElement).value).toBe('')
  expect(window.location.hash).toBe('')
  const request = fetchMock.mock.calls.find(([url]) => url.endsWith('-password'))!
  expect(request[0]).toBe(`/api/v1/auth/${mode === 'change' ? 'change' : 'reset'}-password`)
  expect(JSON.parse(String(request[1]?.body))).toEqual(mode === 'change'
    ? { current_password: 'old-password-123', new_password: newPassword }
    : { recovery_code: 'one-use-code', new_password: newPassword })
  expect(new Headers(request[1]?.headers).get('X-PaperAssist-Client')).toBe('web')
  expect(new Headers(request[1]?.headers).get('X-CSRF-Token')).toBe(mode === 'change' ? session.csrf_token : null)
  expect(send.mock.calls).toEqual([['session_changed']])
  expect(localStorage.length).toBe(0); expect(sessionStorage.length).toBe(0)
  await apiFetch('/probe', { method: 'POST' })
  expect(new Headers(fetchMock.mock.calls.at(-1)?.[1]?.headers).has('X-CSRF-Token')).toBe(false)
})
it.each([
  ['change', 400, 'invalid_current_password', '当前密码不正确'],
  ['reset', 400, 'invalid_recovery_code', '恢复码无效或已过期'],
  ['reset', 422, 'invalid_request', '12–128'],
  ['change', 429, 'password_rate_limited', '900 秒后'],
  ['reset', 503, 'database_unavailable', '密码更新失败'],
] as const)('shows safe %s error %s without reflecting credentials', async (mode, status, code, message) => {
  await open(mode, async () => Response.json({ detail: { code, message: 'server leaked one-use-code' } }, { status, headers: { 'Retry-After': '900' } }))
  fill(mode); submit()
  expect((await screen.findByRole('alert')).textContent).toContain(message)
  expect(screen.queryByText(/server leaked/)).toBeNull()
  expect((screen.getByLabelText('新密码') as HTMLInputElement).value).toBe('')
  expect((screen.getByLabelText(mode === 'change' ? '当前密码' : '恢复码') as HTMLInputElement).value).toBe('')
})
it('shows connection failure and allows retry without claiming success', async () => {
  await open('reset', async () => { throw new Error('offline') }); fill('reset'); submit()
  expect((await screen.findByRole('alert')).textContent).toContain('检查连接')
  expect(screen.getByRole('button', { name: '重置密码' }).hasAttribute('disabled')).toBe(false)
  expect(screen.queryByText('密码已更新，请重新登录。')).toBeNull()
})
it.each([
  ['short', 'short', '12–128'],
  ['x'.repeat(129), 'x'.repeat(129), '12–128'],
  [newPassword, 'different-password', '两次输入的新密码不一致'],
  ['😀'.repeat(11), '😀'.repeat(11), '12–128'],
])('validates confirmation and code point length locally (%s)', async (password, confirmation, message) => {
  const { fetchMock } = await open('reset'); fill('reset', password, confirmation); submit()
  expect(screen.getByRole('alert').textContent).toContain(message)
  expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('-password'))).toHaveLength(0)
})
it('accepts 128 Unicode code points even when UTF-16 length is greater', async () => {
  await open('reset'); fill('reset', '😀'.repeat(128)); submit()
  await screen.findByText('密码已更新，请重新登录。')
})
it('guards double submit and cancellation, wiping fields on reopening', async () => {
  let finish!: (response: Response) => void
  let signal: AbortSignal | null | undefined
  const { fetchMock } = await open('change', init => { signal = init.signal; return new Promise(resolve => { finish = resolve }) })
  fill('change'); submit(); submit()
  expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('-password'))).toHaveLength(1)
  expect(screen.getByRole('button', { name: '正在更新密码……' }).hasAttribute('disabled')).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: '取消' }))
  expect(signal?.aborted).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: '修改密码' }))
  expect((screen.getByLabelText('当前密码') as HTMLInputElement).value).toBe('')
  await act(async () => { finish(new Response(null, { status: 204 })) })
  await screen.findByText(session.user.email)
  expect(screen.queryByText('密码已更新，请重新登录。')).toBeNull()
})
it('clears login password on entering recovery and returning', async () => {
  await open('reset')
  fill('reset'); fireEvent.click(screen.getByRole('button', { name: '返回登录' }))
  fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'login-secret' } })
  fireEvent.click(screen.getByRole('button', { name: '忘记密码' }))
  expect((screen.getByLabelText('恢复码') as HTMLInputElement).value).toBe('')
  fireEvent.click(screen.getByRole('button', { name: '返回登录' }))
  expect((screen.getByLabelText('密码') as HTMLInputElement).value).toBe('')
})
it('allows pasting a valid 128-code-point new password at login', async () => {
  await open('reset')
  fireEvent.click(screen.getByRole('button', { name: '返回登录' }))
  const user = userEvent.setup()
  await user.click(screen.getByLabelText('密码'))
  await user.paste('😀'.repeat(128))
  expect((screen.getByLabelText('密码') as HTMLInputElement).value).toBe('😀'.repeat(128))
})
it('discards a delayed error body after session switching and wipes secrets', async () => {
  let finish!: (body: unknown) => void
  const response = Response.json({ detail: { code: 'invalid_current_password' } }, { status: 400 })
  response.json = () => new Promise(resolve => { finish = resolve })
  await open('change', async () => response); fill('change'); submit()
  await waitFor(() => expect(finish).toBeTypeOf('function'))
  act(() => setApiSession('new-session'))
  await act(async () => { finish({ detail: { code: 'invalid_current_password' } }) })
  expect(screen.queryByText('当前密码不正确。')).toBeNull()
  expect(screen.queryByText('密码已更新，请重新登录。')).toBeNull()
  expect(screen.queryByDisplayValue(newPassword)).toBeNull()
})
it('times out even when fetch ignores abort and does not adopt its late success', async () => {
  let finish!: (response: Response) => void
  let signal: AbortSignal | null | undefined
  await open('reset', init => { signal = init.signal; return new Promise(resolve => { finish = resolve }) })
  vi.useFakeTimers(); fill('reset'); submit()
  await act(async () => { await vi.advanceTimersByTimeAsync(15000) })
  expect(screen.getByRole('alert').textContent).toContain('超时')
  expect(signal?.aborted).toBe(true)
  expect(screen.getByRole('button', { name: '重置密码' }).hasAttribute('disabled')).toBe(false)
  await act(async () => { finish(new Response(null, { status: 204 })) })
  expect(screen.queryByText('密码已更新，请重新登录。')).toBeNull()
  vi.useRealTimers()
  await screen.findByLabelText('邮箱')
})
it('aborts the pending password request on unmount', async () => {
  let signal: AbortSignal | null | undefined
  await open('change', init => { signal = init.signal; return new Promise(() => {}) })
  fill('change'); submit(); cleanup()
  expect(signal?.aborted).toBe(true)
})
it('times out a delayed error body without adopting its text later', async () => {
  let finish!: (body: unknown) => void
  const response = Response.json({ detail: { code: 'invalid_recovery_code' } }, { status: 400 })
  response.json = () => new Promise(resolve => { finish = resolve })
  await open('reset', async () => response)
  vi.useFakeTimers()
  fill('reset'); submit()
  await act(async () => { await Promise.resolve() })
  expect(finish).toBeTypeOf('function')
  await act(async () => { await vi.advanceTimersByTimeAsync(15000) })
  expect(screen.getByRole('alert').textContent).toContain('超时')
  await act(async () => { finish({ detail: { code: 'invalid_recovery_code' } }) })
  expect(screen.queryByText(/恢复码无效或已过期/)).toBeNull()
  expect(screen.queryByText('密码已更新，请重新登录。')).toBeNull()
})
