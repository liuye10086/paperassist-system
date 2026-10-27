import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import ProjectSummary from './ProjectSummary'
import { clearApiSession, setApiSession } from '../../shared/api/client'
import { summaryFixture } from '../../test/fixtures/summaryFixture'
import { setLocale } from '../../shared/i18n'
import {isProjectSummary} from './projectSummaryTypes'

beforeEach(() => { setApiSession('summary-test') })
afterEach(() => { cleanup(); clearApiSession(); setLocale('zh-CN'); vi.useRealTimers(); vi.unstubAllGlobals() })
const source = { id: 'job', file_id: 'f1', filename: '研究.xlsx', analysis_run_id: 'r1',
  setup_revision: 1, current_revision: 2, engine_version: 'test-v1', recorded_at: '2026-10-03T08:00:00Z',
  figure_id: null, explanation_id: null }
test('shows only the latest confirmed target and its own independently recorded progress',async()=>{
 const event={id:'e1',project_id:'p1',target_id:'target1',status:'submitted',event_date:'2026-10-23',note:'本人记录',manuscript:null,export_id:null,corrects_event_id:null,created_at:'2026-10-23T00:00:00Z',recorded_by:'me'}
 const fixture={...summaryFixture(),journal:{target_id:'target1',profile_name:'Fixed Journal',recommendation_id:'rec1',confirmed_at:'2026-10-23T00:00:00Z',progress:event}}
 expect(isProjectSummary({...fixture,journal:{...fixture.journal,progress:{...event,target_id:'other'}}},'p1','sci',1,1)).toBe(false)
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json(fixture)))
 render(<ProjectSummary projectId="p1" projectType="sci"/>);const region=await screen.findByRole('region',{name:'目标期刊与实际进展'})
 expect(region.textContent).toContain('Fixed Journal');expect(region.textContent).toContain('rec1');expect(region.textContent).toContain('已投稿');expect(region.textContent).toContain('本人记录')
})
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}

test('shows queued Word tasks without inventing an artifact and translates their status', async () => {
  const fixture = summaryFixture()
  const fetch = vi.fn(async () => Response.json({ ...fixture,
    tasks: { ...fixture.tasks, total: 1, items: [{ ...source, kind: 'report', status: 'queued' }] } }))
  vi.stubGlobal('fetch', fetch)
  render(<ProjectSummary projectId="p1" projectType="sci" />)
  expect(await screen.findByText('待执行')).toBeTruthy()
  expect(screen.getByText('Word 报告导出')).toBeTruthy()
  expect(screen.queryByRole('link')).toBeNull()
  act(() => setLocale('en'))
  expect(screen.getByText('Queued')).toBeTruthy(); expect(fetch).toHaveBeenCalledTimes(1)
})

test.each(['sci', 'thesis'] as const)('shows honest empty states for %s without inferring progress', async kind => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json(summaryFixture('p1', kind))))
  render(<ProjectSummary projectId="p1" projectType={kind} />)
  expect(await screen.findByText('还没有已保存的分析任务记录。')).toBeTruthy()
  expect(screen.getByText('还没有已生成的 PNG 或 Word 文件。')).toBeTruthy()
  expect(screen.getByText(kind === 'sci' ? '期刊目标适配与投稿进展' : '学校与毕业论文评审')).toBeTruthy()
  expect(screen.queryByText(kind === 'thesis' ? '期刊目标适配与投稿进展' : '学校与毕业论文评审')).toBeNull()
  expect(screen.getByText('写作与修改')).toBeTruthy()
  expect(screen.getAllByText('功能未开放').length).toBe(1)
  expect(screen.queryByText(/任务完成不代表/)).toBeNull()
})

