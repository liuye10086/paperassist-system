import { afterEach, expect, it, vi } from 'vitest'
import { apiFetch, setApiSession, clearApiSession, onSessionCookieChanged, onSessionExpired } from './api'
import { watchProjectAccess } from './projectAccess'
afterEach(() => { clearApiSession(); vi.unstubAllGlobals() })
it.each(['/api/v1/auth/change-password', '/api/v1/auth/reset-password'])('resynchronizes late cookie clearing from %s after abort or new session', async endpoint => {
  for (const reason of ['abort', 'session']) {
    let finish!: (response: Response) => void
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(resolve => { finish = resolve })))
    const changed = vi.fn()
    const stop = onSessionCookieChanged(changed)
    const controller = new AbortController()
    try {
      const pending = apiFetch(endpoint, { method: 'POST', signal: controller.signal })
      if (reason === 'abort') controller.abort()
      else setApiSession('new-session')
      finish(new Response(null, { status: 204 }))
      await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
      expect(changed).toHaveBeenCalledTimes(1)
    } finally { stop() }
  }
})
it.each(['/api/v1/auth/change-password', '/api/v1/auth/reset-password'])('rejects late %s body and reports possible cookie changes once', async endpoint => {
  let finish!: (body: unknown) => void
  const response = Response.json({ detail: { code: 'invalid_request' } }, { status: 422 })
  response.json = () => new Promise(resolve => { finish = resolve })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))
  const changed = vi.fn(); const stop = onSessionCookieChanged(changed)
  try {
    const returned = await apiFetch(endpoint, { method: 'POST' })
    const body = returned.json()
    setApiSession('peer')
    finish({ detail: { code: 'invalid_request' } })
    await expect(body).rejects.toMatchObject({ name: 'AbortError' })
    await expect(returned.json()).rejects.toMatchObject({ name: 'AbortError' })
    expect(changed).toHaveBeenCalledTimes(1)
  } finally { stop() }
})
const missingProject = () => Response.json({ detail: { code: 'project_not_found', message: '项目不可用' } }, { status: 404 })
it('notifies project loss once without consuming the caller error body', async () => {
  const unavailable = vi.fn(); const stop = watchProjectAccess('p1', unavailable)
  vi.stubGlobal('fetch', vi.fn().mockImplementation(() => missingProject()))
  try {
    const response = await apiFetch('/api/v1/projects/p1/files/f1/download')
    expect(unavailable).toHaveBeenCalledTimes(1)
    expect(response.bodyUsed).toBe(false)
    await expect(response.json()).rejects.toMatchObject({ name: 'AbortError' })
    await expect(apiFetch('/api/v1/projects/p1')).rejects.toMatchObject({ name: 'AbortError' })
    expect(unavailable).toHaveBeenCalledTimes(1)
  } finally { stop() }
})
it.each([
  [404, { detail: { code: 'file_not_found' } }],
  [410, { detail: { code: 'project_not_found' } }],
  [404, '<html>not found</html>'],
])('keeps ordinary resource errors available (%s, %j)', async (status, body) => {
  const unavailable = vi.fn(); const stop = watchProjectAccess('p1', unavailable)
  const response = typeof body === 'string' ? new Response(body, { status }) : Response.json(body, { status })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))
  try {
    const returned = await apiFetch('/api/v1/projects/p1/files/f1/download')
    expect(await returned.text()).toBe(typeof body === 'string' ? body : JSON.stringify(body))
    expect(unavailable).not.toHaveBeenCalled()
  } finally { stop() }
})
it('does not treat project_not_found from a non-project path as project loss', async () => {
  const unavailable = vi.fn(); const stop = watchProjectAccess('p1', unavailable)
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(missingProject()))
  try { await apiFetch('/api/v1/ai/config'); expect(unavailable).not.toHaveBeenCalled() } finally { stop() }
})
it.each(['stop', 'reopen', 'switch', 'session', 'abort'])('rejects delayed 404 inspection after %s', async change => {
  const oldUnavailable = vi.fn(); const currentUnavailable = vi.fn()
  const stop = watchProjectAccess('p1', oldUnavailable)
  let finish!: (body: unknown) => void
  const response = missingProject(); const clone = response.clone()
  clone.json = () => new Promise(resolve => { finish = resolve })
  response.clone = () => clone
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))
  const controller = new AbortController()
  const pending = apiFetch('/api/v1/projects/p1/files', { signal: controller.signal })
  await vi.waitFor(() => expect(finish).toBeTypeOf('function'))
  let currentStop = () => {}
  if (change === 'session') setApiSession('new-account')
  else if (change === 'abort') controller.abort()
  else { stop(); if (change === 'switch') { const stopB = watchProjectAccess('p2', vi.fn()); stopB() }; if (change !== 'stop') currentStop = watchProjectAccess('p1', currentUnavailable) }
  finish({ detail: { code: 'project_not_found' } })
  await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  expect(oldUnavailable).not.toHaveBeenCalled(); expect(currentUnavailable).not.toHaveBeenCalled()
  stop(); currentStop()
})
it.each(['stop', 'reopen', 'session', 'unavailable'])('rejects a saved successful body after %s', async change => {
  const stop = watchProjectAccess('p1', vi.fn())
  let finish!: (body: Blob) => void
  const response = new Response('private'); response.blob = () => new Promise(resolve => { finish = resolve })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))
  const returned = await apiFetch('/api/v1/projects/p1/files/f1/download')
  const pending = returned.blob(); let currentStop = () => {}
  if (change === 'session') setApiSession('new')
  else if (change === 'unavailable') { vi.stubGlobal('fetch', vi.fn().mockResolvedValue(missingProject())); await apiFetch('/api/v1/projects/p1') }
  else { stop(); if (change === 'reopen') currentStop = watchProjectAccess('p1', vi.fn()) }
  finish(new Blob(['private']))
  await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  stop(); currentStop()
})
it.each(['reopen', 'session'])('keeps cloned successful responses protected after %s', async change => {
  const stop = watchProjectAccess('p1', vi.fn())
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('private')))
  const returned = await apiFetch('/api/v1/projects/p1/files/f1/download')
  const clone = returned.clone()
  let stopNew = () => {}
  if (change === 'session') setApiSession('new')
  else { stop(); stopNew = watchProjectAccess('p1', vi.fn()) }
  await expect(clone.text()).rejects.toMatchObject({ name: 'AbortError' })
  expect(() => returned.clone()).toThrow()
  stop(); stopNew()
})
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
