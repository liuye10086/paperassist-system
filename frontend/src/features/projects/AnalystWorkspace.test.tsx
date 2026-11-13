// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { clearApiSession } from '../../shared/api/client'
import { emptyRequirement } from '../research-intake/state'
import { sourceFixture, taskFixture } from '../tasks/taskFixtures'
import { processedFixture, runFixture } from '../bioinformatics/spatialFixtures'
import ProjectWorkspace from './ProjectWorkspace'

const date = '2026-11-11T01:00:00Z'
const project = { id: 'assigned', name: '客户表达谱', research_topic: '比较病例和对照', project_type: 'research', file_count: 1, created_at: date, updated_at: date, assignment_revision: 2 }
const personal = { ...project, id: 'personal', name: '我的历史项目', project_type: 'sci', assignment_revision: undefined }
const base = '/api/v1/projects/assigned'
const analyst = `${base}/analyst-workspace`
const delivery = `${base}/deliveries/d1`
const requirement = {
  id: 'r1', version: 1, operation: 'confirm', created_at: date, sha256: 'b'.repeat(64), project_id: project.id,
  content: { ...emptyRequirement(), services: ['analysis'], notes: '先核对两组样本。', scope_items: [
    { id: 'customer.type.bulk', title: 'RNA 转录组学分析（Bulk RNA-seq）', delivery_kind: 'analysis', status: 'planned' },
    { id: 'customer.figure.bulk.volcano', title: 'Bulk RNA-seq · 火山图', delivery_kind: 'analysis', status: 'planned' },
  ] },
}
const draft = { ...requirement, id: 'r2', version: 2, operation: 'save', content: { ...requirement.content, notes: '客户未提交的草稿' } }
const feedback = [{ id: 'f1', message: '已补充样本表。', created_at: date }]
const selection = { kind: 'file', file_id: 'f1' }
const snapshot = {
  id: 's1', sha256: 'a'.repeat(64), revision: 1, parent_snapshot_id: null, requirement_version_id: 'r1',
  stage: 'first', mode: 'complete', required_formats: [], change_note: '比较结果', opinion_round: '分析交付',
  members: [{ id: 'm1', selection, name: 'expression.csv', format: 'csv', size_bytes: 12, source_metadata: {} }],
  gaps: [], quality_items: [], completeness: 'complete', changes: { added: ['m1'], removed: [], replaced: [], reason: '比较结果' }, created_at: date,
}
const file = { id: 'f1', filename: '实验.xlsx', file_type: 'xlsx', size_bytes: 100, uploaded_at: date, parse_status: 'parsed',
  error: null, purposes: [], metadata_revision: 1, uploader_recorded: true }
const bioFile = { ...file, id: 'bio1', filename: 'counts.tsv', file_type: 'bio_component', parse_status: 'stored' }
const statisticsTask = { ...taskFixture, project_id: project.id, task_type: 'statistics_compute', status: 'succeeded', display_status: 'succeeded',
  reason_code: null, error_code: null, result_analysis_run_id: 'run1', execution_receipt: {},
  input_version: { kind: 'statistics_compute', setup_revision: 1, output_language: 'zh-CN', source: null, analysis_plan_id: null, workflow_version: 'statistics_compute_v1' } }
const plotTask = { ...taskFixture, id: 'plot-task', project_id: project.id, status: 'succeeded', display_status: 'succeeded',
  reason_code: null, error_code: null, result_figure_id: 'plot1' }
const spatialSource = { ...runFixture.raw_source, project_id: project.id }
const completedRun = { ...runFixture, raw_source: spatialSource, task: { ...runFixture.task, status: 'succeeded', display_status: 'succeeded' },
  result_source: { ...processedFixture.source, project_id: project.id, raw_source: spatialSource } }

function open(hash: string) {
  window.history.replaceState(null, '', `${window.location.pathname}${hash}`)
  return render(<ProjectWorkspace analysisOnly />)
}

