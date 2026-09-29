import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import BoxplotFigure from './BoxplotFigure'

const figure = { id: 'figure', analysis_run_id: 'run', setup_revision: 1, title: '图 1 测量值箱线图', caption: '完整记录；n=3', x_label: '分组', y_label: '测量值', source_sha256: 'source', sha256: 'image', created_at: '2026-09-29', engine: { id: 'boxplot-v1', provider: 'openai_code_interpreter', model: 'model' }, verification: { status: 'matched', note: '统计核对一致' } }
const empty = { current_revision: 1, is_current: true, figure: null, job: null }
const props = { base: '/file', runId: 'run', revision: 1, canGenerate: true, disabled: false, onBusyChange: vi.fn() }
const json = (value: unknown) => Promise.resolve({ ok: true, json: async () => value })
function api(state: unknown = empty, configured = true) {
  return vi.fn((url: string, _init?: RequestInit) => json(url === '/api/v1/ai/config' ? { configured, model: 'model', message: '请在 backend/.env 配置 API。' } : state))
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers() })

it('restores saved image without POST and keeps its provenance', async () => {
  const fetch = api({ ...empty, figure }); vi.stubGlobal('fetch', fetch)
  render(<BoxplotFigure {...props} />)
  expect(await screen.findByAltText(figure.title)).toBeTruthy()
  expect(screen.getByText(figure.caption)).toBeTruthy()
  expect(fetch.mock.calls.every(call => !call[1]?.method)).toBe(true)
})
it('missing configuration disables generation but permits restored image', async () => {
  vi.stubGlobal('fetch', api({ ...empty, figure }, false))
  render(<BoxplotFigure {...props} />)
  await screen.findByText('请在 backend/.env 配置 API。')
  expect((screen.getByRole('button', { name: '使用 OpenAI 生成箱线图' }) as HTMLButtonElement).disabled).toBe(true)
  expect(screen.getByAltText(figure.title)).toBeTruthy()
})
it('dirty or stale configuration disables generation and retains old image', async () => {
  vi.stubGlobal('fetch', api({ ...empty, is_current: false, current_revision: 2, figure }))
  render(<BoxplotFigure {...props} canGenerate={false} />)
  await screen.findByAltText(figure.title)
  expect((screen.getByRole('button', { name: '使用 OpenAI 生成箱线图' }) as HTMLButtonElement).disabled).toBe(true)
  expect(screen.getByText(/以下图表对应旧配置/)).toBeTruthy()
})
it.each(['failed', 'uncertain'])('explicit %s retry sends retry true and duplicate clicks submit once', async status => {
  const fetch = vi.fn((url: string, init?: RequestInit) => init?.method === 'POST' ? new Promise(() => {}) : json(url === '/api/v1/ai/config' ? { configured: true, model: 'model', message: '' } : { ...empty, job: { id: 'job', status, message: '需要重试', response_id: null, created_at: '' } }))
  vi.stubGlobal('fetch', fetch); render(<BoxplotFigure {...props} />)
  const button = await screen.findByRole('button', { name: '重试生成（再次调用 API）' })
  await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(button); fireEvent.click(button)
  const posts = fetch.mock.calls.filter(call => call[1]?.method === 'POST')
  expect(posts).toHaveLength(1); expect(JSON.parse(posts[0][1]!.body as string)).toEqual({ expected_revision: 1, retry: true })
})
it('polls a submitted task to completion without another POST', async () => {
  vi.useFakeTimers()
  let submitted = false
  let polls = 0
  const fetch = vi.fn((url: string, init?: RequestInit) => {
    if (url === '/api/v1/ai/config') return json({ configured: true, model: 'model', message: '' })
    if (init?.method === 'POST') { submitted = true; return json({ ...empty, job: { id: 'job', status: 'submitting', message: '正在提交', response_id: null, created_at: '' } }) }
    if (submitted && polls++ === 0) return json({ ...empty, job: { id: 'job', status: 'running', message: '处理中', response_id: 'response', created_at: '' } })
    return json(submitted ? { ...empty, figure } : empty)
  })
  vi.stubGlobal('fetch', fetch); render(<BoxplotFigure {...props} />)
  await act(async () => {})
  fireEvent.click(screen.getByRole('button', { name: '使用 OpenAI 生成箱线图' }))
  await act(async () => {})
  await act(async () => { vi.advanceTimersByTime(3000) })
  expect(screen.getByAltText(figure.title)).toBeTruthy()
  expect(fetch.mock.calls.filter(call => call[1]?.method === 'POST')).toHaveLength(1)
})
it('ignores late responses after switching runs', async () => {
  let resolve!: (value: unknown) => void
  vi.stubGlobal('fetch', vi.fn((url: string) => url.includes('/run/boxplot') ? new Promise(done => { resolve = done }) : json(url === '/api/v1/ai/config' ? { configured: true, model: '', message: '' } : empty)))
  const view = render(<BoxplotFigure {...props} />)
  view.rerender(<BoxplotFigure {...props} runId="new" />)
  await act(async () => { resolve({ ok: true, json: async () => ({ ...empty, figure }) }) })
  expect(screen.queryByAltText(figure.title)).toBeNull()
})
it('image failure provides explicit reload feedback', async () => {
  vi.stubGlobal('fetch', api({ ...empty, figure })); render(<BoxplotFigure {...props} />)
  fireEvent.error(await screen.findByAltText(figure.title))
  expect(screen.getByRole('alert').textContent).toMatch(/图片读取失败/)
  expect(screen.getByRole('button', { name: '重新读取图表' })).toBeTruthy()
})

