import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import ExcelPreview from '../../features/files/ExcelPreview'
import AnalysisSetup from '../../features/analysis/AnalysisSetup'
import StatisticsResults from '../../features/analysis/StatisticsResults'
import BoxplotFigure from '../../features/figures/BoxplotFigure'
import AnalysisExplanation from '../../features/explanations/AnalysisExplanation'

import { setLocale, translate } from '../../shared/i18n'
import { workflowNotice } from '../../shared/i18n/workflowMessages'
const locale = (value: 'zh-CN' | 'en') => act(() => setLocale(value))
afterEach(() => { cleanup(); locale('zh-CN'); vi.unstubAllGlobals(); vi.useRealTimers() })

const selection = { task_type: 'descriptive_boxplot' as const, sheet_name: '研究数据', numeric_column: 'A', group_column: null, unit: '研究单位', missing_policy: 'exclude_selected_missing' as const }
const check = { ready: true, row_count: 3, valid_count: 3, excluded_count: 0, groups: [], issues: [], warnings: [] }
const stats = { n: 3, mean: 2, std: 1, min: 1, q1: 1.5, median: 2, q3: 2.5, max: 3, iqr: 1, warnings: [] }
const figure = { id: 'figure', analysis_run_id: 'run', setup_revision: 1, title: '已保存图标题', caption: '已保存图说明', x_label: '分组原文', y_label: '数值原文', source_sha256: 'source', sha256: 'image', created_at: '2026-10-05', engine: { id: 'boxplot-v1', provider: 'test', model: 'test' }, verification: { status: 'matched', note: '历史核验说明' } }
const explanation = { id: 'exp', analysis_run_id: 'run', figure_id: 'figure', setup_revision: 1, language: 'zh-CN', figure_sha256: 'image', source_sha256: 'source', created_at: '2026-10-05', sections: [{ key: 'purpose', title: '研究标题原文', text: '研究正文原文', evidence: [{ key: 'count', label: '证据原文', value: '3' }] }], limitations: ['历史限制原文'], engine: { id: 'explanation-v1', provider: 'test', model: 'test' }, verification: { status: 'matched', note: '历史核验说明' }, provenance: {} }
const report = { id: 'report', analysis_run_id: 'run', figure_id: 'figure', explanation_id: 'exp', setup_revision: 1, source_sha256: 'source', figure_sha256: 'image', created_at: '2026-10-05', filename: '研究报告原文.docx', size_bytes: 20, sha256: 'docx', language: 'zh-CN', engine: { id: 'word-v1', python_docx: 'test' }, input_sha256: 'input' }

it('switches upload labels and preserves selected user filename without another request', async () => {
  const fetch = vi.fn(async () => Response.json({ max_upload_bytes: 1024 * 1024, allowed_extensions: ['.xlsx'] }))
  vi.stubGlobal('fetch', fetch); render(<ExcelPreview />)
  fireEvent.change(await screen.findByLabelText('选择 Excel 文件'), { target: { files: [new File(['data'], '研究数据.xlsx')] } })
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1)); locale('en')
  expect(screen.getByLabelText('Choose an Excel file')).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Upload and preview' })).toBeTruthy()
  expect(screen.getByText(/研究数据.xlsx/)).toBeTruthy()
  expect(fetch).toHaveBeenCalledTimes(1)
})

