import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import ProjectSummary from './ProjectSummary'
import { clearApiSession, setApiSession } from './api'
import { summaryFixture } from './test/summaryFixture'

beforeEach(() => { setApiSession('summary-test') })
afterEach(() => { cleanup(); clearApiSession(); vi.useRealTimers(); vi.unstubAllGlobals() })
const source = { id: 'job', file_id: 'f1', filename: '研究.xlsx', analysis_run_id: 'r1',
  setup_revision: 1, current_revision: 2, engine_version: 'test-v1', recorded_at: '2026-10-03T08:00:00Z',
  figure_id: null, explanation_id: null }
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}

test.each(['sci', 'thesis'] as const)('shows honest empty states for %s without inferring progress', async kind => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json(summaryFixture('p1', kind))))
  render(<ProjectSummary projectId="p1" projectType={kind} />)
  expect(await screen.findByText('还没有已保存的分析任务记录。')).toBeTruthy()
  expect(screen.getByText('还没有已生成的 PNG 或 Word 文件。')).toBeTruthy()
  expect(screen.getByText(kind === 'sci' ? 'SCI 期刊与投稿' : '学校与毕业论文评审')).toBeTruthy()
  expect(screen.queryByText(kind === 'thesis' ? 'SCI 期刊与投稿' : '学校与毕业论文评审')).toBeNull()
  expect(screen.getByText('当前稿件：无记录')).toBeTruthy()
  expect(screen.getByText('当前修改轮次：无记录')).toBeTruthy()
  expect(screen.getAllByText('功能未开放').length).toBe(3)
  expect(screen.getByText(/任务完成不代表/)).toBeTruthy()
})

test('shows each persisted task status, old source revision and protected artifact downloads', async () => {
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
  expect(screen.getAllByText('配置 v1 · 当前 v2（历史配置）').length).toBe(8)
  expect(screen.getByRole('link', { name: '下载成果 图表.png' }).getAttribute('href')).toContain('/figures/figure/download')
  expect(screen.getByRole('link', { name: '下载成果 报告.docx' }).getAttribute('href')).toContain('/report/report/download')
  expect(screen.getByText('实际投稿进展：无记录')).toBeTruthy()
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
  expect(screen.queryByText('SCI 期刊与投稿')).toBeNull()
})

test('times out even when fetch ignores abort and ignores a later response', async () => {
  vi.useFakeTimers()
  const pending = deferred<Response>()
  vi.stubGlobal('fetch', vi.fn(() => pending.promise))
  render(<ProjectSummary projectId="p1" projectType="sci" />)
  await act(async () => { await vi.advanceTimersByTimeAsync(15_000) })
  expect(screen.getByRole('alert').textContent).toBe('项目摘要读取超时，请重试。')
  await act(async () => { pending.resolve(Response.json(summaryFixture())) })
  expect(screen.queryByText('SCI 期刊与投稿')).toBeNull()
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
  await screen.findByText('SCI 期刊与投稿')
  fireEvent.click(screen.getByRole('button', { name: '刷新项目摘要' }))
  act(() => { setApiSession('other-user') })
  await act(async () => { pending.resolve(Response.json(summaryFixture())) })
  expect(screen.queryByText('SCI 期刊与投稿')).toBeNull()
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
