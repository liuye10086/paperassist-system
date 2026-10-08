import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import BoxplotFigure from './BoxplotFigure'
import { WorkflowProvider, WorkflowNavigation } from '../analysis/AnalysisWorkflow'
import { captureProjectAccess, watchProjectAccess } from '../../shared/api/projectAccess'

const figure = { id: 'figure', analysis_run_id: 'run', setup_revision: 1, title: '图 1 测量值箱线图', caption: '完整记录；n=3', x_label: '分组', y_label: '测量值', source_sha256: 'source', sha256: 'image', created_at: '2026-09-29', engine: { id: 'boxplot-v1', provider: 'openai_code_interpreter', model: 'model' }, verification: { status: 'matched', note: '统计核对一致' } }
const empty = { current_revision: 1, is_current: true, figure: null, job: null }
const props = { base: '/file', runId: 'run', revision: 1, canGenerate: true, disabled: false, onBusyChange: vi.fn() }
const json = (value: unknown) => Promise.resolve({ ok: true, json: async () => value })
function api(state: unknown = empty, configured = true) {
  return vi.fn((url: string, _init?: RequestInit) => json((url === '/api/v1/ai/plot-config' || url === '/api/v1/ai/explanation-config') ? { configured, model: 'model', message: '请在 backend/.env 配置 API。' } : state))
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers() })

it.each(['分析解释', 'Word报告'])('surfaces figure read loading and errors in %s with read-only recovery', async step => {
  let rejectRead!: (error: Error) => void
  let initial = true
  const fetch = vi.fn((url: string, _init?: RequestInit) => {
    if (url.endsWith('/boxplot') && initial) {
      initial = false
      return new Promise((_resolve, reject) => { rejectRead = reject })
    }
    return json((url === '/api/v1/ai/plot-config' || url === '/api/v1/ai/explanation-config') ? { configured: true } : url.endsWith('/explanation') ? { explanation: null, job: null } : { ...empty, figure })
  })
  vi.stubGlobal('fetch', fetch)
  render(<WorkflowProvider><WorkflowNavigation /><BoxplotFigure {...props} /></WorkflowProvider>)
  fireEvent.click(screen.getByRole('button', { name: step }))
  expect(screen.getByRole('status').textContent).toContain('正在读取图表')
  await act(async () => { rejectRead(new TypeError('offline')) })
  expect(screen.getByRole('alert').textContent).toContain('重新读取图表')
  expect(screen.queryByText('请先生成并保存箱线图，再生成分析解释。')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '重新读取图表' }))
  await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
  fireEvent.click(screen.getByRole('button', { name: '图表' }))
  expect(await screen.findByAltText(figure.title)).toBeTruthy()
  expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true)
})

