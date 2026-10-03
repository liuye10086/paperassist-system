import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import ProjectWorkspace from './ProjectWorkspace'
import { clearApiSession, setApiSession } from './api'
import { summaryFixture } from './test/summaryFixture'

// Keep permission requests, saved previews and all three download components real.
// Only replace the expensive configuration flow with saved-result assembly.
vi.mock('./AnalysisSetup', async () => {
  const { default: BoxplotFigure } = await import('./BoxplotFigure')
  const { default: WordReport } = await import('./WordReport')
  const onBusyChange = () => {}
  return { default: ({ projectId }: { projectId: string }) => {
    const base = `/api/v1/projects/${projectId}/files/f1`
    return <section aria-label="已保存分析">
      <p>统计内容 {projectId}</p><label>分析草稿<input defaultValue={`草稿 ${projectId}`} /></label>
      <BoxplotFigure base={base} runId="run" revision={1} canGenerate={false} disabled={false} onBusyChange={onBusyChange} />
      <WordReport base={base} runId="run" revision={1} figureId="figure" explanationId="explanation" canGenerate={false} disabled={false} onBusyChange={onBusyChange} />
    </section>
  } }
})
vi.mock('./AnalysisExplanation', () => ({ default: () => <p>已保存解释内容</p> }))

const project = { id: 'p1', name: '药学项目', research_topic: '分组比较', project_type: 'sci' as const, file_count: 1,
  created_at: '2026-09-29T10:00:00Z', updated_at: '2026-09-29T10:00:00Z' }
const other = { ...project, id: 'p2', name: '对照项目', file_count: 0 }
const file = { id: 'f1', filename: '实验.xlsx', size_bytes: 123, uploaded_at: project.created_at, parse_status: 'parsed', error: null }
const preview = { filename: file.filename, sheets: [{ name: '数据', columns: ['组别', '数值'], row_count: 1,
  column_count: 2, preview_rows: [['A', 10]], warnings: [] }] }
const figure = { id: 'figure', analysis_run_id: 'run', setup_revision: 1, title: '已保存箱线图', caption: '完整记录',
  x_label: '组别', y_label: '数值', source_sha256: 'source', sha256: 'image', created_at: project.created_at,
  engine: { id: 'boxplot-v1', provider: 'openai_code_interpreter', model: 'model' }, verification: { status: 'matched', note: '核对一致' } }
const report = { id: 'report', analysis_run_id: 'run', figure_id: 'figure', explanation_id: 'explanation', setup_revision: 1,
  filename: '分析报告.docx', size_bytes: 12, source_sha256: 'source', figure_sha256: 'image', sha256: 'report',
  input_sha256: 'input', created_at: project.created_at, language: 'zh-CN', engine: { id: 'report-v1', python_docx: 'test' } }
const missing = () => Response.json({ detail: { code: 'project_not_found', message: '项目不存在或无权访问。' } }, { status: 404 })
const base = '/api/v1/projects/p1'
const downloads = [
  { label: '下载 实验.xlsx', endpoint: `${base}/files/f1/download`, filename: file.filename },
  { label: '下载箱线图 PNG', endpoint: `${base}/files/f1/analysis-runs/run/boxplot/image?download=true`, filename: 'boxplot.png' },
  { label: '下载 Word 报告', endpoint: `${base}/files/f1/analysis-runs/run/report/report/download`, filename: report.filename },
]

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}
// Override individual requests, never the api module or Response permission parsing.
function api() {
  let items = [project, other]
  let override: (url: string, init?: RequestInit) => Response | Promise<Response> | undefined = () => undefined
  const fetch = vi.fn(async (url: string, init?: RequestInit): Promise<Response> => {
    const result = override(url, init)
    if (result !== undefined) return result
    const summaryProject = items.find(item => url.startsWith(`/api/v1/projects/${item.id}/summary?`))
    if (summaryProject) return Response.json(summaryFixture(summaryProject.id, summaryProject.project_type))
    const path = new URL(url, 'http://localhost')
    if (path.pathname === '/api/v1/projects') return Response.json({ items, total: items.length,
      page: Number(path.searchParams.get('page')), page_size: Number(path.searchParams.get('page_size')) })
    if (url === base || url === '/api/v1/projects/p2') return Response.json(url === base ? project : other)
    if (url === '/api/v1/excel/config') return Response.json({ max_upload_bytes: 10485760, preview_row_limit: 20 })
    if (url === '/api/v1/ai/config') return Response.json({ configured: false, model: null, message: '测试不调用模型' })
    if (url.endsWith('/files')) return Response.json(url.startsWith(base) ? [file] : [])
    if (url.endsWith('/preview')) return Response.json(preview)
    if (url.endsWith('/boxplot')) return Response.json({ current_revision: 1, is_current: true, figure, job: null })
    if (url.endsWith('/report')) return Response.json({ current_revision: 1, is_current: true, ready: true, issues: [], report })
    if (downloads.some(item => item.endpoint === url)) return new Response(`bytes:${url}`)
    throw new Error(`Unexpected API: ${url}`)
  })
  vi.stubGlobal('fetch', fetch)
  return { fetch, override: (handler: typeof override) => { override = handler }, removeProject: () => { items = [other] } }
}

