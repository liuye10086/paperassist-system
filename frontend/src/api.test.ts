import { afterEach, expect, it, vi } from 'vitest'
import { apiFetch, setApiSession, clearApiSession, onSessionCookieChanged, onSessionExpired } from './api'
afterEach(() => { clearApiSession(); vi.unstubAllGlobals() })
it('resynchronizes a successful login cookie when its body cannot be read', async () => {
  const response = Response.json({})
  response.json = async () => { throw new Error('body connection lost') }
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))
  const changed = vi.fn()
  const unsubscribe = onSessionCookieChanged(changed)
  try {
    const returned = await apiFetch('/api/v1/auth/login', { method: 'POST' })
    await expect(returned.json()).rejects.toThrow('body connection lost')
    expect(changed).toHaveBeenCalledTimes(1)
  } finally { unsubscribe() }
})
it('reports obsolete auth bodies once while rejecting their contents', async () => {
  let finish!: (value: object) => void
  const response = new Response('{}')
  response.json = () => new Promise(resolve => { finish = resolve })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))
  const changed = vi.fn()
  const unsubscribe = onSessionCookieChanged(changed)
  try {
    const returned = await apiFetch('/api/v1/auth/login', { method: 'POST' })
    const body = returned.json()
    setApiSession('peer')
    finish({ csrf_token: 'obsolete' })
    await expect(body).rejects.toMatchObject({ name: 'AbortError' })
    await expect(returned.json()).rejects.toMatchObject({ name: 'AbortError' })
    expect(changed).toHaveBeenCalledTimes(1)
  } finally { unsubscribe() }
})
it('resynchronizes even a stale failed auth response without treating it as expiry', async () => {
  let finish!: (response: Response) => void
  vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(resolve => { finish = resolve })))
  const changed = vi.fn()
  const unsubscribe = onSessionCookieChanged(changed)
  try {
    const request = apiFetch('/api/v1/auth/logout', { method: 'POST' })
    setApiSession('peer')
    finish(new Response(null, { status: 401 }))
    await expect(request).rejects.toMatchObject({ name: 'AbortError' })
    expect(changed).toHaveBeenCalledTimes(1)
  } finally { unsubscribe() }
})
it('adds same-origin cookies and in-memory CSRF only to mutations', async () => {
  setApiSession('secret')
  const mock = vi.fn().mockResolvedValue(new Response('ok'))
  vi.stubGlobal('fetch', mock)
  await apiFetch('/api/v1/projects', { method: 'POST', headers: { 'Content-Type': 'application/json' } })
  const init = mock.mock.calls[0][1]
  expect(init.credentials).toBe('same-origin')
  expect(init.headers.get('X-CSRF-Token')).toBe('secret')
  expect(init.headers.get('X-PaperAssist-Client')).toBe('web')
  await apiFetch('/api/v1/projects')
  expect(mock.mock.calls[1][1].headers.has('X-CSRF-Token')).toBe(false)
})
it('rejects stale responses without expiring a newer session', async () => {
  let finish!: (response: Response) => void
  vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(resolve => { finish = resolve })))
  const expired = vi.fn()
  const unsubscribe = onSessionExpired(expired)
  setApiSession('old')
  const pending = apiFetch('/api/v1/projects')
  setApiSession('new')
  finish(new Response('', { status: 401 }))
  await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  expect(expired).not.toHaveBeenCalled()
  unsubscribe()
})
it('rejects bodies that arrive after session changes', async () => {
  let finish!: (value: object) => void
  const response = new Response('{}')
  response.json = () => new Promise(resolve => { finish = resolve })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))
  setApiSession('old')
  const returned = await apiFetch('/api/v1/projects')
  const pending = returned.json()
  clearApiSession()
  finish({ private: true })
  await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
})
it('ignores aborted response even if transport completes instead of rejecting', async () => {
  let finish!: (response: Response) => void
  vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(resolve => { finish = resolve })))
  const listener = vi.fn()
  const unsubscribe = onSessionExpired(listener)
  const controller = new AbortController()
  const pending = apiFetch('/api/v1/auth/me', { signal: controller.signal })
  controller.abort()
  finish(new Response(null, { status: 401 }))
  await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  expect(listener).not.toHaveBeenCalled()
  unsubscribe()
})
