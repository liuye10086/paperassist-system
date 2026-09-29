import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import AnalysisExplanation from './AnalysisExplanation'

const explanation = { id: 'exp', analysis_run_id: 'run', figure_id: 'figure', setup_revision: 1, figure_sha256: 'image', source_sha256: 'source', language: 'zh-CN', created_at: 'today', sections: ['purpose', 'data', 'methods', 'results', 'interpretation', 'paper_text'].map(key => ({ key, title: key, text: `正文 ${key} <script>unsafe</script>`, evidence: [{ key: 'count', label: '有效样本数', value: '3' }] })), limitations: ['未进行显著性检验'], engine: { id: 'explanation-v1', provider: 'openai', model: 'model' }, verification: { status: 'matched', note: '证据校验通过' }, provenance: { analysis_run_id: 'run', prompt_version: 'v1' } }
const empty = { current_revision: 1, is_current: true, figure_id: 'figure', explanation: null, job: null }
const job = (status: string) => ({ id: 'job', status, message: '解释任务处理中', response_id: null, created_at: '' })
const props = { base: '/file', runId: 'run', revision: 1, figureId: 'figure', canGenerate: true, disabled: false, onBusyChange: vi.fn() }
const reportState = { current_revision: 1, is_current: true, ready: true, issues: [], report: null }
const json = (value: unknown) => Promise.resolve({ ok: true, json: async () => value })
function api(state: unknown = empty, configured = true) { return vi.fn((url: string, _init?: RequestInit) => json(url.endsWith('/report') ? reportState : url === '/api/v1/ai/config' ? { configured, model: 'model', message: '未配置 API' } : state)) }
const button = () => screen.getByRole('button', { name: '使用 OpenAI 生成解释' }) as HTMLButtonElement
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers() })