it.each([
  [404, 'project_not_found', true], [404, 'file_not_found', false], [410, 'project_not_found', false], [200, '', false], [500, '', false],
])('rechecks project after image failure (%s %s)', async (status, code, loss) => {
  const base = '/api/v1/projects/p1/files/f1'; const unavailable = vi.fn(); const stop = watchProjectAccess('p1', unavailable)
  const fetch = vi.fn((url: string, _init?: RequestInit) => Promise.resolve(url === '/api/v1/projects/p1'
    ? Response.json({ detail: { code } }, { status })
    : Response.json((url === '/api/v1/ai/plot-config' || url === '/api/v1/ai/explanation-config') ? { configured: true } : url.endsWith('/explanation') ? { explanation: null, job: null } : { ...empty, figure })))
  vi.stubGlobal('fetch', fetch); const view = render(<BoxplotFigure {...props} base={base} />)
  fireEvent.error(await screen.findByAltText(figure.title))
  expect(screen.getByRole('alert').textContent).toContain('图片读取失败')
  await waitFor(() => expect(fetch.mock.calls.some(([url]) => url === '/api/v1/projects/p1')).toBe(true))
  await act(async () => {})
  expect(unavailable).toHaveBeenCalledTimes(loss ? 1 : 0)
  if (loss) expect(() => captureProjectAccess(base).check()).toThrow()
  expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true)
  view.unmount(); stop()
})
it('aborts the 15 second image recheck and never infers project loss from timeout', async () => {
  vi.useFakeTimers(); let signal!: AbortSignal
  const unavailable = vi.fn(); const stop = watchProjectAccess('p1', unavailable)
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    if (url === '/api/v1/projects/p1') { signal = init?.signal as AbortSignal; return new Promise<Response>(() => {}) }
    return Response.json((url === '/api/v1/ai/plot-config' || url === '/api/v1/ai/explanation-config') ? { configured: true } : url.endsWith('/explanation') ? { explanation: null, job: null } : { ...empty, figure })
  }))
  const view = render(<BoxplotFigure {...props} base="/api/v1/projects/p1/files/f1" />); await act(async () => {})
  fireEvent.error(screen.getByAltText(figure.title)); await act(async () => { vi.advanceTimersByTime(15_000) })
  expect(signal.aborted).toBe(true); expect(unavailable).not.toHaveBeenCalled(); expect(screen.getByRole('alert').textContent).toContain('图片读取失败')
  view.unmount(); stop()
})
it('aborts the image recheck when the figure panel unmounts', async () => {
  let signal!: AbortSignal
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    if (url === '/api/v1/projects/p1') { signal = init?.signal as AbortSignal; return new Promise<Response>(() => {}) }
    return Response.json((url === '/api/v1/ai/plot-config' || url === '/api/v1/ai/explanation-config') ? { configured: true } : url.endsWith('/explanation') ? { explanation: null, job: null } : { ...empty, figure })
  }))
  const view = render(<BoxplotFigure {...props} base="/api/v1/projects/p1/files/f1" />)
  fireEvent.error(await screen.findByAltText(figure.title)); view.unmount(); expect(signal.aborted).toBe(true)
})
it('downloads saved PNG bytes with a safe default filename without generation', async () => {
  const create = vi.fn((_blob: Blob) => 'blob:png'); const revoke = vi.fn()
  vi.stubGlobal('URL', class extends URL { static createObjectURL = create; static revokeObjectURL = revoke })
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { expect(this.download).toBe('boxplot.png') })
  const fetch = vi.fn((url: string, _init?: RequestInit) => Promise.resolve(url.endsWith('/image?download=true') ? new Response('png bytes') : Response.json((url === '/api/v1/ai/plot-config' || url === '/api/v1/ai/explanation-config') ? { configured: true } : url.endsWith('/explanation') ? { explanation: null, job: null } : { ...empty, figure })))
  vi.stubGlobal('fetch', fetch); render(<BoxplotFigure {...props} />)
  fireEvent.click(await screen.findByRole('link', { name: '下载箱线图 PNG' }))
  await waitFor(() => expect(create).toHaveBeenCalledTimes(1)); expect(await create.mock.calls[0][0].text()).toBe('png bytes')
  expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true); expect(revoke).toHaveBeenCalledWith('blob:png'); click.mockRestore()
})

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
  await within(screen.getByRole('region', { name: 'OpenAI 箱线图' })).findByText('云端模型尚未配置，请联系管理员配置后重试。')
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
it.each(['failed'])('explicit %s retry sends retry true and duplicate clicks submit once', async status => {
  const fetch = vi.fn((url: string, init?: RequestInit) => init?.method === 'POST' ? new Promise(() => {}) : json((url === '/api/v1/ai/plot-config' || url === '/api/v1/ai/explanation-config') ? { configured: true, model: 'model', message: '' } : { ...empty, job: { id: 'job', status, message: '需要重试', response_id: null, created_at: '' } }))
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
    if ((url === '/api/v1/ai/plot-config' || url === '/api/v1/ai/explanation-config')) return json({ configured: true, model: 'model', message: '' })
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
  vi.stubGlobal('fetch', vi.fn((url: string) => url.includes('/run/boxplot') ? new Promise(done => { resolve = done }) : json((url === '/api/v1/ai/plot-config' || url === '/api/v1/ai/explanation-config') ? { configured: true, model: '', message: '' } : empty)))
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
  const original = fetch.getMockImplementation()!
  let fail = true
  fetch.mockImplementation((url: string, init?: RequestInit) => {
    if (url.endsWith('/boxplot') && fail) { fail = false; return Promise.reject(new TypeError('offline')) }
    return original(url, init)
  })
  fireEvent.click(screen.getByRole('button', { name: '重新读取图表' }))
  await screen.findByRole('alert')
  expect(screen.getByAltText(figure.title)).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '重新读取图表' }))
  await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
  expect(fetch.mock.calls.every(call => !call[1]?.method)).toBe(true)
})
it('GET timeout stops automatic polling and exposes reread action', async () => {
  vi.useFakeTimers()
  const fetch = vi.fn((url: string) => (url === '/api/v1/ai/plot-config' || url === '/api/v1/ai/explanation-config') ? json({ configured: true, model: 'model', message: '' }) : new Promise(() => {}))
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
    if ((url === '/api/v1/ai/plot-config' || url === '/api/v1/ai/explanation-config') && fail) { fail = false; return Promise.reject(new TypeError('offline')) }
    return json((url === '/api/v1/ai/plot-config' || url === '/api/v1/ai/explanation-config') ? { configured: true, model: 'model', message: '' } : empty)
  })
  vi.stubGlobal('fetch', fetch); render(<BoxplotFigure {...props} />)
  fireEvent.click(await screen.findByRole('button', { name: '重试读取 OpenAI 配置' }))
  await waitFor(() => expect((screen.getByRole('button', { name: '使用 OpenAI 生成箱线图' }) as HTMLButtonElement).disabled).toBe(false))
  expect(screen.queryByRole('alert')).toBeNull()
})

