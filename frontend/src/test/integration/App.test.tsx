import { afterEach, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../../app/App'
import { summaryFixture } from '../fixtures/summaryFixture'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.location.hash = '' })
const session = { user: { id: 'a', email: 'admin@paperassist.local', role: 'admin' }, csrf_token: 'csrf' }
function empty(url: string) {
  const parameters = new URL(url, 'http://localhost').searchParams
  return Response.json(url.startsWith('/api/v1/projects?')
    ? { items: [], total: 0, page: Number(parameters.get('page')), page_size: Number(parameters.get('page_size')) } : [])
}
it.each([
  ['change-password', false], ['reset-password', false],
  ['change-password', true], ['reset-password', true],
] as const)('removes both tab workspaces after %s cookie clearing (late=%s)', async (endpoint, late) => {
  vi.resetModules()
  const { default: FirstApp } = await import('../../app/App')
  const firstApi = await import('../../shared/api/client')
  vi.resetModules()
  const { default: SecondApp } = await import('../../app/App')
  const secondApi = await import('../../shared/api/client')
  const nextSession = { user: { id: 'b', email: 'b@example.com', role: 'user' }, csrf_token: 'b-csrf' }
  let cookie: typeof session | null = endpoint === 'change-password' ? session : null
  let finish!: () => void
  let passwordSignal: AbortSignal | null | undefined
  const tokens: (string | null)[] = []
  const channels: Channel[] = []
  class Channel {
    onmessage: ((event: MessageEvent) => void) | null = null
    constructor() { channels.push(this) }
    postMessage(data: string) { for (const peer of channels) if (peer !== this) peer.onmessage?.(new MessageEvent('message', { data })) }
    close() { channels.splice(channels.indexOf(this), 1) }
  }
  vi.stubGlobal('BroadcastChannel', Channel)
  const fetchMock = vi.fn(async (url: string, init?: RequestInit): Promise<Response> => {
    if (url.endsWith('/me')) return cookie ? Response.json(cookie) : new Response(null, { status: 401 })
    if (url.endsWith(`/${endpoint}`)) {
      passwordSignal = init?.signal
      return new Promise(resolve => { finish = () => { cookie = null; resolve(new Response(null, { status: 204 })) } })
    }
    if (url === '/cookie-probe') { tokens.push(new Headers(init?.headers).get('X-CSRF-Token')); return new Response(null, { status: 204 }) }
    if (url.startsWith('/api/v1/projects?')) {
      const parameters = new URL(url, 'http://localhost').searchParams
      const projects = cookie ? [{ id: cookie.user.id, name: `${cookie.user.id}-private`, research_topic: 'topic', project_type: 'sci',
        file_count: 0, created_at: '2026-09-30T10:00:00Z', updated_at: '2026-09-30T10:00:00Z' }] : []
      return Response.json({ items: projects, total: projects.length, page: Number(parameters.get('page')), page_size: Number(parameters.get('page_size')) })
    }
    return empty(url)
  })
  vi.stubGlobal('fetch', fetchMock)
  const first = within(render(<FirstApp />).container)
  const second = within(render(<SecondApp />).container)
  const changing = endpoint === 'change-password'
  if (changing) { await first.findByRole('button', { name: 'a-private' }); await second.findByRole('button', { name: 'a-private' }) }
  if (changing) fireEvent.click(await first.findByRole('button', { name: '账号' }))
  fireEvent.click(await first.findByRole('button', { name: changing ? '修改密码' : '忘记密码' }))
  fireEvent.change(first.getByLabelText(changing ? '当前密码' : '恢复码'), { target: { value: 'one-use-secret-123' } })
  for (const label of ['新密码', '确认新密码']) fireEvent.change(first.getByLabelText(label), { target: { value: 'updated-password-123' } })
  fireEvent.submit(first.getByLabelText('新密码').closest('form')!)
  await waitFor(() => expect(finish).toBeTypeOf('function'))
  if (late) {
    act(() => {
      // A third tab logged in; both mounted tabs receive the shared-cookie change.
      cookie = nextSession
      const source = new Channel(); source.postMessage('session_changed'); source.close()
    })
    await first.findByRole('button', { name: 'b-private' })
    await second.findByRole('button', { name: 'b-private' })
    expect(passwordSignal?.aborted).toBe(true)
    expect(first.queryByLabelText('新密码')).toBeNull()
  }
  window.location.hash = '#private-project'
  await act(async () => { finish() })
  for (const tab of [first, second]) {
    await tab.findByLabelText('邮箱')
    expect(tab.queryByText('项目中心')).toBeNull()
    expect(tab.queryAllByText(/a-private|b-private/)).toHaveLength(0)
    expect(tab.queryByText(nextSession.user.email)).toBeNull()
  }
  expect(window.location.hash).toBe('')
  expect(first.queryByText('密码已更新，请重新登录。') !== null).toBe(!late)
  if (late) expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('/me')).length).toBeGreaterThanOrEqual(5)
  await firstApi.apiFetch('/cookie-probe', { method: 'POST' })
  await secondApi.apiFetch('/cookie-probe', { method: 'POST' })
  expect(tokens).toEqual([null, null])
})
for (const late of ['login', 'logout'] as const) {
  it(`rebinds both tab workspaces to shared cookie after late ${late}`, async () => {
    vi.resetModules()
    const { default: FirstApp } = await import('../../app/App')
    const firstApi = await import('../../shared/api/client')
    vi.resetModules()
    const { default: SecondApp } = await import('../../app/App')
    const secondApi = await import('../../shared/api/client')
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
      if (url.startsWith('/api/v1/projects?')) {
        const parameters = new URL(url, 'http://localhost').searchParams
        const projects = cookie ? [{ id: cookie.user.id, name: `${cookie.user.id}-private`, research_topic: 'topic', project_type: 'sci',
          file_count: 0, created_at: '2026-09-30T10:00:00Z', updated_at: '2026-09-30T10:00:00Z' }] : []
        return Response.json({ items: projects, total: projects.length, page: Number(parameters.get('page')), page_size: Number(parameters.get('page_size')) })
      }
      return empty(url)
    }))
    const firstTab = within(render(<FirstApp />).container)
    const secondTab = within(render(<SecondApp />).container)
    if (late === 'login') {
      fireEvent.change(await firstTab.findByLabelText('邮箱'), { target: { value: b.user.email } })
      fireEvent.change(firstTab.getByLabelText('密码'), { target: { value: 'valid-password' } })
      fireEvent.submit(firstTab.getByLabelText('密码').closest('form')!)
    } else {
      await firstTab.findByRole('button', { name: 'a-private' })
      fireEvent.click(firstTab.getByRole('button', { name: '账号' }))
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
    await firstTab.findByRole('button', { name: 'a-private' })
    await secondTab.findByRole('button', { name: 'a-private' })
    await act(async () => { finish() })
    for (const tab of [firstTab, secondTab]) {
      if (late === 'login') {
        await tab.findByText(b.user.email)
        await tab.findByRole('button', { name: 'b-private' })
      } else {
        await tab.findByLabelText('邮箱')
        expect(tab.queryByText('项目中心')).toBeNull()
      }
      expect(tab.queryAllByText(/a-private/)).toHaveLength(0)
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
  const fetchMock = vi.fn(async (url: string) => url.endsWith('/me') ? Response.json(session) : url.endsWith('/logout') ? new Response('', { status: 503 }) : empty(url))
  vi.stubGlobal('fetch', fetchMock)
  window.location.hash = '#project-old'
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: '账号' }))
  await waitFor(() => expect(screen.getByText('还没有项目，请先创建一个项目。')).toBeTruthy())
  window.location.hash = '#project-old'
  fireEvent.click(screen.getByRole('button', { name: '退出登录' }))
  expect(await screen.findByRole('alert')).toBeTruthy()
  expect(screen.getByText(session.user.email)).toBeTruthy()
  expect(window.location.hash).toBe('#project-old')
  fetchMock.mockImplementation(async (url: string) => url.endsWith('/logout') ? new Response(null, { status: 204 }) : empty(url))
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
  expect(await screen.findByRole('button', { name: '账号' })).toBeTruthy()
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
    if (url.startsWith('/api/v1/projects?') && lists++ === 0) return new Promise<Response>(resolve => { expire = resolve })
    return empty(url)
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
    return empty(url)
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
    return empty(url)
  }))
  render(<App />)
  fireEvent.change(await screen.findByLabelText('邮箱'), { target: { value: session.user.email } })
  fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'valid-password-123' } })
  fireEvent.submit(screen.getByLabelText('密码').closest('form')!)
  fireEvent.click(await screen.findByRole('button', { name: '账号' }))
  fireEvent.click(screen.getByRole('button', { name: '退出登录' }))
  await screen.findByLabelText('密码')
  expect(send.mock.calls).toEqual([['session_changed'], ['session_changed']])
})

