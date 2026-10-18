import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { setLocale } from '../../shared/i18n'
import PreparedHistory from './PreparedHistory'
import PreparationReview from './PreparationReview'
import { baseVersion, impacts, qualityCounts, qualityRecipe, qualityReview, qualityTask, qualityVersion } from './batch07Fixtures'
import backendFixture from './batch07BackendFixture.json'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); setLocale('zh-CN') })
function mockApi(review: unknown = qualityReview) {
 const fetch = vi.fn(async (url: string, init?: RequestInit) => {
  if (url.includes('prepared-dataset-versions?')) return Response.json({ items: [baseVersion], total: 1, page: 1, page_size: 5 })
  if (url.endsWith('/prepared-dataset-versions/pd1')) return Response.json(baseVersion)
  if (url.endsWith('/quality-defaults')) return Response.json({ source: baseVersion.source, recipe: qualityRecipe, summary: qualityCounts, sheet: { ...qualityVersion.sheet } })
  if (url.includes('/rows?')) { const start = Number(new URL(url, 'http://local').searchParams.get('start_row')); return Response.json({ dataset: baseVersion, start_row: start, limit: 20, total_rows: 45, has_more: start + 19 < 46, rows: Array.from({ length: Math.min(20, 47 - start) }, (_, i) => ({ row: start + i, cells: [{ row: start + i, column: 1, coordinate: `A${start + i}`, kind: 'number', value: String(i) }] })) }) }
  if (url.endsWith('/dataset-quality-preparations')) return Response.json(qualityTask)
  if (url.endsWith('/dataset-preparation')) return Response.json(review)
  if (url.includes('/impacts?')) { const page = Number(new URL(url, 'http://local').searchParams.get('page')); return Response.json({ items: impacts.slice((page - 1) * 20, page * 20), total: 45, page, page_size: 20 }) }
  if (url.endsWith('/decision') && init?.method === 'POST') return Response.json({ ...qualityTask, status: 'queued', revision: 2 })
  throw new Error(url)
 }); vi.stubGlobal('fetch', fetch); return fetch
}
test('quality processing starts from the selected parent, requires reasons, and keeps selections across pages and languages', async () => {
 const fetch = mockApi(); const user = userEvent.setup(); render(<PreparedHistory projectId="p1" fileId="f1" />)
 await user.click(await screen.findByRole('button', { name: '按此版本处理质量问题' }))
 expect((await screen.findByLabelText('重复值策略') as HTMLSelectElement).value).toBe('retain')
 expect(screen.getByRole('combobox', { name: '重复值策略' })).toBe(screen.getByLabelText('重复值策略'))
 expect(screen.queryByLabelText('字段名称 A')).toBeNull()
 await user.click(await screen.findByLabelText('排除源行 2'))
 expect((screen.getByRole('button', { name: '生成质量预览' }) as HTMLButtonElement).disabled).toBe(true)
 await user.type(screen.getByLabelText('源行 2 的排除理由（用户声明）'), '核对原始登记后发现重复录入')
 await user.click(screen.getByRole('button', { name: '下一页可选源行' }))
 await user.click(await screen.findByLabelText('排除源行 22'))
 await user.type(screen.getByLabelText('源行 22 的排除理由（用户声明）'), '记录错误')
 act(() => setLocale('en'))
 expect((screen.getByLabelText('Reason for excluding source row 2 (user statement)') as HTMLTextAreaElement).value).toBe('核对原始登记后发现重复录入')
 await user.click(screen.getByRole('button', { name: 'Generate quality preview' }))
 await screen.findByRole('button', { name: 'Confirm and publish' })
 const call = fetch.mock.calls.find(([url]) => url.endsWith('/dataset-quality-preparations'))!
 expect(JSON.parse(String(call[1]?.body))).toEqual({ base_dataset_id: 'pd1', recipe: { ...qualityRecipe, manual_exclusions: [{ row: 2, reason: '核对原始登记后发现重复录入' }, { row: 22, reason: '记录错误' }] } })
 expect(fetch.mock.calls.filter(([url]) => url.endsWith('/decision'))).toHaveLength(0)
})
test('complete immutable impacts page 20/20/5, downloads, and edits invalidate approval', async () => {
 mockApi(); const user = userEvent.setup(); render(<PreparationReview projectId="p1" taskId="t1" />)
 const table = await screen.findByRole('table', { name: '完整质量影响明细' })
 expect(within(table).getAllByRole('row')).toHaveLength(21)
 await user.click(screen.getByRole('button', { name: '下一页影响' }))
 await waitFor(() => expect(within(screen.getByRole('table', { name: '完整质量影响明细' })).getByText('A22')).toBeTruthy())
 expect(within(screen.getByRole('table', { name: '完整质量影响明细' })).getAllByRole('row')).toHaveLength(21)
 await user.click(screen.getByRole('button', { name: '下一页影响' }))
 await waitFor(() => expect(within(screen.getByRole('table', { name: '完整质量影响明细' })).getAllByRole('row')).toHaveLength(6))
 expect(screen.getByRole('link', { name: '下载完整质量回执' }).getAttribute('href')).toBe(qualityReview.impact_download_url)
 expect(screen.getByText('质量确认不替代分析计划确认。新版本须重新检查字段、类型、单位、有效记录和研究设计，并独立确认分析计划。')).toBeTruthy()
 expect(screen.queryByText('private-checkpoint')).toBeNull()
 await user.click(screen.getByRole('button', { name: '修改规则' }))
 expect(screen.queryByRole('button', { name: '确认并发布' })).toBeNull()
 expect(screen.queryByRole('table', { name: '完整质量影响明细' })).toBeNull()
 expect(screen.getByText('规则已进入编辑；原预览不可确认，重新生成完整预览后再确认。')).toBeTruthy()
})
test('zero retained records block publishing while keeping the preview and revise action', async () => {
 mockApi({ ...qualityReview, preview: { ...qualityReview.preview, retained_record_count: 0, changed_cell_count: 0, retained_changed_cell_count: 0, excluded_changed_cell_count: 0, cumulative_excluded_row_count: 45, manual_excluded_row_count: 45, duplicate_excluded_row_count: 0, after_quality: { ...qualityCounts, record_count: 0 } } })
 render(<PreparationReview projectId="p1" taskId="t1" />)
 expect((await screen.findByRole('button', { name: '确认并发布' }) as HTMLButtonElement).disabled).toBe(true)
 expect(screen.getByRole('button', { name: '修改规则' })).toBeTruthy()
 expect(await screen.findByRole('table', { name: '完整质量影响明细' })).toBeTruthy()
})