it('generates six sections with evidence and safely renders AI draft and provenance', async () => {
  const fetch = api(); vi.stubGlobal('fetch', fetch); render(<AnalysisExplanation {...props} />)
  await waitFor(() => expect(button().disabled).toBe(false))
  fetch.mockImplementation((url: string, init?: RequestInit) => json(url.endsWith('/report') ? reportState : init?.method === 'POST' ? { ...empty, explanation } : url === '/api/v1/ai/config' ? { configured: true } : empty))
  fireEvent.click(button()); fireEvent.click(button())
  expect(await screen.findByText(explanation.sections[0].text)).toBeTruthy()
  for (const section of explanation.sections) expect(screen.getByRole('heading', { name: section.title })).toBeTruthy()
  expect(screen.getAllByText('有效样本数：3')).toHaveLength(6)
  expect(screen.getByText(/AI 草稿/)).toBeTruthy(); expect(screen.getByText('未进行显著性检验')).toBeTruthy()
  expect(screen.getByText(/图片 SHA256：image/)).toBeTruthy(); expect(document.querySelector('script')).toBeNull()
  const posts = fetch.mock.calls.filter(call => call[1]?.method === 'POST')
  expect(posts).toHaveLength(1); expect(JSON.parse(posts[0][1]!.body as string)).toEqual({ expected_revision: 1, figure_id: 'figure' })
})
it('restores running work and polls without POST', async () => {
  vi.useFakeTimers(); let reads = 0
  const fetch = vi.fn((url: string, _init?: RequestInit) => json(url.endsWith('/report') ? reportState : url === '/api/v1/ai/config' ? { configured: true } : reads++ === 0 ? { ...empty, job: job('running') } : { ...empty, explanation }))
  vi.stubGlobal('fetch', fetch); render(<AnalysisExplanation {...props} />); await act(async () => {})
  expect(props.onBusyChange).toHaveBeenLastCalledWith(true)
  await act(async () => { vi.advanceTimersByTime(3000) })
  expect(screen.getByText(explanation.sections[0].text)).toBeTruthy()
  expect(fetch.mock.calls.every(call => !call[1]?.method)).toBe(true)
})
it.each(['failed', 'uncertain'])('only explicit %s retry adds retry and warns about cost', async status => {
  const fetch = api({ ...empty, job: job(status) }); vi.stubGlobal('fetch', fetch); render(<AnalysisExplanation {...props} />)
  const retry = await screen.findByRole('button', { name: '重试生成解释（再次调用 API）' })
  await waitFor(() => expect((retry as HTMLButtonElement).disabled).toBe(false))
  expect(screen.getByText(/额外费用/)).toBeTruthy(); expect(fetch.mock.calls.every(call => !call[1]?.method)).toBe(true)
  fireEvent.click(retry)
  expect(JSON.parse(fetch.mock.calls.find(call => call[1]?.method === 'POST')![1]!.body as string)).toEqual({ expected_revision: 1, figure_id: 'figure', retry: true })
})
it('missing key keeps cached explanation readable and configuration reload available', async () => {
  const fetch = api({ ...empty, explanation }, false); vi.stubGlobal('fetch', fetch); render(<AnalysisExplanation {...props} />)
  expect(await screen.findByText(explanation.sections[0].text)).toBeTruthy(); expect(button().disabled).toBe(true)
  fetch.mockImplementation((url: string) => json(url.endsWith('/report') ? reportState : url === '/api/v1/ai/config' ? { configured: true } : { ...empty, explanation }))
  fireEvent.click(screen.getByRole('button', { name: '重新读取解释 OpenAI 配置' }))
  await waitFor(() => expect(button().disabled).toBe(false))
})
it.each([{ is_current: false }, { current_revision: 2 }, { figure_id: 'other' }])('blocks mismatched state while preserving cached draft: %j', async mismatch => {
  vi.stubGlobal('fetch', api({ ...empty, explanation, ...mismatch })); render(<AnalysisExplanation {...props} />)
  await screen.findByText(explanation.sections[0].text); expect(button().disabled).toBe(true)
  expect(screen.getByText(/以下解释对应旧配置或旧图表/)).toBeTruthy()
})
it('unsaved fields block generation', async () => {
  vi.stubGlobal('fetch', api()); render(<AnalysisExplanation {...props} canGenerate={false} />)
  await screen.findByRole('button', { name: '重新读取解释' }); expect(button().disabled).toBe(true)
})
it('network failure preserves draft and manual reread clears error without POST', async () => {
  const fetch = api({ ...empty, explanation }); vi.stubGlobal('fetch', fetch); render(<AnalysisExplanation {...props} />)
  await screen.findByText(explanation.sections[0].text); fetch.mockRejectedValueOnce(new TypeError('offline'))
  fireEvent.click(screen.getByRole('button', { name: '重新读取解释' })); await screen.findByRole('alert')
  expect(screen.getByText(explanation.sections[0].text)).toBeTruthy(); expect(button().disabled).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: '重新读取解释' })); await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
  expect(fetch.mock.calls.every(call => !call[1]?.method)).toBe(true)
})
it('request timeout stops polling and enables manual reread', async () => {
  vi.useFakeTimers(); const fetch = vi.fn((url: string) => url === '/api/v1/ai/config' ? json({ configured: true }) : new Promise(() => {}))
  vi.stubGlobal('fetch', fetch); render(<AnalysisExplanation {...props} />); await act(async () => {})
  await act(async () => { vi.advanceTimersByTime(30_000) })
  expect(screen.getByRole('alert').textContent).toMatch(/超时/)
  expect((screen.getByRole('button', { name: '重新读取解释' }) as HTMLButtonElement).disabled).toBe(false)
  await act(async () => { vi.advanceTimersByTime(9000) }); expect(fetch).toHaveBeenCalledTimes(2)
})
it('ignores late reads after figure switching and aborts reads on unmount', async () => {
  let resolve!: (value: unknown) => void; let oldSignal: AbortSignal | undefined
  const fetch = vi.fn((url: string, init?: RequestInit) => url.includes('/run/explanation') ? new Promise(done => { resolve = done; oldSignal = init?.signal as AbortSignal }) : url.includes('/new/explanation') ? new Promise(() => {}) : json({ configured: true }))
  vi.stubGlobal('fetch', fetch); const view = render(<AnalysisExplanation {...props} />)
  view.rerender(<AnalysisExplanation {...props} runId="new" figureId="new" />)
  expect(oldSignal?.aborted).toBe(true)
  await act(async () => { resolve({ ok: true, json: async () => ({ ...empty, explanation }) }) })
  expect(screen.queryByText(explanation.sections[0].text)).toBeNull()
  const latest = fetch.mock.calls.findLast(call => call[0].includes('/new/explanation'))![1]!.signal
  view.unmount(); expect(latest?.aborted).toBe(true)
})


