import { afterEach, expect, test, vi } from 'vitest'
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AnalysisPlanLauncher from './AnalysisPlanLauncher'
import AnalysisPlanReview from './AnalysisPlanReview'
import TaskPendingAction from '../tasks/TaskPendingAction'
import StatisticsResults from '../analysis/StatisticsResults'
import { isPlanReview } from './analysisPlanApi'
import { reviewFixture } from './analysisPlanFixtures'
import { isWorkspace, type TaskWorkspace } from '../tasks/taskTypes'
import { validStatisticsContext } from '../analysis/statisticsContext'
import { setLocale } from '../../shared/i18n'
import type { PreparedDatasetAnalysisSource } from '../analysis/datasetSource'
import type { Selection } from '../analysis/AnalysisSetup'

const research = { question: '  Describe synthetic observations.\n', output_language: 'en', population: 'Synthetic participants', study_design: 'Cross-sectional', observation_unit: 'One row per participant', observation_structure: 'paired', relationship_description: 'Two rows per pair', output_requirements: '' }
const input = { ...reviewFixture.input_version, workflow_version: 'analysis_plan_v2' }
const candidate = { ...reviewFixture, input_version: input, research_request: research, task: { ...reviewFixture.task, input_version: input }, check: { ...reviewFixture.check, rules_version: 'analysis_plan_rules_v2', research_missing: [] } }
const waiting = { ...candidate, research_request: { ...research, population: '' }, task: { ...candidate.task, status: 'waiting_input', display_status: 'waiting_input' }, check: { ...candidate.check, research_missing: ['population'] } }
afterEach(() => { cleanup(); vi.unstubAllGlobals(); setLocale('zh-CN') })

test('validates v2 requirements and rejects missing, excess or crossed workflow fields while keeping v1', () => {
  expect(isPlanReview(candidate, 'p1', 't1')).toBe(true)
  expect(isPlanReview(reviewFixture, 'p1', 't1')).toBe(true)
  expect(isPlanReview({ ...candidate, research_request: undefined }, 'p1', 't1')).toBe(false)
  expect(isPlanReview({ ...candidate, research_request: { ...research, arbitrary_method: 'regression' } }, 'p1', 't1')).toBe(false)
  expect(isPlanReview({ ...candidate, check: { ...candidate.check, research_missing: ['secret_id'] } }, 'p1', 't1')).toBe(false)
  expect(isPlanReview({ ...reviewFixture, research_request: research }, 'p1', 't1')).toBe(false)
  expect(isPlanReview({ ...candidate, input_version: { ...input, workflow_version: 'analysis_plan_v1' } }, 'p1', 't1')).toBe(false)
})

test('accepts waiting_input workspace only with a matching revise-only wait', () => {
  const workspace = { task: waiting.task, source: { file_id: 'f1', filename: 'synthetic.xlsx', analysis_run_id: null, is_current: true, dataset_source: candidate.source }, wait: { id: 'w1', kind: 'analysis_plan_input', status: 'open', task_revision: waiting.task.revision, input_version: input, reason_code: 'input_required', error_code: null, created_at: waiting.task.created_at, resolved_at: null }, allowed_actions: ['revise'], artifacts: { figure: null, explanation: null, report: null } }
  expect(isWorkspace(workspace, 'p1', 't1')).toBe(true)
  expect(isWorkspace({ ...workspace, allowed_actions: ['approve', 'revise'] }, 'p1', 't1')).toBe(false)
  expect(isWorkspace({ ...workspace, allowed_actions: ['retry'] }, 'p1', 't1')).toBe(false)
  expect(isWorkspace({ ...workspace, wait: { ...workspace.wait, task_revision: workspace.wait.task_revision - 1 } }, 'p1', 't1')).toBe(false)
})

