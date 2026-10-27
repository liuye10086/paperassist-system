import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { dataset, version as structureVersion } from '../datasets/datasetFixtures'
import PreparedHistory from './PreparedHistory'
afterEach(() => { cleanup(); vi.unstubAllGlobals() })
const source = { kind: 'prepared_dataset_version', schema_version: 1, dataset_id: 'pd1', structure_id: 's1', dataset_version: 2, file_id: 'f1', source_sha256: 'a'.repeat(64), dataset_sha256: 'b'.repeat(64), dataset_size_bytes: 100, dataset_schema_version: 1, sheet_index: 0, sheet_name: 'Sheet1', parser_version: 'structure-v1', parent_dataset_id: 'd1', parent_dataset_version: 1, transform_version: 'excel_prepare_v1' }
const recipe = { header_row: 4, data_range: 'C5:D35', fields: [{ column: 3, name: 'Value', unit: { status: 'confirmed', value: 'mg' }, trim_text: true, missing_markers: ['NA'] }, { column: 4, name: 'Group', unit: { status: 'unconfirmed', value: null }, trim_text: false, missing_markers: [] }] }
const version = { id: 'pd1', file_id: 'f1', parent_dataset_id: 'd1', parent_dataset_version: 1, version: 2, created_at: dataset.created_at, task_id: 'pt1', source, recipe, summary: { record_count: 31, changed_cell_count: 1, changed_row_count: 1, trimmed_cell_count: 1, missing_marker_cell_count: 0, columns: [], unresolved: [], changes_truncated: false }, download_url: '/api/v1/projects/p1/files/f1/prepared-dataset-versions/pd1/download' }
test('prepared history reads actual Excel row coordinates and copies recipe from raw to a new task', async () => {
 const fetch = vi.fn(async (url: string) => {
  if (url.includes('prepared-dataset-versions?')) return Response.json({ items: [version], total: 1, page: 1, page_size: 5 })
  if (url.endsWith('/prepared-dataset-versions/pd1')) return Response.json(version)
  if (url.includes('/rows?')) return Response.json({ dataset: version, start_row: 5, limit: 20, total_rows: 31, has_more: true, rows: [{ row: 5, cells: [{ row: 5, column: 3, coordinate: 'C5', kind: 'number', value: '2' }] }] })
  throw new Error(url)
 }); vi.stubGlobal('fetch', fetch)
 const user = userEvent.setup(); render(<PreparedHistory projectId="p1" fileId="f1" rawDataset={dataset} />)
 await user.click(await screen.findByRole('button', { name: '查看整理版本' }))
 await screen.findByRole('table', { name: '整理后的数据行' })
 expect(fetch.mock.calls.some(([url]) => url.includes('start_row=5&limit=20'))).toBe(true)
 await user.click(screen.getByRole('button', { name: '返回整理版本列表' }))
 await user.click(screen.getByRole('button', { name: '复制规则到新任务' }))
 expect((screen.getByLabelText('字段名称 C') as HTMLInputElement).value).toBe('Value')
 expect((screen.getByLabelText('去除首尾空白 C') as HTMLInputElement).checked).toBe(true)
 await waitFor(() => expect(screen.getByRole('button', { name: '生成预览' })).toBeTruthy())
 expect(fetch.mock.calls.some(([url]) => url.includes('preparation-defaults'))).toBe(false)
 await user.type(screen.getByLabelText('字段名称 C'), ' edited')
 expect((screen.getByLabelText('字段名称 C') as HTMLInputElement).value).toBe('Value edited')
 await user.click(screen.getByRole('button', { name: '返回整理版本列表' }))
 await user.click(screen.getByRole('button', { name: '复制规则到新任务' }))
 await waitFor(() => expect((screen.getByLabelText('字段名称 C') as HTMLInputElement).value).toBe('Value edited'))
})

