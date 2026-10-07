import { afterEach, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import App from '../../app/App'
import { clearApiSession } from '../../shared/api/client'
import { setLocale } from '../../shared/i18n'
import ProjectDetails from '../../features/projects/ProjectDetails'

afterEach(() => { cleanup(); clearApiSession(); setLocale('zh-CN'); vi.useRealTimers(); vi.unstubAllGlobals(); window.location.hash = '' })
const session = { user: { id: 'a', email: 'a@example.com', role: 'user', ui_language: 'en' }, csrf_token: 'token' }
const project = { id: 'p', name: '中文研究名', research_topic: '原文主题', project_type: 'sci' as const,
  default_output_language: 'zh-CN' as const, file_count: 0, created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z' }
function empty(url: string) {
  const params = new URL(url, 'http://localhost').searchParams
  return Response.json({ items: [], total: 0, page: Number(params.get('page')), page_size: Number(params.get('page_size')) })
}

it('switches anonymous login without storing credentials or language in browser storage', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(null, { status: 401 })))
  render(<App />)
  await screen.findByLabelText('邮箱')
  fireEvent.change(screen.getByLabelText('界面语言'), { target: { value: 'en' } })
  expect(screen.getByLabelText('Email')).toBeTruthy()
  expect(document.documentElement.lang).toBe('en')
  expect(localStorage.length).toBe(0)
})

it('restores the user language and persists changes without reloading projects or losing drafts', async () => {
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/me')) return Response.json(session)
    if (url.endsWith('/preferences')) {
      expect(new Headers(init?.headers).get('X-CSRF-Token')).toBe('token')
      return Response.json({ ui_language: JSON.parse(String(init?.body)).ui_language })
    }
    return empty(url)
  })
  vi.stubGlobal('fetch', fetcher)
  render(<App />)
  await screen.findByRole('heading', { name: 'Projects' })
  fireEvent.click(screen.getByRole('button', { name: 'Create a research project' }))
  fireEvent.change(screen.getByLabelText('Project name'), { target: { value: '草稿' } })
  fireEvent.click(screen.getByRole('button', { name: 'Cancel creation' }))
  const before = fetcher.mock.calls.filter(([url]) => url.startsWith('/api/v1/projects')).length
  fireEvent.change(screen.getByLabelText('Interface language'), { target: { value: 'zh-CN' } })
  await screen.findByRole('heading', { name: '项目中心' })
  fireEvent.click(screen.getByRole('button', { name: '新建研究项目' }))
  expect((screen.getByLabelText('项目名称') as HTMLInputElement).value).toBe('草稿')
  expect(fetcher.mock.calls.filter(([url]) => url.startsWith('/api/v1/projects')).length).toBe(before)
})

it('keeps the saved language on failure and never displays untrusted server text', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => url.endsWith('/me') ? Response.json(session)
    : url.endsWith('/preferences') ? Response.json({ detail: { code: 'unknown', message: 'SECRET SQL' } }, { status: 500 }) : empty(url)))
  render(<App />)
  await screen.findByLabelText('Interface language')
  await screen.findByRole('heading', { name: 'Projects' })
  fireEvent.change(screen.getByLabelText('Interface language'), { target: { value: 'zh-CN' } })
  await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/language.*save|save.*language/i))
  expect(document.documentElement.lang).toBe('en')
  expect(document.body.textContent).not.toContain('SECRET SQL')
})

it('ignores a delayed preference response after logout', async () => {
  let finish!: () => void
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith('/me')) return Response.json(session)
    if (url.endsWith('/preferences')) return new Promise<Response>(resolve => { finish = () => resolve(Response.json({ ui_language: 'en' })) })
    if (url.endsWith('/logout')) return new Response(null, { status: 204 })
    return empty(url)
  }))
  render(<App />)
  await screen.findByRole('heading', { name: 'Projects' })
  fireEvent.change(screen.getByLabelText('Interface language'), { target: { value: 'zh-CN' } })
  await waitFor(() => expect(finish).toBeTypeOf('function'))
  fireEvent.click(screen.getByRole('button', { name: /^(Account|账号)$/ }))
  fireEvent.click(screen.getByRole('button', { name: 'Log out' }))
  await screen.findByLabelText('邮箱')
  await act(async () => finish())
  expect(document.documentElement.lang).toBe('zh-CN')
})

it('saves project output language separately and keeps original project content', async () => {
  const updated = vi.fn()
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    expect(url).toBe('/api/v1/projects/p/language')
    expect(JSON.parse(String(init?.body))).toEqual({ default_output_language: 'en' })
    return Response.json({ ...project, default_output_language: 'en' })
  }))
  render(<ProjectDetails project={project} onUpdated={updated} />)
  fireEvent.change(screen.getByLabelText('项目默认输出语言'), { target: { value: 'en' } })
  fireEvent.click(screen.getByRole('button', { name: '保存输出语言' }))
  await waitFor(() => expect(updated).toHaveBeenCalledWith(expect.objectContaining({ default_output_language: 'en' })))
  expect(screen.getByText('中文研究名')).toBeTruthy()
  expect(screen.getByText('原文主题')).toBeTruthy()
})

it('prevents metadata editing while an output language update is pending', async () => {
  let finish!: () => void
  vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(resolve => { finish = () => resolve(Response.json({ ...project, default_output_language: 'en' })) })))
  render(<ProjectDetails project={project} onUpdated={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('项目默认输出语言'), { target: { value: 'en' } })
  fireEvent.click(screen.getByRole('button', { name: '保存输出语言' }))
  expect((screen.getByRole('button', { name: '编辑项目信息' }) as HTMLButtonElement).disabled).toBe(true)
  await act(async () => finish())
  expect((screen.getByRole('button', { name: '编辑项目信息' }) as HTMLButtonElement).disabled).toBe(false)
})

it('times out preference writes, ignores their late body and allows retry', async () => {
  vi.useFakeTimers()
  let finish!: () => void
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith('/me')) return Response.json(session)
    if (url.endsWith('/preferences')) return new Promise<Response>(resolve => { finish = () => resolve(Response.json({ ui_language: 'zh-CN' })) })
    return empty(url)
  }))
  render(<App />)
  await act(async () => {})
  fireEvent.change(screen.getByLabelText('Interface language'), { target: { value: 'zh-CN' } })
  await act(async () => vi.advanceTimersByTime(15_000))
  expect(screen.getByRole('alert').textContent).toMatch(/timed out/)
  await act(async () => finish())
  expect(document.documentElement.lang).toBe('en')
  expect((screen.getByRole('button', { name: 'Retry saving language' }) as HTMLButtonElement).disabled).toBe(false)
})

it('keeps original project text when it happens to match a translation key', () => {
  setLocale('en')
  render(<ProjectDetails project={{ ...project, name: '项目中心', research_topic: '退出登录' }} onUpdated={vi.fn()} />)
  expect(screen.getByRole('heading', { name: '项目中心' })).toBeTruthy()
  expect(screen.getByText('退出登录')).toBeTruthy()
  expect(screen.getByLabelText('Default project output language')).toBeTruthy()
})
