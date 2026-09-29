import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AnalysisSetup from './AnalysisSetup'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const files = [{ id: 'f1', filename: '研究.xlsx', uploaded_at: '2026-09-29T01:00:00Z', parse_status: 'parsed' as const },
  { id: 'f2', filename: '另一份.xlsx', uploaded_at: '2026-09-29T02:00:00Z', parse_status: 'parsed' as const }]
const selection = { task_type: 'descriptive_boxplot', sheet_name: '数据 & 表', numeric_column: 'A', group_column: 'B',
  unit: 'mg/L', missing_policy: 'exclude_selected_missing' }
const check = { ready: true, row_count: 25, valid_count: 23, excluded_count: 2, groups: [{ label: 'A组', count: 23 }], issues: [], warnings: ['有 2 行缺失。'] }
const saved = { file_id: 'f1', source_sha256: 'a'.repeat(64), status: 'configured', revision: 1,
  selection, check, updated_at: '2026-09-29T03:00:00Z' }
const column = { id: 'A', name: '指标', type: 'number', non_missing_count: 24, missing_count: 1, numeric_count: 24,
  can_be_numeric: true, can_be_group: true, issue_cells: [] }
const profile = { sheet_name: '数据 & 表', row_count: 25, warnings: [], columns: [column,
  { ...column, id: 'B', name: '指标', type: 'text', numeric_count: 0, can_be_numeric: false },
  { ...column, id: 'C', name: '混合值', type: 'mixed', numeric_count: 23, can_be_numeric: false, can_be_group: false, issue_cells: ['C26'] }] }
const stats = { n: 23, mean: 2.5, std: 1.25, min: 0, q1: 1.5, median: 2.5, q3: 3.5, max: 5, iqr: 2, warnings: [] }
const analysisResult = { id: 'run-1', file_id: 'f1', filename: '研究.xlsx', source_sha256: 'a'.repeat(64),
  setup_revision: 1, selection, check, numeric_name: '指标', group_name: '组别',
  engine: { id: 'descriptive_statistics_v1', python_version: '3.11.4', openpyxl_version: '3.1.5', std_ddof: 1, quantile_method: 'linear_inclusive' },
  started_at: '2026-09-29T03:00:00Z', completed_at: '2026-09-29T03:00:01Z', overall: stats,
  groups: [{ label: 'A组', statistics: { ...stats, n: 1, std: null, warnings: ['有效记录不足 2 条，样本标准差无法计算。'] } }] }

function api(options: { existing?: boolean; conflict?: boolean; invalid?: boolean; failOnce?: boolean; slowProfile?: Promise<Response>
  existingResult?: boolean; runFailOnce?: boolean; resultFailOnce?: boolean; runConflict?: boolean; slowRun?: Promise<Response> } = {}) {
  let current: typeof saved | null = options.existing ? saved : null
  let result: typeof analysisResult | null = options.existingResult ? analysisResult : null
  const mock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/v1/ai/config') return Response.json({ configured: true, model: 'test-model', message: '' })
    if (url.endsWith('/boxplot')) return Response.json({ current_revision: current?.revision ?? null,
      is_current: result?.setup_revision === current?.revision, figure: null, job: null })
    if (url.endsWith('/analysis-result')) {
      if (options.resultFailOnce) { options.resultFailOnce = false; throw new TypeError('offline') }
      return Response.json({ current_revision: current?.revision ?? null, is_current: !!result && result.setup_revision === current?.revision, result })
    }
    if (url.endsWith('/analysis-runs')) {
      if (options.slowRun) return options.slowRun
      if (options.runFailOnce) { options.runFailOnce = false; throw new TypeError('offline') }
      if (options.runConflict) return Response.json({ detail: { message: '分析配置已变化，请重新载入配置后再执行。' } }, { status: 409 })
      result = { ...analysisResult, setup_revision: current!.revision, selection: current!.selection }
      return Response.json(result)
    }
    if (url.endsWith('/preview')) return Response.json({ sheets: [{ name: '数据 & 表' }, { name: '空表' }] })
    if (url.includes('/analysis-profile?')) {
      if (options.failOnce) { options.failOnce = false; throw new TypeError('offline') }
      if (options.slowProfile && url.includes('/f1/')) return options.slowProfile
      return Response.json(url.includes(encodeURIComponent('空表')) ? { ...profile, sheet_name: '空表', row_count: 0, columns: [] } : profile)
    }
    if (url.endsWith('/analysis-check')) return Response.json(options.invalid
      ? { ...check, ready: false, valid_count: 0, issues: ['选中字段没有完整记录。'] } : check)
    if (url.endsWith('/analysis-setup')) {
      if (init?.method === 'PUT') {
        if (options.conflict) return Response.json({ detail: { message: '配置已在其他页面更新，请重新载入。' } }, { status: 409 })
        const body = JSON.parse(init.body as string)
        current = { ...saved, revision: body.expected_revision + 1, selection: { ...selection, ...body } }
      }
      return Response.json(current)
    }
    throw new Error(`Unexpected API: ${url}`)
  })
  vi.stubGlobal('fetch', mock)
  return mock
}