test('requires an original question then creates v2 even with missing research details', async () => {
  const fetch = vi.fn(async (url: string, init?: RequestInit) => url.endsWith('/analysis-plans') && init?.method === 'POST' ? Response.json(candidate.task) : url.endsWith('/analysis-plan') ? Response.json(candidate) : Response.json({ items: [], total: 0, page: 1, page_size: 5 }))
  vi.stubGlobal('fetch', fetch)
  const user = userEvent.setup()
  render(<AnalysisPlanLauncher projectId="p1" fileId="f1" source={candidate.source as PreparedDatasetAnalysisSource} selection={candidate.selection as Selection} setupRevision={0} disabled={false} onPublished={() => {}} />)
  const create = screen.getByRole('button', { name: '生成分析计划' }) as HTMLButtonElement
  expect(create.disabled).toBe(true)
  await user.type(screen.getByLabelText('研究问题'), research.question)
  await user.selectOptions(screen.getByLabelText('输出语言'), 'en')
  await user.click(create)
  await waitFor(() => expect(fetch.mock.calls.some(([url]) => url.endsWith('/analysis-plans'))).toBe(true))
  const body = JSON.parse(String(fetch.mock.calls.find(([url]) => url.endsWith('/analysis-plans'))![1]?.body))
  expect(body.research_request).toEqual({ ...research, population: '', study_design: '', observation_unit: '', observation_structure: 'unknown', relationship_description: '' })
  expect(screen.getAllByText('新成果沿用已确认的任务语言；已保存历史成果保留原语言。').length).toBeGreaterThan(0)
})

test.each(['zh-CN', 'en'] as const)('supplements research in %s then still requires a separate approval without a research payload', async locale => {
  setLocale(locale)
  let current: unknown = waiting
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/decisions')) { const body = JSON.parse(String(init?.body)); current = body.operation === 'revise' ? { ...candidate, checkpoint_id: 'cp2', wait_id: 'w2', plan_revision: 2, task: { ...candidate.task, revision: candidate.task.revision + 1 } } : candidate; return Response.json((current as typeof candidate).task) }
    return Response.json(current)
  })
  vi.stubGlobal('fetch', fetch)
  const user = userEvent.setup()
  render(<AnalysisPlanReview projectId="p1" taskId="t1" />)
  await screen.findByLabelText(locale === 'en' ? 'Study population' : '研究人群')
  expect(screen.queryByRole('button', { name: locale === 'en' ? 'Approve and publish analysis plan' : '确认并发布分析计划' })).toBeNull()
  await user.type(screen.getByLabelText(locale === 'en' ? 'Study population' : '研究人群'), 'Synthetic participants')
  await user.click(screen.getByRole('button', { name: locale === 'en' ? 'Provide information and recheck' : '补充资料并重新检查' }))
  const approve = await screen.findByRole('button', { name: locale === 'en' ? 'Approve and publish analysis plan' : '确认并发布分析计划' })
  expect(fetch.mock.calls.filter(([url]) => url.endsWith('/decisions'))).toHaveLength(1)
  await user.selectOptions(screen.getByLabelText(locale === 'en' ? 'Resolve: Missing values in selected fields (C)' : '处理：所选字段存在缺失值（C）'), 'exclude_selected_missing')
  await user.click(approve)
  const bodies = fetch.mock.calls.filter(([url]) => url.endsWith('/decisions')).map(([, init]) => JSON.parse(String(init?.body)))
  expect(bodies[0]).toMatchObject({ operation: 'revise', checkpoint_id: 'cp1', wait_id: 'w1', resolutions: {}, research_request: research })
  expect(bodies[1]).toMatchObject({ operation: 'approve', checkpoint_id: 'cp2', wait_id: 'w2', plan_revision: 2 })
  expect(bodies[1]).not.toHaveProperty('research_request')
  expect(bodies[1]).not.toHaveProperty('selection')
  expect(document.body.textContent).not.toContain('cp1')
})

