import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import BoxplotFigure from './BoxplotFigure'
import { setLocale } from '../../shared/i18n'

const props = { base: '/file', runId: 'run', revision: 1, canGenerate: true, disabled: false, onBusyChange: vi.fn() }
const empty = { current_revision: 1, is_current: true, figure: null, job: null, task: null }
const task = (status: string, extra = {}) => ({ id: 'task', status, revision: 3, reason_code: null, error_code: null, ...extra })
const json = (value: unknown) => Promise.resolve({ ok: true, status: 200, json: async () => value })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); vi.clearAllMocks(); setLocale('zh-CN') })

it('requires independent plot policy configuration', async () => {
  const fetch = vi.fn((url: string) => json(url === '/api/v1/ai/plot-config' ? { configured: false, message_code: 'plot_not_configured' }
    : url === '/api/v1/ai/config' ? { configured: true } : empty))
  vi.stubGlobal('fetch', fetch); render(<BoxplotFigure {...props} />)
  await waitFor(() => expect(fetch.mock.calls.some(([url]) => url === '/api/v1/ai/plot-config')).toBe(true))
  expect((screen.getByRole('button', { name: '使用 OpenAI 生成箱线图' }) as HTMLButtonElement).disabled).toBe(true)
})

it('polls queued tasks without locking workspace or submitting new paid work', async () => {
  vi.useFakeTimers()
  const fetch = vi.fn((url: string, _init?: RequestInit) => json(url.includes('plot-config') ? { configured: true } : { ...empty, task: task('queued') }))
  vi.stubGlobal('fetch', fetch); render(<BoxplotFigure {...props} />); await act(async () => {})
  expect(props.onBusyChange).toHaveBeenLastCalledWith(false)
  await act(async () => { vi.advanceTimersByTime(3000) })
  expect(fetch.mock.calls.filter(([url]) => url.endsWith('/boxplot'))).toHaveLength(2)
  expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true)
})

it('resumes budget wait using the original task and revision', async () => {
  const fetch = vi.fn((url: string, init?: RequestInit) => json(url.includes('plot-config') ? { configured: true }
    : init?.method === 'POST' ? task('queued', { revision: 4 }) : { ...empty, task: task('waiting_confirmation', { reason_code: 'budget_exceeded' }) }))
  vi.stubGlobal('fetch', fetch); render(<BoxplotFigure {...props} />)
  fireEvent.click(await screen.findByRole('button', { name: '预算已配置，继续生成图表' }))
  await waitFor(() => expect(fetch.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1))
  const [url, init] = fetch.mock.calls.find(([, init]) => init?.method === 'POST')!
  expect(url).toBe('/api/v1/tasks/task/retry')
  expect(JSON.parse(init!.body as string)).toEqual({ expected_revision: 3 })
})

it.each(['legacy', 'unified'])('blocks blind paid retry for %s unknown submission', async kind => {
  const state = kind === 'legacy' ? { ...empty, job: { status: 'uncertain' } }
    : { ...empty, task: task('waiting_confirmation', { reason_code: 'submission_unknown' }) }
  const fetch = vi.fn((url: string, _init?: RequestInit) => json(url.includes('plot-config') ? { configured: true } : state))
  vi.stubGlobal('fetch', fetch); render(<BoxplotFigure {...props} />)
  await screen.findByText('提交结果尚未核实，已停止再次调用。请联系管理员核对。')
  expect(screen.queryByRole('button', { name: /重试生成/ })).toBeNull()
  expect((screen.getByRole('button', { name: '使用 OpenAI 生成箱线图' }) as HTMLButtonElement).disabled).toBe(true)
  expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true)
})