test('shows each persisted task status, readable historical source and protected artifact downloads', async () => {
  const fixture = summaryFixture()
  const statuses = ['submitting', 'running', 'completed', 'failed', 'uncertain', 'unknown']
  const response = { ...fixture,
    tasks: { ...fixture.tasks, total: 6, items: statuses.map((status, i) => ({ ...source, id: `j${i}`, kind: 'boxplot', status })) },
    artifacts: { ...fixture.artifacts, total: 2, items: ['figure', 'report'].map(kind => ({ ...source,
      kind, id: kind, download_filename: kind === 'figure' ? '图表.png' : '报告.docx', size_bytes: 100,
      sha256: 'a'.repeat(64), download_url: `/api/v1/projects/p1/files/f1/analysis-runs/r1/${kind === 'figure' ? 'figures' : 'report'}/${kind}/download`,
    })) },
  }
  vi.stubGlobal('fetch', vi.fn(async () => Response.json(response)))
  render(<ProjectSummary projectId="p1" projectType="sci" />)
  for (const label of ['提交中', '运行中', '已完成', '失败', '结果不确定', '状态未知']) {
    expect(await screen.findByText(label)).toBeTruthy()
  }
  expect(screen.getAllByText('历史结果').length).toBe(8)
  expect(screen.getByRole('link', { name: '下载成果 图表.png' }).getAttribute('href')).toContain('/figures/figure/download')
  expect(screen.getByRole('link', { name: '下载成果 报告.docx' }).getAttribute('href')).toContain('/report/report/download')
  expect(screen.getByText('期刊目标适配与投稿进展')).toBeTruthy()
})

test('renders readable source context without internal identifiers, versions or hidden source details', async () => {
  const fixture = summaryFixture()
  const technical = { ...source, id: 'INTERNAL-TASK', file_id: 'INTERNAL-FILE', analysis_run_id: 'INTERNAL-ANALYSIS',
    figure_id: 'INTERNAL-FIGURE', explanation_id: 'INTERNAL-EXPLANATION', engine_version: 'INTERNAL-ENGINE',
    setup_revision: 87123, raw_source: 'INTERNAL-RAW-SOURCE', sha256: 'b'.repeat(64) }
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ ...fixture, tasks: { ...fixture.tasks, total: 3, items: [
    { ...technical, kind: 'statistics', status: 'completed', current_revision: 87123 },
    { ...technical, id: 'INTERNAL-HISTORICAL', kind: 'boxplot', status: 'completed', current_revision: 98765 },
    { ...technical, id: 'INTERNAL-UNKNOWN', kind: 'explanation', status: 'unknown', current_revision: null },
  ] } })))
  const { container } = render(<ProjectSummary projectId="p1" projectType="sci" />)
  expect(await screen.findByText('当前结果')).toBeTruthy()
  expect(screen.getByText('历史结果')).toBeTruthy()
  expect(screen.getByText('当前设置未记录')).toBeTruthy()
  expect(screen.getAllByText('研究.xlsx')).toHaveLength(3)
  expect(container.textContent).not.toMatch(/INTERNAL-|87123|98765|记录 ID|文件 ID|工具版本|配置 v/)
  expect(container.textContent).not.toContain('b'.repeat(64))
  expect(container.querySelector('details')).toBeNull()
})