function server({ intakeDraft = false } = {}) {
  const state = { status: 'assigned', note: null as string | null, frozen: false, published: false, revoked: false, stale: false, assignedTotal: 1 }
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    const [path, query] = url.split('?')
    const parameters = new URLSearchParams(query)
    const method = init?.method ?? 'GET'
    if (path === '/api/v1/assigned-projects') {
      return Response.json({ items: state.revoked ? [] : [project], total: state.revoked ? 0 : state.assignedTotal,
        page: Number(parameters.get('page') ?? 1), page_size: 5 })
    }
    if (path === '/api/v1/projects') return Response.json({ items: [personal], total: 1, page: 1, page_size: 5 })
    if (path === '/api/v1/projects/personal') return Response.json(personal)
    if (path.endsWith('/workflow-state')) return Response.json({ files: { total: 1, ready: 1 }, requirements: { saved: true, version: 1, services: ['analysis'] }, results: { available: false }, next_step: 'analysis' })
    if (state.revoked && path.startsWith(base)) return Response.json({ detail: { code: 'project_not_found' } }, { status: 404 })
    if (path === base) return Response.json(project)
    if (path === analyst) return Response.json({ assignment_revision: 2, requirement: { id: 'r1', version: 1 }, status: state.status,
      note: state.note, feedback, publications: state.published ? [{ id: 's1', title: '第一版表达谱', published_at: date,
        feedback: [{ id: 'f2', message: '已下载分析结果。', created_at: date }] }] : [] })
    if (path === analyst + '/progress' && method === 'PATCH') {
      if (state.stale) return Response.json({ detail: { code: 'project_assignment_stale' } }, { status: 409 })
      const body = JSON.parse(String(init?.body))
      state.note = body.note
      state.status = body.status
      return Response.json({})
    }
    if (path === analyst + '/publish' && method === 'POST') {
      state.published = true
      state.status = 'delivered'
      return Response.json({}, { status: 201 })
    }
    if (path === base + '/research-intake') return Response.json({ project_id: project.id, revision: 2, current_requirement: intakeDraft ? draft : requirement,
      current_design: null, deliveries: [{ id: 'd1', kind: 'analysis', active: true, origin: 'explicit' }, { id: 'd2', kind: 'sci_draft', active: true }], capabilities: {}, gaps: [] })
    if (path === base + '/requirements/r1') return Response.json(requirement)
    if (path === delivery + '/candidates') return Response.json({ items: [{ selection, label: 'expression.csv', format: 'csv', status: 'existing_upload' }],
      requirements: [{ id: 'r1', version: 1 }, { id: 'r2', version: 2 }] })
    if (path === delivery + '/snapshots/preview') return Response.json({ ...snapshot, sha256: undefined })
    if (path === delivery + '/snapshots' && method === 'POST') {
      state.frozen = true
      return Response.json(snapshot, { status: 201 })
    }
    if (path === delivery + '/snapshots') return Response.json({ items: state.frozen ? [snapshot] : [] })
    if (path === delivery + '/snapshots/s1') return Response.json(snapshot)
    if (path.endsWith('/package')) return Response.json({ task: null, task_id: null, download_url: null, progress: null })
    if (path.endsWith('/files')) return Response.json(url.includes('?') ? { items: [file, bioFile], total: 2, page: 1, page_size: 5 } : [file, bioFile])
    if (path === base + '/files/f1/preview') return Response.json({ filename: file.filename, sheets: [{
      name: '样本表', columns: ['组别'], row_count: 1, column_count: 1, preview_rows: [['对照组']], warnings: [],
    }] })
    if (path === '/api/v1/excel/config') return Response.json({ max_upload_bytes: 10485760, preview_row_limit: 20 })
    if (path.endsWith('/files/f1/details')) return Response.json({ ...file, references: {}, source: { kind: 'excel_parse', preview_available: true, preview_row_limit: 20, parser_version: 'excel-v1' } })
    if (path.endsWith('/structure-versions')) return Response.json({ items: [], total: 0, page: 1, page_size: 5, latest_version: 0 })
    if (path === base + '/bio-analysis-runs') return Response.json({ items: [completedRun], total: 1, page: 1, page_size: 50 })
    if (path === base + '/bio-analysis-runs/run1') return Response.json(completedRun)
    if (path === base + '/tasks') return Response.json({ project_id: project.id, total: 1, page: 1, page_size: 10,
      items: [parameters.get('task_type') === 'boxplot' ? { task: plotTask, source: sourceFixture }
        : { task: statisticsTask, source: { ...sourceFixture, analysis_run_id: null } }] })
    return Response.json({ items: [], total: 0, page: 1, page_size: 5 })
  })
  vi.stubGlobal('fetch', fetcher)
  return { state, fetcher }
}

afterEach(() => {
  cleanup()
  clearApiSession()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  sessionStorage.clear()
  window.history.replaceState(null, '', window.location.pathname)
})

