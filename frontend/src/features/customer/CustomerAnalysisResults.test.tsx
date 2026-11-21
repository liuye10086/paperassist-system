// B05 task 4 (D3, wireframes 17②③ and 18): a read-only list of the customer's published analysis results,
// opened inside a paper project with a return token.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { watchProjectAccess } from '../../shared/api/projectAccess'
import { setLocale } from '../../shared/i18n'
import { findTechnicalText } from '../../test/technicalText'
import CustomerAnalysisResults, { type AnalysisPick } from './CustomerAnalysisResults'
import type { ReturnTarget } from './returnToken'

const project = (id: string, name: string) => ({
  id, name, research_topic: '合成课题', project_type: 'research', file_count: 0,
  created_at: '2026-11-01T00:00:00Z', updated_at: '2026-11-01T00:00:00Z',
})
const deliveries = (id: string) => `/api/v1/projects/${id}/customer-workspace/deliveries`
const older = { id: 's1', delivery_id: 'd1', title: '差异分析报告', kind: 'analysis', revision: 1,
  published_at: '2026-11-18T08:00:00Z', member_count: 2 }
const newer = { id: 's2', delivery_id: 'd2', title: '生存分析', kind: 'analysis', revision: 2,
  published_at: '2026-11-19T08:00:00Z', member_count: 1 }
const writing = { id: 's9', delivery_id: 'd9', title: '历史写作稿', kind: 'sci_draft', revision: 1,
  published_at: '2026-11-20T08:00:00Z', member_count: 1 }
