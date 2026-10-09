import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import BoxplotFigure from './BoxplotFigure'
import AnalysisExplanation from '../explanations/AnalysisExplanation'
import { clearApiSession } from '../../shared/api/client'
import { setLocale } from '../../shared/i18n'

const props = { base: '/file', runId: 'run', revision: 1, canGenerate: true, disabled: false, onBusyChange: vi.fn() }
const cases = [
  { kind: 'boxplot', generate: '使用 OpenAI 生成箱线图', empty: { current_revision: 1, is_current: true, figure: null, job: null, task: null }, panel: (extra = {}) => <BoxplotFigure {...props} {...extra} /> },
  { kind: 'explanation', generate: '使用 OpenAI 生成解释', empty: { current_revision: 1, is_current: true, figure_id: 'figure', explanation: null, job: null, task: null }, panel: (extra = {}) => <AnalysisExplanation {...props} figureId="figure" {...extra} /> },
]
const disclosure = (kind: string) => ({ version: 1, provider: 'openai', task_type: kind, source_digest: 'hidden-source-digest', has_saved_result: false,
  summary: { valid_count: 7, excluded_count: 2, group_count: 2 }, labels: [{ key: 'numeric_name', value: '原始测量值' }, { key: 'unit', value: 'mg' }, { key: 'group_name', value: '原分组' }, { key: 'group:0', value: '一组' }, { key: 'group:1', value: '二组' }, ...(kind === 'explanation' ? [{ key: 'figure_title', value: '原图标题' }] : [])] })
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); setLocale('zh-CN') })