it('dismisses account actions when pressing non-focusable content outside the menu', async () => {
  const user = userEvent.setup()
  vi.stubGlobal('fetch', vi.fn(async (url: string) => url.endsWith('/me') ? Response.json(session) : empty(url)))
  render(<App />)
  const account = await screen.findByRole('button', { name: '账号' })
  await user.click(account)
  expect(account.getAttribute('aria-expanded')).toBe('true')
  fireEvent.pointerDown(screen.getByRole('heading', { name: '项目中心' }))
  expect(screen.queryByRole('button', { name: '退出登录' })).toBeNull()
  expect(account.getAttribute('aria-expanded')).toBe('false')
  await user.click(account)
  expect(screen.getByRole('button', { name: '修改密码' })).toBeTruthy()
  await user.click(account)
  expect(account.getAttribute('aria-expanded')).toBe('false')
})

it('dismisses account actions only after keyboard focus leaves the account controls', async () => {
  const user = userEvent.setup()
  vi.stubGlobal('fetch', vi.fn(async (url: string) => url.endsWith('/me') ? Response.json(session) : empty(url)))
  render(<App />)
  const account = await screen.findByRole('button', { name: '账号' })
  await user.click(account)
  await user.tab()
  expect(document.activeElement).toBe(screen.getByRole('button', { name: '修改密码' }))
  await user.tab()
  expect(document.activeElement).toBe(screen.getByRole('button', { name: '退出登录' }))
  await user.tab()
  expect(screen.queryByRole('button', { name: '退出登录' })).toBeNull()
  expect(account.getAttribute('aria-expanded')).toBe('false')
  expect(document.activeElement).not.toBe(account)
  expect(document.activeElement?.closest('.auth-account')).toBeNull()
})