const plan = { schema_version: 2, workflow_version: 'analysis_plan_v2', rules_version: 'analysis_plan_rules_v2', id: 'plan-v2', task_id: 't1', decision_id: 'decision-v2', project_id: 'p1', file_id: 'f1', source: candidate.source, selection: candidate.selection, check: candidate.check, resolutions: { 'missing:C': 'exclude_selected_missing' }, plan_revision: 1, setup_revision: 2, created_at: candidate.task.created_at, sha256: 'c'.repeat(64), research_request: research }
const statistics = { n: 4, mean: 5, std: 2, min: 3, q1: 4, median: 5, q3: 6, max: 8, iqr: 2, warnings: [] }
const result = { schema_version: 2, analysis_context: { plan, method: { id: 'descriptive', parameters: candidate.selection, observation_basis: 'rows' }, rounding: { display_significant_digits: 6, stored_values: 'full_precision' }, not_computed: { p_value: { value: null, reason: 'not_applicable_descriptive' }, effect_size: { value: null, reason: 'not_applicable_descriptive' }, confidence_interval: { value: null, reason: 'not_applicable_descriptive' } } }, id: 'run2', filename: 'synthetic.xlsx', source: candidate.source as PreparedDatasetAnalysisSource, source_sha256: candidate.source.source_sha256, setup_revision: 2, selection: candidate.selection as Selection, check: candidate.check.selection_check, numeric_name: 'weight', group_name: null, engine: { id: 'descriptive', python_version: '3' }, started_at: candidate.task.created_at, completed_at: candidate.task.created_at, overall: statistics, groups: [] }

test('shows frozen v2 research, row basis, unavailable inferential metrics and approved artifact language', async () => {
  setLocale('en')
  vi.stubGlobal('fetch', vi.fn(async (url: string) => Response.json(url.endsWith('/analysis-result') ? { current_revision: 2, is_current: true, result } : { current_revision: 2, is_current: true, figure: null, job: null })))
  render(<StatisticsResults base="/api/v1/projects/p1/files/f1" savedRevision={2} savedSource={candidate.source as PreparedDatasetAnalysisSource} fieldsMatch disabled={false} onBusyChange={() => {}} />)
  await screen.findByText('Describe synthetic observations.')
  expect(screen.getByText('Statistics describe rows. Paired or repeated-measures inference and correlation adjustments were not performed.')).toBeTruthy()
  expect(screen.getByText('P values, effect sizes and confidence intervals are not computed because this analysis is descriptive.')).toBeTruthy()
  expect(screen.getByText('New artifacts use the approved task language. Saved historical artifacts retain their original language.')).toBeTruthy()
  expect(document.body.textContent).not.toContain('plan-v2')
  expect(document.body.textContent).not.toContain('c'.repeat(64))
})

test.each(['revision', 'context'] as const)('rejects current statistics with mismatching %s', async field => {
  const malformed = field === 'revision' ? { ...result, setup_revision: 1 } : { ...result, analysis_context: undefined }
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ current_revision: 2, is_current: true, result: malformed })))
  render(<StatisticsResults base="/api/v1/projects/p1/files/f1" savedRevision={2} savedSource={candidate.source as PreparedDatasetAnalysisSource} fieldsMatch disabled={false} onBusyChange={() => {}} />)
  await screen.findByRole('alert')
  expect(screen.queryByRole('table')).toBeNull()
  expect((screen.getByRole('button', { name: '执行描述统计' }) as HTMLButtonElement).disabled).toBe(true)
})

test('source change discards the research draft and ignores late review responses', async () => {
  let finish!: (value: Response) => void
  vi.stubGlobal('fetch', vi.fn((url: string) => url.includes('/analysis-plans?') ? Promise.resolve(Response.json({ items: [candidate], total: 1, page: 1, page_size: 5 })) : new Promise<Response>(resolve => { finish = resolve })))
  const props = { projectId: 'p1', fileId: 'f1', selection: candidate.selection as Selection, setupRevision: 0, disabled: false, onPublished: vi.fn() }
  const view = render(<AnalysisPlanLauncher {...props} source={candidate.source as PreparedDatasetAnalysisSource} />)
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('研究问题'), 'old draft')
  await waitFor(() => expect(finish).toBeTypeOf('function'))
  view.rerender(<AnalysisPlanLauncher {...props} source={{ ...candidate.source, dataset_id: 'other' } as PreparedDatasetAnalysisSource} />)
  await act(async () => { finish(Response.json({ ...candidate, result: plan })) })
  expect((screen.getByLabelText('研究问题') as HTMLTextAreaElement).value).toBe('')
  expect(props.onPublished).not.toHaveBeenCalled()
})