beforeEach(() => { window.history.replaceState(null, '', '/'); setApiSession('integration-csrf') })
afterEach(() => { cleanup(); clearApiSession(); vi.restoreAllMocks(); vi.unstubAllGlobals(); window.history.replaceState(null, '', '/') })

async function open(name = project.name) {
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: `打开项目 ${name}` }))
  await screen.findByRole('heading', { name })
  return user
}
async function savedWorkspace() {
  const user = await open()
  await user.click(await screen.findByRole('button', { name: `预览 ${file.filename}` }))
  await screen.findByRole('cell', { name: '10' })
  await screen.findByRole('link', { name: '下载 Word 报告' })
  await screen.findByAltText(figure.title)
  await user.clear(screen.getByLabelText('分析草稿'))
  await user.type(screen.getByLabelText('分析草稿'), '不能泄露的草稿')
  return user
}
async function expectCleared() {
  await screen.findByRole('button', { name: '重试打开项目' })
  expect(screen.queryByRole('heading', { name: project.name })).toBeNull()
  expect(screen.queryByLabelText('选择 Excel 文件')).toBeNull()
  expect(screen.queryByRole('button', { name: `预览 ${file.filename}` })).toBeNull()
  expect(screen.queryByRole('cell', { name: '10' })).toBeNull()
  expect(screen.queryByLabelText('分析草稿')).toBeNull()
  expect(screen.queryByText('统计内容 p1')).toBeNull()
  expect(screen.queryByText('已保存解释内容')).toBeNull()
  expect(screen.queryByRole('region', { name: '项目任务与成果' })).toBeNull()
  expect(screen.queryByAltText(figure.title)).toBeNull()
  for (const download of downloads) expect(screen.queryByRole('link', { name: download.label })).toBeNull()
  expect(window.location.hash).toBe('')
  expect(screen.queryByRole('button', { name: `打开项目 ${project.name}` })).toBeNull()
}

test('summary project 404 clears the whole workspace and file preview', async () => {
  const mock = api()
  render(<ProjectWorkspace />)
  const user = await savedWorkspace()
  await screen.findByText('SCI 期刊与投稿')
  mock.removeProject()
  mock.override(url => url.includes('/p1/summary?') ? missing() : undefined)
  await user.click(screen.getByRole('button', { name: '刷新项目摘要' }))
  await expectCleared()
})

test.each([404, 410])('ordinary resource %s preserves the selected project, draft and saved analysis', async status => {
  const mock = api(); render(<ProjectWorkspace />)
  const user = await savedWorkspace()
  mock.override(url => url.endsWith('/preview')
    ? Response.json({ detail: { code: status === 404 ? 'file_not_found' : 'file_missing', message: '普通资源不可用' } }, { status }) : undefined)
  await user.click(screen.getByRole('button', { name: `预览 ${file.filename}` }))
  await screen.findByText('普通资源不可用')
  expect(screen.getByRole('heading', { name: project.name })).toBeTruthy()
  expect((screen.getByLabelText('分析草稿') as HTMLInputElement).value).toBe('不能泄露的草稿')
  expect(screen.getByAltText(figure.title)).toBeTruthy()
  expect(screen.getByRole('link', { name: '下载 Word 报告' })).toBeTruthy()
  expect(window.location.hash).toBe('#project=p1')
  expect(screen.queryByRole('button', { name: '重试打开项目' })).toBeNull()
})

test.each(downloads)('$label project 404 clears the complete workspace and hash', async download => {
  const mock = api(); render(<ProjectWorkspace />); const user = await savedWorkspace()
  mock.removeProject(); mock.override(url => url === download.endpoint ? missing() : undefined)
  await user.click(screen.getByRole('link', { name: download.label }))
  await expectCleared()
  expect(mock.fetch.mock.calls.some(([url]) => url === download.endpoint)).toBe(true)
})

test.each(downloads)('$label downloads real bytes and its filename without generation', async download => {
  const mock = api(); const create = vi.fn((_blob: Blob) => 'blob:integration'); const revoke = vi.fn()
  vi.stubGlobal('URL', class extends URL { static createObjectURL = create; static revokeObjectURL = revoke })
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    expect(this.download).toBe(download.filename)
  })
  render(<ProjectWorkspace />); await open()
  fireEvent.click(await screen.findByRole('link', { name: download.label }))
  await waitFor(() => expect(create).toHaveBeenCalledTimes(1))
  expect(await create.mock.calls[0][0].text()).toBe(`bytes:${download.endpoint}`)
  expect(revoke).toHaveBeenCalledWith('blob:integration'); expect(click).toHaveBeenCalledTimes(1)
  const request = mock.fetch.mock.calls.find(([url]) => url === download.endpoint)
  expect(request?.[1]?.credentials).toBe('same-origin')
  expect(request?.[1]?.signal).toBeInstanceOf(AbortSignal)
  expect(mock.fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true)
})

