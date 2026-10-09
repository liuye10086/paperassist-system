import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import BoxplotFigure from './BoxplotFigure'
import AnalysisExplanation from '../explanations/AnalysisExplanation'
import { setLocale, translate } from '../../shared/i18n'
import { clearApiSession } from '../../shared/api/client'

const common = { base: '/file', runId: 'run', revision: 1, canGenerate: true, disabled: false, onBusyChange: vi.fn() }
const cases = [
  { kind: 'plot', path: 'boxplot', generate: '使用 OpenAI 生成箱线图', retry: '重试生成（再次调用 API）', reload: '重新读取图表', failure: 'plot_invalid_result',
    empty: { current_revision: 1, is_current: true, figure: null, job: null, task: null },
    panel: (revision = 1) => <BoxplotFigure {...common} revision={revision} /> },
  { kind: 'explanation', path: 'explanation', generate: '使用 OpenAI 生成解释', retry: '重试生成解释（再次调用 API）', reload: '重新读取解释', failure: 'explanation_invalid',
    empty: { current_revision: 1, is_current: true, figure_id: 'figure', explanation: null, job: null, task: null },
    panel: (revision = 1) => <AnalysisExplanation {...common} revision={revision} figureId="figure" /> },
]
const disclosure = (kind: string) => ({ version: 1, provider: 'openai', task_type: kind === 'plot' ? 'boxplot' : 'explanation', source_digest: 'source', has_saved_result: false, summary: { valid_count: 3, excluded_count: 0, group_count: 1 }, labels: [{ key: 'numeric_name', value: '测量值' }, { key: 'unit', value: '' }, ...(kind === 'explanation' ? [{ key: 'figure_title', value: '图表' }] : [])] })
async function confirmSend() { await act(async () => {}); fireEvent.click(screen.getByRole('button', { name: translate('确认发送并生成') })); await act(async () => {}) }
const task = (status: string, error_code: string | null, id = 'B') => ({ id, status, revision: 4, reason_code: status === 'waiting_confirmation' ? 'budget_exceeded' : null, error_code })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); setLocale('zh-CN') })