it.each(['', '#workspace=home', '#workspace=projects'])('opens assigned projects from the analyst entry %j', async (hash) => {
  const { fetcher } = server()
  open(hash)
  await screen.findByRole('button', { name: '打开项目 客户表达谱' })
  expect(window.location.hash).toBe('#workspace=assigned')
  for (const name of ['工作台', '我的项目', '新建研究项目']) {
    expect(screen.queryByRole('button', { name })).toBeNull()
  }
  expect(fetcher.mock.calls.some(([url]) => url.startsWith('/api/v1/projects?'))).toBe(false)
})

it('opens the assigned list from a saved address and applies its project filters', async () => {
  const { fetcher, state } = server()
  state.assignedTotal = 6
  open('#workspace=assigned')
  await screen.findByRole('heading', { name: '分配给我的项目' })
  expect(screen.getByRole('button', { name: '分配给我的项目' }).getAttribute('aria-current')).toBe('page')
  fireEvent.change(screen.getByLabelText('筛选项目类型'), { target: { value: 'research' } })
  fireEvent.change(screen.getByLabelText('搜索项目名称'), { target: { value: '表达谱' } })
  fireEvent.click(screen.getByRole('button', { name: '搜索项目' }))
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => {
    const value = new URL(url, window.location.origin)
    return value.pathname === '/api/v1/assigned-projects' && value.searchParams.get('q') === '表达谱'
      && value.searchParams.get('page') === '1' && value.searchParams.get('type') === 'research'
  })).toBe(true))
  await screen.findByRole('button', { name: '打开项目 客户表达谱' })
  fireEvent.click(screen.getByRole('button', { name: '下一页' }))
  fireEvent.click(await screen.findByRole('button', { name: '打开项目 客户表达谱' }))
  const information = within(await screen.findByRole('region', { name: '项目资料' }))
  expect(information.getByRole('heading', { name: '项目资料', level: 1 })).toBeTruthy()
  expect(screen.queryByRole('heading', { name: project.name })).toBeNull()
  expect(information.getByText(project.research_topic)).toBeTruthy()
  expect(information.queryByLabelText('修改研究主题')).toBeNull()
  expect(information.getByRole('region', { name: '处理进度' })).toBeTruthy()
  fireEvent.click(information.getByRole('button', { name: '返回项目列表' }))
  await screen.findByRole('heading', { name: '分配给我的项目' })
  expect((screen.getByLabelText('筛选项目类型') as HTMLSelectElement).value).toBe('research')
  expect((screen.getByLabelText('搜索项目名称') as HTMLInputElement).value).toBe('表达谱')
  await screen.findByText('共 6 个项目 · 第 2 / 2 页')
})

it('redirects legacy writing addresses before activating their views', async () => {
  const { fetcher } = server()
  open('#project=personal&section=manuscripts')
  const navigation = within(await screen.findByRole('navigation', { name: '项目导航' }))
  expect(navigation.getByRole('button', { name: '执行分析' })).toBeTruthy()
  expect(navigation.getByRole('button', { name: '分析交付' })).toBeTruthy()
  expect(navigation.queryByRole('button', { name: /写作|期刊|评审/ })).toBeNull()
  expect(window.location.hash).toBe('#project=personal&section=overview&view=settings')
  act(() => {
    window.history.pushState(null, '', '#project=personal&section=journals')
    window.dispatchEvent(new PopStateEvent('popstate'))
  })
  expect(window.location.hash).toBe('#project=personal&section=overview&view=settings')
  expect(fetcher.mock.calls.some(([url]) => /\/(manuscripts|journals|reviews|school-templates)([/?]|$)/.test(url))).toBe(false)
})

it('reads the selected customer scope and notes from the submitted requirement version', async () => {
  server({ intakeDraft: true })
  open('#project=assigned&section=overview&view=requirements')
  await screen.findByRole('heading', { name: '已提交需求' })
  expect(await screen.findByText('Bulk RNA-seq · 火山图')).toBeTruthy()
  expect(screen.getByText('先核对两组样本。')).toBeTruthy()
  expect(screen.queryByText('客户未提交的草稿')).toBeNull()
  expect(screen.queryByRole('button', { name: '保存' })).toBeNull()
})