it('translates analysis labels while preserving field values and a draft on language switches', async () => {
  const fetch = vi.fn(async (url: string) => Response.json(url.endsWith('/preview') ? { sheets: [{ name: '研究数据' }] }
    : url.endsWith('/analysis-setup') ? null : { sheet_name: '研究数据', row_count: 3, warnings: [], columns: [{ id: 'A', name: '指标原文', type: 'number', non_missing_count: 3, missing_count: 0, numeric_count: 3, can_be_numeric: true, can_be_group: true, issue_cells: [] }] }))
  vi.stubGlobal('fetch', fetch); render(<AnalysisSetup projectId="p" files={[{ id: 'f', filename: '研究数据.xlsx', parse_status: 'parsed', uploaded_at: '2026-10-05' }]} />)
  fireEvent.change(screen.getByLabelText('用于分析的文件'), { target: { value: 'f' } })
  fireEvent.change(await screen.findByLabelText('数值单位（可选）'), { target: { value: '用户单位原文' } })
  const calls = fetch.mock.calls.length; locale('en')
  expect(screen.getByLabelText('Numeric column')).toBeTruthy()
  expect((screen.getByLabelText('Unit (optional)') as HTMLInputElement).value).toBe('用户单位原文')
  expect(screen.getAllByText(/指标原文/).length).toBeGreaterThan(0)
  expect(fetch).toHaveBeenCalledTimes(calls)
  expect(screen.getByRole('button', { name: 'Field setup' }).getAttribute('aria-current')).toBe('step')
  fireEvent.click(screen.getByRole('button', { name: 'Chart' }))
  expect(screen.getByText('Complete descriptive statistics before generating figures, explanations and reports.', { selector: '.workflow-stage:not([hidden]) p' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Field setup' }))
  expect((screen.getByLabelText('Unit (optional)') as HTMLInputElement).value).toBe('用户单位原文')
  expect(fetch).toHaveBeenCalledTimes(calls)
})

it('translates statistics labels without translating groups or numeric values', async () => {
  locale('en')
  vi.stubGlobal('fetch', vi.fn(async (url: string) => Response.json(url.endsWith('/analysis-result') ? { current_revision: 1, is_current: true, result: { id: 'run', filename: '研究数据.xlsx', source_sha256: 'source', setup_revision: 1, selection, check, numeric_name: '指标原文', group_name: '组名原文', started_at: '2026-10-05', completed_at: '2026-10-05', engine: { id: 'test', python_version: 'test', openpyxl_version: 'test' }, overall: stats, groups: [{ label: '总体（完整记录）', statistics: stats }] } } : url.endsWith('/config') ? { configured: false } : { current_revision: 1, is_current: true, figure: null, job: null })))
  render(<StatisticsResults base="/file" savedRevision={1} fieldsMatch={true} disabled={false} onBusyChange={() => {}} />)
  expect(await screen.findByRole('table', { name: 'Descriptive statistics results' })).toBeTruthy()
  expect(screen.getByRole('columnheader', { name: 'Mean' })).toBeTruthy()
  expect(screen.getByRole('rowheader', { name: 'Overall (complete records)' })).toBeTruthy()
  expect(screen.getByRole('rowheader', { name: '总体（完整记录）' })).toBeTruthy()
  expect(screen.queryByText(/Setup revision|SHA256|openpyxl|Result ID/)).toBeNull()
})

it('translates figure and explanation controls while preserving historical artifacts and avoiding generation', async () => {
  const fetch = vi.fn(async (url: string) => Response.json(url.endsWith('/config') ? { configured: true } : url.endsWith('/explanation') ? { current_revision: 1, is_current: true, figure_id: 'figure', explanation, job: null } : url.endsWith('/report') ? { current_revision: 1, is_current: true, ready: true, issues: [], report } : { current_revision: 1, is_current: true, figure, job: null }))
  vi.stubGlobal('fetch', fetch); render(<BoxplotFigure base="/file" runId="run" revision={1} canGenerate disabled={false} onBusyChange={() => {}} />)
  await screen.findByRole('link', { name: '下载 Word 报告' }); const calls = fetch.mock.calls.length; locale('en')
  expect(screen.getByRole('button', { name: 'Generate a boxplot with OpenAI' })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Generate an explanation with OpenAI' })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Generate Word report' })).toBeTruthy()
  expect(screen.getByRole('link', { name: 'Download Word report' })).toBeTruthy()
  for (const text of ['已保存图标题', '已保存图说明', '研究标题原文', '研究正文原文', '历史限制原文']) expect(screen.getByText(text)).toBeTruthy()
  expect(screen.getByText(/研究报告原文.docx/)).toBeTruthy(); expect(fetch).toHaveBeenCalledTimes(calls)
})

it('does not expose arbitrary service messages and retranslates retained errors', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => url.endsWith('/config') ? Response.json({ configured: true }) : Response.json({ detail: { code: 'unknown_code', message: 'SECRET upstream raw error', params: {} } }, { status: 500 })))
  render(<AnalysisExplanation base="/file" runId="run" revision={1} figureId="figure" canGenerate disabled={false} onBusyChange={() => {}} />)
  await screen.findByRole('alert'); locale('en')
  expect(screen.getByRole('alert').textContent).toBe('Explanation request failed. Reload the explanation.')
  expect(screen.queryByText(/SECRET/)).toBeNull()
})