describe.each(cases)('$kind stable generation submission', item => {
  it.each(['timeout', 'offline', 'server', 'malformed', 'malformedTask'] as const)('keeps original creation key and body after %s and a failed successor, then uses a new key for the next decision', async failure => {
    vi.useFakeTimers(); let posts = 0; let state = { ...item.empty, task: task('failed', item.failure, 'A') }
    const fetch = vi.fn((url: string, init?: RequestInit): Promise<Response> => {
      if (url.endsWith('/disclosure')) return Promise.resolve(Response.json(disclosure(item.kind)))
      if (url.endsWith('config')) return Promise.resolve(Response.json({ configured: true }))
      if (init?.method === 'POST') {
        posts++
        if (posts === 1) {
          state = { ...item.empty, task: task('failed', item.failure) }
          if (failure === 'timeout') return new Promise(() => {})
          if (failure === 'offline') return Promise.reject(new TypeError('offline'))
          if (failure === 'malformedTask') return Promise.resolve(Response.json({ ...item.empty, task: {} }))
          return Promise.resolve(failure === 'server' ? Response.json({ detail: { code: 'internal_error' } }, { status: 503 }) : Response.json(null))
        }
      }
      return Promise.resolve(Response.json(state))
    })
    vi.stubGlobal('fetch', fetch); render(item.panel()); await act(async () => {})
    const first = screen.getByRole('button', { name: item.retry })
    fireEvent.click(first); fireEvent.click(first); await confirmSend()
    await act(async () => { if (failure === 'timeout') vi.advanceTimersByTime(30_000) })
    const firstPost = fetch.mock.calls.filter(([, init]) => init?.method === 'POST')[0]
    const key = new Headers(firstPost[1]?.headers).get('Idempotency-Key')
    expect(key).toMatch(/^[0-9a-f-]{36}$/i)
    expect(JSON.parse(firstPost[1]?.body as string).expected_predecessor_id).toBe('A')
    expect(JSON.parse(firstPost[1]?.body as string).expected_predecessor_revision).toBe(4)
    expect(posts).toBe(1)
    const confirm = screen.getByRole('button', { name: '确认上次提交' }) as HTMLButtonElement
    expect(confirm.disabled).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: item.reload })); await act(async () => {})
    expect(confirm.disabled).toBe(false); expect(posts).toBe(1)
    fireEvent.click(confirm); await act(async () => {})
    const replay = fetch.mock.calls.filter(([, init]) => init?.method === 'POST')[1]
    expect(replay[0]).toBe(firstPost[0]); expect(replay[1]?.body).toBe(firstPost[1]?.body)
    expect(new Headers(replay[1]?.headers).get('Idempotency-Key')).toBe(key)
    expect(screen.queryByRole('button', { name: '确认上次提交' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: item.retry })); await confirmSend(); await act(async () => {})
    const next = fetch.mock.calls.filter(([, init]) => init?.method === 'POST')[2]
    expect(new Headers(next[1]?.headers).get('Idempotency-Key')).not.toBe(key)
    expect(JSON.parse(next[1]?.body as string).expected_predecessor_id).toBe('B')
    expect(JSON.parse(next[1]?.body as string).expected_predecessor_revision).toBe(4)
  })

  it.each(['running', 'waiting_confirmation', 'failed'])('confirms the original POST when reread finds %s, without converting to task retry', async status => {
    vi.useFakeTimers(); let posted = false
    const state = { ...item.empty, task: task(status, status === 'failed' ? 'openai_request_failed' : null) }
    const fetch = vi.fn((url: string, init?: RequestInit): Promise<Response> => {
      if (url.endsWith('/disclosure')) return Promise.resolve(Response.json(disclosure(item.kind)))
      if (url.endsWith('config')) return Promise.resolve(Response.json({ configured: true }))
      if (init?.method === 'POST') { if (!posted) { posted = true; return Promise.reject(new TypeError('offline')) }; return Promise.resolve(Response.json(state)) }
      return Promise.resolve(Response.json(posted ? state : item.empty))
    })
    vi.stubGlobal('fetch', fetch); render(item.panel()); await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: item.generate })); await confirmSend(); await act(async () => {})
    expect(new Headers(fetch.mock.calls.find(([, init]) => init?.method === 'POST')![1]?.headers).get('Idempotency-Key')).toMatch(/^[0-9a-f-]{36}$/i)
    fireEvent.click(screen.getByRole('button', { name: item.reload })); await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: '确认上次提交' })); await act(async () => {})
    const requests = fetch.mock.calls.filter(([, init]) => init?.method === 'POST')
    expect(requests).toHaveLength(2); expect(requests[1][0]).toBe(requests[0][0])
    expect(requests[1][1]?.body).toBe(requests[0][1]?.body)
    expect(new Headers(requests[1][1]?.headers).get('Idempotency-Key')).toBe(new Headers(requests[0][1]?.headers).get('Idempotency-Key'))
    expect(JSON.parse(requests[1][1]?.body as string)).not.toHaveProperty('retry')
    expect(JSON.parse(requests[1][1]?.body as string)).not.toHaveProperty('expected_predecessor_id')
    expect(JSON.parse(requests[1][1]?.body as string)).not.toHaveProperty('expected_predecessor_revision')
  })

  it.each(['queued', 'failed'])('freezes failed predecessor A while reread sees successor B %s, and requires a new decision after conflict', async status => {
    vi.useFakeTimers(); let posts = 0
    let state = { ...item.empty, task: task('failed', item.failure, 'A') }
    const fetch = vi.fn((url: string, init?: RequestInit): Promise<Response> => {
      if (url.endsWith('/disclosure')) return Promise.resolve(Response.json(disclosure(item.kind)))
      if (url.endsWith('config')) return Promise.resolve(Response.json({ configured: true }))
      if (init?.method === 'POST') {
        posts++
        if (posts === 1) { state = { ...item.empty, task: task(status, status === 'failed' ? item.failure : null) }; return Promise.reject(new TypeError('offline')) }
        if (posts === 2) return Promise.resolve(Response.json({ detail: { code: 'setup_conflict' } }, { status: 409 }))
      }
      return Promise.resolve(Response.json(state))
    })
    vi.stubGlobal('fetch', fetch); render(item.panel()); await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: item.retry })); await confirmSend(); await act(async () => {})
    const first = fetch.mock.calls.find(([, init]) => init?.method === 'POST')!
    expect(JSON.parse(first[1]?.body as string).expected_predecessor_id).toBe('A')
    fireEvent.click(screen.getByRole('button', { name: item.reload })); await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: '确认上次提交' })); await act(async () => {})
    const replay = fetch.mock.calls.filter(([, init]) => init?.method === 'POST')[1]
    expect(replay[1]?.body).toBe(first[1]?.body)
    expect(new Headers(replay[1]?.headers).get('Idempotency-Key')).toBe(new Headers(first[1]?.headers).get('Idempotency-Key'))
    expect(screen.queryByRole('button', { name: '确认上次提交' })).toBeNull(); expect(posts).toBe(2)
    expect((screen.getByRole('button', { name: status === 'failed' ? item.retry : item.generate }) as HTMLButtonElement).disabled).toBe(true)
    state = { ...item.empty, task: task('failed', item.failure) }
    fireEvent.click(screen.getByRole('button', { name: item.reload })); await act(async () => {})
    expect(posts).toBe(2)
    fireEvent.click(screen.getByRole('button', { name: item.retry })); await confirmSend(); await act(async () => {})
    const next = fetch.mock.calls.filter(([, init]) => init?.method === 'POST')[2]
    expect(JSON.parse(next[1]?.body as string).expected_predecessor_id).toBe('B')
    expect(new Headers(next[1]?.headers).get('Idempotency-Key')).not.toBe(new Headers(first[1]?.headers).get('Idempotency-Key'))
  })

  it.each([403, 409, 422])('clears explicitly rejected %s submissions and never silently repeats them', async status => {
    vi.useFakeTimers()
    const fetch = vi.fn((url: string, init?: RequestInit) => Promise.resolve(init?.method === 'POST'
      ? Response.json({ detail: { code: status === 409 ? 'setup_conflict' : 'task_input_invalid' } }, { status })
      : Response.json(url.endsWith('/disclosure') ? disclosure(item.kind) : url.endsWith('config') ? { configured: true } : item.empty)))
    vi.stubGlobal('fetch', fetch); render(item.panel()); await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: item.generate })); await confirmSend(); await act(async () => {})
    expect(screen.queryByRole('button', { name: '确认上次提交' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: item.reload })); await act(async () => {})
    expect(fetch.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
  })

  it('confirms the frozen revision when the same predecessor ID advances, then captures the latest revision for a new decision', async () => {
    vi.useFakeTimers(); let posts = 0
    let state = { ...item.empty, task: task('failed', item.failure, 'A') }
    const fetch = vi.fn((url: string, init?: RequestInit): Promise<Response> => {
      if (url.endsWith('/disclosure')) return Promise.resolve(Response.json(disclosure(item.kind)))
      if (url.endsWith('config')) return Promise.resolve(Response.json({ configured: true }))
      if (init?.method === 'POST') {
        posts++
        if (posts === 1) { state = { ...item.empty, task: { ...task('failed', item.failure, 'A'), revision: 5 } }; return Promise.reject(new TypeError('offline')) }
        if (posts === 2) return Promise.resolve(Response.json({ detail: { code: 'setup_conflict' } }, { status: 409 }))
      }
      return Promise.resolve(Response.json(state))
    })
    vi.stubGlobal('fetch', fetch); render(item.panel()); await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: item.retry })); await confirmSend(); await act(async () => {})
    const first = fetch.mock.calls.find(([, init]) => init?.method === 'POST')!
    expect(JSON.parse(first[1]?.body as string)).toMatchObject({ expected_predecessor_id: 'A', expected_predecessor_revision: 4 })
    fireEvent.click(screen.getByRole('button', { name: item.reload })); await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: '确认上次提交' })); await act(async () => {})
    const replay = fetch.mock.calls.filter(([, init]) => init?.method === 'POST')[1]
    expect(replay[1]?.body).toBe(first[1]?.body)
    expect(new Headers(replay[1]?.headers).get('Idempotency-Key')).toBe(new Headers(first[1]?.headers).get('Idempotency-Key'))
    expect(screen.queryByRole('button', { name: '确认上次提交' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: item.reload })); await act(async () => {})
    expect(posts).toBe(2)
    fireEvent.click(screen.getByRole('button', { name: item.retry })); await confirmSend(); await act(async () => {})
    const next = fetch.mock.calls.filter(([, init]) => init?.method === 'POST')[2]
    expect(JSON.parse(next[1]?.body as string)).toMatchObject({ expected_predecessor_id: 'A', expected_predecessor_revision: 5 })
    expect(new Headers(next[1]?.headers).get('Idempotency-Key')).not.toBe(new Headers(first[1]?.headers).get('Idempotency-Key'))
  })

  it('invalidates pending identity on a changed source revision and ignores its late result', async () => {
    vi.useFakeTimers(); let resolve!: (value: Response) => void; let signal!: AbortSignal
    const fetch = vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === 'POST') { signal = init.signal as AbortSignal; return new Promise<Response>(done => { resolve = done }) }
      return Promise.resolve(Response.json(url.endsWith('/disclosure') ? disclosure(item.kind) : url.endsWith('config') ? { configured: true } : item.empty))
    })
    vi.stubGlobal('fetch', fetch); const view = render(item.panel()); await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: item.generate })); await confirmSend(); view.rerender(item.panel(2))
    expect(signal.aborted).toBe(true)
    await act(async () => { resolve(Response.json({ ...item.empty, task: task('failed', item.failure) })) })
    expect(screen.queryByRole('button', { name: '确认上次提交' })).toBeNull()
    expect((screen.getByRole('button', { name: item.generate }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('aborts and clears pending generation on logout and unmount', async () => {
    vi.useFakeTimers(); let signal!: AbortSignal
    const fetch = vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === 'POST') { signal = init.signal as AbortSignal; return new Promise<Response>(() => {}) }
      return Promise.resolve(Response.json(url.endsWith('/disclosure') ? disclosure(item.kind) : url.endsWith('config') ? { configured: true } : item.empty))
    })
    vi.stubGlobal('fetch', fetch); const view = render(item.panel()); await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: item.generate })); await confirmSend(); act(() => clearApiSession())
    expect(signal.aborted).toBe(true); expect(screen.queryByRole('button', { name: '确认上次提交' })).toBeNull()
    expect((screen.getByRole('button', { name: item.generate }) as HTMLButtonElement).disabled).toBe(true)
    view.unmount(); expect(signal.aborted).toBe(true)
  })

  it('aborts a submission when its source becomes unsaved and does not restore that identity', async () => {
    vi.useFakeTimers(); let signal!: AbortSignal
    const fetch = vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === 'POST') { signal = init.signal as AbortSignal; return new Promise<Response>(() => {}) }
      return Promise.resolve(Response.json(url.endsWith('/disclosure') ? disclosure(item.kind) : url.endsWith('config') ? { configured: true } : item.empty))
    })
    vi.stubGlobal('fetch', fetch); const view = render(item.panel()); await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: item.generate })); await confirmSend()
    view.rerender(item.kind === 'plot' ? <BoxplotFigure {...common} canGenerate={false} /> : <AnalysisExplanation {...common} canGenerate={false} figureId="figure" />)
    expect(signal.aborted).toBe(true)
    view.rerender(item.panel()); await act(async () => { vi.advanceTimersByTime(30_000) })
    expect(screen.queryByRole('button', { name: '确认上次提交' })).toBeNull()
    expect(fetch.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
  })

  it('discards the old confirmation when reread identifies a stale source', async () => {
    vi.useFakeTimers(); let posted = false
    const fetch = vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === 'POST') { posted = true; return Promise.reject(new TypeError('offline')) }
      return Promise.resolve(Response.json(url.endsWith('/disclosure') ? disclosure(item.kind) : url.endsWith('config') ? { configured: true } : { ...item.empty, is_current: !posted }))
    })
    vi.stubGlobal('fetch', fetch); render(item.panel()); await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: item.generate })); await confirmSend(); await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: item.reload })); await act(async () => {})
    expect(screen.queryByRole('button', { name: '确认上次提交' })).toBeNull()
    expect(fetch.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
  })

  it('keeps a newer submission busy when a canceled old submission settles', async () => {
    vi.useFakeTimers(); const responses: ((value: Response) => void)[] = []
    const fetch = vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === 'POST') return new Promise<Response>(done => { responses.push(done) })
      return Promise.resolve(Response.json(url.endsWith('/disclosure') ? disclosure(item.kind) : url.endsWith('config') ? { configured: true } : item.empty))
    })
    vi.stubGlobal('fetch', fetch); const view = render(item.panel()); await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: item.generate })); await confirmSend()
    view.rerender(item.kind === 'plot' ? <BoxplotFigure {...common} canGenerate={false} /> : <AnalysisExplanation {...common} canGenerate={false} figureId="figure" />)
    view.rerender(item.panel()); fireEvent.click(screen.getByRole('button', { name: item.generate })); await confirmSend()
    expect(responses).toHaveLength(2)
    await act(async () => { responses[0](Response.json(item.empty)) })
    expect((screen.getByRole('button', { name: item.reload }) as HTMLButtonElement).disabled).toBe(true)
    expect(common.onBusyChange).toHaveBeenLastCalledWith(true)
  })

  it.each(['artifact', 'configuration'])('does not repopulate cleared UI when a pre-logout %s read settles', async kind => {
    vi.useFakeTimers(); let resolve!: (value: Response) => void
    const fetch = vi.fn((url: string) => url.endsWith('config') === (kind === 'configuration')
      ? new Promise<Response>(done => { resolve = done })
      : Promise.resolve(Response.json(url.endsWith('/disclosure') ? disclosure(item.kind) : url.endsWith('config') ? { configured: true } : item.empty)))
    vi.stubGlobal('fetch', fetch); render(item.panel()); await act(async () => {})
    act(() => clearApiSession()); await act(async () => { resolve(Response.json(item.empty)) })
    expect(screen.queryByRole('alert')).toBeNull()
    await act(async () => { vi.advanceTimersByTime(30_000) })
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it.each(['zh-CN', 'en'] as const)('shows a readable confirmation action in %s without internal keys', async locale => {
    vi.useFakeTimers(); setLocale(locale)
    const fetch = vi.fn((url: string, init?: RequestInit) => init?.method === 'POST' ? Promise.reject(new TypeError('offline'))
      : Promise.resolve(Response.json(url.endsWith('/disclosure') ? disclosure(item.kind) : url.endsWith('config') ? { configured: true } : item.empty)))
    vi.stubGlobal('fetch', fetch); render(item.panel()); await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: translate(item.generate) })); await confirmSend(); await act(async () => {})
    expect(screen.getByRole('button', { name: locale === 'en' ? 'Confirm previous submission' : '确认上次提交' })).toBeTruthy()
    expect(screen.getByText(translate('上次提交尚未确认。请先重新读取，再确认上次提交；确认不会另建一次生成。'))).toBeTruthy()
    expect(screen.queryByText(/Idempotency|[0-9a-f]{8}-[0-9a-f]{4}/i)).toBeNull()
  })
})