it('server revision conflict marks the retained image as old and blocks generation', async () => {
  const fetch = vi.fn((url: string, init?: RequestInit) => init?.method === 'POST'
    ? Promise.resolve({ ok: false, status: 409, json: async () => ({ detail: { code: 'setup_conflict', message: '配置已变化' } }) })
    : json((url === '/api/v1/ai/plot-config' || url === '/api/v1/ai/explanation-config') ? { configured: true, model: 'model', message: '' } : { ...empty, figure }))
  vi.stubGlobal('fetch', fetch); render(<BoxplotFigure {...props} />)
  await screen.findByAltText(figure.title)
  await waitFor(() => expect((screen.getByRole('button', { name: '使用 OpenAI 生成箱线图' }) as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(screen.getByRole('button', { name: '使用 OpenAI 生成箱线图' }))
  await screen.findByText('分析配置已变化，请读取当前配置并重新执行统计。')
  expect(screen.getByText(/以下图表对应旧配置/)).toBeTruthy()
  expect(screen.getByAltText(figure.title)).toBeTruthy()
})

it('offers analysis explanation after a saved figure without locking on background work', async () => {
  const onBusyChange = vi.fn()
  const fetch = vi.fn((url: string, _init?: RequestInit) => json((url === '/api/v1/ai/plot-config' || url === '/api/v1/ai/explanation-config')
    ? { configured: true, model: 'model', message: '' }
    : url.endsWith('/explanation') ? { current_revision: 1, is_current: true, figure_id: 'figure', explanation: null, job: { id: 'job', status: 'running', message: '解释生成中', response_id: null, created_at: '' } }
    : { ...empty, figure }))
  vi.stubGlobal('fetch', fetch); render(<BoxplotFigure {...props} onBusyChange={onBusyChange} />)
  expect(await screen.findByText('分析解释')).toBeTruthy()
  await screen.findByText('云端任务正在运行，请稍候。')
  await waitFor(() => expect(onBusyChange).toHaveBeenLastCalledWith(false))
  expect((screen.getByRole('button', { name: '使用 OpenAI 生成箱线图' }) as HTMLButtonElement).disabled).toBe(false)
})

it('releases plot controls when a restored explanation task completes without deadlock', async () => {
  vi.useFakeTimers(); let reads = 0; const onBusyChange = vi.fn()
  const fetch = vi.fn((url: string, _init?: RequestInit) => json((url === '/api/v1/ai/plot-config' || url === '/api/v1/ai/explanation-config') ? { configured: true }
    : url.endsWith('/explanation') ? { current_revision: 1, is_current: true, figure_id: 'figure', explanation: null,
      job: reads++ === 0 ? { id: 'job', status: 'running', message: '解释生成中', response_id: null, created_at: '' } : null }
    : { ...empty, figure }))
  vi.stubGlobal('fetch', fetch); render(<BoxplotFigure {...props} onBusyChange={onBusyChange} />); await act(async () => {})
  expect((screen.getByRole('button', { name: '重新读取图表' }) as HTMLButtonElement).disabled).toBe(false)
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

it('shows readable artifact details without system metadata', async () => { vi.stubGlobal('fetch', api({ ...empty, figure })); render(<BoxplotFigure {...props} />); await screen.findByAltText(figure.title); expect(screen.queryAllByText(/SHA256|配置版本|统计结果编号|boxplot-v1/)).toHaveLength(0); expect(screen.getByText(/统计核对一致/)).toBeTruthy(); expect(screen.getByText(/横轴：分组；纵轴：测量值/)).toBeTruthy() })

it('keeps each later stage understandable when no chart has been saved', async () => {
  const fetch = api(); vi.stubGlobal('fetch', fetch)
  render(<WorkflowProvider><WorkflowNavigation /><BoxplotFigure {...props} /></WorkflowProvider>)
  await act(async () => {})
  fireEvent.click(screen.getByRole('button', { name: '分析解释' }))
  expect(screen.getByRole('heading', { name: '分析解释与论文表述' })).toBeTruthy()
  expect(screen.getByText('请先生成并保存箱线图，再生成分析解释。').closest('[hidden]')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Word报告' }))
  expect(screen.getByRole('heading', { name: 'Word 分析报告导出' })).toBeTruthy()
  expect(screen.getByText('请先完成图表和分析解释，再生成 Word 报告。').closest('[hidden]')).toBeNull()
  expect(fetch.mock.calls.some(([url]) => url.endsWith('/explanation') || url.endsWith('/report'))).toBe(false)
})
it('keeps explanation polling mounted while switching between workflow stages', async () => {
  vi.useFakeTimers(); let reads = 0; const onBusyChange = vi.fn()
  const saved = { id: 'exp', analysis_run_id: 'run', figure_id: 'figure', setup_revision: 1, language: 'zh-CN', created_at: 'today', sections: [{ key: 'results', title: '研究结果', text: '中位数为3。', evidence: [] }], limitations: [], verification: { note: '统计证据已核对' } }
  const fetch = vi.fn((url: string) => json((url === '/api/v1/ai/plot-config' || url === '/api/v1/ai/explanation-config') ? { configured: true }
    : url.endsWith('/explanation') ? { current_revision: 1, is_current: true, figure_id: 'figure', explanation: reads++ === 0 ? null : saved, job: reads === 1 ? { status: 'running' } : null }
    : url.endsWith('/report') ? { current_revision: 1, is_current: true, ready: true, issues: [], report: null } : { ...empty, figure }))
  vi.stubGlobal('fetch', fetch)
  render(<WorkflowProvider><WorkflowNavigation /><BoxplotFigure {...props} onBusyChange={onBusyChange} /></WorkflowProvider>); await act(async () => {})
  fireEvent.click(screen.getByRole('button', { name: '图表' }))
  expect(onBusyChange).toHaveBeenLastCalledWith(false)
  fireEvent.click(screen.getByRole('button', { name: 'Word报告' }))
  await act(async () => { vi.advanceTimersByTime(3000) })
  expect(onBusyChange).toHaveBeenLastCalledWith(false)
  expect(screen.getByRole('button', { name: '生成 Word 报告' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '分析解释' }))
  expect(screen.getByText('中位数为3。').closest('[hidden]')).toBeNull()
  expect(reads).toBe(2)
})
