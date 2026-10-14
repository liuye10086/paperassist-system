import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { setLocale } from '../../shared/i18n'
import { dataset } from '../datasets/datasetFixtures'
import { taskFixture } from '../tasks/taskFixtures'
import PreparationPanel from './PreparationPanel'
import PreparationReview from './PreparationReview'
import TaskPendingAction from '../tasks/TaskPendingAction'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); setLocale('zh-CN') })
const source = { kind: 'dataset_version', schema_version: 1, dataset_id: 'd1', structure_id: 's1', dataset_version: 1, file_id: 'f1', source_sha256: 'a'.repeat(64), dataset_sha256: 'b'.repeat(64), dataset_size_bytes: 100, dataset_schema_version: 1, sheet_index: 0, sheet_name: 'Sheet1', parser_version: 'structure-v1' }
const recipe = { header_row: 1, data_range: 'A2:B31', fields: [1, 2].map(column => ({ column, name: `Field ${column}`, unit: { status: 'unconfirmed', value: null }, trim_text: false, missing_markers: [] })) }
const input = { kind: 'dataset_preparation', source, workflow_version: 'dataset_preparation_v1' }
const task = { ...taskFixture, task_type: 'prepare_dataset', status: 'waiting_confirmation', phase: 'plan', input_version: input }
const review = { task, source, checkpoint_id: 'checkpoint-private', recipe_revision: 1, recipe, preview: { record_count: 30, changed_cell_count: 2, changed_row_count: 1, trimmed_cell_count: 1, missing_marker_cell_count: 1, columns: [], unresolved: [{ code: 'unconfirmed_unit', column: 1, count: 1 }], changes_truncated: false }, changes: [{ row: 2, column: 1, coordinate: 'A2', before: { kind: 'text', value: ' NA ' }, after: { kind: 'blank', value: null }, operations: ['trim_text', 'missing_marker'] }], preview_download_url: '/api/v1/tasks/t1/dataset-preparation/preview/download', result: null, wait: { id: 'w1', status: 'open', kind: 'dataset_preparation_confirmation', task_revision: 1, input_version: input, reason_code: 'confirmation_required', error_code: null, created_at: taskFixture.created_at, resolved_at: null } }
function mockApi(conflict = false) {
 const fetch = vi.fn(async (url: string, _init?: RequestInit) => {
  if (url.includes('preparation-defaults')) return Response.json({ source, recipe })
  if (url.endsWith('/dataset-preparations')) return Response.json(task)
  if (url.endsWith('/decision')) return conflict ? Response.json({ detail: { code: 'task_conflict' } }, { status: 409 }) : Response.json({ ...task, status: 'queued', revision: 2 })
  if (url.endsWith('/dataset-preparation')) return Response.json(review)
  throw new Error(url)
 }); vi.stubGlobal('fetch', fetch); return fetch
}
test('defaults require explicit reading, all cleaning is off, drafts survive language changes and full recipe submits', async () => {
 const fetch = mockApi(); const user = userEvent.setup(); render(<PreparationPanel projectId="p1" fileId="f1" dataset={dataset} />)
 expect(fetch).not.toHaveBeenCalled()
 await user.click(screen.getByRole('button', { name: '读取建议字段' }))
 const name = await screen.findByLabelText('字段名称 A'); expect((screen.getByLabelText('去除首尾空白 A') as HTMLInputElement).checked).toBe(false)
 expect((screen.getByLabelText('启用缺失标记 A') as HTMLInputElement).checked).toBe(false)
 await user.clear(name); await user.type(name, ' edited ')
 act(() => setLocale('en')); expect((screen.getByLabelText('Field name A') as HTMLInputElement).value).toBe(' edited ')
 await user.click(screen.getByRole('button', { name: 'Generate preview' })); await screen.findByRole('button', { name: 'Confirm and publish' })
 const call = fetch.mock.calls.find(([url]) => url.endsWith('/dataset-preparations'))!
 expect(JSON.parse(String(call[1]?.body))).toEqual({ dataset_id: 'd1', recipe: { ...recipe, fields: [{ ...recipe.fields[0], name: ' edited ' }, recipe.fields[1]] } })
 expect(screen.queryByText('checkpoint-private')).toBeNull()
})
test.each(['approve', 'revise'])('review %s posts frozen input and current checkpoint, never auto approves', async operation => {
 const fetch = mockApi(); const user = userEvent.setup(); render(<PreparationReview projectId="p1" taskId={task.id} />)
 await screen.findByRole('button', { name: '确认并发布' })
 expect(fetch.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
 if (operation === 'revise') { await user.click(screen.getByRole('button', { name: '修改规则' })); await user.click(screen.getByRole('button', { name: '重新生成预览' })) }
 else await user.click(screen.getByRole('button', { name: '确认并发布' }))
 await waitFor(() => expect(fetch.mock.calls.some(([url]) => url.endsWith('/decision'))).toBe(true))
 const call = fetch.mock.calls.find(([url]) => url.endsWith('/decision'))!
 expect(JSON.parse(String(call[1]?.body))).toEqual({ operation, wait_id: 'w1', checkpoint_id: review.checkpoint_id, expected_task_revision: task.revision, input_version: input, recipe: operation === 'approve' ? null : recipe })
})
test('stale decision conflicts reread saved review and allow an explicit new decision', async () => {
 const fetch = mockApi(true); const user = userEvent.setup(); render(<PreparationReview projectId="p1" taskId={task.id} />)
 await user.click(await screen.findByRole('button', { name: '确认并发布' }))
 await screen.findByRole('alert'); await waitFor(() => expect(fetch.mock.calls.filter(([url]) => url.endsWith('/dataset-preparation')).length).toBe(2))
 expect(fetch.mock.calls.filter(([, init]) => init?.method === 'POST').length).toBe(1)
})
test('a late defaults response is discarded after raw source changes', async () => {
 let finish!: (response: Response) => void
 vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(resolve => { finish = resolve })))
 const user = userEvent.setup(); const ui = render(<PreparationPanel projectId="p1" fileId="f1" dataset={dataset} />)
 await user.click(screen.getByRole('button', { name: '读取建议字段' }))
 ui.rerender(<PreparationPanel projectId="p1" fileId="f1" dataset={{ ...dataset, id: 'd2' }} />)
 await act(async () => finish(Response.json({ source, recipe })))
 expect(screen.queryByLabelText('字段名称 A')).toBeNull()
})