const laterVersion = { ...version, id: 'pd2', version: 3, source: { ...source, dataset_id: 'pd2', dataset_version: 3 }, recipe: { ...recipe, fields: [{ ...recipe.fields[0], name: 'Latest value' }, recipe.fields[1]] }, download_url: '/api/v1/projects/p1/files/f1/prepared-dataset-versions/pd2/download' }
test.each(['view', 'copy'])('the latest history %s choice survives an earlier delayed detail response', async operation => {
 let finish!: (response: Response) => void
 const fetch = vi.fn(async (url: string, _init?: RequestInit) => {
  if (url.includes('prepared-dataset-versions?')) return Response.json({ items: [version, laterVersion], total: 2, page: 1, page_size: 5 })
  if (url.endsWith('/prepared-dataset-versions/pd1')) return new Promise<Response>(resolve => { finish = resolve })
  if (url.endsWith('/prepared-dataset-versions/pd2')) return Response.json(laterVersion)
  if (url.includes('/rows?')) { const d = url.includes('/pd2/') ? laterVersion : version; return Response.json({ dataset: d, start_row: 5, limit: 20, total_rows: 31, has_more: false, rows: [] }) }
  throw new Error(url)
 }); vi.stubGlobal('fetch', fetch)
 const user = userEvent.setup(); render(<PreparedHistory projectId="p1" fileId="f1" rawDataset={dataset} />)
 const controls = await screen.findAllByRole('button', { name: operation === 'view' ? '查看整理版本' : '复制规则到新任务' })
 await user.click(controls[0]); await user.click(controls[1])
 if (operation === 'copy') { await screen.findByLabelText('字段名称 C'); await user.type(screen.getByLabelText('字段名称 C'), ' draft') }
 else await screen.findByRole('table', { name: '当前整理规则' })
 await act(async () => finish(Response.json(version)))
 if (operation === 'copy') expect((screen.getByLabelText('字段名称 C') as HTMLInputElement).value).toBe('Latest value draft')
 else expect(within(screen.getByRole('table', { name: '当前整理规则' })).getByText('Latest value')).toBeTruthy()
 expect(screen.queryByRole('alert')).toBeNull()
 expect(fetch.mock.calls.find(([url]) => url.endsWith('/prepared-dataset-versions/pd1'))?.[1]?.signal?.aborted).toBe(true)
})

test('a delayed raw structure read cannot replace a newer copy choice', async () => {
 let finish!: (response: Response) => void; let structureReads = 0
 const fetch = vi.fn(async (url: string, _init?: RequestInit) => {
  if (url.includes('prepared-dataset-versions?')) return Response.json({ items: [version, laterVersion], total: 2, page: 1, page_size: 5 })
  if (url.endsWith('/prepared-dataset-versions/pd1')) return Response.json(version)
  if (url.endsWith('/prepared-dataset-versions/pd2')) return Response.json(laterVersion)
  if (url.endsWith('/structure-versions/s1')) { structureReads++; return structureReads === 1 ? new Promise<Response>(resolve => { finish = resolve }) : Response.json(structureVersion) }
  throw new Error(url)
 }); vi.stubGlobal('fetch', fetch)
 const user = userEvent.setup(); render(<PreparedHistory projectId="p1" fileId="f1" />)
 const controls = await screen.findAllByRole('button', { name: '复制规则到新任务' })
 await user.click(controls[0]); await waitFor(() => expect(structureReads).toBe(1)); await user.click(controls[1])
 await screen.findByLabelText('字段名称 C'); await user.type(screen.getByLabelText('字段名称 C'), ' draft')
 await act(async () => finish(Response.json(structureVersion)))
 expect((screen.getByLabelText('字段名称 C') as HTMLInputElement).value).toBe('Latest value draft')
 expect(screen.queryByRole('alert')).toBeNull()
})

test('unmounting history aborts its pending choice without fetching a raw parent afterwards', async () => {
 let finish!: (response: Response) => void
 const fetch = vi.fn(async (url: string, _init?: RequestInit) => {
  if (url.includes('prepared-dataset-versions?')) return Response.json({ items: [version], total: 1, page: 1, page_size: 5 })
  if (url.endsWith('/prepared-dataset-versions/pd1')) return new Promise<Response>(resolve => { finish = resolve })
  return Response.json(structureVersion)
 }); vi.stubGlobal('fetch', fetch)
 const user = userEvent.setup(); const ui = render(<PreparedHistory projectId="p1" fileId="f1" />)
 await user.click(await screen.findByRole('button', { name: '复制规则到新任务' })); ui.unmount()
 await act(async () => finish(Response.json(version)))
 expect(fetch.mock.calls.some(([url]) => url.endsWith('/structure-versions/s1'))).toBe(false)
 expect(fetch.mock.calls.find(([url]) => url.endsWith('/prepared-dataset-versions/pd1'))?.[1]?.signal?.aborted).toBe(true)
})