it('failed GET preserves an existing image and allows rereading without POST', async () => {
  const fetch = api({ ...empty, figure }); vi.stubGlobal('fetch', fetch)
  render(<BoxplotFigure {...props} />); await screen.findByAltText(figure.title)
  fetch.mockRejectedValueOnce(new TypeError('offline'))
  fireEvent.click(screen.getByRole('button', { name: '重新读取图表' }))
  await screen.findByRole('alert')
  expect(screen.getByAltText(figure.title)).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '重新读取图表' }))
  await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
  expect(fetch.mock.calls.every(call => !call[1]?.method)).toBe(true)
})
it('GET timeout stops automatic polling and exposes reread action', async () => {
  vi.useFakeTimers()
  const fetch = vi.fn((url: string) => url === '/api/v1/ai/config' ? json({ configured: true, model: 'model', message: '' }) : new Promise(() => {}))
  vi.stubGlobal('fetch', fetch); render(<BoxplotFigure {...props} />)
  await act(async () => {})
  await act(async () => { vi.advanceTimersByTime(30_000) })
  expect(screen.getByRole('alert').textContent).toMatch(/超时/)
  expect((screen.getByRole('button', { name: '重新读取图表' }) as HTMLButtonElement).disabled).toBe(false)
  await act(async () => { vi.advanceTimersByTime(9000) })
  expect(fetch).toHaveBeenCalledTimes(2)
})
it('retries configuration loading independently without generation', async () => {
  let fail = true
  const fetch = vi.fn((url: string) => {
    if (url === '/api/v1/ai/config' && fail) { fail = false; return Promise.reject(new TypeError('offline')) }
    return json(url === '/api/v1/ai/config' ? { configured: true, model: 'model', message: '' } : empty)
  })
  vi.stubGlobal('fetch', fetch); render(<BoxplotFigure {...props} />)
  fireEvent.click(await screen.findByRole('button', { name: '重试读取 OpenAI 配置' }))
  await waitFor(() => expect((screen.getByRole('button', { name: '使用 OpenAI 生成箱线图' }) as HTMLButtonElement).disabled).toBe(false))
  expect(screen.queryByRole('alert')).toBeNull()
})

it('server revision conflict marks the retained image as old and blocks generation', async () => {
  const fetch = vi.fn((url: string, init?: RequestInit) => init?.method === 'POST'
    ? Promise.resolve({ ok: false, status: 409, json: async () => ({ detail: { code: 'revision_conflict', message: '配置已变化' } }) })
    : json(url === '/api/v1/ai/config' ? { configured: true, model: 'model', message: '' } : { ...empty, figure }))
  vi.stubGlobal('fetch', fetch); render(<BoxplotFigure {...props} />)
  await screen.findByAltText(figure.title)
  await waitFor(() => expect((screen.getByRole('button', { name: '使用 OpenAI 生成箱线图' }) as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(screen.getByRole('button', { name: '使用 OpenAI 生成箱线图' }))
  await screen.findByText('配置已变化')
  expect(screen.getByText(/以下图表对应旧配置/)).toBeTruthy()
  expect(screen.getByAltText(figure.title)).toBeTruthy()
})

it('offers fourth-step explanation only after a saved figure and propagates its busy state', async () => {
  const onBusyChange = vi.fn()
  const fetch = vi.fn((url: string, _init?: RequestInit) => json(url === '/api/v1/ai/config'
    ? { configured: true, model: 'model', message: '' }
    : url.endsWith('/explanation') ? { current_revision: 1, is_current: true, figure_id: 'figure', explanation: null, job: { id: 'job', status: 'running', message: '解释生成中', response_id: null, created_at: '' } }
    : { ...empty, figure }))
  vi.stubGlobal('fetch', fetch); render(<BoxplotFigure {...props} onBusyChange={onBusyChange} />)
  expect(await screen.findByText('第四步 · AI 分析解释')).toBeTruthy()
  await screen.findByText('解释生成中')
  await waitFor(() => expect(onBusyChange).toHaveBeenLastCalledWith(true))
  expect((screen.getByRole('button', { name: '使用 OpenAI 生成箱线图' }) as HTMLButtonElement).disabled).toBe(true)
})

it('releases plot controls when a restored explanation task completes without deadlock', async () => {
  vi.useFakeTimers(); let reads = 0; const onBusyChange = vi.fn()
  const fetch = vi.fn((url: string, _init?: RequestInit) => json(url === '/api/v1/ai/config' ? { configured: true }
    : url.endsWith('/explanation') ? { current_revision: 1, is_current: true, figure_id: 'figure', explanation: null,
      job: reads++ === 0 ? { id: 'job', status: 'running', message: '解释生成中', response_id: null, created_at: '' } : null }
    : { ...empty, figure }))
  vi.stubGlobal('fetch', fetch); render(<BoxplotFigure {...props} onBusyChange={onBusyChange} />); await act(async () => {})
  expect((screen.getByRole('button', { name: '重新读取图表' }) as HTMLButtonElement).disabled).toBe(true)
  await act(async () => { vi.advanceTimersByTime(3000) })
  expect((screen.getByRole('button', { name: '使用 OpenAI 生成箱线图' }) as HTMLButtonElement).disabled).toBe(false)
  expect((screen.getByRole('button', { name: '使用 OpenAI 生成解释' }) as HTMLButtonElement).disabled).toBe(false)
  expect(onBusyChange).toHaveBeenLastCalledWith(false)
})
it('prompts for a saved figure before reading or generating explanations', async () => {
  const fetch = api(); vi.stubGlobal('fetch', fetch); render(<BoxplotFigure {...props} />)
  expect(await screen.findByText('请先生成并保存箱线图，再生成分析解释。')).toBeTruthy()
  expect(fetch.mock.calls.some(call => call[0].endsWith('/explanation'))).toBe(false)
})