it('writes progress against the assignment and latest submitted requirement', async () => {
  const { fetcher, state } = server()
  open('#project=assigned&section=overview&view=settings')
  let panel = within(await screen.findByRole('region', { name: '处理进度' }))
  await screen.findByText('已补充样本表。')
  fireEvent.change(panel.getByLabelText('更新进度'), { target: { value: 'needs_materials' } })
  fireEvent.change(panel.getByLabelText('给客户的进度说明'), { target: { value: '请补充分组表。' } })
  const steps = within(screen.getByRole('navigation', { name: '项目操作步骤' }))
  fireEvent.click(steps.getByRole('button', { name: '第 2 步：已提交需求' }))
  await screen.findByRole('heading', { name: '已提交需求' })
  fireEvent.click(steps.getByRole('button', { name: /第 1 步/ }))
  panel = within(await screen.findByRole('region', { name: '处理进度' }))
  expect((panel.getByLabelText('更新进度') as HTMLSelectElement).value).toBe('needs_materials')
  expect((panel.getByLabelText('给客户的进度说明') as HTMLTextAreaElement).value).toBe('请补充分组表。')
  fireEvent.click(panel.getByRole('button', { name: '保存进度' }))
  expect(await panel.findByText('进度已保存。')).toBeTruthy()
  const write = fetcher.mock.calls.find(([url]) => url === analyst + '/progress')
  expect(write?.[1]?.method).toBe('PATCH')
  expect(JSON.parse(String(write?.[1]?.body))).toEqual({ assignment_revision: 2, requirement_version_id: 'r1', status: 'needs_materials', note: '请补充分组表。' })
  state.note = '服务器更新的说明。'
  fireEvent.click(panel.getByRole('button', { name: '刷新进度与反馈' }))
  await waitFor(() => expect((panel.getByLabelText('给客户的进度说明') as HTMLTextAreaElement).value).toBe(state.note))
})

it('marks missing materials from analysis without leaving the current view', async () => {
  const { fetcher } = server()
  const url = '#project=assigned&section=analysis&view=setup&file=f1'
  open(url)
  fireEvent.click(await screen.findByRole('button', { name: '填写补料说明' }))
  const request = within(screen.getByRole('region', { name: '待补材料' }))
  expect(request.getByRole('button', { name: '标记待补材料' })).toHaveProperty('disabled', true)
  fireEvent.change(request.getByLabelText('给客户的进度说明'), { target: { value: '请补充分组表。' } })
  expect(window.location.hash).toBe(url)
  expect(fetcher.mock.calls.some(([address]) => address === analyst + '/progress')).toBe(false)
  fireEvent.click(request.getByRole('button', { name: '标记待补材料' }))
  await request.findByText('进度已保存。')
  const write = fetcher.mock.calls.find(([address]) => address === analyst + '/progress')
  expect(write?.[1]?.method).toBe('PATCH')
  expect(JSON.parse(String(write?.[1]?.body))).toEqual({
    assignment_revision: 2, requirement_version_id: 'r1', status: 'needs_materials', note: '请补充分组表。',
  })
  expect(window.location.hash).toBe(url)
  expect(screen.getByRole<HTMLSelectElement>('combobox', { name: '用于分析的文件' }).value).toBe(file.id)
})