it.each(['我的项目', '收起侧边栏'])('dismisses account actions when using the %s sidebar control', async name => {
  const user = userEvent.setup()
  vi.stubGlobal('fetch', vi.fn(async (url: string) => url.endsWith('/me') ? Response.json(session) : empty(url)))
  render(<App />)
  const account = await screen.findByRole('button', { name: '账号' })
  await user.click(account)
  await user.click(screen.getByRole('button', { name }))
  expect(screen.queryByRole('button', { name: '退出登录' })).toBeNull()
  expect(account.getAttribute('aria-expanded')).toBe('false')
  if (name === '我的项目') expect(screen.getByRole('button', { name }).getAttribute('aria-current')).toBe('page')
  else expect(screen.getByRole('button', { name: '展开侧边栏' })).toBeTruthy()
})

it('dismisses account actions while switching a project section', async () => {
  const user = userEvent.setup()
  const project = { id: 'account-project', name: '菜单交互项目', research_topic: '菜单交互', project_type: 'sci',
    file_count: 0, created_at: '2026-10-07T00:00:00Z', updated_at: '2026-10-07T00:00:00Z' }
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith('/me')) return Response.json(session)
    if (url.startsWith('/api/v1/projects?')) {
      const parameters = new URL(url, 'http://localhost').searchParams
      return Response.json({ items: [project], total: 1, page: Number(parameters.get('page')), page_size: Number(parameters.get('page_size')) })
    }
    if (url === `/api/v1/projects/${project.id}`) return Response.json(project)
    if (url.includes('/summary?')) return Response.json(summaryFixture(project.id))
    if (url.endsWith('/health')) return Response.json({ status: 'ok', service: 'paperassist-system' })
    if (url.endsWith('/config')) return Response.json({ max_upload_bytes: 10485760, preview_row_limit: 20 })
    return empty(url)
  }))
  render(<App />)
  await user.click(await screen.findByRole('button', { name: '打开项目 菜单交互项目' }))
  const files = await screen.findByRole('button', { name: '项目文件' })
  const account = screen.getByRole('button', { name: '账号' })
  await user.click(account)
  await user.click(files)
  expect(screen.queryByRole('button', { name: '退出登录' })).toBeNull()
  expect(account.getAttribute('aria-expanded')).toBe('false')
  expect(files.getAttribute('aria-current')).toBe('page')
})