test('refreshes only when entering artifacts and keeps independent task and artifact pages', async () => {
  const fetch = vi.fn(async (url: string) => {
    const params = new URL(url, 'http://localhost').searchParams
    const taskPage = Number(params.get('task_page')), artifactPage = Number(params.get('artifact_page'))
    const fixture = summaryFixture()
    return Response.json({ ...fixture,
      tasks: { ...fixture.tasks, page: taskPage, total: 11, items: [{ ...source, filename: `task-page-${taskPage}.xlsx`, kind: 'statistics', status: 'completed' }] },
      artifacts: { ...fixture.artifacts, page: artifactPage, total: 11, items: [{ ...source, kind: 'figure', download_filename: `figure-page-${artifactPage}.png`,
        size_bytes: 100, sha256: 'a'.repeat(64), download_url: '/api/v1/projects/p1/files/f1/analysis-runs/r1/figures/job/download' }] },
    })
  })
  vi.stubGlobal('fetch', fetch)
  const user = userEvent.setup()
  const view = render(<ProjectSummary projectId="p1" projectType="sci" view="overview" />)
  await screen.findByRole('table', { name: '分析任务记录' })
  expect(screen.getByRole('heading', { name: '项目任务概览' })).toBeTruthy()
  expect(screen.queryByRole('link', { name: /下载成果/ })).toBeNull()
  await user.click(screen.getByRole('button', { name: '任务下一页' }))
  await screen.findByText('task-page-2.xlsx')
  expect(fetch).toHaveBeenCalledTimes(2)
  view.rerender(<ProjectSummary projectId="p1" projectType="sci" view="artifacts" />)
  expect(screen.getByRole('heading', { name: '图表与报告' })).toBeTruthy()
  expect(screen.queryByRole('table', { name: '分析任务记录' })).toBeNull()
  expect(await screen.findByRole('link', { name: '下载成果 figure-page-1.png' })).toBeTruthy()
  expect(fetch).toHaveBeenCalledTimes(3)
  expect(fetch.mock.calls.at(-1)![0]).toContain('task_page=2&artifact_page=1&page_size=10')
  await user.click(screen.getByRole('button', { name: '成果下一页' }))
  await screen.findByRole('link', { name: '下载成果 figure-page-2.png' })
  expect(fetch).toHaveBeenCalledTimes(4)
  expect(fetch.mock.calls.at(-1)![0]).toContain('task_page=2&artifact_page=2')
  view.rerender(<ProjectSummary projectId="p1" projectType="sci" view="overview" />)
  expect(within(screen.getByRole('table', { name: '分析任务记录' })).getByText('task-page-2.xlsx')).toBeTruthy()
  expect(screen.getByRole('navigation', { name: '任务分页' }).textContent).toContain('第 2 / 2 页')
  expect(fetch).toHaveBeenCalledTimes(4)
  view.rerender(<ProjectSummary projectId="p1" projectType="sci" view="artifacts" />)
  expect(await screen.findByRole('link', { name: '下载成果 figure-page-2.png' })).toBeTruthy()
  expect(fetch).toHaveBeenCalledTimes(5)
  expect(fetch.mock.calls.at(-1)![0]).toContain('task_page=2&artifact_page=2&page_size=10')
  view.rerender(<ProjectSummary projectId="p1" projectType="sci" view="artifacts" />)
  expect(screen.getByRole('link', { name: '下载成果 figure-page-2.png' })).toBeTruthy()
  expect(fetch).toHaveBeenCalledTimes(5)
})

test.each(['figure', 'report'] as const)('loads a newly generated %s when entering artifacts after an empty summary', async kind => {
  const pending = deferred<Response>()
  const fixture = summaryFixture()
  const filename = kind === 'figure' ? '新图表.png' : '新报告.docx'
  const fetch = vi.fn()
    .mockResolvedValueOnce(Response.json(fixture))
    .mockReturnValueOnce(pending.promise)
  vi.stubGlobal('fetch', fetch)
  const view = render(<ProjectSummary projectId="p1" projectType="sci" view="overview" />)
  await screen.findByText('还没有已保存的分析任务记录。')
  expect(fetch).toHaveBeenCalledTimes(1)

  view.rerender(<ProjectSummary projectId="p1" projectType="sci" view="artifacts" />)
  expect(screen.queryByText('还没有已生成的 PNG 或 Word 文件。')).toBeNull()
  expect(screen.getByRole('status').textContent).toBe('正在读取项目摘要……')
  await act(async () => { pending.resolve(Response.json({ ...fixture, artifacts: { ...fixture.artifacts, total: 1,
    items: [{ ...source, kind, download_filename: filename, size_bytes: 100, sha256: 'a'.repeat(64),
      download_url: `/api/v1/projects/p1/files/f1/analysis-runs/r1/${kind === 'figure' ? 'figures' : 'report'}/job/download` }] } })) })
  expect(await screen.findByRole('link', { name: `下载成果 ${filename}` })).toBeTruthy()
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(fetch.mock.calls.at(-1)![0]).toBe('/api/v1/projects/p1/summary?task_page=1&artifact_page=1&page_size=10')
})