describe.each(cases)('$kind external send review', item => {
  it('reports preview timeout and allows a read-only recovery', async () => {
    vi.useFakeTimers()
    const fetch = vi.fn((url: string, _init?: RequestInit) => url.endsWith('/disclosure') ? new Promise<Response>(() => {})
      : Promise.resolve(Response.json(url.endsWith('config') ? { configured: true } : item.empty)))
    vi.stubGlobal('fetch', fetch); render(item.panel()); await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: item.generate })); await act(async () => { vi.advanceTimersByTime(30_000) })
    expect(screen.getByRole('alert').textContent).toContain('超时')
    expect(fetch.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
  })

  it('reads the saved result discovered by preview without generating it again', async () => {
    let saved = false
    const artifact = item.kind === 'boxplot'
      ? { id: 'figure', analysis_run_id: 'run', setup_revision: 1, title: '保存的图表', caption: '原图注', verification: { note: '已核验' } }
      : { id: 'exp', analysis_run_id: 'run', figure_id: 'figure', setup_revision: 1, sections: [], limitations: [], verification: { note: '保存的解释' } }
    const fetch = vi.fn((url: string, _init?: RequestInit) => {
      if (url.endsWith('/disclosure')) { saved = true; return Promise.resolve(Response.json({ ...disclosure(item.kind), has_saved_result: true })) }
      return Promise.resolve(Response.json(url.endsWith('config') ? { configured: true } : url.endsWith('/report') ? { ready: true, report: null } : { ...item.empty, ...(saved ? { [item.kind === 'boxplot' ? 'figure' : 'explanation']: artifact } : {}) }))
    })
    vi.stubGlobal('fetch', fetch); render(item.panel()); await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: item.generate })); await act(async () => {})
    expect(item.kind === 'boxplot' ? screen.getByAltText('保存的图表') : screen.getByText('保存的解释')).toBeTruthy()
    expect(screen.queryByRole('heading', { name: '发送前检查' })).toBeNull()
    expect(fetch.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
  })

  it('freezes the predecessor selected before the preview request', async () => {
    let resolve!: (response: Response) => void
    const failed = { id: 'A', revision: 4, status: 'failed', error_code: item.kind === 'boxplot' ? 'plot_invalid_result' : 'explanation_invalid' }
    const fetch = vi.fn((url: string, init?: RequestInit) => url.endsWith('/disclosure') ? new Promise<Response>(done => { resolve = done })
      : Promise.resolve(Response.json(url.endsWith('config') ? { configured: true } : { ...item.empty, task: init?.method === 'POST' ? { ...failed, id: 'B', revision: 5 } : failed })))
    vi.stubGlobal('fetch', fetch); render(item.panel()); await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: item.kind === 'boxplot' ? '重试生成（再次调用 API）' : '重试生成解释（再次调用 API）' }))
    await act(async () => { resolve(Response.json(disclosure(item.kind))) })
    fireEvent.click(screen.getByRole('button', { name: '确认发送并生成' })); await act(async () => {})
    const post = fetch.mock.calls.find(([, init]) => init?.method === 'POST')!
    expect(JSON.parse(post[1]?.body as string)).toMatchObject({ retry: true, expected_predecessor_id: 'A', expected_predecessor_revision: 4, expected_revision: 1 })
  })

  it('only submits after confirmation, preserves edited labels across language change, and replays the frozen body', async () => {
    const randomKey = vi.spyOn(crypto, 'randomUUID')
    const fetch = vi.fn((url: string, init?: RequestInit): Promise<Response> => init?.method === 'POST' ? Promise.reject(new TypeError('offline'))
      : Promise.resolve(Response.json(url.endsWith('config') ? { configured: true } : url.endsWith('/disclosure') ? disclosure(item.kind) : item.empty)))
    vi.stubGlobal('fetch', fetch); render(item.panel()); await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: item.generate })); await act(async () => {})
    expect(fetch.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
    expect(randomKey).not.toHaveBeenCalled()
    expect(screen.getByRole('heading', { name: '发送前检查' })).toBeTruthy()
    expect(screen.getByText('有效记录：7；排除记录：2；分组：2。')).toBeTruthy()
    expect(screen.queryByText(/hidden-source-digest|numeric_name|group:0|SDK|source_digest/)).toBeNull()
    fireEvent.change(screen.getByRole('textbox', { name: '数值名称' }), { target: { value: '公开名称' } })
    act(() => setLocale('en'))
    expect((screen.getByRole('textbox', { name: 'Numeric label' }) as HTMLInputElement).value).toBe('公开名称')
    const confirm = screen.getByRole('button', { name: 'Confirm send and generate' })
    fireEvent.click(confirm); fireEvent.click(confirm); await act(async () => {})
    expect(randomKey).toHaveBeenCalledOnce()
    const first = fetch.mock.calls.filter(([, init]) => init?.method === 'POST')[0]
    expect(JSON.parse(first[1]?.body as string).external_processing).toEqual({ version: 1, confirmed: true, source_digest: 'hidden-source-digest', labels: { numeric_name: '公开名称', unit: 'mg', group_name: '原分组', 'group:0': '一组', 'group:1': '二组', ...(item.kind === 'explanation' ? { figure_title: '原图标题' } : {}) } })
    fireEvent.click(screen.getByRole('button', { name: item.kind === 'boxplot' ? 'Reload chart' : 'Reload explanation' })); await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: 'Confirm previous submission' })); await act(async () => {})
    const posts = fetch.mock.calls.filter(([, init]) => init?.method === 'POST')
    expect(posts).toHaveLength(2); expect(posts[1][1]?.body).toBe(first[1]?.body)
    expect(new Headers(posts[1][1]?.headers).get('Idempotency-Key')).toBe(new Headers(first[1]?.headers).get('Idempotency-Key'))
    expect(fetch.mock.calls.filter(([url]) => url.endsWith('/disclosure'))).toHaveLength(1)
    expect(randomKey).toHaveBeenCalledOnce()
  })

  it('keeps a newer preview intact when a canceled older preview settles', async () => {
    const responses: ((value: Response) => void)[] = []
    const fetch = vi.fn((url: string, _init?: RequestInit) => url.endsWith('/disclosure') ? new Promise<Response>(resolve => { responses.push(resolve) })
      : Promise.resolve(Response.json(url.endsWith('config') ? { configured: true } : item.empty)))
    vi.stubGlobal('fetch', fetch); render(item.panel()); await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: item.generate })); await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: '取消' }))
    fireEvent.click(screen.getByRole('button', { name: item.generate })); await act(async () => {})
    expect(responses).toHaveLength(2)
    await act(async () => { responses[0](Response.json({ ...disclosure(item.kind), has_saved_result: true })) })
    expect(screen.getByText('正在核对发送资料……')).toBeTruthy()
    await act(async () => { responses[1](Response.json({ ...disclosure(item.kind), source_digest: 'new-source' })) })
    expect(screen.getByRole('heading', { name: '发送前检查' })).toBeTruthy()
    expect(fetch.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
    expect(fetch.mock.calls.filter(([url]) => url.endsWith(`/${item.kind}`))).toHaveLength(1)
  })

  it.each(['cancel', 'dirty', 'logout', 'revision'])('discards a late preview after %s without submitting or reviving the card', async reason => {
    let resolve!: (response: Response) => void; let signal!: AbortSignal
    const fetch = vi.fn((url: string, init?: RequestInit) => url.endsWith('/disclosure') ? new Promise<Response>(done => { resolve = done; signal = init?.signal as AbortSignal })
      : Promise.resolve(Response.json(url.endsWith('config') ? { configured: true } : item.empty)))
    vi.stubGlobal('fetch', fetch); const view = render(item.panel()); await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: item.generate })); await act(async () => {})
    if (reason === 'cancel') fireEvent.click(screen.getByRole('button', { name: '取消' }))
    if (reason === 'dirty') { view.rerender(item.panel({ canGenerate: false })); view.rerender(item.panel()) }
    if (reason === 'logout') act(() => clearApiSession())
    if (reason === 'revision') view.rerender(item.panel({ revision: 2 }))
    expect(signal.aborted).toBe(true)
    await act(async () => { resolve(Response.json(disclosure(item.kind))) })
    expect(screen.queryByRole('heading', { name: '发送前检查' })).toBeNull()
    expect(fetch.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
  })

  it('cancels an opened draft and sends no POST', async () => {
    const fetch = vi.fn((url: string, _init?: RequestInit) => Promise.resolve(Response.json(url.endsWith('config') ? { configured: true } : url.endsWith('/disclosure') ? disclosure(item.kind) : item.empty)))
    vi.stubGlobal('fetch', fetch); render(item.panel()); await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: item.generate })); await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: '取消' }))
    expect(screen.queryByRole('heading', { name: '发送前检查' })).toBeNull()
    expect(fetch.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
  })
})
