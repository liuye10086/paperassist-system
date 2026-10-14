import TaskPendingAction from '../tasks/TaskPendingAction'
import type { TaskWorkspace } from '../tasks/taskTypes'
import AnalysisExplanation from '../explanations/AnalysisExplanation'
import WordReport from '../reports/WordReport'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import BoxplotFigure from '../figures/BoxplotFigure'
import ExternalSendReview from '../../shared/components/ExternalSendReview'
import { isTaskPage, isWorkspace } from '../tasks/taskTypes'
import { taskFixture, workspaceFixture } from '../tasks/taskFixtures'
import type { DatasetAnalysisSource } from './datasetSource'
const source: DatasetAnalysisSource = { kind: 'dataset_version', schema_version: 1, dataset_id: 'd1', structure_id: 's1', dataset_version: 1, file_id: 'f1', source_sha256: 'a'.repeat(64), dataset_sha256: 'b'.repeat(64), dataset_size_bytes: 100, dataset_schema_version: 1, sheet_index: 0, sheet_name: 'Sheet1', parser_version: 'structure-v1' }
const disclosure = { version: 1 as const, provider: 'openai' as const, task_type: 'boxplot' as const, source_digest: 'local-secret', has_saved_result: false, summary: { valid_count: 1, excluded_count: 0, group_count: 0 }, labels: [{ key: 'numeric_name', value: 'Value' }, { key: 'unit', value: '' }] }
afterEach(() => { cleanup(); vi.unstubAllGlobals() })
test('task list rejects dataset source projection that differs from task input', () => {
 const task = { ...taskFixture, input_version: { kind: 'dataset_analysis', setup_revision: 1, output_language: 'zh-CN', source } }
 const projection = { ...workspaceFixture.source, dataset_source: { ...source, dataset_sha256: 'c'.repeat(64) } }
 expect(isTaskPage({ project_id: 'p1', page: 1, page_size: 10, total: 1, items: [{ task, source: projection }] }, 'p1', 1)).toBe(false)
})
test('workspace rejects wait on different frozen source even when revision is unchanged', () => {
 const input = { kind: 'dataset_analysis', setup_revision: 1, output_language: 'zh-CN', source }
 expect(isWorkspace({ ...workspaceFixture, task: { ...taskFixture, input_version: input }, source: { ...workspaceFixture.source, dataset_source: source }, wait: { ...workspaceFixture.wait, input_version: { ...input, source: { ...source, dataset_id: 'd2' } } } }, 'p1', 't1')).toBe(false)
})
test('dataset generation refuses a legacy disclosure before confirming', async () => {
 vi.stubGlobal('fetch', vi.fn(async (url: string) => Response.json(url.endsWith('/disclosure') ? disclosure : url.includes('/plot-config') ? { configured: true } : { current_revision: 1, is_current: true, figure: null, job: null })))
 render(<BoxplotFigure base="/file" runId="run" revision={1} source={source} filename="研究.xlsx" canGenerate disabled={false} onBusyChange={vi.fn()} />)
 await act(async () => {})
 fireEvent.click(screen.getByRole('button', { name: '使用 OpenAI 生成箱线图' }))
 await act(async () => {})
 expect(screen.queryByRole('form', { name: '发送前检查' })).toBeNull()
 expect(screen.getByRole('alert')).toBeTruthy()
})
test('v2 confirmation retains its source digest and version and shows only readable source', () => {
 const onConfirm = vi.fn()
 render(<ExternalSendReview disclosure={{ ...disclosure, version: 2, source: { filename: '研究.xlsx', sheet_name: 'Sheet1', dataset_version: 1 } }} disabled={false} onConfirm={onConfirm} onCancel={vi.fn()} />)
 expect(screen.getByText('来源：研究.xlsx；工作表：Sheet1；原始数据版本 v1。')).toBeTruthy()
 expect(screen.queryByText('local-secret')).toBeNull()
 fireEvent.submit(screen.getByRole('form', { name: '发送前检查' }))
 expect(onConfirm).toHaveBeenCalledWith({ version: 2, confirmed: true, source_digest: 'local-secret', labels: { numeric_name: 'Value', unit: '' } })
})