test('recovers from a previous failed summary when entering artifacts', async () => {
  const pending = deferred<Response>()
  const fetch = vi.fn()
    .mockRejectedValueOnce(new TypeError('offline'))
    .mockReturnValueOnce(pending.promise)
  vi.stubGlobal('fetch', fetch)
  const view = render(<ProjectSummary projectId="p1" projectType="sci" view="overview" />)
  expect(await screen.findByRole('alert')).toHaveProperty('textContent', '项目摘要读取失败，请重试。')

  view.rerender(<ProjectSummary projectId="p1" projectType="sci" view="artifacts" />)
  expect(screen.queryByRole('alert')).toBeNull()
  expect(screen.getByRole('status').textContent).toBe('正在读取项目摘要……')
  await act(async () => { pending.resolve(Response.json(summaryFixture())) })
  expect(await screen.findByText('还没有已生成的 PNG 或 Word 文件。')).toBeTruthy()
  expect(screen.queryByRole('alert')).toBeNull()
  expect(fetch).toHaveBeenCalledTimes(2)
})

test('reloads artifacts when becoming active again without changing the summary view', async () => {
  const pending = deferred<Response>()
  const fixture = summaryFixture()
  const fetch = vi.fn()
    .mockResolvedValueOnce(Response.json(fixture))
    .mockReturnValueOnce(pending.promise)
  vi.stubGlobal('fetch', fetch)
  const view = render(<ProjectSummary projectId="p1" projectType="sci" view="artifacts" active />)
  await screen.findByText('还没有已生成的 PNG 或 Word 文件。')
  expect(fetch).toHaveBeenCalledTimes(1)

  view.rerender(<ProjectSummary projectId="p1" projectType="sci" view="artifacts" active={false} />)
  expect(fetch).toHaveBeenCalledTimes(1)
  view.rerender(<ProjectSummary projectId="p1" projectType="sci" view="artifacts" active />)
  expect(screen.queryByText('还没有已生成的 PNG 或 Word 文件。')).toBeNull()
  expect(screen.getByRole('status').textContent).toBe('正在读取项目摘要……')
  await act(async () => { pending.resolve(Response.json({ ...fixture, artifacts: { ...fixture.artifacts, total: 1,
    items: [{ ...source, kind: 'report', download_filename: '新报告.docx', size_bytes: 100, sha256: 'a'.repeat(64),
      download_url: '/api/v1/projects/p1/files/f1/analysis-runs/r1/report/job/download' }] } })) })
  expect(await screen.findByRole('link', { name: '下载成果 新报告.docx' })).toBeTruthy()
  expect(fetch).toHaveBeenCalledTimes(2)
  view.rerender(<ProjectSummary projectId="p1" projectType="sci" view="artifacts" active />)
  expect(fetch).toHaveBeenCalledTimes(2)
})

