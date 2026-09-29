import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import WordReport from './WordReport'
const props = { base: '/file', runId: 'run', revision: 1, figureId: 'figure', explanationId: 'exp', canGenerate: true, disabled: false, onBusyChange: vi.fn() }
const report = { id: 'report', analysis_run_id: 'run', figure_id: 'figure', explanation_id: 'exp', setup_revision: 1, source_sha256: 'source', figure_sha256: 'image', created_at: 'today', filename: '分析报告.docx', size_bytes: 2048, sha256: 'docx', language: 'zh-CN', engine: { id: 'word-v1', python_docx: '1' }, input_sha256: 'input' }
const state = { current_revision: 1, is_current: true, ready: true, issues: [], report: null }
const json = (value: unknown) => Promise.resolve({ ok: true, json: async () => value })
const generate = () => screen.getByRole('button', { name: '生成 Word 报告' }) as HTMLButtonElement
const reload = () => screen.getByRole('button', { name: '重新读取报告' }) as HTMLButtonElement
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers() })
it('generates once with exact source IDs and restores a download on remount without an API key', async () => {
  let saved = false
  const fetch = vi.fn((_url: string, init?: RequestInit) => { if (init?.method === 'POST') saved = true; return json(saved ? { ...state, report } : state) })
  vi.stubGlobal('fetch', fetch); const view = render(<WordReport {...props} />)
  await waitFor(() => expect(generate().disabled).toBe(false)); fireEvent.click(generate()); fireEvent.click(generate())
  expect((await screen.findByRole('link', { name: '下载 Word 报告' })).getAttribute('href')).toBe('/file/analysis-runs/run/report/report/download')
  const posts = fetch.mock.calls.filter(call => call[1]?.method === 'POST'); expect(posts).toHaveLength(1)
  expect(JSON.parse(posts[0][1]!.body as string)).toEqual({ expected_revision: 1, figure_id: 'figure', explanation_id: 'exp' })
  view.unmount(); render(<WordReport {...props} />); await screen.findByRole('link', { name: '下载 Word 报告' })
  expect(fetch.mock.calls.filter(call => call[1]?.method === 'POST')).toHaveLength(1)
})
it.each([{ canGenerate: false }, { disabled: true }, { explanationId: '' }])('blocks unsafe generation %j', async extra => {
  vi.stubGlobal('fetch', vi.fn(() => json(state))); render(<WordReport {...props} {...extra} />)
  await waitFor(() => expect(screen.getByRole('region', { name: 'Word 分析报告' }).getAttribute('aria-busy')).toBe('false')); expect(generate().disabled).toBe(true)
})
it('preserves historical download but blocks stale generation', async () => {
  vi.stubGlobal('fetch', vi.fn(() => json({ ...state, is_current: false, current_revision: 2, report })))
  render(<WordReport {...props} />); await screen.findByRole('link', { name: '下载 Word 报告' }); expect(generate().disabled).toBe(true)
  expect(screen.getByText(/旧配置/)).toBeTruthy()
})
it.each(['GET', 'POST'])('recovers %s errors only through explicit reread', async method => {
  let fail = method === 'GET'
  const fetch = vi.fn((_url: string, init?: RequestInit) => fail || init?.method === 'POST' ? Promise.resolve({ ok: false, status: 500, json: async () => ({ detail: { message: '报告保存失败' } }) }) : json(state))
  vi.stubGlobal('fetch', fetch); render(<WordReport {...props} />)
  if (method === 'POST') { await waitFor(() => expect(generate().disabled).toBe(false)); fireEvent.click(generate()) }
  await screen.findByText('报告保存失败'); expect(generate().disabled).toBe(true)
  fail = false; fireEvent.click(reload()); await waitFor(() => expect(generate().disabled).toBe(false))
})
it.each(['GET', 'POST'])('%s timeout aborts and releases busy for manual recovery', async method => {
  vi.useFakeTimers(); let stuck = method === 'GET'; let signal: AbortSignal | undefined; const busy = vi.fn()
  const fetch = vi.fn((_url: string, init?: RequestInit) => { if (stuck || init?.method === 'POST') { signal = init?.signal as AbortSignal; return new Promise(() => {}) } return json(state) })
  vi.stubGlobal('fetch', fetch); render(<WordReport {...props} onBusyChange={busy} />); await act(async () => {})
  if (method === 'POST') fireEvent.click(generate())
  await act(async () => { vi.advanceTimersByTime(30_000) }); expect(screen.getByRole('alert').textContent).toMatch(/超时/)
  expect(signal?.aborted).toBe(true); expect(busy).toHaveBeenLastCalledWith(false); expect(generate().disabled).toBe(true)
  stuck = false; fireEvent.click(reload()); await act(async () => {}); expect(generate().disabled).toBe(false)
  expect(fetch.mock.calls.filter(call => call[1]?.method === 'POST')).toHaveLength(method === 'POST' ? 1 : 0)
})
it('aborts reads and ignores late results when explanation changes', async () => {
  let done!: (value: unknown) => void; let signal!: AbortSignal
  vi.stubGlobal('fetch', vi.fn((_url: string, init?: RequestInit) => new Promise(resolve => { done = resolve; signal = init?.signal as AbortSignal })))
  const view = render(<WordReport {...props} />); const firstDone = done; const firstSignal = signal
  view.rerender(<WordReport {...props} explanationId="new" />); expect(firstSignal.aborted).toBe(true)
  await act(async () => { firstDone({ ok: true, json: async () => ({ ...state, report }) }) }); expect(screen.queryByRole('link')).toBeNull()
  view.unmount(); expect(signal.aborted).toBe(true)
})
it('aborts in-flight generation on file switching and ignores late report', async () => {
  let finish!: (value: unknown) => void; let signal!: AbortSignal
  const fetch = vi.fn((_url: string, init?: RequestInit) => {
    if (init?.method === 'POST') { signal = init.signal as AbortSignal; return new Promise(resolve => { finish = resolve }) }
    return json(state)
  })
  vi.stubGlobal('fetch', fetch); const view = render(<WordReport {...props} />)
  await waitFor(() => expect(generate().disabled).toBe(false)); fireEvent.click(generate())
  view.rerender(<WordReport {...props} base="/new-file" runId="new-run" />); expect(signal.aborted).toBe(true)
  await act(async () => { finish({ ok: true, json: async () => ({ ...state, report }) }) })
  expect(screen.queryByRole('link', { name: '下载 Word 报告' })).toBeNull()
})
it('shows readiness issues and rejects mismatched report source IDs', async () => {
  vi.stubGlobal('fetch', vi.fn(() => json({ ...state, ready: false, issues: ['请完成来源核对'], report: { ...report, explanation_id: 'other' } })))
  render(<WordReport {...props} />); await screen.findByText('请完成来源核对')
  expect(generate().disabled).toBe(true); expect(screen.getByRole('link', { name: '下载 Word 报告' })).toBeTruthy()
})
