import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import AuthBoundary from './auth/AuthBoundary'
import { clearApiSession, setApiSession } from './api'

const session = { user: { id: 'synthetic-a', email: 'a@example.test', role: 'user' }, csrf_token: 'synthetic-token' }
const other = { user: { id: 'synthetic-b', email: 'b@example.test', role: 'user' }, csrf_token: 'other-token' }
afterEach(() => { cleanup(); clearApiSession(); vi.useRealTimers(); vi.unstubAllGlobals() })
function mount() { return render(<AuthBoundary><p>Private workspace</p></AuthBoundary>) }
function login() {
  fireEvent.change(screen.getByLabelText('邮箱'), { target: { value: 'a@example.test' } })
  fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'synthetic-password' } })
  fireEvent.submit(screen.getByLabelText('密码').closest('form')!)
}

it.each(['request', 'body'] as const)('bounds session restore %s and rejects its late session after retry', async phase => {
  let finish!: (value: Response | typeof session) => void
  let signal!: AbortSignal
  const pending = new Promise<Response | typeof session>(resolve => { finish = resolve })
  const response = Response.json(session)
  response.json = () => pending as Promise<typeof session>
  let calls = 0
  const fetch = vi.fn((_url: string, init: RequestInit) => {
    signal = init.signal as AbortSignal
    return ++calls === 1 ? phase === 'request' ? pending : Promise.resolve(response) : Promise.resolve(Response.json(other))
  })
  vi.stubGlobal('fetch', fetch); vi.useFakeTimers(); mount()
  await act(async () => {})
  await act(async () => { vi.advanceTimersByTime(15_000) })
  expect(signal.aborted).toBe(true)
  expect(screen.getByRole('alert').textContent).toContain('超时')
  expect(screen.queryByText('Private workspace')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '重试' }))
  await act(async () => {})
  await act(async () => { finish(phase === 'request' ? Response.json(session) : session) })
  expect(screen.getByText(other.user.email)).toBeTruthy()
  expect(screen.queryByText(session.user.email)).toBeNull()
})

it.each(['request', 'body'] as const)('bounds login %s and reconciles a late cookie without adopting stale payload', async phase => {
  let finish!: (value: Response | typeof session) => void
  let loginSignal!: AbortSignal
  let cookie: typeof session | null = null
  const pending = new Promise<Response | typeof session>(resolve => { finish = resolve })
  const response = Response.json(session); response.json = () => pending as Promise<typeof session>
  const fetch = vi.fn((url: string, init?: RequestInit) => {
    if (url.endsWith('/me')) return Promise.resolve(cookie ? Response.json(cookie) : new Response(null, { status: 401 }))
    loginSignal = init?.signal as AbortSignal
    return phase === 'request' ? pending : Promise.resolve(response)
  })
  vi.stubGlobal('fetch', fetch); mount(); await screen.findByLabelText('邮箱')
  vi.useFakeTimers(); login(); await act(async () => {})
  await act(async () => { vi.advanceTimersByTime(15_000) })
  expect(loginSignal.aborted).toBe(true)
  expect(screen.getByRole('alert').textContent).toContain('超时')
  expect((screen.getByRole('button', { name: '登录' }) as HTMLButtonElement).disabled).toBe(false)
  cookie = other
  await act(async () => { finish(phase === 'request' ? Response.json(session) : session) })
  expect(screen.getByText(other.user.email)).toBeTruthy()
  expect(screen.queryByText(session.user.email)).toBeNull()
})

it('bounds logout without claiming revocation and reconciles its late cookie clearing', async () => {
  let finish!: (value: Response) => void
  let cookie: typeof session | null = session
  let signal!: AbortSignal
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    if (url.endsWith('/me')) return Promise.resolve(cookie ? Response.json(cookie) : new Response(null, { status: 401 }))
    signal = init?.signal as AbortSignal
    return new Promise<Response>(resolve => { finish = resolve })
  }))
  mount(); await screen.findByText(session.user.email)
  vi.useFakeTimers(); fireEvent.click(screen.getByRole('button', { name: '退出登录' }))
  await act(async () => { vi.advanceTimersByTime(15_000) })
  expect(signal.aborted).toBe(true)
  expect(screen.getByRole('alert').textContent).toContain('尚未确认撤销')
  expect(screen.getByText('Private workspace')).toBeTruthy()
  expect((screen.getByRole('button', { name: '退出登录' }) as HTMLButtonElement).disabled).toBe(false)
  cookie = null
  await act(async () => { finish(new Response(null, { status: 204 })) })
  expect(screen.getByLabelText('邮箱')).toBeTruthy()
  expect(screen.queryByText('Private workspace')).toBeNull()
})

it('aborts login on unmount and does not adopt its delayed body', async () => {
  let signal!: AbortSignal
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => url.endsWith('/me')
    ? Promise.resolve(new Response(null, { status: 401 }))
    : (signal = init?.signal as AbortSignal, new Promise<Response>(() => {}))))
  const view = mount(); await screen.findByLabelText('邮箱'); login(); view.unmount()
  expect(signal.aborted).toBe(true)
})

it('keeps a malformed restored user in recoverable unavailable state', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ csrf_token: 'synthetic-token' })))
  mount()
  expect((await screen.findByRole('alert')).textContent).toContain('无法恢复会话')
  expect(screen.getByRole('button', { name: '重试' })).toBeTruthy()
  expect(screen.queryByText('Private workspace')).toBeNull()
})

it('cancels a pending restore on external session generation change while anonymous 401 remains valid', async () => {
  let signal!: AbortSignal
  vi.stubGlobal('fetch', vi.fn((_url: string, init: RequestInit) => {
    signal = init.signal as AbortSignal
    return new Promise<Response>(() => {})
  }))
  vi.useFakeTimers(); mount()
  act(() => { setApiSession('synthetic-new-session'); vi.advanceTimersByTime(0) })
  expect(signal.aborted).toBe(true)
  expect(screen.queryByText('Private workspace')).toBeNull()
  expect(screen.getByRole('button', { name: '重试' })).toBeTruthy()
})

it('aborts pending login after external account change and adopts only reconciled cookie truth', async () => {
  let finish!: (value: Response) => void
  let signal!: AbortSignal
  let cookie: typeof session | null = null
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    if (url.endsWith('/me')) return Promise.resolve(cookie ? Response.json(cookie) : new Response(null, { status: 401 }))
    signal = init?.signal as AbortSignal
    return new Promise<Response>(resolve => { finish = resolve })
  }))
  mount(); await screen.findByLabelText('邮箱'); login()
  act(() => setApiSession(other.csrf_token))
  expect(signal.aborted).toBe(true)
  cookie = other
  await act(async () => { finish(Response.json(session)) })
  expect(screen.getByText(other.user.email)).toBeTruthy()
  expect(screen.queryByText(session.user.email)).toBeNull()
})