test('aborts an older summary request when entering artifacts and ignores its late response', async () => {
  const pending = deferred<Response>()
  const fixture = summaryFixture()
  const fetch = vi.fn()
    .mockReturnValueOnce(pending.promise)
    .mockResolvedValueOnce(Response.json(fixture))
  vi.stubGlobal('fetch', fetch)
  const view = render(<ProjectSummary projectId="p1" projectType="sci" view="overview" />)
  const previousSignal = fetch.mock.calls[0][1].signal as AbortSignal

  view.rerender(<ProjectSummary projectId="p1" projectType="sci" view="artifacts" />)
  expect(previousSignal.aborted).toBe(true)
  await screen.findByText('还没有已生成的 PNG 或 Word 文件。')
  await act(async () => { pending.resolve(Response.json({ ...fixture, artifacts: { ...fixture.artifacts, total: 1,
    items: [{ ...source, kind: 'figure', download_filename: '旧图表.png', size_bytes: 100, sha256: 'a'.repeat(64),
      download_url: '/api/v1/projects/p1/files/f1/analysis-runs/r1/figures/job/download' }] } })) })
  expect(screen.queryByRole('link', { name: '下载成果 旧图表.png' })).toBeNull()
  expect(screen.getByText('还没有已生成的 PNG 或 Word 文件。')).toBeTruthy()
  expect(fetch).toHaveBeenCalledTimes(2)
})

test('translates readable source labels without translating filenames or refetching', async () => {
  const fixture = summaryFixture()
  const fetch = vi.fn(async () => Response.json({ ...fixture, tasks: { ...fixture.tasks, total: 1,
    items: [{ ...source, kind: 'statistics', status: 'completed', current_revision: 1 }] } }))
  vi.stubGlobal('fetch', fetch)
  render(<ProjectSummary projectId="p1" projectType="sci" view="overview" />)
  await screen.findByText('研究.xlsx')
  act(() => setLocale('en'))
  expect(screen.getByRole('heading', { name: 'Project task overview' })).toBeTruthy()
  expect(screen.getByText('Current result')).toBeTruthy()
  expect(screen.getByText('研究.xlsx')).toBeTruthy()
  expect(fetch).toHaveBeenCalledTimes(1)
})

test('paginates tasks independently and retries a failed refresh without stale success', async () => {
  let failure = false
  const fetch = vi.fn(async (url: string) => {
    if (failure) throw new TypeError('offline')
    const params = new URL(url, 'http://localhost').searchParams
    const fixture = summaryFixture()
    const page = Number(params.get('task_page'))
    return Response.json({ ...fixture, tasks: { ...fixture.tasks, page, total: 11,
      items: [{ ...source, id: `task-${page}`, filename: `page-${page}.xlsx`, kind: 'statistics', status: 'completed' }] } })
  })
  vi.stubGlobal('fetch', fetch)
  const user = userEvent.setup()
  render(<ProjectSummary projectId="p1" projectType="sci" />)
  await screen.findByText('page-1.xlsx')
  await user.click(screen.getByRole('button', { name: '任务下一页' }))
  await screen.findByText('page-2.xlsx')
  expect(fetch.mock.calls.at(-1)![0]).toContain('artifact_page=1')
  failure = true
  await user.click(screen.getByRole('button', { name: '刷新项目摘要' }))
  expect(await screen.findByRole('alert')).toHaveProperty('textContent', '项目摘要读取失败，请重试。')
  expect(screen.queryByText('page-2.xlsx')).toBeNull()
  failure = false
  await user.click(screen.getByRole('button', { name: '重试项目摘要' }))
  expect(await screen.findByText('page-2.xlsx')).toBeTruthy()
})

test('ignores delayed response bodies after switching projects', async () => {
  const body = deferred<unknown>()
  let started = false
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.includes('/p2/')) return Response.json(summaryFixture('p2', 'thesis'))
    const response = Response.json({})
    response.json = () => { started = true; return body.promise }
    return response
  }))
  const view = render(<ProjectSummary projectId="p1" projectType="sci" />)
  await act(async () => { await Promise.resolve() })
  expect(started).toBe(true)
  view.rerender(<ProjectSummary projectId="p2" projectType="thesis" />)
  await screen.findByText('学校与毕业论文评审')
  await act(async () => { body.resolve(summaryFixture('p1')) })
  expect(screen.queryByText('期刊目标适配与投稿进展')).toBeNull()
})