test.each([
  ['method', { method: { ...result.analysis_context.method, id: 'regression' } }],
  ['rounding', { rounding: { ...result.analysis_context.rounding, display_significant_digits: 5 } }],
  ['inference', { not_computed: { ...result.analysis_context.not_computed, p_value: { value: 0.1, reason: 'not_applicable_descriptive' } } }],
  ['plan research', { plan: { ...plan, research_request: { ...research, output_language: 'fr' } } }],
  ['plan source', { plan: { ...plan, source: { ...plan.source, dataset_id: 'other' } } }],
] as const)('rejects altered context %s', (_field, context) => {
  expect(validStatisticsContext({ ...result, analysis_context: { ...result.analysis_context, ...context } }, '/api/v1/projects/p1/files/f1')).toBe(false)
})

test('current v2 result must match the saved confirmed plan while history remains readable', () => {
  expect(validStatisticsContext(result, '/api/v1/projects/p1/files/f1', { plan_id: 'other', sha256: plan.sha256 })).toBe(false)
  expect(validStatisticsContext(result, '/api/v1/projects/p1/files/f1')).toBe(true)
})

test('published review cannot combine another research question with the saved plan', () => {
  const published = { ...candidate, result: plan, wait_id: null, task: { ...candidate.task, status: 'succeeded', display_status: 'succeeded' } }
  expect(isPlanReview(published, 'p1', 't1')).toBe(true)
  expect(isPlanReview({ ...published, research_request: { ...research, question: 'Another question' } }, 'p1', 't1')).toBe(false)
})

test('an older decision receipt cannot overwrite a newly loaded checkpoint', async () => {
  let current = candidate
  let finish!: (value: Response) => void
  const fetch = vi.fn((url: string) => url.endsWith('/decisions') ? new Promise<Response>(resolve => { finish = resolve }) : Promise.resolve(Response.json(current)))
  vi.stubGlobal('fetch', fetch)
  const user = userEvent.setup()
  const view = render(<AnalysisPlanReview projectId="p1" taskId="t1" refreshKey={0} />)
  await user.selectOptions(await screen.findByLabelText('处理：所选字段存在缺失值（C）'), 'exclude_selected_missing')
  await user.click(screen.getByRole('button', { name: '确认并发布分析计划' }))
  current = { ...candidate, checkpoint_id: 'cp-new', wait_id: 'w-new', plan_revision: 2, task: { ...candidate.task, revision: candidate.task.revision + 1 } }
  view.rerender(<AnalysisPlanReview projectId="p1" taskId="t1" refreshKey={1} />)
  await waitFor(() => expect((screen.getByLabelText('处理：所选字段存在缺失值（C）') as HTMLSelectElement).value).toBe(''))
  await act(async () => { finish(Response.json(candidate.task)) })
  await user.selectOptions(screen.getByLabelText('处理：所选字段存在缺失值（C）'), 'exclude_selected_missing')
  expect((screen.getByRole('button', { name: '确认并发布分析计划' }) as HTMLButtonElement).disabled).toBe(false)
})

test('a reread begun during a decision keeps the new read alive when the old receipt arrives first', async () => {
  let finishDecision!: (value: Response) => void
  let finishRead!: (value: Response) => void
  let reads = 0
  const fetch = vi.fn((url: string) => url.endsWith('/decisions') ? new Promise<Response>(resolve => { finishDecision = resolve }) : ++reads === 1 ? Promise.resolve(Response.json(candidate)) : new Promise<Response>(resolve => { finishRead = resolve }))
  vi.stubGlobal('fetch', fetch)
  const user = userEvent.setup()
  const view = render(<AnalysisPlanReview projectId="p1" taskId="t1" refreshKey={0} />)
  await user.selectOptions(await screen.findByLabelText('处理：所选字段存在缺失值（C）'), 'exclude_selected_missing')
  await user.click(screen.getByRole('button', { name: '确认并发布分析计划' }))
  view.rerender(<AnalysisPlanReview projectId="p1" taskId="t1" refreshKey={1} />)
  await waitFor(() => expect(reads).toBe(2))
  await act(async () => { finishDecision(Response.json(candidate.task)) })
  expect(reads).toBe(2)
  await act(async () => { finishRead(Response.json({ ...candidate, checkpoint_id: 'cp-new', wait_id: 'w-new', plan_revision: 2, task: { ...candidate.task, revision: candidate.task.revision + 1 } })) })
  expect(screen.getByRole('button', { name: '确认并发布分析计划' })).toBeTruthy()
})

