import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import TaskDetail from './TaskDetail'
import { eventsFixture, taskFixture, usageFixture, workspaceFixture } from './taskFixtures'
import { setLocale } from '../../shared/i18n'
import { clearApiSession } from '../../shared/api/client'
import { watchProjectAccess } from '../../shared/api/projectAccess'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); setLocale('zh-CN') })
const props = { projectId: 'p1', taskId: 't1', onChanged: vi.fn() }
function api(workspace: unknown = workspaceFixture) {
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') return Response.json({ ...taskFixture, status: 'queued', display_status: 'queued', revision: 4 })
    if (url.includes('/model-usage')) return Response.json(usageFixture)
    if (url.includes('/events')) return Response.json(eventsFixture)
    return Response.json(workspace)
  }); vi.stubGlobal('fetch', fetch); return fetch
}
it('uses server resume permission with the exact wait, input version and one idempotency key', async () => {
  const fetch = api(); render(<TaskDetail {...props} />)
  const button = await screen.findByRole('button', { name: '预算或配置已调整，继续任务' })
  expect(screen.getByText('分析配置 v1')).toBeTruthy()
  expect(screen.getByText('继续此任务；尚未提交的模型调用会按原策略和预算执行，已有调用沿用已保存结果。')).toBeTruthy()
  fireEvent.click(button); fireEvent.click(button)
  await waitFor(() => expect(fetch.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1))
  const [url, init] = fetch.mock.calls.find(([, init]) => init?.method === 'POST')!
  expect(url).toBe('/api/v1/tasks/t1/resume')
  expect(new Headers(init!.headers).get('Idempotency-Key')).toBeTruthy()
  expect(JSON.parse(String(init!.body))).toEqual({ operation: 'resume', wait_id: 'w1', expected_task_revision: 3, input_version: taskFixture.input_version })
  expect(props.onChanged).toHaveBeenCalled()
})
it('pauses hidden-tab polling without aborting or remounting an ongoing resume operation', async () => {
  vi.useFakeTimers()
  const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
  let completePost!: (value: Response) => void
  const fetch = vi.fn((url: string, init?: RequestInit) => init?.method === 'POST' ? new Promise<Response>(resolve => { completePost = resolve })
    : Promise.resolve(Response.json(url.includes('/model-usage') ? usageFixture : url.includes('/events')
      ? { ...eventsFixture, items: [], next_cursor: 0 } : workspaceFixture)))
  vi.stubGlobal('fetch', fetch); render(<TaskDetail {...props} />)
  await act(async () => {})
  fireEvent.click(screen.getByRole('button', { name: '预算或配置已调整，继续任务' }))
  const posted = fetch.mock.calls.find(([, init]) => init?.method === 'POST')!
  const beforeHidden = fetch.mock.calls.length
  act(() => { visibility.mockReturnValue('hidden'); document.dispatchEvent(new Event('visibilitychange')) })
  await act(async () => { vi.advanceTimersByTime(10_000) })
  expect(fetch).toHaveBeenCalledTimes(beforeHidden)
  expect(posted[1]?.signal?.aborted).toBe(false)
  await act(async () => { visibility.mockReturnValue('visible'); document.dispatchEvent(new Event('visibilitychange')) })
  expect(fetch.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
  expect((screen.getByRole('button', { name: '预算或配置已调整，继续任务' }) as HTMLButtonElement).disabled).toBe(true)
  await act(async () => { completePost(Response.json({ ...taskFixture, revision: 4 })) })
  expect(props.onChanged).toHaveBeenCalled()
})
it('unknown submissions have no resume or paid retry form', async () => {
  api({ ...workspaceFixture, wait: { ...workspaceFixture.wait, kind: 'submission_unknown' }, allowed_actions: [] })
  render(<TaskDetail {...props} />)
  await screen.findByText('提交结果尚未核实，请联系管理员核对；不能重新发送模型请求。')
  expect(screen.queryByRole('button', { name: /继续任务|重试原任务/ })).toBeNull()
  expect(screen.queryByRole('textbox')).toBeNull()
})
it('displays exact historical artifacts while a temporary reload failure preserves them', async () => {
  const workspace = { ...workspaceFixture, source: { ...workspaceFixture.source, is_current: false }, allowed_actions: [], wait: null,
    task: { ...taskFixture, status: 'succeeded', display_status: 'succeeded', result_figure_id: 'fig1' },
    artifacts: { ...workspaceFixture.artifacts, figure: { title: '历史箱线图', caption: '保存的图注', download_url: '/api/v1/projects/p1/files/f1/analysis-runs/r1/figures/fig1/download' } } }
  let failure = false
  const fetch = vi.fn(async (url: string) => {
    if (url.includes('/model-usage')) return Response.json(usageFixture)
    if (url.includes('/events')) return Response.json(eventsFixture)
    if (failure) throw new TypeError('offline')
    return Response.json(workspace)
  }); vi.stubGlobal('fetch', fetch); render(<TaskDetail {...props} />)
  const link = await screen.findByRole('link', { name: '下载此任务的 PNG' })
  expect(link.getAttribute('href')).toContain('/r1/figures/fig1/download')
  failure = true; fireEvent.click(screen.getByRole('button', { name: '重新读取任务' }))
  await screen.findByText('任务详情读取失败，请重试。')
  expect(screen.getByText('历史箱线图')).toBeTruthy()
})
it('rejects task data for another project without showing its content', async () => {
  api({ ...workspaceFixture, task: { ...taskFixture, project_id: 'p2' }, source: { ...workspaceFixture.source, filename: '其他项目秘密.xlsx' } })
  render(<TaskDetail {...props} />)
  await screen.findByText('任务详情读取失败，请重试。')
  expect(screen.queryByText('其他项目秘密.xlsx')).toBeNull()
})
it('reads events incrementally and stops requests after unmount', async () => {
  vi.useFakeTimers()
  const fetch = vi.fn(async (url: string) => Response.json(url.includes('/model-usage') ? usageFixture
    : url.includes('/events') ? url.includes('after=0') ? eventsFixture : { ...eventsFixture, items: [], next_cursor: 1 } : workspaceFixture))
  vi.stubGlobal('fetch', fetch); const view = render(<TaskDetail {...props} />)
  await act(async () => {})
  await act(async () => { vi.advanceTimersByTime(5000) })
  expect(fetch.mock.calls.some(([url]) => url.includes('/events?after=1'))).toBe(true)
  view.unmount(); const count = fetch.mock.calls.length
  await act(async () => { vi.advanceTimersByTime(15000) })
  expect(fetch.mock.calls).toHaveLength(count)
})
it('reuses the same key after an unconfirmed response and a read of unchanged task state', async () => {
  let posts = 0
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      if (++posts === 1) throw new TypeError('connection lost')
      return Response.json({ ...taskFixture, status: 'queued', display_status: 'queued', revision: 4 })
    }
    return Response.json(url.includes('/model-usage') ? usageFixture : url.includes('/events')
      ? { ...eventsFixture, items: [], next_cursor: 0 } : workspaceFixture)
  }); vi.stubGlobal('fetch', fetch); render(<TaskDetail {...props} />)
  fireEvent.click(await screen.findByRole('button', { name: '预算或配置已调整，继续任务' }))
  await screen.findByText('恢复请求未确认，请先重新读取任务。')
  await waitFor(() => expect((screen.getByRole('button', { name: '预算或配置已调整，继续任务' }) as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(screen.getByRole('button', { name: '预算或配置已调整，继续任务' }))
  await waitFor(() => expect(posts).toBe(2))
  const keys = fetch.mock.calls.filter(([, init]) => init?.method === 'POST').map(([, init]) => new Headers(init!.headers).get('Idempotency-Key'))
  expect(keys[0]).toBeTruthy(); expect(keys[0]).toBe(keys[1])
})
it('shows unsupported waits without inventing a form or recovery action', async () => {
  api({ ...workspaceFixture, wait: { ...workspaceFixture.wait, kind: 'unsupported_input' }, allowed_actions: [] })
  render(<TaskDetail {...props} />)
  await screen.findByText('此任务需要的资料或确认暂未提供处理入口，请联系管理员。')
  expect(screen.queryByRole('textbox')).toBeNull(); expect(screen.queryByRole('button', { name: /继续.*任务|重试原任务/ })).toBeNull()
})
it('rejects an external artifact download URL', async () => {
  api({ ...workspaceFixture, task: { ...taskFixture, result_figure_id: 'fig1' },
    artifacts: { ...workspaceFixture.artifacts, figure: { title: 'unsafe', caption: '', download_url: 'https://other.example/private' } } })
  render(<TaskDetail {...props} />)
  await screen.findByText('任务详情读取失败，请重试。')
  expect(screen.queryByRole('link')).toBeNull()
})
it('renders actions and wait instructions in English without translating saved research', async () => {
  setLocale('en'); api(); render(<TaskDetail {...props} />)
  await screen.findByRole('button', { name: 'Budget or configuration updated — continue task' })
  expect(screen.getByText('实验.xlsx')).toBeTruthy()
  expect(screen.queryByText('任务正在等待预算或模型配置，请联系管理员调整后继续。')).toBeNull()
})
it('reuses the exact body and key after a hung resume request reaches its timeout', async () => {
  vi.useFakeTimers()
  let posts = 0
  const fetch = vi.fn((url: string, init?: RequestInit) => {
    if (init?.method === 'POST') return ++posts === 1 ? new Promise<Response>(() => {})
      : Promise.resolve(Response.json({ ...taskFixture, revision: 4 }))
    return Promise.resolve(Response.json(url.includes('/model-usage') ? usageFixture : url.includes('/events')
      ? { ...eventsFixture, items: [], next_cursor: 0 } : workspaceFixture))
  }); vi.stubGlobal('fetch', fetch); render(<TaskDetail {...props} />)
  await act(async () => {})
  fireEvent.click(screen.getByRole('button', { name: '预算或配置已调整，继续任务' }))
  await act(async () => { vi.advanceTimersByTime(15_001) })
  expect(screen.getByText('恢复请求未确认，请先重新读取任务。')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '预算或配置已调整，继续任务' }))
  await act(async () => {})
  const calls = fetch.mock.calls.filter(([, init]) => init?.method === 'POST')
  expect(calls).toHaveLength(2)
  expect(calls[0][1]?.signal?.aborted).toBe(true)
  expect(calls[0][1]?.body).toBe(calls[1][1]?.body)
  expect(new Headers(calls[0][1]?.headers).get('Idempotency-Key')).toBe(new Headers(calls[1][1]?.headers).get('Idempotency-Key'))
})
it('reloads conflicts and creates a new key only for the newly reviewed revision', async () => {
  let current = workspaceFixture
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      current = { ...workspaceFixture, task: { ...taskFixture, revision: 4 }, wait: { ...workspaceFixture.wait, id: 'w2', task_revision: 4 } }
      return Response.json({ detail: { code: 'task_revision_conflict' } }, { status: 409 })
    }
    return Response.json(url.includes('/model-usage') ? usageFixture : url.includes('/events')
      ? { ...eventsFixture, items: [], next_cursor: 0 } : current)
  }); vi.stubGlobal('fetch', fetch); render(<TaskDetail {...props} />)
  fireEvent.click(await screen.findByRole('button', { name: '预算或配置已调整，继续任务' }))
  await screen.findByText('任务状态已更新，请核对重新读取的内容后再操作。')
  await waitFor(() => expect((screen.getByRole('button', { name: '预算或配置已调整，继续任务' }) as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(screen.getByRole('button', { name: '预算或配置已调整，继续任务' }))
  await waitFor(() => expect(fetch.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(2))
  const calls = fetch.mock.calls.filter(([, init]) => init?.method === 'POST')
  expect(JSON.parse(String(calls[1][1]?.body))).toEqual({ operation: 'resume', wait_id: 'w2', expected_task_revision: 4, input_version: taskFixture.input_version })
  expect(new Headers(calls[0][1]?.headers).get('Idempotency-Key')).not.toBe(new Headers(calls[1][1]?.headers).get('Idempotency-Key'))
})
it('does not backfill a stale response when switching away from and back to a task', async () => {
  let completeOld!: (response: Response) => void
  let workspaceReads = 0
  const fetch = vi.fn((url: string) => {
    if (url.includes('/model-usage')) return Promise.resolve(Response.json(usageFixture))
    if (url.includes('/events')) return Promise.resolve(Response.json({ ...eventsFixture, task_id: url.includes('/t2/') ? 't2' : 't1', items: [], next_cursor: 0 }))
    if (++workspaceReads === 1) return new Promise<Response>(resolve => { completeOld = resolve })
    return Promise.resolve(Response.json({ ...workspaceFixture, task: { ...taskFixture, id: url.includes('/t2/') ? 't2' : 't1' },
      source: { ...workspaceFixture.source, filename: url.includes('/t2/') ? '第二任务.xlsx' : '当前配置.xlsx' } }))
  }); vi.stubGlobal('fetch', fetch)
  const view = render(<TaskDetail {...props} />)
  view.rerender(<TaskDetail {...props} taskId="t2" />)
  await screen.findByText('第二任务.xlsx')
  view.rerender(<TaskDetail {...props} />)
  await screen.findByText('当前配置.xlsx')
  await act(async () => { completeOld(Response.json({ ...workspaceFixture, source: { ...workspaceFixture.source, filename: '过期回包.xlsx' } })) })
  expect(screen.queryByText('过期回包.xlsx')).toBeNull()
  expect(screen.queryByText('第二任务.xlsx')).toBeNull()
  expect(screen.getByText('当前配置.xlsx')).toBeTruthy()
})
it('clears a missing task without invalidating its project', async () => {
  const unavailable = vi.fn(); const stop = watchProjectAccess('p1', unavailable)
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ detail: { code: 'task_not_found' } }, { status: 404 })))
  render(<TaskDetail {...props} />)
  await screen.findByText('任务不存在或无权访问，请选择其他任务。')
  expect(unavailable).not.toHaveBeenCalled(); stop()
})
it('clears private task detail, events and usage after session invalidation', async () => {
  api(); render(<TaskDetail {...props} />)
  await screen.findByText('实验.xlsx')
  await screen.findByText('test-model')
  act(() => clearApiSession())
  expect(screen.queryByText('实验.xlsx')).toBeNull()
  expect(screen.queryByText('test-model')).toBeNull()
  expect(screen.queryByRole('region', { name: '执行记录' })).toBeNull()
  expect(screen.queryByRole('button', { name: '预算或配置已调整，继续任务' })).toBeNull()
})