test('times out even when fetch ignores abort and ignores a later response', async () => {
  vi.useFakeTimers()
  const pending = deferred<Response>()
  vi.stubGlobal('fetch', vi.fn(() => pending.promise))
  render(<ProjectSummary projectId="p1" projectType="sci" />)
  await act(async () => { await vi.advanceTimersByTimeAsync(15_000) })
  expect(screen.getByRole('alert').textContent).toBe('项目摘要读取超时，请重试。')
  await act(async () => { pending.resolve(Response.json(summaryFixture())) })
  expect(screen.queryByText('期刊目标适配与投稿进展')).toBeNull()
})

test('rejects malformed or mismatched response data without fabricating an empty summary', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ ...summaryFixture(), project_id: 'another' })))
  render(<ProjectSummary projectId="p1" projectType="sci" />)
  expect(await screen.findByRole('alert')).toBeTruthy()
  expect(screen.queryByText('还没有已保存的分析任务记录。')).toBeNull()
})

test('clears saved summary when the session changes and ignores late responses', async () => {
  const pending = deferred<Response>()
  let calls = 0
  vi.stubGlobal('fetch', vi.fn(() => ++calls === 1 ? Promise.resolve(Response.json(summaryFixture())) : pending.promise))
  render(<ProjectSummary projectId="p1" projectType="sci" />)
  await screen.findByText('期刊目标适配与投稿进展')
  fireEvent.click(screen.getByRole('button', { name: '刷新项目摘要' }))
  act(() => { setApiSession('other-user') })
  await act(async () => { pending.resolve(Response.json(summaryFixture())) })
  expect(screen.queryByText('期刊目标适配与投稿进展')).toBeNull()
  expect(within(screen.getByRole('region', { name: '项目任务与成果' })).queryByRole('link')).toBeNull()
})

test('paginates artifacts independently and returns to the last valid page after records shrink', async () => {
  let shrunk = false
  const fetch = vi.fn(async (url: string) => {
    const page = Number(new URL(url, 'http://localhost').searchParams.get('artifact_page'))
    const fixture = summaryFixture()
    return Response.json({ ...fixture, artifacts: { ...fixture.artifacts, page, total: shrunk ? 0 : 11,
      items: shrunk ? [] : [{ ...source, kind: 'figure', download_filename: `figure-page-${page}.png`,
        size_bytes: 100, sha256: 'a'.repeat(64), download_url: '/api/v1/projects/p1/files/f1/analysis-runs/r1/figures/job/download' }] } })
  })
  vi.stubGlobal('fetch', fetch)
  const user = userEvent.setup()
  render(<ProjectSummary projectId="p1" projectType="sci" />)
  await screen.findByText('figure-page-1.png')
  await user.click(screen.getByRole('button', { name: '成果下一页' }))
  await screen.findByText('figure-page-2.png')
  expect(fetch.mock.calls.at(-1)![0]).toContain('task_page=1&artifact_page=2')
  shrunk = true
  await user.click(screen.getByRole('button', { name: '刷新项目摘要' }))
  await screen.findByText('还没有已生成的 PNG 或 Word 文件。')
  expect(fetch.mock.calls.at(-1)![0]).toContain('artifact_page=1')
})

test('rejects downloads outside the requested project resource path', async () => {
  const fixture = summaryFixture()
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ ...fixture, artifacts: { ...fixture.artifacts, total: 1,
    items: [{ ...source, kind: 'figure', download_filename: 'external.png', size_bytes: 100, sha256: 'a'.repeat(64),
      download_url: 'https://untrusted.example/asset.png' }] } })))
  render(<ProjectSummary projectId="p1" projectType="sci" />)
  await screen.findByRole('alert')
  expect(screen.queryByRole('link')).toBeNull()
})