test('a late statistics execution cannot become the result of a newer saved revision', async () => {
  let finish!: (value: Response) => void
  let revision = 2
  vi.stubGlobal('fetch', vi.fn((_url: string, init?: RequestInit) => init?.method === 'POST' ? new Promise<Response>(resolve => { finish = resolve }) : Promise.resolve(Response.json({ current_revision: revision, is_current: false, result: null }))))
  const props = { base: '/api/v1/projects/p1/files/f1', savedSource: candidate.source as PreparedDatasetAnalysisSource, fieldsMatch: true, disabled: false, onBusyChange: () => {} }
  const view = render(<StatisticsResults {...props} savedRevision={2} />)
  const user = userEvent.setup()
  await waitFor(() => expect((screen.getByRole('button', { name: '执行描述统计' }) as HTMLButtonElement).disabled).toBe(false))
  await user.click(screen.getByRole('button', { name: '执行描述统计' }))
  revision = 3
  view.rerender(<StatisticsResults {...props} savedRevision={3} />)
  await screen.findByText('尚未执行当前配置的描述统计。')
  await act(async () => { finish(Response.json(result)) })
  expect(screen.queryByRole('table')).toBeNull()
  expect(screen.queryByText('Describe synthetic observations.')).toBeNull()
})

test.each(['create', 'list', 'workspace', 'refresh'] as const)('rejects a same-source v2-to-v1 downgrade from %s without sending decisions', async entry => {
  let loaded: unknown = entry === 'refresh' ? candidate : reviewFixture
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/analysis-plans') && init?.method === 'POST') return Response.json(candidate.task)
    if (url.includes('/analysis-plans?')) return Response.json({ items: entry === 'list' ? [candidate] : [], total: entry === 'list' ? 1 : 0, page: 1, page_size: 5 })
    return Response.json(loaded)
  })
  vi.stubGlobal('fetch', fetch)
  const user = userEvent.setup()
  if (entry === 'create' || entry === 'list') {
    render(<AnalysisPlanLauncher projectId="p1" fileId="f1" source={candidate.source as PreparedDatasetAnalysisSource} selection={candidate.selection as Selection} setupRevision={0} disabled={false} onPublished={() => {}} />)
    if (entry === 'create') {
      await user.type(screen.getByLabelText('研究问题'), 'Synthetic study')
      await user.click(screen.getByRole('button', { name: '生成分析计划' }))
    }
  } else if (entry === 'workspace') {
    const workspace = { task: candidate.task, source: { file_id: 'f1', filename: 'synthetic.xlsx', analysis_run_id: null, is_current: true, dataset_source: candidate.source }, wait: null, allowed_actions: [], artifacts: { figure: null, explanation: null, report: null } } as unknown as TaskWorkspace
    render(<TaskPendingAction workspace={workspace} blocked={false} onChanged={() => {}} />)
  } else {
    render(<AnalysisPlanReview projectId="p1" taskId="t1" />)
    await screen.findByText('Describe synthetic observations.')
    loaded = { ...reviewFixture, task: { ...reviewFixture.task, revision: candidate.task.revision + 1 } }
    await user.click(screen.getByRole('button', { name: '重新读取分析计划' }))
  }
  await screen.findByRole('alert')
  expect(screen.queryByRole('button', { name: '确认并发布分析计划' })).toBeNull()
  expect(screen.queryByRole('button', { name: '修改字段重审' })).toBeNull()
  expect(fetch.mock.calls.filter(([url]) => url.endsWith('/decisions'))).toHaveLength(0)
})

test('a successful list refresh cannot erase a rejected create receipt',async()=>{
 let listReads=0
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/analysis-plans')&&init?.method==='POST')return Response.json(candidate.task)
  if(url.includes('/analysis-plans?')){listReads++;return Response.json({items:[],total:0,page:1,page_size:5})}
  return Response.json(reviewFixture)
 }))
 const user=userEvent.setup()
 render(<AnalysisPlanLauncher projectId="p1" fileId="f1" source={candidate.source as PreparedDatasetAnalysisSource} selection={candidate.selection as Selection} setupRevision={0} disabled={false} onPublished={()=>{}}/>)
 await user.type(screen.getByLabelText('研究问题'),'Synthetic study')
 await user.click(screen.getByRole('button',{name:'生成分析计划'}))
 await waitFor(()=>expect(listReads).toBe(2));await act(async()=>{})
 expect(screen.getByRole('alert').textContent).toContain('计划创建结果尚未确认')
})