test('revised range explicitly rereads matching fields before regenerating on the same task', async () => {
 const fetch = mockApi(); const user = userEvent.setup(); render(<PreparationReview projectId="p1" taskId={task.id} />)
 await user.click(await screen.findByRole('button', { name: '修改规则' }))
 const range = screen.getByLabelText('数据区域'); await user.clear(range); await user.type(range, 'B2:B31')
 await user.click(screen.getByRole('button', { name: '读取建议字段' }))
 await waitFor(() => expect(fetch.mock.calls.some(([url]) => url.includes('preparation-defaults') && url.includes('data_range=B2%3AB31'))).toBe(true))
 expect(fetch.mock.calls.some(([url]) => url.endsWith('/dataset-preparations'))).toBe(false)
})
test('confirmation displays the persisted field rules before the user approves', async () => {
 mockApi(); render(<PreparationReview projectId="p1" taskId={task.id} />)
 await screen.findByRole('button', { name: '确认并发布' })
 expect(screen.getByRole('table', { name: '当前整理规则' })).toBeTruthy()
 expect(screen.getByText('Field 1')).toBeTruthy()
})
test('failed preparation tasks keep the existing retry action alongside shared review', async () => {
 const fetch = mockApi(); const original = fetch.getMockImplementation()!
 fetch.mockImplementation((url, init) => url.endsWith('/resume') ? Promise.resolve(Response.json({ ...task, status: 'queued', revision: task.revision + 1 })) : original(url, init))
 const user = userEvent.setup(); render(<TaskPendingAction workspace={{ task: { ...task, status: 'failed' }, source: { file_id: 'f1', filename: 'data.xlsx', analysis_run_id: null, is_current: true, dataset_source: source }, wait: null, allowed_actions: ['retry'], artifacts: { figure: null, explanation: null, report: null } } as never} blocked={false} onChanged={() => {}} />)
 await screen.findByRole('button', { name: '确认并发布' })
 await user.click(screen.getByRole('button', { name: '重试原任务' }))
 await waitFor(() => expect(fetch.mock.calls.some(([url]) => url.endsWith('/resume'))).toBe(true))
})
test('an unconfirmed revise keeps its edited recipe and reuses the same idempotency key', async () => {
 const fetch = mockApi(); const original = fetch.getMockImplementation()!; let once = true
 fetch.mockImplementation((url, init) => { if (url.endsWith('/decision') && once) { once = false; return Promise.reject(new TypeError('network')) } return original(url, init) })
 const user = userEvent.setup(); render(<PreparationReview projectId="p1" taskId={task.id} />)
 await user.click(await screen.findByRole('button', { name: '修改规则' }))
 await user.type(screen.getByLabelText('字段名称 A'), ' edited')
 await user.click(screen.getByRole('button', { name: '重新生成预览' })); await screen.findByRole('alert')
 expect((screen.getByLabelText('字段名称 A') as HTMLInputElement).value).toBe('Field 1 edited')
 await user.click(screen.getByRole('button', { name: '重新生成预览' }))
 const decisions = fetch.mock.calls.filter(([url]) => url.endsWith('/decision'))
 expect(decisions).toHaveLength(2)
 expect(decisions[0][1]?.body).toBe(decisions[1][1]?.body)
 expect(new Headers(decisions[0][1]?.headers).get('Idempotency-Key')).toBe(new Headers(decisions[1][1]?.headers).get('Idempotency-Key'))
})

test('a preparation source summary without filename omits an empty filename prefix', async () => {
 mockApi(); render(<PreparationReview projectId="p1" taskId={task.id} />)
 await screen.findByRole('button', { name: '确认并发布' })
 expect(screen.getByText('工作表：Sheet1；原始数据版本 v1。')).toBeTruthy()
 expect(screen.queryByText('来源：；工作表：Sheet1；原始数据版本 v1。')).toBeNull()
})