test('uses readable names for actual system artifacts while preserving source names and download routes', async () => {
  const fixture = summaryFixture()
  const figureId = '8ba6da0a-193d-45bf-8e68-60f837d88c02'
  const reportId = 'a1b2c3d4-1234-4567-8901-123456789abc'
  const artifacts = [
    { ...source, id: figureId, kind: 'figure', setup_revision: 12, filename: '样本编号-v12-a1b2c3d4.xlsx', download_filename: `boxplot-${figureId}.png`, download_url: `/api/v1/projects/p1/files/f1/analysis-runs/r1/figures/${figureId}/download`, size_bytes: 100, sha256: 'a'.repeat(64) },
    { ...source, id: reportId, kind: 'report', setup_revision: 12, download_filename: '分析报告-v12-a1b2c3d4.docx', download_url: `/api/v1/projects/p1/files/f1/analysis-runs/r1/report/${reportId}/download`, size_bytes: 100, sha256: 'a'.repeat(64) },
  ]
  vi.stubGlobal('URL', class extends URL { static createObjectURL = vi.fn(() => 'blob:artifact'); static revokeObjectURL = vi.fn() })
  const names: string[] = []
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { names.push(this.download) })
  const fetcher = vi.fn(async (url: string) => url.includes('/summary?') ? Response.json({ ...fixture, artifacts: { ...fixture.artifacts, total: 2, items: artifacts } }) : new Response('saved bytes'))
  vi.stubGlobal('fetch', fetcher)
  const { container } = render(<ProjectSummary projectId="p1" projectType="sci" view="artifacts" />)
  const figureLink = await screen.findByRole('link', { name: '下载成果 boxplot.png' })
  const reportLink = screen.getByRole('link', { name: '下载成果 分析报告.docx' })
  expect(figureLink.getAttribute('href')).toBe(artifacts[0].download_url)
  expect(reportLink.getAttribute('href')).toBe(artifacts[1].download_url)
  expect(screen.getByText('样本编号-v12-a1b2c3d4.xlsx')).toBeTruthy()
  expect(container.textContent).not.toContain(figureId)
  expect(container.textContent).not.toContain('分析报告-v12-a1b2c3d4.docx')
  try {
    const user = userEvent.setup()
    await user.click(figureLink); await user.click(reportLink)
    expect(names).toEqual(['boxplot.png', '分析报告.docx'])
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/download')).map(([url]) => url)).toEqual(artifacts.map(item => item.download_url))
    act(() => setLocale('en'))
    expect(screen.getByText('样本编号-v12-a1b2c3d4.xlsx')).toBeTruthy()
    expect(fetcher.mock.calls.filter(([url]) => url.includes('/summary?'))).toHaveLength(1)
    await user.click(screen.getByRole('link', { name: 'Download artifact analysis-report.docx' }))
    expect(names).toEqual(['boxplot.png', '分析报告.docx', 'analysis-report.docx'])
  } finally { click.mockRestore() }
})

test('configured PNGs and collection exports have exact routes and readable multiple-result context', async()=>{
 const fixture=summaryFixture()
 const figure={...source,id:'new-line-id',kind:'figure',figure_kind:'line',figure_config_version_id:'config-version',download_filename:'line-new-line-id.png',size_bytes:120,sha256:'a'.repeat(64),download_url:'/api/v1/projects/p1/files/f1/analysis-runs/r1/figure-workbench/figures/new-line-id/png'}
 const report={...source,id:'collection-report-id',kind:'report',analysis_run_id:null,setup_revision:null,current_revision:null,collection_id:'collection-id',collection_version_id:'collection-version-id',collection_revision:2,export_revision:3,collection_title:'Cohort overview',result_count:2,download_filename:'Analysis-report-v3-collecti.docx',size_bytes:220,sha256:'b'.repeat(64),download_url:'/api/v1/projects/p1/report-collections/collection-id/reports/collection-report-id/download'}
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({...fixture,artifacts:{...fixture.artifacts,total:2,items:[figure,report]}})))
 const {container}=render(<ProjectSummary projectId='p1' projectType='sci' view='artifacts'/>)
 const line=await screen.findByRole('link',{name:'下载成果 line.png'})
 expect(line.getAttribute('href')).toBe(figure.download_url)
 expect(screen.getByText('Cohort overview')).toBeTruthy()
 expect(screen.getByText('集合版本 2 · 导出版本 3 · 2 个分析结果')).toBeTruthy()
 expect(screen.getByRole('link',{name:'下载成果 集合报告-v2-导出3.docx'}).getAttribute('href')).toBe(report.download_url)
 expect(container.textContent).not.toMatch(/collection-id|collection-version-id|collection-report-id|new-line-id|config-version|collecti\.docx/)
 act(()=>setLocale('en'))
 expect(screen.getByText('Collection version 2 · Export 3 · 2 analysis results')).toBeTruthy()
 expect(screen.getByRole('link',{name:'Download artifact collection-report-v2-export3.docx'})).toBeTruthy()
})

