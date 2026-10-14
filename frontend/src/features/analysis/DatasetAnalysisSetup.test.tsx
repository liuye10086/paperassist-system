import { afterEach, expect, test, vi } from 'vitest'
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AnalysisSetup from './AnalysisSetup'
import { version, dataset, page } from '../datasets/datasetFixtures'
import type { StructureVersion } from '../datasets/datasetApi'
import { reviewFixture } from '../analysisPlan/analysisPlanFixtures'
afterEach(() => { cleanup(); vi.unstubAllGlobals() })
const source = { kind: 'dataset_version', schema_version: 1, dataset_id: 'd1', structure_id: 's1', dataset_version: 1, file_id: 'f1', source_sha256: 'a'.repeat(64), dataset_sha256: 'b'.repeat(64), dataset_size_bytes: 100, dataset_schema_version: 1, sheet_index: 0, sheet_name: 'Sheet1', parser_version: 'openpyxl-3.1.5-structure-v1' }
const selection = { task_type: 'descriptive_boxplot', sheet_name: 'Sheet1', numeric_column: 'A', group_column: null, unit: '', missing_policy: 'exclude_selected_missing' }
const check = { ready: true, row_count: 30, valid_count: 30, excluded_count: 0, groups: [], issues: [], warnings: [] }
const saved = { file_id: 'f1', source_sha256: source.source_sha256, source, status: 'configured', revision: 1, selection, check, updated_at: dataset.created_at }
const profile = { sheet_name: 'Sheet1', row_count: 30, columns: [{ id: 'A', name: '数值', type: 'number', non_missing_count: 30, missing_count: 0, numeric_count: 30, can_be_numeric: true, can_be_group: true, issue_cells: [] }], warnings: [] }
const stats = { n: 30, mean: 1, std: 0, min: 1, q1: 1, median: 1, q3: 1, max: 1, iqr: 0, warnings: [] }
const result = { id: 'run1', filename: '研究.xlsx', file_type: 'xlsx', source_sha256: source.source_sha256, source, setup_revision: 1, selection, check, numeric_name: '数值', group_name: null, started_at: dataset.created_at, completed_at: dataset.created_at, engine: { id: 'descriptive_statistics_dataset_v1', parser_version: 'structure-v1', python_version: '3' }, overall: stats, groups: [] }
const newer: StructureVersion = { ...version, id: 's2', version: 2, task: { ...version.task, input_version: { kind: 'excel_structure', structure_id: 's2', source_sha256: source.source_sha256, parser_version: source.parser_version } }, datasets: [{ ...dataset, id: 'd2', structure_id: 's2', version: 2 }] }
const files = [{ id: 'f1', filename: '研究.xlsx', file_type: 'xlsx', uploaded_at: dataset.created_at, parse_status: 'parsed' as const }, { id: 'f2', filename: '另一份.xlsx', file_type: 'xlsx', uploaded_at: dataset.created_at, parse_status: 'parsed' as const }]
function mockApi(options: { saved?: unknown; items?: StructureVersion[]; result?: unknown } = {}) {
 const fetch = vi.fn(async (url: string, init?: RequestInit) => {
  if (url.includes('/structure-versions?page=2')) return Response.json({ ...page, items: [version], page: 2, total: 6, latest_version: 2 })
  if (url.includes('/structure-versions?')) return Response.json({ ...page, items: options.items ?? [newer, version], total: 6, latest_version: 2 })
  if (url.endsWith('/structure-versions/s1')) return Response.json(version)
  if (url.endsWith('/structure-versions/s2')) return Response.json(newer)
  if (url.endsWith('/profile')) {
   const selectedSource = url.includes('/pd1/') ? preparedSource : url.includes('/d2/') ? { ...source, dataset_id: 'd2', structure_id: 's2', dataset_version: 2 } : source
   return Response.json({ schema_version: 1, rules_version: 'excel_profile_v1', source: selectedSource, filename: '研究.xlsx', sheet_name: 'Sheet1', data_range: 'A2:B31', record_count: 30, blank_row_count: 0, duplicate_groups: 0, duplicate_rows: 0, duplicate_extra_rows: 0, fields: [] })
  }
  if (url.endsWith('/analysis-setup')) {
   if (init?.method === 'PUT') { const body = JSON.parse(String(init.body)); return Response.json({ ...saved, revision: 2, source: body.dataset_id === 'd2' ? { ...source, dataset_id: 'd2', structure_id: 's2', dataset_version: 2 } : source }) }
   return Response.json(options.saved ?? null)
  }
  if (url.includes('/analysis-profile?')) return Response.json(profile)
  if (url.endsWith('/analysis-check')) return Response.json(check)
  if (url.endsWith('/analysis-result')) return Response.json({ current_revision: 1, is_current: true, result: options.result ?? null })
  if (url.endsWith('/boxplot')) return Response.json({ current_revision: 1, is_current: true, figure: null, job: null })
  if (url.endsWith('/plot-config')) return Response.json({ configured: false, model: null, message: '' })
  throw new Error(url)
 })
 vi.stubGlobal('fetch', fetch); return fetch
}
async function open(user: ReturnType<typeof userEvent.setup>) {
 render(<AnalysisSetup projectId="p1" files={files} />)
 await user.selectOptions(screen.getByLabelText('用于分析的文件'), 'f1')
 return await screen.findByLabelText('原始数据版本') as HTMLSelectElement
}
async function pick(user: ReturnType<typeof userEvent.setup>, structure = 's1', d = 'd1') {
 await user.selectOptions(screen.getByLabelText('原始数据版本'), structure)
 await user.selectOptions(screen.getByLabelText('分析工作表'), d)
 await screen.findByLabelText('数值列')
}
test('requires explicit version and sheet before loading a dataset profile or posting', async () => {
 const fetch = mockApi(); const user = userEvent.setup(); const select = await open(user)
 expect(select.value).toBe('')
 expect(fetch.mock.calls.some(([url]) => url.includes('/analysis-profile?'))).toBe(false)
 await user.selectOptions(select, version.id)
 expect(fetch.mock.calls.some(([url]) => url.includes('/analysis-profile?'))).toBe(false)
 await user.selectOptions(screen.getByLabelText('分析工作表'), dataset.id)
 await screen.findByLabelText('数值列')
 await screen.findByRole('heading', { name: '字段详细概况' })
 expect(fetch.mock.calls.some(([url]) => url.includes('dataset_id=d1'))).toBe(true)
 expect(fetch.mock.calls.some(([url]) => url.endsWith('/dataset-versions/d1/profile'))).toBe(true)
 expect(fetch.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
 expect(fetch.mock.calls.some(([url]) => url.includes('/preview'))).toBe(false)
})
test('only successful versions are selectable and the restored bound version is fetched outside page one', async () => {
 const failed = { ...newer, task: { ...newer.task, status: 'failed' as const }, datasets: [] }
 const fetch = mockApi({ saved, items: [failed] }); const user = userEvent.setup(); const select = await open(user)
 expect(select.value).toBe('s1')
 expect(select.querySelector('option[value="s2"]')).toBeNull()
 expect(fetch.mock.calls.some(([url]) => url.endsWith('/structure-versions/s1'))).toBe(true)
 expect((await screen.findByLabelText('数值列') as HTMLSelectElement).value).toBe('A')
})
test('pagination and refreshing a newer failed version preserve selected version and draft', async () => {
 const fetch = mockApi({ saved }); const user = userEvent.setup(); const select = await open(user)
 const unit = await screen.findByLabelText('数值单位（可选）')
 await user.type(unit, ' draft')
 await user.click(screen.getByRole('button', { name: '下一页数据版本' }))
 expect(select.value).toBe('s1'); expect(screen.getByLabelText('数值单位（可选）')).toBe(unit)
 const original = fetch.getMockImplementation()!
 fetch.mockImplementation((url, init) => url.includes('/structure-versions?') ? Promise.resolve(Response.json({ ...page, page: 2, total: 6, latest_version: 3 })) : original(url, init))
 await user.click(screen.getByRole('button', { name: '刷新数据版本' }))
 await waitFor(() => expect(fetch.mock.calls.filter(([url]) => url.includes('page=2')).length).toBeGreaterThan(1))
 expect(select.value).toBe('s1'); expect((unit as HTMLInputElement).value).toBe(' draft')
})
test('changing only dataset source leaves existing statistics and their frozen label but blocks new execution', async () => {
 mockApi({ saved, result }); const user = userEvent.setup(); await open(user); await screen.findByLabelText('数值列')
 await user.click(screen.getByRole('button', { name: '描述统计' }))
 const table = await screen.findByRole('table', { name: '描述统计结果' })
 await user.click(screen.getByRole('button', { name: '字段配置' })); await pick(user, 's2', 'd2')
 expect((screen.getByLabelText('数值列') as HTMLSelectElement).value).toBe('')
 await user.click(screen.getByRole('button', { name: '描述统计' }))
 expect(screen.getByRole('table', { name: '描述统计结果' })).toBe(table)
 expect((screen.getByRole('button', { name: '执行描述统计' }) as HTMLButtonElement).disabled).toBe(true)
 expect(screen.queryByText(/以下为历史结果/)).toBeNull()
 expect(screen.getByText(/来源：研究.xlsx；工作表：Sheet1；原始数据版本 v1。/, { selector: '.statistics-results .analysis-source' })).toBeTruthy()
})
test('legacy configuration and results remain readable while execution requires explicitly saved dataset source', async () => {
 const { source: _source, ...legacySaved } = saved; const { source: _resultSource, ...legacyResult } = result
 const fetch = mockApi({ saved: legacySaved, result: legacyResult }); const user = userEvent.setup(); const select = await open(user)
 expect(select.value).toBe(''); expect(screen.getAllByText('来源：历史 Excel 配置。')[0]).toBeTruthy()
 await user.click(screen.getByRole('button', { name: '描述统计' })); await screen.findByRole('table', { name: '描述统计结果' })
 expect((screen.getByRole('button', { name: '执行描述统计' }) as HTMLButtonElement).disabled).toBe(true)
 expect(fetch.mock.calls.some(([, init]) => init?.method === 'POST' || init?.method === 'PUT')).toBe(false)
})
test('late dataset profile cannot replace a different selected version', async () => {
 const fetch = mockApi(); const original = fetch.getMockImplementation()!; let finish!: (response: Response) => void
 fetch.mockImplementation((url, init) => url.includes('dataset_id=d1') ? new Promise<Response>(resolve => { finish = resolve }) : original(url, init))
 const user = userEvent.setup(); await open(user)
 await user.selectOptions(screen.getByLabelText('原始数据版本'), 's1'); await user.selectOptions(screen.getByLabelText('分析工作表'), 'd1')
 await screen.findByText('正在检查整张工作表……'); await pick(user, 's2', 'd2')
 await act(async () => finish(Response.json({ ...profile, row_count: 999 })))
 expect(screen.queryByText('整表检查：999 行数据')).toBeNull()
 expect((screen.getByLabelText('原始数据版本') as HTMLSelectElement).value).toBe('s2')
})
test('save conflict reloads and restores the other page exact frozen source', async () => {
 const fetch = mockApi({ saved }); const original = fetch.getMockImplementation()!; let conflicted = false
 fetch.mockImplementation((url, init) => {
  if (url.endsWith('/analysis-setup') && init?.method === 'PUT') { conflicted = true; return Promise.resolve(Response.json({ detail: { code: 'setup_conflict' } }, { status: 409 })) }
  if (conflicted && url.endsWith('/analysis-setup')) return Promise.resolve(Response.json({ ...saved, revision: 2, source: { ...source, dataset_id: 'd2', structure_id: 's2', dataset_version: 2 } }))
  return original(url, init)
 })
 const user = userEvent.setup(); await open(user); await screen.findByLabelText('数值列')
 await user.click(screen.getByRole('button', { name: '检查字段' })); await screen.findByText('可用 30 行，排除 0 行。')
 await user.click(screen.getByRole('button', { name: '保存分析配置' }))
 await waitFor(() => expect((screen.getByLabelText('原始数据版本') as HTMLSelectElement).value).toBe('s2'))
 expect((screen.getByLabelText('分析工作表') as HTMLSelectElement).value).toBe('d2')
 expect(screen.queryByText('已保存分析配置，可前往描述统计。')).toBeNull()
 expect((screen.getByLabelText('原始数据版本') as HTMLSelectElement).disabled).toBe(false)
})

test.each(['check', 'save'])('late %s response after unmount cannot bind a new draft', async operation => {
 const fetch = mockApi({ saved }); const original = fetch.getMockImplementation()!; let finish!: (response: Response) => void; let delayed = false
 fetch.mockImplementation((url, init) => {
  if (!delayed && (operation === 'check' && url.endsWith('/analysis-check') || operation === 'save' && url.endsWith('/analysis-setup') && init?.method === 'PUT')) { delayed = true; return new Promise<Response>(resolve => { finish = resolve }) }
  return original(url, init)
 })
 const user = userEvent.setup(); await open(user); await screen.findByLabelText('数值列')
 await user.click(screen.getByRole('button', { name: '检查字段' }))
 if (operation === 'save') { await screen.findByText('可用 30 行，排除 0 行。'); await user.click(screen.getByRole('button', { name: '保存分析配置' })) }
 cleanup(); await open(user); await pick(user, 's2', 'd2')
 await act(async () => finish(Response.json(operation === 'check' ? check : { ...saved, revision: 2 })))
 expect((screen.getByLabelText('原始数据版本') as HTMLSelectElement).value).toBe('s2')
 expect(screen.queryByText('可用 30 行，排除 0 行。')).toBeNull()
 expect(screen.queryByText('已保存分析配置，可前往描述统计。')).toBeNull()
})
test('saved dataset execution waits for the dataset profile to load successfully', async () => {
 const fetch = mockApi({ saved }); const original = fetch.getMockImplementation()!
 fetch.mockImplementation((url, init) => url.includes('/analysis-profile?') ? new Promise<Response>(() => {}) : original(url, init))
 const user = userEvent.setup(); await open(user)
 await screen.findByText('正在检查整张工作表……')
 await user.click(screen.getByRole('button', { name: '描述统计' }))
 expect((screen.getByRole('button', { name: '执行描述统计' }) as HTMLButtonElement).disabled).toBe(true)
})

test.each([
 ['revision', { revision: 1 }],
 ['selection', { selection: { ...selection, unit: 'wrong' } }],
 ['dataset hash', { source: { ...source, dataset_sha256: 'c'.repeat(64) } }],
 ['dataset size', { source: { ...source, dataset_size_bytes: 101 } }],
 ['parser', { source: { ...source, parser_version: 'wrong' } }],
] as const)('rejects saved response with inconsistent %s', async (_field, change) => {
 const fetch = mockApi({ saved }); const original = fetch.getMockImplementation()!
 fetch.mockImplementation((url, init) => url.endsWith('/analysis-setup') && init?.method === 'PUT'
  ? Promise.resolve(Response.json({ ...saved, revision: 2, ...change })) : original(url, init))
 const user = userEvent.setup(); await open(user); await screen.findByLabelText('数值列')
 await user.click(screen.getByRole('button', { name: '检查字段' })); await screen.findByText('可用 30 行，排除 0 行。')
 await user.click(screen.getByRole('button', { name: '保存分析配置' }))
 await screen.findByText('数据来源或版本不一致，请重新载入配置。')
 expect(screen.queryByText('已保存分析配置，可前往描述统计。')).toBeNull()
})

test.each(['source_sha256', 'parser_version'] as const)('rejects restored source whose %s contradicts structure metadata', async field => {
 mockApi({ saved: { ...saved, source_sha256: field === 'source_sha256' ? 'c'.repeat(64) : saved.source_sha256,
  source: { ...source, [field]: field === 'source_sha256' ? 'c'.repeat(64) : 'wrong' } } })
 const user = userEvent.setup(); render(<AnalysisSetup projectId="p1" files={files} />)
 await user.selectOptions(screen.getByLabelText('用于分析的文件'), 'f1')
 await screen.findByRole('alert')
 expect(screen.queryByLabelText('数值列')).toBeNull()
})

test.each(['source_sha256', 'parser_version'] as const)('rejects first binding whose %s contradicts selected structure metadata', async field => {
 const fetch = mockApi(); const original = fetch.getMockImplementation()!
 const altered = { ...source, [field]: field === 'source_sha256' ? 'c'.repeat(64) : 'wrong' }
 fetch.mockImplementation((url, init) => url.endsWith('/analysis-setup') && init?.method === 'PUT'
  ? Promise.resolve(Response.json({ ...saved, revision: 1, source_sha256: altered.source_sha256, source: altered })) : original(url, init))
 const user = userEvent.setup(); await open(user); await pick(user)
 await user.selectOptions(screen.getByLabelText('数值列'), 'A')
 await user.click(screen.getByRole('button', { name: '检查字段' })); await screen.findByText('可用 30 行，排除 0 行。')
 await user.click(screen.getByRole('button', { name: '保存分析配置' }))
 await screen.findByText('数据来源或版本不一致，请重新载入配置。')
 expect(screen.queryByText('已保存分析配置，可前往描述统计。')).toBeNull()
})

test('initial setup GET times out and reload recovers', async () => {
 const fetch = mockApi(); const original = fetch.getMockImplementation()!; let first = true; let signal: AbortSignal | null = null
 fetch.mockImplementation((url, init) => {
  if (first && url.endsWith('/analysis-setup') && !init?.method) {
   first = false; signal = init?.signal as AbortSignal
   return new Promise<Response>((_resolve, reject) => signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError'))))
  }
  return original(url, init)
 })
 const timer = vi.spyOn(window, 'setTimeout')
 const user = userEvent.setup(); render(<AnalysisSetup projectId="p1" files={files} />)
 try {
  await user.selectOptions(screen.getByLabelText('用于分析的文件'), 'f1')
  const expire = timer.mock.calls.find(([, delay]) => delay === 30_000)?.[0] as (() => void) | undefined
  expect(expire).toBeTypeOf('function')
  await act(async () => expire!()); expect(signal!.aborted).toBe(true)
 }
 finally { timer.mockRestore() }
 await screen.findByText('请求超时，请重新载入配置确认结果后重试。')
 await user.click(screen.getByRole('button', { name: '重新载入分析配置' }))
 expect((await screen.findByLabelText('原始数据版本') as HTMLSelectElement).value).toBe('')
})

const preparedSource = { ...source, kind: 'prepared_dataset_version', dataset_id: 'pd1', dataset_version: 7, parent_dataset_id: 'd1', parent_dataset_version: 1, transform_version: 'excel_prepare_v1' }
const preparedVersion = { id: 'pd1', file_id: 'f1', parent_dataset_id: 'd1', parent_dataset_version: 1, version: 7, created_at: dataset.created_at, task_id: 'pt1', source: preparedSource, recipe: { header_row: 1, data_range: 'A2:B31', fields: [{ column: 1, name: '数值', unit: { status: 'confirmed', value: 'mg' }, trim_text: false, missing_markers: [] }] }, summary: { record_count: 30, changed_cell_count: 0, changed_row_count: 0, trimmed_cell_count: 0, missing_marker_cell_count: 0, columns: [], unresolved: [], changes_truncated: false }, download_url: '/api/v1/projects/p1/files/f1/prepared-dataset-versions/pd1/download' }

test.each([false,true])('parent setup stays mounted after published plan (initially published=%s)',async(initiallyPublished)=>{
 let published=initiallyPublished
 const input={...reviewFixture.input_version,source:preparedSource}
 const candidate={...reviewFixture,source:preparedSource,input_version:input,selection,check:{...reviewFixture.check,selection_check:check,issues:[]},task:{...reviewFixture.task,input_version:input}}
 const plan={schema_version:1,workflow_version:'analysis_plan_v1',rules_version:'analysis_plan_rules_v1',id:'plan1',task_id:'t1',decision_id:'decision1',project_id:'p1',file_id:'f1',source:preparedSource,selection,check:candidate.check,resolutions:{},plan_revision:1,setup_revision:2,created_at:dataset.created_at,sha256:'c'.repeat(64)}
 const current=()=>published?{...candidate,wait_id:null,result:plan,task:{...candidate.task,status:'succeeded',display_status:'succeeded'}}:candidate
 const fetch=mockApi();const original=fetch.getMockImplementation()!
 fetch.mockImplementation((url,init)=>{
  if(url.endsWith('/analysis-setup'))return Promise.resolve(Response.json({...saved,source:preparedSource,revision:published?2:1,...(published?{analysis_plan:{plan_id:'plan1',sha256:plan.sha256,resolutions:{}}}:{})}))
  if(url.endsWith('/analysis-result'))return Promise.resolve(Response.json({current_revision:published?2:1,is_current:false,result:null}))
  if(url.endsWith('/prepared-dataset-versions/pd1'))return Promise.resolve(Response.json(preparedVersion))
  if(url.includes('/prepared-dataset-versions?'))return Promise.resolve(Response.json({items:[preparedVersion],total:1,page:1,page_size:5}))
  if(url.includes('/analysis-plans?'))return Promise.resolve(Response.json({items:[current()],total:1,page:1,page_size:5}))
  if(url.endsWith('/analysis-plan/decisions')){published=true;return Promise.resolve(Response.json(current().task))}
  if(url.endsWith('/analysis-plan'))return Promise.resolve(Response.json(current()))
  return original(url,init)
 })
 const user=userEvent.setup();render(<AnalysisSetup projectId="p1" files={files}/>);await user.selectOptions(screen.getByLabelText('用于分析的文件'),'f1')
 if(!initiallyPublished)await user.click(await screen.findByRole('button',{name:'确认并发布分析计划'}))
 await screen.findByText('当前配置已关联已确认分析计划。')
 await act(async()=>{await new Promise(resolve=>setTimeout(resolve,100))})
 expect(fetch.mock.calls.filter(([url])=>url.endsWith('/analysis-setup'))).toHaveLength(initiallyPublished?1:2)
 await user.click(screen.getByRole('button',{name:'描述统计'}))
 await waitFor(()=>expect((screen.getByRole('button',{name:'执行描述统计'}) as HTMLButtonElement).disabled).toBe(false))
})
test('restores a prepared version outside page one and keeps draft and selection when newer version appears', async () => {
 const fetch = mockApi({ saved: { ...saved, source: preparedSource } }); const original = fetch.getMockImplementation()!
 fetch.mockImplementation((url, init) => {
  if (url.includes('/prepared-dataset-versions?')) return Promise.resolve(Response.json({ items: [], total: 0, page: 1, page_size: 5 }))
  if (url.endsWith('/prepared-dataset-versions/pd1')) return Promise.resolve(Response.json(preparedVersion))
  return original(url, init)
 })
 const user = userEvent.setup(); render(<AnalysisSetup projectId="p1" files={files} />)
 await user.selectOptions(screen.getByLabelText('用于分析的文件'), 'f1')
 const sourceKind = await screen.findByLabelText('数据来源类型') as HTMLSelectElement
 await waitFor(() => expect(sourceKind.value).toBe('prepared'))
 expect((screen.getByLabelText('整理数据版本') as HTMLSelectElement).value).toBe('pd1')
 const unit = await screen.findByLabelText('数值单位（可选）'); await user.type(unit, 'draft')
 await user.click(screen.getByRole('button', { name: '刷新数据版本' }))
 expect((screen.getByLabelText('整理数据版本') as HTMLSelectElement).value).toBe('pd1')
 expect(screen.getByLabelText('数值单位（可选）')).toBe(unit)
 expect(fetch.mock.calls.some(([url]) => url.endsWith('/prepared-dataset-versions/pd1'))).toBe(true)
})
test('explicit prepared selection uses confirmed unit default and sends its prepared id', async () => {
 const fetch = mockApi(); const original = fetch.getMockImplementation()!
 fetch.mockImplementation((url, init) => {
  if (url.includes('/prepared-dataset-versions?')) return Promise.resolve(Response.json({ items: [preparedVersion], total: 1, page: 1, page_size: 5 }))
  if (url.includes('/analysis-profile?')) return Promise.resolve(Response.json({ ...profile, columns: [{ ...profile.columns[0], unit: { status: 'confirmed', value: 'mg' } }] }))
  return original(url, init)
 })
 const user = userEvent.setup(); await open(user)
 await user.selectOptions(screen.getByLabelText('数据来源类型'), 'prepared')
 await user.selectOptions(await screen.findByLabelText('整理数据版本'), 'pd1')
 await user.selectOptions(await screen.findByLabelText('数值列'), 'A')
 expect((screen.getByLabelText('数值单位（可选）') as HTMLInputElement).value).toBe('mg')
 await user.click(screen.getByRole('button', { name: '检查字段' }))
 await screen.findByText('可用 30 行，排除 0 行。')
 const call = fetch.mock.calls.find(([url]) => url.endsWith('/analysis-check'))!
 expect(JSON.parse(String(call[1]?.body)).dataset_id).toBe('pd1')
})

test('a new same-name prepared source starts fresh and uses its own unit instead of the raw saved unit', async () => {
 const fetch = mockApi({ saved: { ...saved, selection: { ...selection, unit: 'kg' } } }); const original = fetch.getMockImplementation()!
 fetch.mockImplementation((url, init) => {
  if (url.includes('/prepared-dataset-versions?')) return Promise.resolve(Response.json({ items: [preparedVersion], total: 1, page: 1, page_size: 5 }))
  if (url.includes('/analysis-profile?') && url.includes('dataset_id=pd1')) return Promise.resolve(Response.json({ ...profile, columns: [{ ...profile.columns[0], unit: { status: 'confirmed', value: 'mg' } }] }))
  return original(url, init)
 })
 const user = userEvent.setup(); await open(user)
 expect((await screen.findByLabelText('数值单位（可选）') as HTMLInputElement).value).toBe('kg')
 await user.selectOptions(screen.getByLabelText('数据来源类型'), 'prepared')
 await user.selectOptions(await screen.findByLabelText('整理数据版本'), 'pd1')
 expect((await screen.findByLabelText('数值列') as HTMLSelectElement).value).toBe('')
 expect((screen.getByLabelText('数值单位（可选）') as HTMLInputElement).value).toBe('')
 await user.selectOptions(screen.getByLabelText('数值列'), 'A')
 expect((screen.getByLabelText('数值单位（可选）') as HTMLInputElement).value).toBe('mg')
 await user.clear(screen.getByLabelText('数值单位（可选）')); await user.type(screen.getByLabelText('数值单位（可选）'), 'mcg')
 await user.click(screen.getByRole('button', { name: '刷新数据版本' }))
 expect((screen.getByLabelText('数值单位（可选）') as HTMLInputElement).value).toBe('mcg')
 await user.click(screen.getByRole('button', { name: '检查字段' }))
 await screen.findByText('可用 30 行，排除 0 行。')
 const call = fetch.mock.calls.find(([url]) => url.endsWith('/analysis-check'))!
 expect(JSON.parse(String(call[1]?.body))).toMatchObject({ dataset_id: 'pd1', unit: 'mcg' })
})

test('restoring the exact prepared source preserves its saved explicit unit rather than the metadata default', async () => {
 const fetch = mockApi({ saved: { ...saved, source: preparedSource, selection: { ...selection, unit: 'mcg' } } }); const original = fetch.getMockImplementation()!
 fetch.mockImplementation((url, init) => {
  if (url.includes('/prepared-dataset-versions?')) return Promise.resolve(Response.json({ items: [], total: 0, page: 1, page_size: 5 }))
  if (url.endsWith('/prepared-dataset-versions/pd1')) return Promise.resolve(Response.json(preparedVersion))
  if (url.includes('/analysis-profile?')) return Promise.resolve(Response.json({ ...profile, columns: [{ ...profile.columns[0], unit: { status: 'confirmed', value: 'mg' } }] }))
  return original(url, init)
 })
 const user = userEvent.setup(); render(<AnalysisSetup projectId="p1" files={files} />)
 await user.selectOptions(screen.getByLabelText('用于分析的文件'), 'f1')
 expect((await screen.findByLabelText('数值列') as HTMLSelectElement).value).toBe('A')
 expect((screen.getByLabelText('数值单位（可选）') as HTMLInputElement).value).toBe('mcg')
})