test('published v2 history exposes its frozen receipt, direct parent, and sparse next page', async () => {
 const fetch = vi.fn(async (url: string) => {
  if (url.includes('prepared-dataset-versions?')) return Response.json({ items: [qualityVersion], total: 1, page: 1, page_size: 5 })
  if (url.endsWith('/prepared-dataset-versions/pd2')) return Response.json(qualityVersion)
  if (url.endsWith('/prepared-dataset-versions/pd1')) return Response.json(baseVersion)
  if (url.includes('/impacts?')) return Response.json({ items: impacts.slice(0, 20), total: 45, page: 1, page_size: 20 })
  if (url.includes('/rows?')) { const start = Number(new URL(url, 'http://local').searchParams.get('start_row')); return Response.json({ dataset: qualityVersion, start_row: start, limit: 20, total_rows: 43, has_more: start === 2, next_start_row: start === 2 ? 24 : null, rows: [{ row: start === 2 ? 3 : 24, cells: [] }] }) }
  return Response.json({ detail: { code: 'dataset_missing' } }, { status: 404 })
 }); vi.stubGlobal('fetch', fetch); const user = userEvent.setup(); render(<PreparedHistory projectId="p1" fileId="f1" />)
 await user.click(await screen.findByRole('button', { name: '查看整理版本' }))
 expect(await screen.findByRole('link', { name: '下载完整质量回执' })).toBeTruthy()
 expect(screen.getByRole('button', { name: '查看直接父版本回执' })).toBeTruthy()
 expect(screen.queryByRole('button', { name: '复制规则到新任务' })).toBeNull()
 await screen.findByRole('table', { name: '整理后的数据行' })
 await user.click(screen.getByRole('button', { name: '下一页原始行' }))
 await waitFor(() => expect(fetch.mock.calls.some(([url]) => url.includes('start_row=24&limit=20'))).toBe(true))
 await user.click(screen.getByRole('button', { name: '上一页原始行' }))
 await waitFor(() => expect(fetch.mock.calls.filter(([url]) => url.includes('start_row=2&limit=20'))).toHaveLength(2))
})