test('a genuine v1 list item still opens its original confirmation UI', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => Response.json(url.includes('/analysis-plans?') ? { items: [reviewFixture], total: 1, page: 1, page_size: 5 } : reviewFixture)))
  render(<AnalysisPlanLauncher projectId="p1" fileId="f1" source={candidate.source as PreparedDatasetAnalysisSource} selection={candidate.selection as Selection} setupRevision={0} disabled={false} onPublished={() => {}} />)
  expect(await screen.findByRole('button', { name: '确认并发布分析计划' })).toBeTruthy()
  expect(screen.getByRole('button', { name: '修改字段重审' })).toBeTruthy()
})

test('a lost create receipt retries the unchanged research body with the same idempotency key', async () => {
  let posts = 0
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/analysis-plans') && init?.method === 'POST') { if (++posts === 1) throw new TypeError('offline'); return Response.json(candidate.task) }
    if (url.includes('/analysis-plans?')) return Response.json({ items: [], total: 0, page: 1, page_size: 5 })
    return Response.json(candidate)
  })
  vi.stubGlobal('fetch', fetch)
  const user = userEvent.setup()
  render(<AnalysisPlanLauncher projectId="p1" fileId="f1" source={candidate.source as PreparedDatasetAnalysisSource} selection={candidate.selection as Selection} setupRevision={0} disabled={false} onPublished={() => {}} />)
  await user.type(screen.getByLabelText('研究问题'), research.question)
  await user.click(screen.getByRole('button', { name: '生成分析计划' }))
  await waitFor(() => expect((screen.getByRole('button', { name: '生成分析计划' }) as HTMLButtonElement).disabled).toBe(false))
  expect((screen.getByLabelText('研究问题') as HTMLTextAreaElement).value).toBe(research.question)
  await user.click(screen.getByRole('button', { name: '生成分析计划' }))
  await waitFor(() => expect(posts).toBe(2))
  const calls = fetch.mock.calls.filter(([url]) => url.endsWith('/analysis-plans'))
  expect(calls[0][1]?.body).toBe(calls[1][1]?.body)
  expect(new Headers(calls[0][1]?.headers).get('Idempotency-Key')).toBe(new Headers(calls[1][1]?.headers).get('Idempotency-Key'))
})

test('a lost revise receipt retains the research draft and retries the same checkpoint and idempotency key', async () => {
  let reads = 0
  let posts = 0
  const fetch = vi.fn(async (url: string, _init?: RequestInit) => {
    if (url.endsWith('/decisions')) { if (++posts === 1) throw new TypeError('offline'); return Response.json(waiting.task) }
    ++reads
    return Response.json(waiting)
  })
  vi.stubGlobal('fetch', fetch)
  const user = userEvent.setup()
  render(<AnalysisPlanReview projectId="p1" taskId="t1" />)
  await user.type(await screen.findByLabelText('研究人群'), 'Synthetic participants')
  await user.click(screen.getByRole('button', { name: '补充资料并重新检查' }))
  await waitFor(() => expect(reads).toBe(2))
  expect((screen.getByLabelText('研究人群') as HTMLTextAreaElement).value).toBe('Synthetic participants')
  await user.click(screen.getByRole('button', { name: '补充资料并重新检查' }))
  await waitFor(() => expect(posts).toBe(2))
  const calls = fetch.mock.calls.filter(([url]) => url.endsWith('/decisions'))
  expect(calls[0][1]?.body).toBe(calls[1][1]?.body)
  expect(JSON.parse(String(calls[1][1]?.body))).toMatchObject({ operation: 'revise', checkpoint_id: 'cp1', wait_id: 'w1', research_request: research })
  expect(new Headers(calls[0][1]?.headers).get('Idempotency-Key')).toBe(new Headers(calls[1][1]?.headers).get('Idempotency-Key'))
})