async function chooseFile(user: ReturnType<typeof userEvent.setup>) {
  await user.selectOptions(screen.getByLabelText('用于分析的文件'), 'f1')
  await screen.findByLabelText('数值列')
}

test('restored statistics expose an explicit OpenAI generation action without submitting', async () => {
  const mock = api({ existing: true, existingResult: true })
  const user = userEvent.setup()
  render(<AnalysisSetup projectId="p1" files={files} />)
  await chooseFile(user)
  expect(await screen.findByRole('button', { name: '使用 OpenAI 生成箱线图' })).toBeTruthy()
  expect(mock.mock.calls.some(call => call[0].endsWith('/boxplot') && call[1]?.method === 'POST')).toBe(false)
})

test('OpenAI submission locks configuration and statistics but allows file switching', async () => {
  const mock = api({ existing: true, existingResult: true })
  const original = mock.getMockImplementation()!
  let submitted = false
  mock.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/boxplot') && (init?.method === 'POST' || submitted)) {
      submitted = true
      return Response.json({ current_revision: 1, is_current: true, figure: null,
        job: { id: 'j', status: 'running', message: '处理中', response_id: 'r', created_at: '' } })
    }
    return original(url, init)
  })
  const user = userEvent.setup()
  render(<AnalysisSetup projectId="p1" files={files} />)
  await chooseFile(user)
  const generate = await screen.findByRole('button', { name: '使用 OpenAI 生成箱线图' })
  await waitFor(() => expect((generate as HTMLButtonElement).disabled).toBe(false))
  await user.click(generate)
  await waitFor(() => expect((screen.getByLabelText('数值列') as HTMLSelectElement).disabled).toBe(true))
  expect((screen.getByRole('button', { name: '执行描述统计' }) as HTMLButtonElement).disabled).toBe(true)
  expect((screen.getByLabelText('用于分析的文件') as HTMLSelectElement).disabled).toBe(false)
})

test('chooses fields, checks complete rows and saves configuration without running statistics', async () => {
  const mock = api()
  const user = userEvent.setup()
  render(<AnalysisSetup projectId="p1" files={files} />)
  await chooseFile(user)
  expect(screen.getByText('整表检查：25 行数据')).toBeTruthy()
  const invalid = screen.getByLabelText('数值列').querySelector('option[value="C"]') as HTMLOptionElement
  expect(invalid.disabled).toBe(true)
  await user.selectOptions(screen.getByLabelText('数值列'), 'A')
  await user.selectOptions(screen.getByLabelText('分组列（可选）'), 'B')
  await user.type(screen.getByLabelText('数值单位（可选）'), 'mg/L')
  expect((screen.getByRole('button', { name: '保存分析配置' }) as HTMLButtonElement).disabled).toBe(true)
  await user.click(screen.getByRole('button', { name: '检查字段' }))
  expect(await screen.findByText('可用 23 行，排除 2 行。')).toBeTruthy()
  await user.click(screen.getByRole('button', { name: '保存分析配置' }))
  expect(await screen.findByText(/已保存分析配置/)).toBeTruthy()
  const call = mock.mock.calls.find(([, init]) => init?.method === 'PUT')!
  expect(JSON.parse(call[1]!.body as string)).toEqual({ ...selection, expected_revision: 0 })
  expect(mock.mock.calls.every(([url]) => !url.includes('/run'))).toBe(true)
})

test('restores saved fields after remount and invalidates checks when input changes', async () => {
  api({ existing: true })
  const user = userEvent.setup()
  const first = render(<AnalysisSetup projectId="p1" files={files} />)
  await chooseFile(user)
  expect((screen.getByLabelText('分组列（可选）') as HTMLSelectElement).value).toBe('B')
  expect((screen.getByLabelText('数值单位（可选）') as HTMLInputElement).value).toBe('mg/L')
  await user.selectOptions(screen.getByLabelText('分组列（可选）'), '')
  expect((screen.getByRole('button', { name: '保存分析配置' }) as HTMLButtonElement).disabled).toBe(true)
  first.unmount()
  render(<AnalysisSetup projectId="p1" files={files} />)
  await chooseFile(user)
  expect((screen.getByLabelText('分组列（可选）') as HTMLSelectElement).value).toBe('B')
})

