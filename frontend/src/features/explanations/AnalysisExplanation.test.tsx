import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ComponentProps } from 'react'
import { apiError, setLocale, translate } from '../../shared/i18n'
import { WorkflowNavigation, WorkflowProvider } from '../analysis/AnalysisWorkflow'
import AnalysisExplanation from './AnalysisExplanation'

const explanation = { id: 'exp', analysis_run_id: 'run', figure_id: 'figure', setup_revision: 1, figure_sha256: 'image', source_sha256: 'source', language: 'zh-CN', created_at: 'today', sections: ['purpose', 'data', 'methods', 'results', 'interpretation', 'paper_text'].map(key => ({ key, title: key, text: `正文 ${key} <script>unsafe</script>`, evidence: [{ key: 'count', label: '有效样本数', value: '3' }] })), limitations: ['未进行显著性检验'], engine: { id: 'explanation-v1', provider: 'openai', model: 'model' }, verification: { status: 'matched', note: '证据校验通过' }, provenance: { analysis_run_id: 'run', prompt_version: 'v1' } }
const empty = { current_revision: 1, is_current: true, figure_id: 'figure', explanation: null, job: null }
const job = (status: string) => ({ id: 'job', status, message: '解释任务处理中', response_id: null, created_at: '' })
const props = { base: '/file', runId: 'run', revision: 1, figureId: 'figure', canGenerate: true, disabled: false, onBusyChange: vi.fn() }
const reportState = { current_revision: 1, is_current: true, ready: true, issues: [], report: null }
const json = (value: unknown) => Promise.resolve({ ok: true, json: async () => value })
function api(state: unknown = empty, configured = true) { return vi.fn((url: string, _init?: RequestInit) => json(url.endsWith('/report') ? reportState : url === '/api/v1/ai/config' ? { configured, model: 'model', message: '未配置 API' } : state)) }
const button = () => screen.getByRole('button', { name: '使用 OpenAI 生成解释' }) as HTMLButtonElement
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); setLocale('zh-CN') })

it('shows explanation loading and failure in Word report with read-only recovery', async () => {
  let rejectRead!: (error: Error) => void
  let initial = true
  const fetch = vi.fn((url: string, _init?: RequestInit) => {
    if (url.endsWith('/explanation') && initial) {
      initial = false
      return new Promise((_resolve, reject) => { rejectRead = reject })
    }
    return json(url === '/api/v1/ai/config' ? { configured: true } : url.endsWith('/report') ? reportState : { ...empty, explanation })
  })
  vi.stubGlobal('fetch', fetch)
  render(<WorkflowProvider><WorkflowNavigation /><AnalysisExplanation {...props} /></WorkflowProvider>)
  fireEvent.click(screen.getByRole('button', { name: 'Word报告' }))
  expect(screen.getByRole('status').textContent).toContain('正在读取解释')
  await act(async () => { rejectRead(new TypeError('offline')) })
  expect(screen.getByRole('alert').textContent).toContain('重新读取解释')
  expect(screen.queryByText('请先生成并保存分析解释，再生成 Word 报告。')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '重新读取解释' }))
  await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
  expect(await screen.findByRole('button', { name: '生成 Word 报告' })).toBeTruthy()
  expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true)
})