it('publishes a frozen analysis snapshot and shows feedback without starting a ZIP task', async () => {
  const { fetcher } = server()
  open('#project=assigned&section=overview&view=deliveries')
  const sections = within(await screen.findByRole('navigation', { name: '交付流程' }))
  const candidates = within(await screen.findByRole('region', { name: '交付候选' }))
  fireEvent.click(await candidates.findByLabelText('expression.csv · CSV 数据表'))
  expect(screen.queryByRole('textbox', { name: '本次修改说明' })).toBeNull()
  expect(screen.queryByRole('button', { name: '发布给客户' })).toBeNull()
  fireEvent.click(sections.getByRole('button', { name: '冻结快照' }))
  expect(screen.getByRole('option', { name: '客户最新提交' })).toHaveProperty('selected', true)
  fireEvent.change(screen.getByLabelText('本次修改说明'), { target: { value: '比较结果' } })
  fireEvent.click(sections.getByRole('button', { name: '交付候选' }))
  expect(candidates.getByLabelText('expression.csv · CSV 数据表')).toHaveProperty('checked', true)
  fireEvent.click(sections.getByRole('button', { name: '发布交付' }))
  expect(screen.getByText('请先冻结交付快照。')).toBeTruthy()
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
  fireEvent.click(sections.getByRole('button', { name: '冻结快照' }))
  expect(screen.getByLabelText('本次修改说明')).toHaveProperty('value', '比较结果')
  fireEvent.click(screen.getByRole('button', { name: '核对所选成员与缺口' }))
  fireEvent.click(await screen.findByRole('button', { name: '冻结本次交付快照' }))
  await waitFor(() => expect(window.location.hash).toBe('#project=assigned&section=overview&view=deliveries&delivery=d1&snapshot=s1'))
  expect(sections.getByRole('button', { name: '发布交付' }).getAttribute('aria-pressed')).toBe('true')
  expect(await screen.findByRole('option', { name: /首次交付 · / })).toHaveProperty('selected', true)
  expect(screen.queryByText(/版本\s+1/)).toBeNull()
  fireEvent.change(await screen.findByLabelText('交付标题'), { target: { value: '第一版表达谱' } })
  const steps = within(screen.getByRole('navigation', { name: '项目操作步骤' }))
  fireEvent.click(steps.getByRole('button', { name: /第 1 步/ }))
  await screen.findByRole('heading', { name: '项目资料', level: 1 })
  fireEvent.click(steps.getByRole('button', { name: '第 5 步：分析交付' }))
  expect((await screen.findByLabelText('交付标题') as HTMLInputElement).value).toBe('第一版表达谱')
  fireEvent.click(screen.getByRole('button', { name: '发布给客户' }))
  expect(await screen.findByText('已下载分析结果。')).toBeTruthy()
  const posts = fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')
  expect(posts.map(([url]) => url)).toEqual([delivery + '/snapshots/preview', delivery + '/snapshots', analyst + '/publish'])
  expect(JSON.parse(String(posts[2][1]?.body))).toEqual({ assignment_revision: 2, snapshot_id: 's1', title: '第一版表达谱' })
})

it('clears the assigned project and returns to its list when permission is withdrawn', async () => {
  const { state } = server()
  open('#project=assigned')
  await screen.findByText('已补充样本表。')
  state.revoked = true
  fireEvent.click(screen.getByRole('button', { name: '刷新进度与反馈' }))
  await screen.findByRole('heading', { name: '分配给我的项目' })
  expect(await screen.findByText('目前没有分配给你的项目。')).toBeTruthy()
  expect(screen.queryByText('已补充样本表。')).toBeNull()
  expect(screen.queryByText('比较病例和对照')).toBeNull()
  expect(screen.getByRole('button', { name: '重试打开项目' })).toBeTruthy()
})

it('discards the selected project when a progress write reports an obsolete assignment', async () => {
  const { state } = server()
  open('#project=assigned')
  const button = await screen.findByRole('button', { name: '保存进度' })
  state.stale = true
  fireEvent.click(button)
  await screen.findByRole('heading', { name: '分配给我的项目' })
  expect(screen.queryByRole('region', { name: '处理进度' })).toBeNull()
})

it('offers direct table and bio analysis when submitted choices have no linked material', async () => {
  server()
  open('#project=assigned&section=analysis')
  await screen.findByRole('region', { name: '本次分析清单' })
  expect(screen.getByRole('button', { name: /表格数据与统计/ })).toBeTruthy()
  expect(screen.getByRole('button', { name: /组学与生信数据/ })).toBeTruthy()
  expect(screen.getByRole('button', { name: '进入 Bulk RNA-seq 工作流' })).toBeTruthy()
})

it('opens customer materials and previews the workbook within the five-step analysis flow', async () => {
  server()
  open('#workspace=assigned')
  fireEvent.click(await screen.findByRole('button', { name: '打开项目 客户表达谱' }))
  const steps = within(await screen.findByRole('navigation', { name: '项目操作步骤' }))
  expect(steps.getAllByRole('button').map(button => button.getAttribute('aria-label'))).toEqual([
    '第 1 步：项目资料', '第 2 步：已提交需求', '第 3 步：执行分析', '第 4 步：查看结果', '第 5 步：分析交付',
  ])
  expect(within(screen.getByRole('navigation', { name: '项目导航' })).queryByRole('button', { name: '项目文件' })).toBeNull()
  fireEvent.click(steps.getByRole('button', { name: '第 3 步：执行分析' }))
  fireEvent.click(await screen.findByRole('button', { name: /表格数据与统计/ }))
  const source = screen.getByRole<HTMLSelectElement>('combobox', { name: '用于分析的文件' })
  await within(source).findByRole('option', { name: /实验.xlsx/ })
  fireEvent.change(source, { target: { value: file.id } })
  fireEvent.click(screen.getByRole('button', { name: '查看客户资料' }))
  fireEvent.click(await screen.findByRole('button', { name: '预览 实验.xlsx' }))
  expect(await screen.findByRole('cell', { name: '对照组' })).toBeTruthy()
  expect(steps.getByRole('button', { name: '第 3 步：执行分析' }).getAttribute('aria-current')).toBe('step')
  expect(screen.queryByRole('button', { name: '上传文件' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '返回执行分析' }))
  expect(window.location.hash).toBe('#project=assigned&section=analysis&view=setup&file=f1')
  expect(screen.getByRole<HTMLSelectElement>('combobox', { name: '用于分析的文件' }).value).toBe(file.id)
})

