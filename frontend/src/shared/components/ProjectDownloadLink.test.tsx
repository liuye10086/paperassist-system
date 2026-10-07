import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import ProjectDownloadLink from './ProjectDownloadLink'
import { clearApiSession, setApiSession, onSessionExpired } from '../api/client'
import { watchProjectAccess } from '../api/projectAccess'

const href = '/api/v1/projects/p1/files/f1/download'
let create: ReturnType<typeof vi.fn>; let revoke: ReturnType<typeof vi.fn>; let clicks: { href: string; download: string }[]
beforeEach(() => {
  clicks = []; create = vi.fn(() => 'blob:download'); revoke = vi.fn()
  vi.stubGlobal('URL', class extends URL { static createObjectURL = create; static revokeObjectURL = revoke })
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { clicks.push({ href: this.href, download: this.download }) })
})
afterEach(() => { cleanup(); clearApiSession(); vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers() })
const link = () => screen.getByRole('link', { name: '下载原文件' })
const mount = (filename = '实验.xlsx') => render(<ProjectDownloadLink href={href} filename={filename}>下载原文件</ProjectDownloadLink>)
it('downloads exact successful bytes once and cleans the filename and object URL', async () => {
  let finish!: (response: Response) => void
  const fetch = vi.fn((_url: string, _init?: RequestInit) => new Promise<Response>(resolve => { finish = resolve })); vi.stubGlobal('fetch', fetch)
  mount('../目录\\实\u0000验.xlsx'); expect(link().getAttribute('href')).toBe(href)
  fireEvent.click(link()); fireEvent.click(link()); expect(fetch).toHaveBeenCalledTimes(1)
  await act(async () => { finish(new Response('original bytes')) })
  expect(await create.mock.calls[0][0].text()).toBe('original bytes')
  expect(clicks).toEqual([{ href: 'blob:download', download: '实验.xlsx' }]); expect(revoke).toHaveBeenCalledWith('blob:download')
  expect(fetch.mock.calls[0][1]).toMatchObject({ credentials: 'same-origin' })
})
it.each([401, 404, 410, 500])('does not download HTTP %s and allows retry for ordinary errors', async status => {
  setApiSession('owner'); const expired = vi.fn(); const off = onSessionExpired(expired)
  const unavailable = vi.fn(); const stop = watchProjectAccess('p1', unavailable)
  const fetch = vi.fn().mockResolvedValueOnce(Response.json({ detail: { code: status === 404 ? 'project_not_found' : 'file_missing', message: '下载失败' } }, { status })).mockResolvedValue(new Response('retry bytes'))
  vi.stubGlobal('fetch', fetch); mount(); fireEvent.click(link())
  await waitFor(() => expect(link().getAttribute('aria-busy')).toBe('false'))
  expect(create).not.toHaveBeenCalled()
  expect(expired).toHaveBeenCalledTimes(status === 401 ? 1 : 0)
  expect(unavailable).toHaveBeenCalledTimes(status === 404 ? 1 : 0)
  if (status >= 410) { expect(screen.getByRole('alert').textContent).toContain('原始文件已缺失'); fireEvent.click(link()); await waitFor(() => expect(create).toHaveBeenCalledTimes(1)) }
  stop(); off()
})
it.each(['unmount', 'href', 'session', 'scope'])('cancels late blob consumption after %s', async change => {
  const stop = watchProjectAccess('p1', vi.fn()); let finish!: (value: Blob) => void
  const response = new Response('private'); response.blob = () => new Promise(resolve => { finish = resolve })
  let signal!: AbortSignal; vi.stubGlobal('fetch', vi.fn((_url: string, init: RequestInit) => { signal = init.signal as AbortSignal; return Promise.resolve(response) }))
  const view = mount(); fireEvent.click(link()); await waitFor(() => expect(finish).toBeTypeOf('function'))
  if (change === 'unmount') view.unmount()
  if (change === 'href') view.rerender(<ProjectDownloadLink href="/api/v1/projects/p2/files/f2/download" filename="other.xlsx">下载原文件</ProjectDownloadLink>)
  if (change === 'session') setApiSession('new-account')
  if (change === 'scope') stop()
  await act(async () => { finish(new Blob(['private'])) })
  expect(create).not.toHaveBeenCalled(); if (change !== 'scope') expect(signal.aborted).toBe(true)
  stop()
})
it('times out after 30 seconds and retries without duplicating downloads', async () => {
  vi.useFakeTimers(); let signal!: AbortSignal
  const fetch = vi.fn((_url: string, init: RequestInit) => { signal = init.signal as AbortSignal; return new Promise<Response>(() => {}) })
  vi.stubGlobal('fetch', fetch); mount(); fireEvent.click(link())
  await act(async () => { vi.advanceTimersByTime(30_000) })
  expect(signal.aborted).toBe(true); expect(screen.getByRole('alert').textContent).toContain('超时')
  fireEvent.click(link()); expect(fetch).toHaveBeenCalledTimes(2)
})
it('preserves modified and middle clicks as original authenticated navigation', () => {
  const fetch = vi.fn(); vi.stubGlobal('fetch', fetch); mount()
  const canceled: boolean[] = []
  const preventNavigation = (event: Event) => { canceled.push(event.defaultPrevented); event.preventDefault() }
  document.addEventListener('click', preventNavigation)
  try {
    fireEvent.click(link(), { ctrlKey: true }); fireEvent.click(link(), { metaKey: true }); fireEvent.click(link(), { shiftKey: true }); fireEvent.click(link(), { altKey: true }); fireEvent.click(link(), { button: 1 })
  } finally { document.removeEventListener('click', preventNavigation) }
  expect(canceled).toEqual([false, false, false, false, false])
  expect(fetch).not.toHaveBeenCalled(); expect(link().getAttribute('href')).toBe(href)
})
it('does not start a download from a component belonging to a changed session', () => {
  const fetch = vi.fn(); vi.stubGlobal('fetch', fetch); mount(); setApiSession('other'); fireEvent.click(link())
  expect(fetch).not.toHaveBeenCalled()
})