describe.each(['zh-CN', 'en'] as const)('shared configuration in the explanation workflow (%s)', locale => {
  it.each([
    { name: 'loading', configuration: null, error: '', notice: '正在读取解释 OpenAI 配置……' },
    { name: 'missing', configuration: { configured: false, model: null, message: '', message_code: 'openai_not_configured' }, error: '', notice: apiError({ code: 'openai_not_configured' }, '请联系管理员配置 OpenAI API。') },
    { name: 'error', configuration: null, error: '无法连接后端，请确认服务正常后重新读取图表。', notice: '无法连接后端，请确认服务正常后重新读取图表。' },
  ])('shows $name and recovers through the parent configuration callback', async ({ configuration, error, notice }) => {
    setLocale(locale)
    const fetch = api(); vi.stubGlobal('fetch', fetch)
    const onReloadConfiguration = vi.fn()
    const workflow = (configurationProps: Pick<ComponentProps<typeof AnalysisExplanation>, 'configuration' | 'configurationError'>) =>
      <WorkflowProvider><WorkflowNavigation /><AnalysisExplanation {...props} {...configurationProps} onReloadConfiguration={onReloadConfiguration} /></WorkflowProvider>
    const view = render(workflow({ configuration, configurationError: translate(error) }))
    fireEvent.click(screen.getByRole('button', { name: translate('分析解释') }))
    const panel = within(screen.getByRole('region', { name: translate('AI 分析解释') }))
    await panel.findByText(translate('尚未生成此图表的分析解释。'))
    expect(panel.getByText(translate(notice)).closest('[hidden]')).toBeNull()
    const generate = panel.getByRole('button', { name: translate('使用 OpenAI 生成解释') }) as HTMLButtonElement
    expect(generate.disabled).toBe(true)
    fireEvent.click(panel.getByRole('button', { name: translate('重新读取解释 OpenAI 配置') }))
    expect(onReloadConfiguration).toHaveBeenCalledOnce()
    view.rerender(workflow({ configuration: { configured: true, model: 'model', message: '' }, configurationError: '' }))
    await waitFor(() => expect(generate.disabled).toBe(false))
    expect(panel.queryByText(translate(notice))).toBeNull()
    expect(fetch.mock.calls.some(([url]) => url === '/api/v1/ai/config')).toBe(false)
    expect(fetch.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
  })
})

it('generates six sections with evidence and safely renders AI draft and provenance', async () => {
  const fetch = api(); vi.stubGlobal('fetch', fetch); render(<AnalysisExplanation {...props} />)
  await waitFor(() => expect(button().disabled).toBe(false))
  fetch.mockImplementation((url: string, init?: RequestInit) => json(url.endsWith('/report') ? reportState : init?.method === 'POST' ? { ...empty, explanation } : url === '/api/v1/ai/config' ? { configured: true } : empty))
  fireEvent.click(button()); fireEvent.click(button())
  expect(await screen.findByText(explanation.sections[0].text)).toBeTruthy()
  for (const section of explanation.sections) expect(screen.getByRole('heading', { name: section.title })).toBeTruthy()
  expect(screen.getAllByText('有效样本数：3')).toHaveLength(6)
  expect(screen.getByText(/AI 草稿/)).toBeTruthy(); expect(screen.getByText('未进行显著性检验')).toBeTruthy()
  expect(screen.queryAllByText(/SHA256|解释编号|配置版本|统计结果编号|图表编号|prompt_version|explanation-v1/)).toHaveLength(0); expect(screen.getByText('证据校验通过')).toBeTruthy(); expect(document.querySelector('script')).toBeNull()
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
    ? Promise.resolve({ ok: false, status: 409, json: async () => ({ detail: { code: 'setup_conflict', params: {}, message: 'ignored legacy text' } }) })
    : json(url.endsWith('/report') ? reportState : url === '/api/v1/ai/config' ? { configured: true } : { ...empty, explanation }))
  vi.stubGlobal('fetch', fetch); render(<AnalysisExplanation {...props} />)
  await waitFor(() => expect(button().disabled).toBe(false)); fireEvent.click(button())
  await screen.findByText('分析配置已变化，请读取当前配置并重新执行统计。'); expect(button().disabled).toBe(true)
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

it('preserves research sample identifiers and Excel positions in saved evidence', async () => {
  const sample = { ...explanation, sections: [{ key: 'data', title: '使用数据', text: '样本编号和原始位置用于核对研究数据。', evidence: [{ key: 'grouping', label: '样本编号', value: 'S-2026-001' }, { key: 'sheet', label: 'Excel 位置', value: 'C12' }] }] }
  vi.stubGlobal('fetch', api({ ...empty, explanation: sample })); render(<AnalysisExplanation {...props} />)
  expect(await screen.findByText('样本编号：S-2026-001')).toBeTruthy()
  expect(screen.getByText('Excel 位置：C12')).toBeTruthy()
  expect(screen.queryAllByText(/SHA256|配置版本|prompt_version/)).toHaveLength(0)
})
