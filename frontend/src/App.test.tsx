import { afterEach, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import App from './App'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.location.hash = '' })
const session = { user: { id: 'a', email: 'admin@paperassist.local', role: 'admin' }, csrf_token: 'csrf' }
for (const late of ['login', 'logout'] as const) {
  it(`rebinds both tab workspaces to shared cookie after late ${late}`, async () => {
    vi.resetModules()
    const { default: FirstApp } = await import('./App')
    const firstApi = await import('./api')
    vi.resetModules()
    const { default: SecondApp } = await import('./App')
    const secondApi = await import('./api')
    const b = { user: { id: 'b', email: 'b@example.com', role: 'user' }, csrf_token: 'b-csrf' }
    let cookie: typeof session | null = late === 'logout' ? session : null
    let finish!: () => void
    const mutationTokens: (string | null)[] = []
    const channels: Channel[] = []
    class Channel {
      onmessage: ((event: MessageEvent) => void) | null = null
      constructor() { channels.push(this) }
      postMessage(data: string) {
        for (const peer of channels) if (peer !== this) peer.onmessage?.(new MessageEvent('message', { data }))
      }
      close() { channels.splice(channels.indexOf(this), 1) }
    }
    vi.stubGlobal('BroadcastChannel', Channel)
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/cookie-probe') {
        mutationTokens.push(new Headers(init?.headers).get('X-CSRF-Token'))
        return new Response(null, { status: 204 })
      }
      if (url.endsWith('/me')) return cookie ? Response.json(cookie) : new Response(null, { status: 401 })
      if (late === 'login' && url.endsWith('/login') && JSON.parse(String(init?.body)).email === session.user.email) {
        cookie = session
        return Response.json(session)
      }
      if (url.endsWith(`/${late}`)) return new Promise<Response>(resolve => {
        finish = () => {
          // Set-Cookie is applied before fetch resolves; never adopt this stale body.
          cookie = late === 'login' ? b : null
          resolve(late === 'login' ? Response.json(session) : new Response(null, { status: 204 }))
        }
      })
      if (url === '/api/v1/projects') return Response.json(cookie ? [{ id: cookie.user.id, name: `${cookie.user.id}-private`, research_topic: 'topic', project_type: 'sci' }] : [])
      return Response.json([])
    }))
    const firstTab = within(render(<FirstApp />).container)
    const secondTab = within(render(<SecondApp />).container)
    if (late === 'login') {
      fireEvent.change(await firstTab.findByLabelText('邮箱'), { target: { value: b.user.email } })
      fireEvent.change(firstTab.getByLabelText('密码'), { target: { value: 'valid-password' } })
      fireEvent.submit(firstTab.getByLabelText('密码').closest('form')!)
    } else {
      await firstTab.findByText(/a-private/)
      fireEvent.click(firstTab.getByRole('button', { name: '退出登录' }))
    }
    await waitFor(() => expect(finish).toBeTypeOf('function'))
    // Peer login completed first; both tabs restore its shared cookie.
    if (late === 'login') {
      fireEvent.change(await secondTab.findByLabelText('邮箱'), { target: { value: session.user.email } })
      fireEvent.change(secondTab.getByLabelText('密码'), { target: { value: 'valid-password' } })
      fireEvent.submit(secondTab.getByLabelText('密码').closest('form')!)
    } else {
      act(() => { cookie = session; channels[1].postMessage('session_changed') })
    }
    await firstTab.findByText(/a-private/)
    await secondTab.findByText(/a-private/)
    await act(async () => { finish() })
    for (const tab of [firstTab, secondTab]) {
      if (late === 'login') {
        await tab.findByText(b.user.email)
        await tab.findByText(/b-private/)
      } else {
        await tab.findByLabelText('邮箱')
        expect(tab.queryByText('项目中心')).toBeNull()
      }
      expect(tab.queryByText(/a-private/)).toBeNull()
      expect(tab.queryByText(session.user.email)).toBeNull()
    }
    expect(cookie).toEqual(late === 'login' ? b : null)
    await firstApi.apiFetch('/cookie-probe', { method: 'POST' })
    await secondApi.apiFetch('/cookie-probe', { method: 'POST' })
    expect(mutationTokens).toEqual(late === 'login' ? [b.csrf_token, b.csrf_token] : [null, null])
  })
}
it('keeps workspace hidden for anonymous visitors and shows labelled login', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 401 })))
  render(<App />)
  expect(await screen.findByLabelText('邮箱')).toBeTruthy()
  expect(screen.getByLabelText('密码')).toBeTruthy()
  expect(screen.queryByText('创建项目')).toBeNull()
})
it('offers retry when session restoration fails without pretending anonymous', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network')))
  render(<App />)
  expect(await screen.findByRole('button', { name: '重试' })).toBeTruthy()
  expect(screen.queryByLabelText('密码')).toBeNull()
})
it('restores session and retains workspace if logout fails, clearing hash only after revocation', async () => {
  const fetchMock = vi.fn(async (url: string) => url.endsWith('/me') ? Response.json(session) : url.endsWith('/logout') ? new Response('', { status: 503 }) : Response.json([]))
  vi.stubGlobal('fetch', fetchMock)
  window.location.hash = '#project-old'
  render(<App />)
  await screen.findByRole('button', { name: '退出登录' })
  await waitFor(() => expect(screen.getByText('还没有项目，请先创建一个项目。')).toBeTruthy())
  window.location.hash = '#project-old'
  fireEvent.click(screen.getByRole('button', { name: '退出登录' }))
  expect(await screen.findByRole('alert')).toBeTruthy()
  expect(screen.getByText(session.user.email)).toBeTruthy()
  expect(window.location.hash).toBe('#project-old')
  fetchMock.mockImplementation(async (url: string) => url.endsWith('/logout') ? new Response(null, { status: 204 }) : Response.json([]))
  fireEvent.click(screen.getByRole('button', { name: '退出登录' }))
  await waitFor(() => expect(screen.getByLabelText('邮箱')).toBeTruthy())
  expect(window.location.hash).toBe('')
})
it('blocks workspace during restore and retries a 503', async () => {
  let finish!: (response: Response) => void
  const mock = vi.fn().mockImplementationOnce(() => new Promise<Response>(resolve => { finish = resolve })).mockResolvedValue(Response.json(session))
  vi.stubGlobal('fetch', mock)
  render(<App />)
  expect(screen.getByRole('status').textContent).toContain('正在恢复')
  expect(screen.queryByText('项目中心')).toBeNull()
  finish(new Response(null, { status: 503 }))
  fireEvent.click(await screen.findByRole('button', { name: '重试' }))
  expect(await screen.findByRole('button', { name: '退出登录' })).toBeTruthy()
})
it('shows busy login, generic credentials error and Retry-After without storing credentials', async () => {
  let finish!: (response: Response) => void
  const mock = vi.fn(async (url: string) => url.endsWith('/me') ? new Response(null, { status: 401 }) : new Promise<Response>(resolve => { finish = resolve }))
  vi.stubGlobal('fetch', mock)
  render(<App />)
  fireEvent.change(await screen.findByLabelText('邮箱'), { target: { value: 'admin@paperassist.local' } })
  fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'valid-password-123' } })
  fireEvent.submit(screen.getByLabelText('密码').closest('form')!)
  expect((screen.getByRole('button', { name: '正在登录……' }) as HTMLButtonElement).disabled).toBe(true)
  finish(new Response(null, { status: 401 }))
  expect((await screen.findByRole('alert')).textContent).toBe('账号或密码错误。')
  fireEvent.submit(screen.getByLabelText('密码').closest('form')!)
  finish(new Response(null, { status: 429, headers: { 'Retry-After': '60' } }))
  await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('60 秒后'))
  expect(localStorage.length).toBe(0)
  expect(sessionStorage.length).toBe(0)
})
it('unmounts private workspace on expiry and mounts fresh state after a new login', async () => {
  let expire!: (response: Response) => void
  let lists = 0
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith('/me') || url.endsWith('/login')) return Response.json(session)
    if (url === '/api/v1/projects' && lists++ === 0) return new Promise<Response>(resolve => { expire = resolve })
    return Response.json([])
  }))
  render(<App />)
  await screen.findByText(session.user.email)
  await waitFor(() => expect(expire).toBeTypeOf('function'))
  window.location.hash = '#old-private-project'
  expire(new Response(null, { status: 401 }))
  expect(await screen.findByLabelText('邮箱')).toBeTruthy()
  expect(screen.queryByText('项目中心')).toBeNull()
  expect(window.location.hash).toBe('')
  fireEvent.change(screen.getByLabelText('邮箱'), { target: { value: session.user.email } })
  fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'valid-password-123' } })
  fireEvent.submit(screen.getByLabelText('密码').closest('form')!)
  expect(await screen.findByText('还没有项目，请先创建一个项目。')).toBeTruthy()
  expect(screen.queryByLabelText('密码')).toBeNull()
})
it('does not report expiration to a first anonymous visitor', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 401 })))
  render(<App />)
  await screen.findByLabelText('邮箱')
  expect(screen.queryByRole('alert')).toBeNull()
})
it('removes private workspace before restoring after another tab changes the cookie session', async () => {
  let receive!: (event: MessageEvent) => void
  class Channel {
    set onmessage(value: (event: MessageEvent) => void) { receive = value }
    postMessage() {}
    close() {}
  }
  vi.stubGlobal('BroadcastChannel', Channel)
  let restores = 0
  let restore!: (response: Response) => void
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith('/me')) {
      if (restores++ === 0) return Response.json(session)
      return new Promise<Response>(resolve => { restore = resolve })
    }
    return Response.json([])
  }))
  render(<App />)
  await screen.findByText('还没有项目，请先创建一个项目。')
  act(() => receive(new MessageEvent('message', { data: 'session_changed' })))
  await waitFor(() => expect(screen.queryByText('项目中心')).toBeNull())
  expect(screen.queryByText(session.user.email)).toBeNull()
  await waitFor(() => expect(restore).toBeTypeOf('function'))
  restore(new Response(null, { status: 401 }))
  expect(await screen.findByLabelText('邮箱')).toBeTruthy()
})
it('broadcasts only a non-secret session change after login and confirmed logout', async () => {
  const send = vi.fn()
  class Channel { onmessage = null; postMessage = send; close() {} }
  vi.stubGlobal('BroadcastChannel', Channel)
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith('/me')) return new Response(null, { status: 401 })
    if (url.endsWith('/login')) return Response.json(session)
    if (url.endsWith('/logout')) return new Response(null, { status: 204 })
    return Response.json([])
  }))
  render(<App />)
  fireEvent.change(await screen.findByLabelText('邮箱'), { target: { value: session.user.email } })
  fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'valid-password-123' } })
  fireEvent.submit(screen.getByLabelText('密码').closest('form')!)
  fireEvent.click(await screen.findByRole('button', { name: '退出登录' }))
  await screen.findByLabelText('密码')
  expect(send.mock.calls).toEqual([['session_changed'], ['session_changed']])
})
