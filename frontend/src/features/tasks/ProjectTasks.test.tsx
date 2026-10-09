import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import ProjectTasks from './ProjectTasks'
import { legacyTaskFixture, legacyWorkspaceFixture, pageFixture } from './taskFixtures'
import { clearApiSession } from '../../shared/api/client'
import { setLocale } from '../../shared/i18n'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); setLocale('zh-CN') })
const props = { projectId: 'p1', active: true, selectedTaskId: '', onSelectTask: vi.fn() }
it('reads only unified project tasks and exposes readable source without internal identifiers', async () => {
  const fetch = vi.fn(async (_url: string) => Response.json(pageFixture)); vi.stubGlobal('fetch', fetch)
  render(<ProjectTasks {...props} />)
  await screen.findByText('实验.xlsx')
  expect(screen.getByText('分析配置 v1')).toBeTruthy()
  expect(fetch.mock.calls[0][0]).toBe('/api/v1/projects/p1/tasks?page=1&page_size=10')
  expect(screen.queryByText('t1')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '查看箱线图生成任务' }))
  expect(props.onSelectTask).toHaveBeenCalledWith('t1')
})
it('pauses hidden-tab reads, aborts an in-flight poll, and resumes with only one timer', async () => {
  vi.useFakeTimers()
  const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
  const fetch = vi.fn((url: string, init?: RequestInit) => fetch.mock.calls.length === 2
    ? new Promise<Response>(() => { void url; void init }) : Promise.resolve(Response.json(pageFixture)))
  vi.stubGlobal('fetch', fetch); render(<ProjectTasks {...props} />)
  await act(async () => {})
  await act(async () => { vi.advanceTimersByTime(5000) })
  expect(fetch).toHaveBeenCalledTimes(2)
  const signal = fetch.mock.calls[1][1]?.signal
  act(() => { visibility.mockReturnValue('hidden'); document.dispatchEvent(new Event('visibilitychange')) })
  expect(signal?.aborted).toBe(true)
  await act(async () => { vi.advanceTimersByTime(30_000) })
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(screen.getByText('实验.xlsx')).toBeTruthy()
  await act(async () => { visibility.mockReturnValue('visible'); document.dispatchEvent(new Event('visibilitychange')) })
  expect(fetch).toHaveBeenCalledTimes(3)
  await act(async () => { document.dispatchEvent(new Event('visibilitychange')); vi.advanceTimersByTime(5000) })
  expect(fetch).toHaveBeenCalledTimes(4)
})
it('filters on the server and resets pagination without creating tasks', async () => {
  const fetch = vi.fn(async (url: string, _init?: RequestInit) => {
    const q = new URL(url, 'http://local').searchParams
    return Response.json({ ...pageFixture, items: [], total: 0, page: Number(q.get('page')) })
  }); vi.stubGlobal('fetch', fetch); render(<ProjectTasks {...props} />)
  await screen.findByText('此筛选下没有任务。')
  fireEvent.change(screen.getByLabelText('任务状态'), { target: { value: 'failed' } })
  fireEvent.change(screen.getByLabelText('任务类型'), { target: { value: 'explanation' } })
  await waitFor(() => expect(fetch.mock.calls.some(([url]) => url.includes('status=failed&task_type=explanation'))).toBe(true))
  expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true)
})
it('does not fetch hidden tasks and clears private content on session change', async () => {
  const fetch = vi.fn(async () => Response.json(pageFixture)); vi.stubGlobal('fetch', fetch)
  const view = render(<ProjectTasks {...props} active={false} />)
  expect(fetch).not.toHaveBeenCalled()
  view.rerender(<ProjectTasks {...props} />); await screen.findByText('实验.xlsx')
  act(() => clearApiSession())
  expect(screen.queryByText('实验.xlsx')).toBeNull()
})
it.each(['zh-CN', 'en'] as const)('displays mixed historical tasks with unknown updated time in %s', async locale => {
  setLocale(locale)
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ ...pageFixture, total: 2,
    items: [...pageFixture.items, { task: legacyTaskFixture, source: { ...legacyWorkspaceFixture.source, filename: '历史来源.xlsx' } }] })))
  render(<ProjectTasks {...props} />)
  await screen.findByText('历史来源.xlsx')
  expect(screen.getByText(locale === 'en' ? 'Historical task' : '历史任务')).toBeTruthy()
  expect(screen.getByText(locale === 'en' ? 'Not recorded' : '未记录')).toBeTruthy()
  expect(screen.queryByText(legacyTaskFixture.id)).toBeNull()
  expect(document.body.textContent).not.toContain('1970')
  fireEvent.click(screen.getAllByRole('button', { name: locale === 'en' ? 'View Boxplot generation task' : '查看箱线图生成任务' })[1])
  expect(props.onSelectTask).toHaveBeenCalledWith(legacyTaskFixture.id)
})