test('empty sheet disables field checking and saving', async () => {
  api()
  const user = userEvent.setup()
  render(<AnalysisSetup projectId="p1" files={files} />)
  await chooseFile(user)
  await user.selectOptions(screen.getByLabelText('分析工作表'), '空表')
  expect(await screen.findByText('当前工作表没有数据行，请选择其他工作表。')).toBeTruthy()
  expect((screen.getByRole('button', { name: '检查字段' }) as HTMLButtonElement).disabled).toBe(true)
})

test('invalid complete-record check prevents save', async () => {
  const mock = api({ invalid: true })
  const user = userEvent.setup()
  render(<AnalysisSetup projectId="p1" files={files} />)
  await chooseFile(user)
  await user.selectOptions(screen.getByLabelText('数值列'), 'A')
  await user.click(screen.getByRole('button', { name: '检查字段' }))
  expect(await screen.findByText('选中字段没有完整记录。')).toBeTruthy()
  expect((screen.getByRole('button', { name: '保存分析配置' }) as HTMLButtonElement).disabled).toBe(true)
  expect(mock.mock.calls.some(([, init]) => init?.method === 'PUT')).toBe(false)
})

test('save conflict gives recovery action instead of claiming success', async () => {
  api({ existing: true, conflict: true })
  const user = userEvent.setup()
  render(<AnalysisSetup projectId="p1" files={files} />)
  await chooseFile(user)
  await user.click(screen.getByRole('button', { name: '检查字段' }))
  await screen.findByText('可用 23 行，排除 2 行。')
  await user.click(screen.getByRole('button', { name: '保存分析配置' }))
  expect((await screen.findByRole('alert')).textContent).toContain('其他页面更新')
  expect(screen.getByRole('button', { name: '重新载入分析配置' })).toBeTruthy()
})

test('profile failure can be retried', async () => {
  api({ failOnce: true })
  const user = userEvent.setup()
  render(<AnalysisSetup projectId="p1" files={files} />)
  await user.selectOptions(screen.getByLabelText('用于分析的文件'), 'f1')
  await screen.findByRole('alert')
  await user.click(screen.getByRole('button', { name: '重试字段检查' }))
  expect(await screen.findByLabelText('数值列')).toBeTruthy()
})

test('late profile response cannot replace another file', async () => {
  let finish: (response: Response) => void = () => {}
  api({ slowProfile: new Promise(resolve => { finish = resolve }) })
  const user = userEvent.setup()
  render(<AnalysisSetup projectId="p1" files={files} />)
  await user.selectOptions(screen.getByLabelText('用于分析的文件'), 'f1')
  await screen.findByText('正在检查整张工作表……')
  await user.selectOptions(screen.getByLabelText('用于分析的文件'), 'f2')
  await screen.findByLabelText('数值列')
  finish(Response.json({ ...profile, row_count: 999 }))
  await waitFor(() => expect(screen.queryByText('整表检查：999 行数据')).toBeNull())
  expect((screen.getByLabelText('用于分析的文件') as HTMLSelectElement).value).toBe('f2')
})

test('executes saved configuration and shows actual statistics, provenance and undefined SD', async () => {
  const mock = api({ existing: true })
  const user = userEvent.setup()
  render(<AnalysisSetup projectId="p1" files={files} />)
  await chooseFile(user)
  await user.click(await screen.findByRole('button', { name: '执行描述统计' }))
  const table = await screen.findByRole('table', { name: '描述统计结果' })
  expect(within(table).getByRole('row', { name: /总体/ }).textContent).toContain('2.5')
  expect(within(table).getByRole('row', { name: /A组/ }).textContent).toContain('—')
  expect(screen.getByText('有效记录不足 2 条，样本标准差无法计算。')).toBeTruthy()
  expect(screen.getByText(/结果已保存/)).toBeTruthy()
  expect(screen.getByText(/配置版本：1/)).toBeTruthy()
  const call = mock.mock.calls.find(([url]) => url.endsWith('/analysis-runs'))!
  expect(JSON.parse(call[1]!.body as string)).toEqual({ expected_revision: 1 })
})