it('redirects an old analyst upload link to customer materials in the same project', async () => {
  const { fetcher } = server()
  open('#project=assigned&section=files&view=upload')
  const materials = within(await screen.findByRole('region', { name: '客户资料' }))
  expect(await materials.findByRole('button', { name: '文件详情 实验.xlsx' })).toBeTruthy()
  expect(window.location.hash).toBe('#project=assigned&section=files')
  expect(screen.queryByRole('button', { name: '上传文件' })).toBeNull()
  expect(fetcher.mock.calls.some(([url]) => /\/(file-batches|bio-upload-batches)([/?]|$)/.test(url))).toBe(false)
})

it('opens a completed statistics result without asking for the owner project summary', async () => {
  const { fetcher } = server()
  open('#project=assigned&section=artifacts')
  await screen.findByRole('heading', { name: '生信分析结果与 Word' })
  fireEvent.click(await screen.findByRole('button', { name: '查看固定统计计算成果' }))
  expect(window.location.hash).toBe('#project=assigned&section=tasks&view=result&task=t1')
  expect(fetcher.mock.calls.some(([url]) => url.startsWith(`${base}/tasks?`) && url.includes('status=succeeded') && url.includes('task_type=statistics_compute'))).toBe(true)
  expect(fetcher.mock.calls.some(([url]) => url.startsWith(`${base}/summary`))).toBe(false)
})

it('returns a table result to its original filtered list and keeps the result step selected', async () => {
  server()
  open('#project=assigned&section=artifacts')
  fireEvent.change(await screen.findByLabelText('成果类型'), { target: { value: 'boxplot' } })
  fireEvent.click(await screen.findByRole('button', { name: '查看图表生成成果' }))
  expect(window.location.hash).toBe('#project=assigned&section=tasks&view=result&task=plot-task')
  const steps = within(screen.getByRole('navigation', { name: '项目操作步骤' }))
  expect(steps.getByRole('button', { name: '第 4 步：查看结果' }).getAttribute('aria-current')).toBe('step')
  fireEvent.click(within(screen.getByRole('navigation', { name: '任务详情视图' })).getByRole('button', { name: '概况' }))
  expect(steps.getByRole('button', { name: '第 4 步：查看结果' }).getAttribute('aria-current')).toBe('step')
  fireEvent.click(screen.getByRole('button', { name: '返回成果列表' }))
  expect(window.location.hash).toBe('#project=assigned&section=artifacts')
  expect((await screen.findByLabelText('成果类型') as HTMLSelectElement).value).toBe('boxplot')
  fireEvent.click(screen.getByRole('button', { name: '项目任务' }))
  expect(window.location.hash).toBe('#project=assigned&section=tasks')
})

it('takes the execute step to the analysis entry from a fixed analysis result', async () => {
  server()
  open('#project=assigned&section=analysis&view=bio-result&processed=result1&tab=qc')
  const steps = within(await screen.findByRole('navigation', { name: '项目操作步骤' }))
  expect(steps.getByRole('button', { name: '第 4 步：查看结果' }).getAttribute('aria-current')).toBe('step')
  fireEvent.click(steps.getByRole('button', { name: '第 3 步：执行分析' }))
  expect(window.location.hash).toBe('#project=assigned&section=analysis')
  expect(steps.getByRole('button', { name: '第 3 步：执行分析' }).getAttribute('aria-current')).toBe('step')
})