test('shows the latest layout export records separately with exact DOCX and task links',async()=>{
 const hash='a'.repeat(64),row={id:'layout1',project_id:'p1',source_kind:'report',source_id:'report1',source_sha256:hash,status:'succeeded',task_id:'layout-task',created_at:'2026-10-20T00:00:00Z',layout:{source_sha256:hash,formulas:[],references:[],headings:[],toc:null,pagination:null,landscape_anchor_ids:[]},layout_version:'document_layout_v1',output_language:'en',request_key:'key',can_retry:false,parent_export_id:null,filename:'layout.docx',error_code:null,renderer_manifest:{},sha256:'b'.repeat(64),size_bytes:100,download_url:'/api/v1/projects/p1/layout-exports/layout1/download'}
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({...summaryFixture(),layout_exports:[row]})));render(<ProjectSummary projectId="p1" projectType="sci" view="artifacts"/>);fireEvent.click(await screen.findByRole('button',{name:'排版导出记录'}));const link=await screen.findByRole('link',{name:'下载排版 DOCX'});expect(link.getAttribute('href')).toBe(row.download_url);expect(screen.getByRole('link',{name:'查看排版任务'}).getAttribute('href')).toContain('task=layout-task')
})

test('shows the actual school manuscript title and saved versions in the overview',async()=>{
 const fixture=summaryFixture('p1','thesis'),onOpen=vi.fn()
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({...fixture,future:{...fixture.future,writing:{state:'available',current_manuscript:{id:'school1',title:'实际学校稿件',current_revision:2},versions:[{id:'v1',manuscript_id:'school1',revision:1},{id:'v2',manuscript_id:'school1',revision:2}],tasks:[]}}})))
 render(<ProjectSummary projectId="p1" projectType="thesis" onOpenManuscripts={onOpen}/>)
 expect(await screen.findByText('实际学校稿件')).toBeTruthy();expect(screen.getByText('已保存版本 2')).toBeTruthy();fireEvent.click(screen.getByRole('button',{name:'打开毕业论文写作'}));expect(onOpen).toHaveBeenCalledTimes(1)
})

test('distinguishes same-number opinions from different sources in the summary',async()=>{
 const fixture=summaryFixture();vi.stubGlobal('fetch',vi.fn(async()=>Response.json({...fixture,future:{...fixture.future,revision:{state:'available',tasks:[],current_round:{id:'round1',title:'合成意见',round_number:1,revision:1,synthetic:true,manuscript:{id:'m1',revision:1,version_id:'v1',title:'固定稿'}},rounds:[],opinions:['Reviewer 1','Reviewer 2'].map((source_label,n)=>({id:'i'+n,source_id:'s'+n,source_label,number:1,category:'method',status:'pending',uncompleted_reason:''})),pending_materials:[]}}})));render(<ProjectSummary projectId="p1" projectType="sci"/>);expect(await screen.findByText('Reviewer 1 · 意见 1 · 待处理')).toBeTruthy();expect(screen.getByText('Reviewer 2 · 意见 1 · 待处理')).toBeTruthy()
})