const member = (projectId: string, snapshot: string, id: string, name: string, format: string) => ({
  id, name, format, size_bytes: 2048, download_url: `${deliveries(projectId)}/${snapshot}/members/${id}/download`,
})
const detail = {
  ...older, feedback: [], package_url: `${deliveries('ra')}/s1/download`,
  members: [member('ra', 's1', 'x1', '结果表.xlsx', 'xlsx'), member('ra', 's1', 'w1', '报告.docx', 'docx')],
}
const minute = (value: string, locale = 'zh-CN') => new Date(value).toLocaleString(locale,
  { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
const reviewTarget: ReturnTarget = { href: '#customer-project=paper1&step=reviews&view=supplements', label: '第 1 轮 · 意见 3' }
const materialsTarget: ReturnTarget = { href: '#customer-project=paper1&step=materials&view=files', label: '写作资料' }

let clicks: string[]
beforeEach(() => {
  clicks = []
  vi.stubGlobal('URL', class extends URL { static createObjectURL = vi.fn(() => 'blob:x'); static revokeObjectURL = vi.fn() })
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { clicks.push(this.download) })
})
afterEach(() => {
  cleanup()
  setLocale('zh-CN')
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function serve(routes: (url: string) => Response | undefined) {
  const fetch = vi.fn(async (url: string, _init?: RequestInit) => routes(url) ?? new Response(null, { status: 404 }))
  vi.stubGlobal('fetch', fetch)
  return fetch
}

function View({ purpose = 'reviews', target = reviewTarget, onPick = vi.fn(), onReturn = vi.fn() }: {
  purpose?: 'reviews' | 'materials'; target?: ReturnTarget | null; onPick?: (pick: AnalysisPick) => void; onReturn?: (href: string) => void
}) {
  const [selected, setSelected] = useState<{ projectId: string; snapshotId: string } | null>(null)
  return <CustomerAnalysisResults paperProjectId="paper1" purpose={purpose} returnTarget={target} onReturn={onReturn}
    selected={selected} onSelect={setSelected} onPick={onPick} headingRef={{ current: null }} />
}

it('reads every analysis project page and lists only analysis deliveries, newest first', async () => {
  const fillers = Array.from({ length: 99 }, (_, index) => project('rf' + index, '空项目 ' + index))
  const fetch = serve(url => {
    if (url === '/api/v1/projects?type=research&page=1&page_size=100') return Response.json({ items: [project('ra', '分析项目甲'), ...fillers], total: 101, page: 1, page_size: 100 })
    if (url === '/api/v1/projects?type=research&page=2&page_size=100') return Response.json({ items: [project('rb', '分析项目乙')], total: 101, page: 2, page_size: 100 })
    if (url === deliveries('ra')) return Response.json({ items: [writing, older] })
    if (url === deliveries('rb')) return Response.json({ items: [newer] })
    if (url.endsWith('/customer-workspace/deliveries')) return Response.json({ items: [] })
  })
  render(<View />)
  const list = await screen.findByRole('list', { name: '已发布的分析成果' })
  await waitFor(() => expect(within(list).getAllByRole('button')).toHaveLength(2))
  expect(within(list).getAllByRole('button').map(button => button.textContent)).toEqual([
    `分析项目乙 · 生存分析 · ${minute(newer.published_at)}`, `分析项目甲 · 差异分析报告 · ${minute(older.published_at)}`,
  ])
  expect(screen.queryByText(/历史写作稿/)).toBeNull()
  expect(fetch.mock.calls.filter(([url]) => url.startsWith('/api/v1/projects?'))).toHaveLength(2)
  expect(fetch.mock.calls.every(([, init]) => !init?.method || init.method === 'GET')).toBe(true)
})

it('shows the empty state with a primary way back', async () => {
  serve(url => url.startsWith('/api/v1/projects?') ? Response.json({ items: [project('ra', '分析项目甲')], total: 1, page: 1, page_size: 100 })
    : url === deliveries('ra') ? Response.json({ items: [writing] }) : undefined)
  const onReturn = vi.fn()
  render(<View onReturn={onReturn} />)
  expect(await screen.findByText('还没有已发布的分析成果。分析完成后会在这里出现。')).toBeTruthy()
  const back = screen.getByRole('button', { name: '返回 第 1 轮 · 意见 3' })
  expect(back.className).toContain('button-primary')
  fireEvent.click(back)
  expect(onReturn).toHaveBeenCalledWith(reviewTarget.href)
})

it('opens a result, lists Word first for a review and reports the downloaded file', async () => {
  const fetch = serve(url => {
    if (url.startsWith('/api/v1/projects?')) return Response.json({ items: [project('ra', '分析项目甲')], total: 1, page: 1, page_size: 100 })
    if (url === deliveries('ra')) return Response.json({ items: [older] })
    if (url === deliveries('ra') + '/s1') return Response.json(detail)
    if (url.endsWith('/members/w1/download')) return new Response('word bytes')
  })
  const onPick = vi.fn()
  render(<View onPick={onPick} />)
  expect(await screen.findByText('正在为“第 1 轮 · 意见 3”取分析结果')).toBeTruthy()
  fireEvent.click(await screen.findByRole('button', { name: /分析项目甲 · 差异分析报告/ }))
  const files = await screen.findByRole('list', { name: '成果文件' })
  const rows = within(files).getAllByRole('listitem')
  expect(rows[0].textContent).toContain('报告.docx')
  expect(rows[1].textContent).toContain('结果表.xlsx')
  expect(rows[0].querySelector('p')?.textContent).toMatch(/^Word · /)
  expect(rows[1].querySelector('p')?.textContent).toMatch(/^Excel · /)
  expect(rows[1].textContent).toContain('需放进 Word 后再上传')
  expect(rows[0].textContent).not.toContain('需放进 Word 后再上传')
  const link = within(rows[0]).getByRole('link', { name: '下载 报告.docx' })
  expect(link.getAttribute('href')).toBe(`${deliveries('ra')}/s1/members/w1/download`)
  expect(screen.getByRole('link', { name: '下载全部文件' }).getAttribute('href')).toBe(`${deliveries('ra')}/s1/download`)
  expect(screen.queryByText(/下载所需文件后/)).toBeNull()
  fireEvent.click(link)
  expect(await screen.findByText('下载所需文件后，可以返回 第 1 轮 · 意见 3 继续上传。')).toBeTruthy()
  expect(clicks).toEqual(['报告.docx'])
  expect(onPick).toHaveBeenCalledWith({ researchProjectName: '分析项目甲', deliveryTitle: '差异分析报告', memberNames: ['报告.docx'] })
  expect(fetch.mock.calls.every(([, init]) => !init?.method || init.method === 'GET')).toBe(true)
  expect(document.querySelector('details, [aria-expanded]')).toBeNull()
  expect(findTechnicalText(document.body, { systemIds: ['ra', 's1', 'w1', 'x1', 'd1'] })).toEqual([])
})

it('keeps the original order for writing materials and says what it is for', async () => {
  serve(url => {
    if (url.startsWith('/api/v1/projects?')) return Response.json({ items: [project('ra', '分析项目甲')], total: 1, page: 1, page_size: 100 })
    if (url === deliveries('ra')) return Response.json({ items: [older] })
    if (url === deliveries('ra') + '/s1') return Response.json(detail)
  })
  render(<View purpose="materials" target={materialsTarget} />)
  expect(await screen.findByText('正在为“写作资料”取分析成果')).toBeTruthy()
  fireEvent.click(await screen.findByRole('button', { name: /差异分析报告/ }))
  const rows = within(await screen.findByRole('list', { name: '成果文件' })).getAllByRole('listitem')
  expect(rows.map(row => row.querySelector('strong')?.textContent)).toEqual(['结果表.xlsx', '报告.docx'])
  expect(rows.map(row => row.querySelector('p')?.textContent?.split(' · ')[0])).toEqual(['Excel', 'Word'])
  expect(screen.queryByText('需放进 Word 后再上传')).toBeNull()
})

it('reports one unreadable analysis project with a retry, keeps the others and leaves the paper project alone', async () => {
  const unavailable = vi.fn()
  const stop = watchProjectAccess('paper1', unavailable)
  let failing = true
  serve(url => {
    if (url.startsWith('/api/v1/projects?')) return Response.json({ items: [project('ra', '分析项目甲'), project('rb', '分析项目乙')], total: 2, page: 1, page_size: 100 })
    if (url === deliveries('ra')) return failing ? Response.json({ detail: { code: 'forbidden', message: 'x' } }, { status: 403 }) : Response.json({ items: [older] })
    if (url === deliveries('rb')) return Response.json({ items: [newer] })
  })
  render(<View />)
  const alert = await screen.findByRole('alert')
  expect(alert.textContent).toContain('暂时无法读取“分析项目甲”的分析成果。')
  expect(await screen.findByRole('button', { name: /分析项目乙 · 生存分析/ })).toBeTruthy()
  failing = false
  fireEvent.click(within(alert).getByRole('button', { name: '重试' }))
  expect(await screen.findByRole('button', { name: /分析项目甲 · 差异分析报告/ })).toBeTruthy()
  expect(screen.queryByRole('alert')).toBeNull()
  expect(unavailable).not.toHaveBeenCalled()
  stop()
})

it('has English for the page', async () => {
  setLocale('en')
  serve(url => {
    if (url.startsWith('/api/v1/projects?')) return Response.json({ items: [project('ra', '分析项目甲')], total: 1, page: 1, page_size: 100 })
    if (url === deliveries('ra')) return Response.json({ items: [older] })
    if (url === deliveries('ra') + '/s1') return Response.json(detail)
    if (url.endsWith('/download')) return new Response('bytes')
  })
  render(<View />)
  expect(await screen.findByRole('heading', { name: 'Choose an analysis result' })).toBeTruthy()
  expect(screen.getByText('Getting analysis results for “第 1 轮 · 意见 3”')).toBeTruthy()
  fireEvent.click(await screen.findByRole('button', { name: /分析项目甲 · 差异分析报告/ }))
  const files = await screen.findByRole('list', { name: 'Result files' })
  expect(within(files).getAllByRole('listitem').map(row => row.querySelector('p')?.textContent?.split(' · ')[0])).toEqual(['Word', 'Excel'])
  expect(within(files).getByText('Word · 2,048 bytes')).toBeTruthy()
  expect(within(files).getByText(/^Excel · 2,048 bytes · /)).toBeTruthy()
  expect(files.textContent).toContain('Put it into a Word file before uploading')
  fireEvent.click(screen.getByRole('link', { name: 'Download all files' }))
  expect(await screen.findByText('After downloading the files you need, you can return to 第 1 轮 · 意见 3 and upload them.')).toBeTruthy()
  expect(document.body.textContent).not.toMatch(/选择分析成果|成果文件|下载全部文件|正在为|需放进/)
})

it('says so when nothing can be read at all', async () => {
  serve(url => url.startsWith('/api/v1/projects?') ? Response.json({ detail: { code: 'internal_error', message: 'x' } }, { status: 500 }) : undefined)
  render(<View />)
  const alert = await screen.findByRole('alert')
  expect(within(alert).getByRole('button', { name: '重试' })).toBeTruthy()
})