it('opens completed QC from results and returns to the same project after opening the deep link', async () => {
  server()
  const view = open('#project=assigned&section=artifacts')
  fireEvent.click(await screen.findByRole('button', { name: '查看空间分析运行与 QC 确认' }))
  await screen.findByRole('heading', { name: '空间分析运行与 QC 确认' })
  expect(screen.getByRole('button', { name: '第 4 步：查看结果' }).getAttribute('aria-current')).toBe('step')
  const deepLink = window.location.hash
  view.unmount()
  open(deepLink)
  await screen.findByRole('heading', { name: '空间分析运行与 QC 确认' })
  expect(screen.getByRole('button', { name: '第 4 步：查看结果' }).getAttribute('aria-current')).toBe('step')
  fireEvent.click(screen.getByRole('button', { name: '返回成果列表' }))
  expect(window.location.hash).toBe('#project=assigned&section=artifacts')
})

it('retains the import draft while browsing materials and guards leaving the project', async () => {
  server()
  const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(false).mockReturnValue(true)
  open('#workspace=assigned')
  const listIndex: number = window.history.state.paperassistNavigationIndex
  fireEvent.click(await screen.findByRole('button', { name: '打开项目 客户表达谱' }))
  const steps = within(await screen.findByRole('navigation', { name: '项目操作步骤' }))
  fireEvent.click(steps.getByRole('button', { name: '第 3 步：执行分析' }))
  fireEvent.click(await screen.findByRole('button', { name: /组学与生信数据/ }))
  fireEvent.click(await screen.findByRole('button', { name: '导入与检查' }))
  const importUrl = window.location.hash
  const selection = () => screen.getByRole<HTMLInputElement>('checkbox', { name: /counts.tsv/ })
  const dataset = () => screen.getByRole<HTMLInputElement>('textbox', { name: '数据集名称' })
  fireEvent.click(await screen.findByRole('checkbox', { name: /counts.tsv/ }))
  fireEvent.change(dataset(), { target: { value: '导入草稿' } })

  fireEvent.click(screen.getByRole('button', { name: '查看客户资料' }))
  await screen.findByRole('region', { name: '客户资料' })
  await act(async () => window.history.back())
  await screen.findByRole('textbox', { name: '数据集名称' })
  expect(window.location.hash).toBe(importUrl)
  expect(selection().checked).toBe(true)
  expect(dataset().value).toBe('导入草稿')
  await act(async () => window.history.forward())
  await screen.findByRole('region', { name: '客户资料' })
  expect(confirm).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '返回执行分析' }))
  expect(window.location.hash).toBe(importUrl)
  expect(selection().checked).toBe(true)
  expect(dataset().value).toBe('导入草稿')

  fireEvent.click(screen.getByRole('button', { name: '返回项目列表' }))
  expect(confirm).toHaveBeenCalledTimes(1)
  expect(window.location.hash).toBe(importUrl)
  expect(dataset().value).toBe('导入草稿')

  const returnDelta = listIndex - window.history.state.paperassistNavigationIndex
  await act(async () => window.history.go(returnDelta))
  await waitFor(() => expect(confirm).toHaveBeenCalledTimes(2))
  expect(window.location.hash).toBe(importUrl)
  expect(dataset().value).toBe('导入草稿')

  await act(async () => window.history.go(returnDelta))
  await screen.findByRole('heading', { name: '分配给我的项目' })
  expect(window.location.hash).toBe('#workspace=assigned')
})

it('opens file details and structure versions with lifecycle deletion hidden', async () => {
  const { fetcher } = server()
  open('#project=assigned&section=files&view=detail&file=f1')
  await screen.findByRole('heading', { name: '文件详情 · 实验.xlsx' })
  expect(screen.queryByRole('button', { name: '生命周期' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '结构与数据整理' }))
  await screen.findByRole('heading', { name: '原始结构与版本' })
  expect(fetcher.mock.calls.some(([url]) => url.includes('/lifecycle/deletion-requests'))).toBe(false)
})

it('keeps local bio import available without exposing FASTQ cloud for assigned projects', async () => {
  const { fetcher } = server()
  open('#project=assigned&section=analysis&view=bio-datasets')
  fireEvent.click(await screen.findByRole('button', { name: '导入与检查' }))
  await screen.findByRole('group', { name: '从已保存原件发起导入' })
  expect(screen.queryByRole('button', { name: '打开 FASTQ 云端工作区' })).toBeNull()
  expect(fetcher.mock.calls.some(([url]) => url.includes('/bio-cloud'))).toBe(false)
})