test('PNG image failure rechecks the project and clears all saved content on precise project 404', async () => {
  const mock = api(); render(<ProjectWorkspace />); await savedWorkspace()
  mock.removeProject(); mock.override(url => url === base ? missing() : undefined)
  fireEvent.error(screen.getByAltText(figure.title))
  await expectCleared()
  expect(mock.fetch.mock.calls.filter(([url]) => url === base)).toHaveLength(2)
  expect(mock.fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true)
})

test('a successful list requested before project loss cannot restore the invalid project', async () => {
  const mock = api(); const pending = deferred<Response>(); render(<ProjectWorkspace />)
  const user = await savedWorkspace()
  let pendingIssued = false
  mock.override(url => {
    if (url.includes('q=stale') && !pendingIssued) { pendingIssued = true; return pending.promise }
    return url === downloads[0].endpoint ? missing() : undefined
  })
  await user.type(screen.getByLabelText('搜索项目名称'), 'stale')
  await user.click(screen.getByRole('button', { name: '搜索项目' }))
  await waitFor(() => expect(mock.fetch.mock.calls.some(([url]) => url.includes('q=stale'))).toBe(true))
  mock.removeProject(); await user.click(screen.getByRole('link', { name: downloads[0].label }))
  await expectCleared()
  await act(async () => { pending.resolve(Response.json({ items: [project], total: 1, page: 1, page_size: 10 })) })
  await expectCleared()
})

test('successful preview body consumed before loss cannot revive cleared private content', async () => {
  const mock = api(); const body = deferred<typeof preview>(); const started = deferred<void>()
  render(<ProjectWorkspace />); const user = await savedWorkspace()
  const response = Response.json(preview)
  vi.spyOn(response, 'json').mockImplementation(() => { started.resolve(undefined); return body.promise })
  mock.override(url => url.endsWith('/preview') ? response : url === downloads[0].endpoint ? missing() : undefined)
  await user.click(screen.getByRole('button', { name: `预览 ${file.filename}` })); await started.promise
  mock.removeProject(); await user.click(screen.getByRole('link', { name: downloads[0].label })); await expectCleared()
  await act(async () => { body.resolve(preview) }); await expectCleared()
})

test('A to B to A rejects the first A detail body instead of overwriting fresh metadata', async () => {
  const mock = api(); const body = deferred<typeof project>(); const started = deferred<void>()
  const old = Response.json(project); vi.spyOn(old, 'json').mockImplementation(() => { started.resolve(undefined); return body.promise })
  let reads = 0
  mock.override(url => url === base && reads++ === 0 ? old : undefined)
  render(<ProjectWorkspace />); const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: `打开项目 ${project.name}` })); await started.promise
  await open(other.name); await open(); await screen.findByLabelText('分析草稿')
  await act(async () => { body.resolve({ ...project, name: '迟到旧项目名称' }) })
  expect(screen.queryByRole('heading', { name: '迟到旧项目名称' })).toBeNull()
  expect(screen.getByRole('heading', { name: project.name })).toBeTruthy()
  expect(window.location.hash).toBe('#project=p1')
})

test('A to B to A ignores a first-instance project 404 whose clone body arrives late', async () => {
  const mock = api(); const cloneBody = deferred<unknown>(); const started = deferred<void>()
  const old = missing(); const clone = old.clone()
  vi.spyOn(clone, 'json').mockImplementation(() => { started.resolve(undefined); return cloneBody.promise })
  vi.spyOn(old, 'clone').mockReturnValue(clone)
  render(<ProjectWorkspace />); const user = await savedWorkspace()
  mock.override(url => url.endsWith('/preview') ? old : undefined)
  await user.click(screen.getByRole('button', { name: `预览 ${file.filename}` })); await started.promise
  await open(other.name); mock.override(() => undefined); await open()
  await user.click(await screen.findByRole('button', { name: `预览 ${file.filename}` })); await screen.findByRole('cell', { name: '10' })
  await act(async () => { cloneBody.resolve({ detail: { code: 'project_not_found' } }) })
  expect(screen.getByRole('heading', { name: project.name })).toBeTruthy()
  expect(screen.getByRole('cell', { name: '10' })).toBeTruthy()
  expect(window.location.hash).toBe('#project=p1')
  expect(screen.queryByRole('button', { name: '重试打开项目' })).toBeNull()
})