it('translates only legacy system notice templates and leaves unfamiliar text unchanged', () => {
  locale('en')
  expect(workflowNotice('存在重复列名，已按原始列顺序保留。', translate)).toBe('Duplicate column names are retained in their original order.')
  expect(workflowNotice('有效分组超过 20 个，请选择分类字段，避免使用样本编号作为分组。', translate)).toContain('more than 20 valid groups')
  expect(workflowNotice('数值列必须包含实际数值，且非缺失值全部为数值；文本数字、布尔、日期、公式或错误不能直接分析，例如 A21、AB22。', translate)).toContain('A21、AB22')
  expect(workflowNotice('样本标准差超出可表示的数值范围，结果标记为无法计算。', translate)).toBe('Sample standard deviation exceeds the representable numeric range and is marked as unavailable.')
  expect(workflowNotice('数据准备', translate)).toBe('数据准备')
  expect(workflowNotice('用户备注：均值超出可表示的数值范围，结果标记为无法计算。', translate)).toBe('用户备注：均值超出可表示的数值范围，结果标记为无法计算。')
  locale('zh-CN')
  expect(workflowNotice('样本标准差超出可表示的数值范围，结果标记为无法计算。', translate)).toBe('样本标准差超出可表示的数值范围，结果标记为无法计算。')
})

it('switches historical artifact notices and download names without translating saved research', async () => {
  const fetch = vi.fn(async (url: string) => Response.json(url.endsWith('/config') ? { configured: true }
    : url.endsWith('/explanation') ? { current_revision: 2, is_current: false, figure_id: 'figure', explanation, job: null }
      : url.endsWith('/report') ? { current_revision: 2, is_current: false, ready: false, issues: ['当前结果属于旧配置，请先完成当前配置的统计、图表和解释。'], report }
        : { current_revision: 2, is_current: false, figure, job: null }))
  vi.stubGlobal('fetch', fetch)
  render(<BoxplotFigure base="/file" runId="run" revision={2} canGenerate={false} disabled={false} onBusyChange={() => {}} />)
  await screen.findByRole('link', { name: '下载 Word 报告' })
  const calls = fetch.mock.calls.length
  locale('en')
  expect(screen.getByText('This chart belongs to an older setup and is available to view and download.')).toBeTruthy()
  expect(screen.getByText('This explanation belongs to an older setup or chart. Generate a new explanation from the current results.')).toBeTruthy()
  expect(screen.getByText('This report belongs to an older setup or source. The historical report remains available to download.')).toBeTruthy()
  expect(screen.getByRole('link', { name: 'Download boxplot PNG' })).toBeTruthy()
  expect(screen.getByRole('link', { name: 'Download Word report' })).toBeTruthy()
  expect(screen.getByText('These results belong to an older setup. Complete the current setup’s statistics, chart, and explanation first.')).toBeTruthy()
  expect(screen.getByText('研究正文原文')).toBeTruthy()
  expect(screen.getByText(/研究报告原文.docx/)).toBeTruthy()
  expect(screen.queryByText(/SHA256|Setup version|Result ID|Step [1-5]/)).toBeNull()
  expect(fetch).toHaveBeenCalledTimes(calls)
  locale('zh-CN')
  expect(screen.getByRole('link', { name: '下载 Word 报告' })).toBeTruthy()
  expect(fetch).toHaveBeenCalledTimes(calls)
})