test('impact filters bind the current checkpoint and never truncate a filtered page', async () => {
 const fetch = mockApi(); const user = userEvent.setup(); render(<PreparationReview projectId="p1" taskId="t1" />)
 await screen.findByRole('table', { name: '完整质量影响明细' })
 await user.selectOptions(screen.getByLabelText('按操作筛选'), 'cell_change')
 await user.type(screen.getByLabelText('按理由精确筛选'), 'user reason')
 await user.click(screen.getByRole('button', { name: '应用理由筛选' }))
 await waitFor(() => expect(fetch.mock.calls.some(([url]) => { const p = new URL(url, 'http://local').searchParams; return p.get('operation') === 'cell_change' && p.get('reason') === 'user reason' && p.get('checkpoint_id') === 'private-checkpoint' })).toBe(true))
})

test('reloading invalidates the visible approval until the replacement review arrives', async () => {
 const fetch = mockApi(); const original = fetch.getMockImplementation()!; let reads = 0; let finish!: (value: Response) => void
 fetch.mockImplementation((url, init) => url.endsWith('/dataset-preparation') && ++reads > 1 ? new Promise(resolve => { finish = resolve }) : original(url, init))
 const user = userEvent.setup(); render(<PreparationReview projectId="p1" taskId="t1" />)
 await screen.findByRole('button', { name: '确认并发布' })
 await user.click(screen.getByRole('button', { name: '重新读取整理任务' }))
 expect(screen.queryByRole('button', { name: '确认并发布' })).toBeNull()
 await act(async () => finish(Response.json(qualityReview)))
 expect(await screen.findByRole('button', { name: '确认并发布' })).toBeTruthy()
})

test('real backend reasons are readable without exposing internal rule identifiers', async () => {
 vi.stubGlobal('fetch', vi.fn(async (url: string) => Response.json(url.includes('/impacts?') ? backendFixture.impacts : backendFixture.review)))
 render(<PreparationReview projectId={backendFixture.review.task.project_id} taskId={backendFixture.review.task.id} />)
 await screen.findByRole('table', { name: '完整质量影响明细' })
 expect(document.body.textContent).not.toContain('exact_duplicate')
 expect(document.body.textContent).not.toContain(backendFixture.review.checkpoint_id)
 expect(document.body.textContent).not.toContain(backendFixture.review.source.dataset_sha256)
 expect(screen.getByText('全部字段精确重复')).toBeTruthy()
 const table = screen.getByRole('table', { name: '完整质量影响明细' })
 expect(within(table).queryByText('null')).toBeNull()
 expect(within(table).getByText('空值（缺失）')).toBeTruthy()
 act(() => setLocale('en'))
 expect(within(table).getByText('Missing')).toBeTruthy()
})

test.each(['waiting_confirmation', 'waiting_input', 'succeeded'] as const)('waiting reminder matches quality task status %s', async status => {
 mockApi({ ...qualityReview, task: { ...qualityTask, status }, wait: status === 'waiting_confirmation' ? qualityReview.wait : null, result: status === 'succeeded' ? qualityVersion : null })
 render(<PreparationReview projectId="p1" taskId="t1" />)
 await screen.findByRole('table', { name: '完整质量影响明细' })
 const reminder = '离开页面后任务仍等待确认，可在任务中心继续。'
 expect(screen.queryByText(reminder) !== null).toBe(status !== 'succeeded')
 act(() => setLocale('en'))
 expect(screen.queryByText('The task keeps waiting when you leave. Continue in the task center.') !== null).toBe(status !== 'succeeded')
})