it('POST timeout requires reread before any further paid call', async () => {
  vi.useFakeTimers(); let posted = false
  const fetch = vi.fn((url: string, init?: RequestInit) => {
    if (url.endsWith('/report')) return json(reportState)
    if (url === '/api/v1/ai/config') return json({ configured: true })
    if (init?.method === 'POST') { posted = true; return new Promise(() => {}) }
    return json(posted ? { ...empty, job: job('uncertain') } : empty)
  })
  vi.stubGlobal('fetch', fetch); render(<AnalysisExplanation {...props} />); await act(async () => {})
  fireEvent.click(button()); await act(async () => { vi.advanceTimersByTime(30_000) })
  expect(screen.getByRole('alert').textContent).toMatch(/先重新读取解释/); expect(button().disabled).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: '重新读取解释' })); await act(async () => {})
  expect((screen.getByRole('button', { name: '重试生成解释（再次调用 API）' }) as HTMLButtonElement).disabled).toBe(false)
  expect(fetch.mock.calls.filter(call => call[1]?.method === 'POST')).toHaveLength(1)
})
it('polls a newly submitted task and releases busy state after completion', async () => {
  vi.useFakeTimers(); let posted = false; let polls = 0; const onBusyChange = vi.fn()
  const fetch = vi.fn((url: string, init?: RequestInit) => {
    if (url.endsWith('/report')) return json(reportState)
    if (url === '/api/v1/ai/config') return json({ configured: true })
    if (init?.method === 'POST') { posted = true; return json({ ...empty, job: job('submitting') }) }
    return json(!posted ? empty : polls++ === 0 ? { ...empty, job: job('running') } : { ...empty, explanation })
  })
  vi.stubGlobal('fetch', fetch); render(<AnalysisExplanation {...props} onBusyChange={onBusyChange} />); await act(async () => {})
  fireEvent.click(button()); await act(async () => {}); expect(onBusyChange).toHaveBeenLastCalledWith(true)
  await act(async () => { vi.advanceTimersByTime(3000) }); expect(screen.getByText(explanation.sections[0].text)).toBeTruthy()
  expect(onBusyChange).toHaveBeenLastCalledWith(false); expect(fetch.mock.calls.filter(call => call[1]?.method === 'POST')).toHaveLength(1)
})
it('ignores a late generation response when the figure changes', async () => {
  let resolve!: (value: unknown) => void; let signal!: AbortSignal
  const fetch = vi.fn((url: string, init?: RequestInit) => {
    if (init?.method === 'POST') { signal = init.signal as AbortSignal; return new Promise(done => { resolve = done }) }
    return json(url.endsWith('/report') ? reportState : url === '/api/v1/ai/config' ? { configured: true } : empty)
  })
  vi.stubGlobal('fetch', fetch); const view = render(<AnalysisExplanation {...props} />)
  await waitFor(() => expect(button().disabled).toBe(false)); fireEvent.click(button())
  view.rerender(<AnalysisExplanation {...props} figureId="replacement" />); expect(signal.aborted).toBe(true)
  await act(async () => { resolve({ ok: true, json: async () => ({ ...empty, explanation }) }) })
  expect(screen.queryByText(explanation.sections[0].text)).toBeNull()
})
it('server revision conflict retains the draft and requires current state before generation', async () => {
  const fetch = vi.fn((url: string, init?: RequestInit) => init?.method === 'POST'
    ? Promise.resolve({ ok: false, status: 409, json: async () => ({ detail: { message: '解释配置已变化' } }) })
    : json(url.endsWith('/report') ? reportState : url === '/api/v1/ai/config' ? { configured: true } : { ...empty, explanation }))
  vi.stubGlobal('fetch', fetch); render(<AnalysisExplanation {...props} />)
  await waitFor(() => expect(button().disabled).toBe(false)); fireEvent.click(button())
  await screen.findByText('解释配置已变化'); expect(button().disabled).toBe(true)
  expect(screen.getByText(explanation.sections[0].text)).toBeTruthy(); expect(screen.getByText(/以下解释对应旧配置或旧图表/)).toBeTruthy()
})

it('exports cached explanations without a key and locks AI actions while report generation is busy', async () => {
  const onBusyChange = vi.fn(); let finish!: (value: unknown) => void
  const fetch = vi.fn((url: string, init?: RequestInit) => {
    if (url.endsWith('/report')) return init?.method === 'POST' ? new Promise(resolve => { finish = resolve }) : json({ current_revision: 1, is_current: true, ready: true, issues: [], report: null })
    return json(url.endsWith('/report') ? reportState : url === '/api/v1/ai/config' ? { configured: false } : { ...empty, explanation })
  })
  vi.stubGlobal('fetch', fetch); render(<AnalysisExplanation {...props} onBusyChange={onBusyChange} />)
  const reportButton = await screen.findByRole('button', { name: '生成 Word 报告' }) as HTMLButtonElement
  await waitFor(() => expect(reportButton.disabled).toBe(false)); fireEvent.click(reportButton)
  expect((screen.getByRole('button', { name: '重新读取解释' }) as HTMLButtonElement).disabled).toBe(true)
  expect(onBusyChange).toHaveBeenLastCalledWith(true)
  await act(async () => { finish({ ok: true, json: async () => ({ current_revision: 1, is_current: true, ready: true, issues: [], report: null }) }) })
  expect(onBusyChange).toHaveBeenLastCalledWith(false)
  expect((screen.getByRole('button', { name: '重新读取解释' }) as HTMLButtonElement).disabled).toBe(false)
})
it('does not mount report before a saved explanation', async () => {
  const fetch = api(); vi.stubGlobal('fetch', fetch); render(<AnalysisExplanation {...props} />)
  await waitFor(() => expect(button().disabled).toBe(false))
  expect(screen.queryByRole('button', { name: '生成 Word 报告' })).toBeNull()
  expect(fetch.mock.calls.some(call => call[0].endsWith('/report'))).toBe(false)
})