it('translates saved Excel preview notices and captions without altering headers and cells', async () => {
  locale('en')
  vi.stubGlobal('fetch', vi.fn(async (url: string) => Response.json(url.endsWith('/config') ? { max_upload_bytes: 1024 } : { filename: '研究数据.xlsx', sheets: [{ name: '工作表', columns: ['数据准备', '指标原文'], row_count: 1, column_count: 2, preview_rows: [['数值列', 0]], warnings: ['存在重复列名，已按原始列顺序保留。'] }] })))
  render(<ExcelPreview projectId="p" savedFile={{ id: 'f', request: 1 }} />)
  expect(await screen.findByRole('table', { name: '工作表 · Showing 1 / 1 rows (— indicates an empty value)' })).toBeTruthy()
  expect(screen.getByRole('columnheader', { name: '数据准备' })).toBeTruthy()
  expect(screen.getByRole('cell', { name: '数值列' })).toBeTruthy()
  expect(screen.getByRole('cell', { name: '0' })).toBeTruthy()
  expect(screen.getByText('Duplicate column names are retained in their original order.')).toBeTruthy()
})

it('translates running task status without restarting polling or submitting work', async () => {
  vi.useFakeTimers()
  const fetch = vi.fn(async (url: string, _init?: RequestInit) => Response.json(url.endsWith('/config') ? { configured: true } : { current_revision: 1, is_current: true, figure: null, job: { id: 'j', status: 'running', message: 'SECRET legacy job text', message_code: 'task_running', message_params: {} } }))
  vi.stubGlobal('fetch', fetch); render(<BoxplotFigure base="/file" runId="run" revision={1} canGenerate disabled={false} onBusyChange={() => {}} />)
  await act(async () => {})
  const calls = fetch.mock.calls.length; locale('en')
  expect(screen.getByText('The cloud task is running. Please wait.')).toBeTruthy()
  expect(screen.queryByText(/SECRET/)).toBeNull(); expect(fetch).toHaveBeenCalledTimes(calls)
  await act(async () => { vi.advanceTimersByTime(2999) }); expect(fetch).toHaveBeenCalledTimes(calls)
  await act(async () => { vi.advanceTimersByTime(1) }); expect(fetch).toHaveBeenCalledTimes(calls + 1)
  expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true)
})

it('clears the saved-upload failure context before opening another saved file', async () => {
  locale('en')
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => url.endsWith('/config') ? Response.json({ max_upload_bytes: 1024 })
    : init?.method === 'POST' ? Response.json({ file: { parse_status: 'failed', error: { code: 'unknown', message: 'SECRET' } } })
      : Response.json({ detail: { code: 'unknown', message: 'SECRET' } }, { status: 500 })))
  const view = render(<ExcelPreview projectId="p" />)
  await waitFor(() => expect((screen.getByLabelText('Choose an Excel file') as HTMLInputElement).disabled).toBe(false))
  fireEvent.change(screen.getByLabelText('Choose an Excel file'), { target: { files: [new File(['data'], '研究.xlsx')] } })
  fireEvent.click(screen.getByRole('button', { name: 'Upload and preview' }))
  expect((await screen.findByRole('alert')).textContent).toContain('The file was saved, but parsing failed:')
  view.rerender(<ExcelPreview projectId="p" savedFile={{ id: 'other', request: 1 }} />)
  expect((await screen.findByRole('alert')).textContent).toBe('Could not load the saved file. Refresh and retry.')
  expect(screen.queryByText(/SECRET/)).toBeNull()
})