test('restores persisted statistics without automatically executing', async () => {
  const mock = api({ existing: true, existingResult: true })
  const user = userEvent.setup()
  render(<AnalysisSetup projectId="p1" files={files} />)
  await chooseFile(user)
  await screen.findByRole('table', { name: '描述统计结果' })
  expect(mock.mock.calls.some(([url]) => url.endsWith('/analysis-runs'))).toBe(false)
})

test('unsaved fields disable execution and label the previous result', async () => {
  api({ existing: true, existingResult: true })
  const user = userEvent.setup()
  render(<AnalysisSetup projectId="p1" files={files} />)
  await chooseFile(user)
  await screen.findByRole('table', { name: '描述统计结果' })
  await user.type(screen.getByLabelText('数值单位（可选）'), ' changed')
  expect((screen.getByRole('button', { name: '执行描述统计' }) as HTMLButtonElement).disabled).toBe(true)
  expect(screen.getByText(/当前字段尚未保存/)).toBeTruthy()
  expect(screen.getByText(/数值：A · 指标；单位：mg\/L/)).toBeTruthy()
})

test('new saved revision marks old result until new calculation succeeds', async () => {
  api({ existing: true, existingResult: true })
  const user = userEvent.setup()
  render(<AnalysisSetup projectId="p1" files={files} />)
  await chooseFile(user)
  await screen.findByRole('table', { name: '描述统计结果' })
  await user.clear(screen.getByLabelText('数值单位（可选）'))
  await user.type(screen.getByLabelText('数值单位（可选）'), 'mmol/L')
  await user.click(screen.getByRole('button', { name: '检查字段' }))
  await screen.findByText('可用 23 行，排除 2 行。')
  await user.click(screen.getByRole('button', { name: '保存分析配置' }))
  await screen.findByText(/旧配置的统计结果/)
  await user.click(screen.getByRole('button', { name: '执行描述统计' }))
  expect(await screen.findByText(/配置版本：2/)).toBeTruthy()
  expect(screen.queryByText(/旧配置的统计结果/)).toBeNull()
})

test('failed execution can read results before retrying', async () => {
  api({ existing: true, runFailOnce: true })
  const user = userEvent.setup()
  render(<AnalysisSetup projectId="p1" files={files} />)
  await chooseFile(user)
  await user.click(await screen.findByRole('button', { name: '执行描述统计' }))
  await screen.findByRole('alert')
  expect(screen.queryByText(/结果已保存/)).toBeNull()
  await user.click(screen.getByRole('button', { name: '重新读取统计结果' }))
  await screen.findByText('尚未执行当前配置的描述统计。')
  await user.click(screen.getByRole('button', { name: '执行描述统计' }))
  await screen.findByRole('table', { name: '描述统计结果' })
})

test('failed result loading has a retry and does not silently enable execution', async () => {
  api({ existing: true, existingResult: true, resultFailOnce: true })
  const user = userEvent.setup()
  render(<AnalysisSetup projectId="p1" files={files} />)
  await chooseFile(user)
  await screen.findByRole('alert')
  expect((screen.getByRole('button', { name: '执行描述统计' }) as HTMLButtonElement).disabled).toBe(true)
  await user.click(screen.getByRole('button', { name: '重新读取统计结果' }))
  await screen.findByRole('table', { name: '描述统计结果' })
})

test('configuration conflict tells the user to reload instead of claiming a result', async () => {
  api({ existing: true, runConflict: true })
  const user = userEvent.setup()
  render(<AnalysisSetup projectId="p1" files={files} />)
  await chooseFile(user)
  await user.click(await screen.findByRole('button', { name: '执行描述统计' }))
  expect((await screen.findByRole('alert')).textContent).toContain('重新载入配置')
  expect(screen.queryByRole('table', { name: '描述统计结果' })).toBeNull()
})

test('pending run disables inputs, prevents duplicate posts and cannot replace another file', async () => {
  let finish: (response: Response) => void = () => {}
  const mock = api({ existing: true, slowRun: new Promise(resolve => { finish = resolve }) })
  const user = userEvent.setup()
  render(<AnalysisSetup projectId="p1" files={files} />)
  await chooseFile(user)
  await user.dblClick(await screen.findByRole('button', { name: '执行描述统计' }))
  expect((screen.getByLabelText('数值列') as HTMLSelectElement).disabled).toBe(true)
  expect(mock.mock.calls.filter(([url]) => url.endsWith('/analysis-runs'))).toHaveLength(1)
  await user.selectOptions(screen.getByLabelText('用于分析的文件'), 'f2')
  await screen.findByLabelText('数值列')
  finish(Response.json(analysisResult))
  await waitFor(() => expect(screen.queryByRole('table', { name: '描述统计结果' })).toBeNull())
})
