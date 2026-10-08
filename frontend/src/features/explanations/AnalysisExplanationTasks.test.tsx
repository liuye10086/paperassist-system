import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import AnalysisExplanation from './AnalysisExplanation'

const props = { base: '/file', runId: 'run', revision: 1, figureId: 'figure', canGenerate: true, disabled: false, onBusyChange: vi.fn() }
const empty = { current_revision: 1, is_current: true, figure_id: 'figure', explanation: null, job: null, task: null }
const task = (status: string, extra = {}) => ({ id: 'task', status, revision: 3, reason_code: null, error_code: null, ...extra })
const json = (value: unknown) => Promise.resolve({ ok: true, status: 200, json: async () => value })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); vi.clearAllMocks() })

it('reads explanation policy independently of plot configuration', async () => {
  const fetch = vi.fn((url: string) => json(url === '/api/v1/ai/explanation-config' ? { configured: false, message_code: 'explanation_not_configured' } : empty))
  vi.stubGlobal('fetch', fetch)
  render(<AnalysisExplanation {...props} configuration={{ configured: true, model: 'plot-only', message: '' }} onReloadConfiguration={vi.fn()} />)
  await waitFor(() => expect(fetch.mock.calls.some(([url]) => url === '/api/v1/ai/explanation-config')).toBe(true))
  expect((screen.getByRole('button', { name: '使用 OpenAI 生成解释' }) as HTMLButtonElement).disabled).toBe(true)
})

it('polls a queued task without locking the whole workspace or making POST requests', async () => {
  vi.useFakeTimers()
  const fetch = vi.fn((url: string, _init?: RequestInit) => json(url.includes('explanation-config') ? { configured: true } : { ...empty, task: task('queued') }))
  vi.stubGlobal('fetch', fetch); render(<AnalysisExplanation {...props} />)
  await act(async () => {})
  expect(props.onBusyChange).toHaveBeenLastCalledWith(false)
  expect((screen.getByRole('button', { name: '使用 OpenAI 生成解释' }) as HTMLButtonElement).disabled).toBe(true)
  await act(async () => { vi.advanceTimersByTime(3000) })
  expect(fetch.mock.calls.filter(([url]) => url.endsWith('/explanation'))).toHaveLength(2)
  expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true)
})

it('resumes a budget wait by exact task revision without a new paid submission', async () => {
  const fetch = vi.fn((url: string, init?: RequestInit) => json(url.includes('explanation-config') ? { configured: true }
    : init?.method === 'POST' ? task('queued', { revision: 4 }) : { ...empty, task: task('waiting_confirmation', { reason_code: 'budget_exceeded', error_code: 'model_budget_missing' }) }))
  vi.stubGlobal('fetch', fetch); render(<AnalysisExplanation {...props} />)
  fireEvent.click(await screen.findByRole('button', { name: '预算已配置，继续生成解释' }))
  await waitFor(() => expect(fetch.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1))
  const [url, init] = fetch.mock.calls.find(([, init]) => init?.method === 'POST')!
  expect(url).toBe('/api/v1/tasks/task/retry')
  expect(JSON.parse(init!.body as string)).toEqual({ expected_revision: 3 })
})

it.each(['legacy', 'unified'])('never offers blind paid retry for %s submission uncertainty', async kind => {
  const state = kind === 'legacy' ? { ...empty, job: { id: 'legacy', status: 'uncertain' } }
    : { ...empty, task: task('waiting_confirmation', { reason_code: 'submission_unknown' }) }
  const fetch = vi.fn((url: string, _init?: RequestInit) => json(url.includes('explanation-config') ? { configured: true } : state))
  vi.stubGlobal('fetch', fetch); render(<AnalysisExplanation {...props} />)
  await screen.findByText('提交结果尚未核实，已停止再次调用。请联系管理员核对。')
  expect(screen.queryByRole('button', { name: /重试生成解释/ })).toBeNull()
  expect((screen.getByRole('button', { name: '使用 OpenAI 生成解释' }) as HTMLButtonElement).disabled).toBe(true)
  expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true)
})

it('keeps fetching the saved artifact after task success without submitting again', async () => {
  vi.useFakeTimers(); let reads = 0
  const saved = { id: 'exp', analysis_run_id: 'run', figure_id: 'figure', setup_revision: 1, sections: [], limitations: [], language: 'zh-CN', created_at: '', verification: { note: '已核验' } }
  const fetch = vi.fn((url: string, _init?: RequestInit) => json(url.includes('explanation-config') ? { configured: true }
    : url.endsWith('/report') ? { ready: true, report: null } : { ...empty, task: task('succeeded'), explanation: reads++ ? saved : null }))
  vi.stubGlobal('fetch', fetch); render(<AnalysisExplanation {...props} />); await act(async () => {})
  await act(async () => { vi.advanceTimersByTime(3000) })
  expect(screen.getByText('已核验')).toBeTruthy()
  expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true)
})

it('does not pretend an unavailable saved response can safely be resumed', async () => {
  const fetch = vi.fn((url: string, _init?: RequestInit) => json(url.includes('explanation-config') ? { configured: true }
    : { ...empty, task: task('failed', { error_code: 'model_response_not_found' }) }))
  vi.stubGlobal('fetch', fetch); render(<AnalysisExplanation {...props} />)
  await screen.findByText('已提交的解释无法恢复，请联系管理员核对。')
  expect(screen.queryByRole('button', { name: '继续解释任务' })).toBeNull()
  expect((screen.getByRole('button', { name: '使用 OpenAI 生成解释' }) as HTMLButtonElement).disabled).toBe(true)
  expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true)
})

it('lets a saved historical explanation win over an unreconciled running job', async () => {
  vi.useFakeTimers()
  const saved = { id: 'exp', analysis_run_id: 'run', figure_id: 'figure', setup_revision: 1, sections: [], limitations: [], language: 'zh-CN', created_at: '', verification: { note: '历史解释已保存' } }
  const fetch = vi.fn((url: string, _init?: RequestInit) => json(url.includes('explanation-config') ? { configured: false }
    : url.endsWith('/report') ? { ready: true, report: null } : { ...empty, explanation: saved, job: { status: 'running' } }))
  vi.stubGlobal('fetch', fetch); render(<AnalysisExplanation {...props} />); await act(async () => {})
  expect(screen.getByText('历史解释已保存')).toBeTruthy()
  await act(async () => { vi.advanceTimersByTime(9000) })
  expect(fetch.mock.calls.filter(([url]) => url.endsWith('/explanation'))).toHaveLength(1)
})