it('requires explicit paid regeneration after remote container expiration', async () => {
  const fetch = vi.fn((url: string, init?: RequestInit) => json(url.includes('plot-config') ? { configured: true }
    : init?.method === 'POST' ? { ...empty, task: task('queued') } : { ...empty, task: task('failed', { error_code: 'plot_container_expired' }) }))
  vi.stubGlobal('fetch', fetch); render(<BoxplotFigure {...props} />)
  await screen.findByText('远端绘图文件已过期，无法继续下载。再次生成可能产生额外费用。')
  expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: '重试生成（再次调用 API）' }))
  await waitFor(() => expect(fetch.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1))
  const [url, init] = fetch.mock.calls.find(([, init]) => init?.method === 'POST')!
  expect(url).toBe('/file/analysis-runs/run/boxplot')
  expect(JSON.parse(init!.body as string)).toEqual({ expected_revision: 1, retry: true })
})

it('uses explicit new paid generation after the frozen input allowance fails', async () => {
  const fetch = vi.fn((url: string, init?: RequestInit) => json(url.includes('plot-config') ? { configured: true }
    : init?.method === 'POST' ? { ...empty, task: task('queued', { id: 'new-task' }) }
      : { ...empty, task: task('failed', { error_code: 'plot_input_limit' }) }))
  vi.stubGlobal('fetch', fetch); render(<BoxplotFigure {...props} />)
  const button = await screen.findByRole('button', { name: '重试生成（再次调用 API）' })
  expect(screen.queryByRole('button', { name: '继续绘图任务' })).toBeNull()
  expect(screen.getByText(/再次调用 API 可能产生额外费用/)).toBeTruthy()
  expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true)
  fireEvent.click(button)
  await waitFor(() => expect(fetch.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1))
  const [url, init] = fetch.mock.calls.find(([, init]) => init?.method === 'POST')!
  expect(url).toBe('/file/analysis-runs/run/boxplot')
  expect(JSON.parse(init!.body as string)).toEqual({ expected_revision: 1, retry: true })
})

it('keeps polling after success until the saved PNG is visible, without another POST', async () => {
  vi.useFakeTimers(); let reads = 0
  const figure = { id: 'figure', analysis_run_id: 'run', setup_revision: 1, title: '历史图', caption: '', verification: { note: '图片已保存' } }
  const fetch = vi.fn((url: string, _init?: RequestInit) => json(url.endsWith('config') ? { configured: false }
    : url.endsWith('/explanation') ? { explanation: null, job: null }
      : { ...empty, task: task('succeeded'), figure: reads++ ? figure : null, job: { status: 'running' } }))
  vi.stubGlobal('fetch', fetch); render(<BoxplotFigure {...props} />); await act(async () => {})
  await act(async () => { vi.advanceTimersByTime(3000) })
  expect(screen.getByAltText('历史图')).toBeTruthy()
  await act(async () => { vi.advanceTimersByTime(9000) })
  expect(fetch.mock.calls.filter(([url]) => url.endsWith('/boxplot'))).toHaveLength(2)
  expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true)
})

it('does not offer paid replacement for a missing original response', async () => {
  const fetch = vi.fn((url: string) => json(url.endsWith('config') ? { configured: true }
    : { ...empty, task: task('failed', { error_code: 'model_response_not_found' }) }))
  vi.stubGlobal('fetch', fetch); render(<BoxplotFigure {...props} />)
  await screen.findByText('已提交的绘图响应无法恢复，请联系管理员核对。')
  expect(screen.queryByRole('button', { name: /继续绘图|重试生成/ })).toBeNull()
  expect((screen.getByRole('button', { name: '使用 OpenAI 生成箱线图' }) as HTMLButtonElement).disabled).toBe(true)
})

it('translates budget recovery and container expiration without showing raw errors', async () => {
  setLocale('en')
  const fetch = vi.fn((url: string) => json(url.endsWith('config') ? { configured: true }
    : { ...empty, task: task('waiting_confirmation', { reason_code: 'budget_exceeded', error_code: 'model_budget_missing' }) }))
  vi.stubGlobal('fetch', fetch); render(<BoxplotFigure {...props} />)
  expect(await screen.findByRole('button', { name: 'Budget configured — continue plot' })).toBeTruthy()
  expect(screen.queryByText('预算已配置，继续生成图表')).toBeNull()
})