test.each(['figure', 'explanation', 'report'])('rejects %s from another frozen dataset even when display version and file hash match', async artifact => {
 const fetch = vi.fn(async (url: string, _init?: RequestInit) => Response.json(url.includes('config') ? { configured: false } : { current_revision: 1, is_current: true, [artifact]: { source: { ...source, dataset_sha256: 'c'.repeat(64) } }, job: null }))
 vi.stubGlobal('fetch', fetch)
 const props = { base: '/file', runId: 'run', revision: 1, source, filename: '研究.xlsx', canGenerate: true, disabled: false, onBusyChange: vi.fn() }
 render(artifact === 'figure' ? <BoxplotFigure {...props} /> : artifact === 'explanation' ? <AnalysisExplanation {...props} figureId="figure" /> : <WordReport {...props} figureId="figure" explanationId="explanation" />)
 expect((await screen.findByRole('alert')).textContent).toContain('数据来源或版本不一致')
 expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true)
})

test('resume sends the complete dataset input and rejects a response rebound to another dataset', async () => {
 const input = { kind: 'dataset_analysis', setup_revision: 1, output_language: 'zh-CN', source }
 const fetch = vi.fn(async (_url: string, _init?: RequestInit) => Response.json({ ...taskFixture, input_version: { ...input, source: { ...source, dataset_id: 'd2' } } }))
 vi.stubGlobal('fetch', fetch)
 const workspace = { ...workspaceFixture, task: { ...taskFixture, input_version: input }, source: { ...workspaceFixture.source, dataset_source: source }, wait: { ...workspaceFixture.wait, input_version: input } } as TaskWorkspace
 render(<TaskPendingAction workspace={workspace} blocked={false} onChanged={vi.fn()} />)
 fireEvent.click(screen.getByRole('button', { name: '预算或配置已调整，继续任务' }))
 await act(async () => {})
 expect(screen.getByRole('alert')).toBeTruthy()
 expect(JSON.parse(String(fetch.mock.calls[0][1]?.body)).input_version).toEqual(input)
})
test('rejects a queued artifact task rebound to another dataset before it can be retried', async () => {
 vi.stubGlobal('fetch', vi.fn(async (url: string) => Response.json(url.includes('config') ? { configured: false } : { current_revision: 1, is_current: true, figure: null, job: null, task: { ...taskFixture, input_version: { kind: 'dataset_analysis', setup_revision: 1, output_language: 'zh-CN', source: { ...source, dataset_id: 'd2' } } } })))
 render(<BoxplotFigure base="/file" runId="run" revision={1} source={source} filename="研究.xlsx" canGenerate disabled={false} onBusyChange={vi.fn()} />)
 expect((await screen.findByRole('alert')).textContent).toContain('数据来源或版本不一致')
})
test.each(['figure', 'explanation', 'report'])('an unsaved source draft blocks generation without marking saved %s historical', async artifact => {
 const figure = { id: 'figure', analysis_run_id: 'run', setup_revision: 1, source, source_sha256: source.source_sha256, title: 'Saved figure', caption: '', x_label: '', y_label: '', created_at: '2026-10-01', verification: { note: '' } }
 const explanation = { id: 'exp', analysis_run_id: 'run', figure_id: 'figure', setup_revision: 1, source, source_sha256: source.source_sha256, sections: [], limitations: [], verification: { note: '' }, language: 'zh-CN', created_at: '2026-10-01' }
 const report = { id: 'report', analysis_run_id: 'run', figure_id: 'figure', explanation_id: 'exp', setup_revision: 1, source, source_sha256: source.source_sha256, filename: 'report.docx', size_bytes: 10, language: 'zh-CN', created_at: '2026-10-01' }
 const state = { current_revision: 1, is_current: true, job: null, figure_id: 'figure', ready: true, [artifact]: { figure, explanation, report }[artifact] }
 vi.stubGlobal('fetch', vi.fn(async (url: string) => Response.json(url.includes('config') ? { configured: false } : url.endsWith(artifact === 'figure' ? '/boxplot' : '/' + artifact) ? state : { current_revision: 1, is_current: true, figure: null, explanation: null, report: null, job: null })))
 const props = { base: '/file', runId: 'run', revision: 1, source, filename: '研究.xlsx', canGenerate: false, disabled: false, onBusyChange: vi.fn() }
 render(artifact === 'figure' ? <BoxplotFigure {...props} /> : artifact === 'explanation' ? <AnalysisExplanation {...props} figureId="figure" /> : <WordReport {...props} figureId="figure" explanationId="exp" />)
 expect(await screen.findByText('当前结果')).toBeTruthy()
 expect(screen.queryByText('历史结果')).toBeNull()
})
