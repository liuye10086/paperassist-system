import { afterEach, expect, test, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../../app/App'
import type { Project } from '../../features/projects/projectTypes'
import { summaryFixture } from '../fixtures/summaryFixture'
import { filePageFixture } from '../fixtures/filePageFixture'
import { batchUploadFixture } from '../fixtures/batchUploadFixture'
import { workflowStateFixture } from '../fixtures/workflowStateFixture'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.history.replaceState(null, '', '/') })

const project: Project = { id: 'p1', name: '药学项目', research_topic: '分组比较', project_type: 'sci', file_count: 1,
  created_at: '2026-09-29T10:00:00Z', updated_at: '2026-09-29T10:00:00Z' }
const record = { id: 'f1', project_id: 'p1', filename: '实验.xlsx', file_type: 'xlsx', size_bytes: 123,
  sha256: 'a'.repeat(64), uploaded_at: '2026-09-29T10:00:00Z', parse_status: 'parsed', error: null }
const preview = { filename: '实验.xlsx', file_type: 'xlsx', sheets: [
  { name: '数据', columns: ['组别', '数值'], row_count: 1, column_count: 2, preview_rows: [['A', 10]], warnings: [] },
  { name: '空表', columns: [], row_count: 0, column_count: 0, preview_rows: [], warnings: ['这是空表，没有可预览的数据。'] },
] }

function api(options: { empty?: boolean; failed?: boolean; uploadFailed?: boolean; listFailsOnce?: boolean; slowPreview?: Promise<Response> } = {}) {
  let projects: Project[] = options.empty ? [] : [project, { ...project, id: 'p2', name: '毕业论文项目', project_type: 'thesis', file_count: 0 }]
  let files: Array<Omit<typeof record, 'error'> & { error: { code: string; message: string } | null }> = options.empty ? [] : options.failed
    ? [{ ...record, parse_status: 'failed', error: { code: 'parse_failed', message: '文件损坏，请重新上传。' } }] : [record]
  const uploadBatch = batchUploadFixture('p1', () => {
    const uploaded = options.uploadFailed
      ? { ...record, id: 'f2', parse_status: 'failed', error: { code: 'parse_failed', message: '文件损坏，请重新上传。' } }
      : { ...record, id: 'f2' }
    files = [...files, uploaded]
    projects = projects.map(item => item.id === 'p1' ? { ...item, file_count: files.length } : item)
    return uploaded
  })
  const mock = vi.fn(async (url: string, init?: RequestInit) => {
    const batchResponse = uploadBatch(url, init)
    if (batchResponse) return batchResponse
    const summaryProject = projects.find(item => url.startsWith(`/api/v1/projects/${item.id}/summary?`))
    if (summaryProject) return Response.json(summaryFixture(summaryProject.id, summaryProject.project_type))
    const flowProject = projects.find(item => url === `/api/v1/projects/${item.id}/workflow-state`)
    if (flowProject) {
      const readyFiles = flowProject.id === project.id ? files.filter(file => file.parse_status === 'parsed').length : 0
      return Response.json(workflowStateFixture(flowProject, { readyFiles }))
    }
    if (url.includes('/file-batches?')) return Response.json({ items: [], total: 0, page: 1, page_size: 5 })
    if (url.endsWith('/me')) return Response.json({ user: { id: 'test-user', email: 'test@paperassist.local', role: 'user' }, csrf_token: 'test-csrf' })
    if (url.endsWith('/health')) return Response.json({ status: 'ok', service: 'paperassist-system' })
    if (url.endsWith('/config')) return Response.json({ max_upload_bytes: 10485760, preview_row_limit: 20 })
    if (new URL(url, 'http://localhost').pathname === '/api/v1/projects') {
      if (init?.method === 'POST') {
        const created = { ...project, ...JSON.parse(init.body as string), file_count: 0 }
        projects = [created]
        return Response.json(created, { status: 201 })
      }
      if (options.listFailsOnce) { options.listFailsOnce = false; throw new TypeError('offline') }
      const parameters = new URL(url, 'http://localhost').searchParams
      return Response.json({ items: projects, total: projects.length, page: Number(parameters.get('page')), page_size: Number(parameters.get('page_size')) })
    }
    const detail = projects.find(item => url === `/api/v1/projects/${item.id}`)
    if (detail) return Response.json(detail)
    if (url.endsWith('/files') && init?.method === 'POST') {
      files = [...files, options.uploadFailed
        ? { ...record, id: 'f2', parse_status: 'failed', error: { code: 'parse_failed', message: '文件损坏，请重新上传。' } }
        : { ...record, id: 'f2' }]
      projects = projects.map(item => item.id === 'p1' ? { ...item, file_count: files.length } : item)
      return Response.json({ file: files[files.length - 1], preview: options.uploadFailed ? null : preview }, { status: 201 })
    }
    if (url === '/api/v1/projects/p1/files') return Response.json(files)
    if (url === '/api/v1/projects/p2/files') return Response.json([])
    if (url.includes('/files?page=')) return Response.json(filePageFixture(url, url.includes('/p1/') ? files : []))
    if (url.endsWith('/preview')) return options.slowPreview ?? Response.json(preview)
    throw new Error(`Unexpected API: ${url}`)
  })
  vi.stubGlobal('fetch', mock)
  return mock
}

async function openFiles(user: ReturnType<typeof userEvent.setup>) {
  if (!screen.queryByRole('button', { name: '项目文件' })) await user.click(await screen.findByRole('button', { name: '材料准备' }))
  await user.click(await screen.findByRole('button', { name: '项目文件' }))
}
const sidebar = () => within(screen.getByRole('complementary', { name: '主要导航' }))

test('creates a project with a type and topic before uploading', async () => {
  const mock = api({ empty: true })
  const user = userEvent.setup()
  render(<App />)
  expect(await screen.findByRole('button', { name: '账号' })).toBeTruthy()
  expect(await screen.findByText('还没有项目，请先创建一个项目。')).toBeTruthy()
  expect(screen.queryByLabelText('批量选择 Excel / Word / PDF / 图片 文件')).toBeNull()
  await user.click(screen.getByRole('button', { name: '新建研究项目' }))
  await user.type(screen.getByLabelText('项目名称'), '新的毕业论文')
  await user.type(screen.getByLabelText('研究主题'), '药物疗效比较')
  await user.selectOptions(screen.getByLabelText('项目类型'), 'thesis')
  await user.click(screen.getByRole('button', { name: '创建项目' }))
  await openFiles(user)
  await user.click(screen.getByRole('button', { name: '上传文件' }))
  await screen.findByLabelText('批量选择 Excel / Word / PDF / 图片 文件')
  const call = mock.mock.calls.find(([url, init]) => url === '/api/v1/projects' && init?.method === 'POST')
  expect(JSON.parse(call![1]!.body as string)).toEqual({ name: '新的毕业论文', research_topic: '药物疗效比较', project_type: 'thesis' })
  expect(window.location.hash).toContain('p1')
})

test('defaults to research and rejects an explicitly cleared project type', async () => {
  const mock = api({ empty: true })
  const user = userEvent.setup()
  render(<App />)
  await screen.findByText('还没有项目，请先创建一个项目。')
  await user.click(screen.getByRole('button', { name: '新建研究项目' }))
  expect((screen.getByLabelText('项目类型') as HTMLSelectElement).value).toBe('research')
  await user.selectOptions(screen.getByLabelText('项目类型'), '')
  await user.type(screen.getByLabelText('项目名称'), '新项目')
  await user.type(screen.getByLabelText('研究主题'), '新主题')
  fireEvent.submit(screen.getByLabelText('项目名称').closest('form')!)
  expect((await screen.findByRole('alert')).textContent).toContain('请选择项目类型')
  expect(mock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
})

test('resets to research after creating another project type', async () => {
  api({ empty: true })
  const user = userEvent.setup()
  render(<App />)
  await screen.findByText('还没有项目，请先创建一个项目。')
  await user.click(screen.getByRole('button', { name: '新建研究项目' }))
  await user.type(screen.getByLabelText('项目名称'), '新项目')
  await user.type(screen.getByLabelText('研究主题'), '新主题')
  await user.selectOptions(screen.getByLabelText('项目类型'), 'thesis')
  await user.click(screen.getByRole('button', { name: '创建项目' }))
  await sidebar().findByRole('button', { name: '新项目' })
  expect(screen.queryByRole('dialog')).toBeNull()
  await user.click(screen.getByRole('button', { name: '新建研究项目' }))
  const dialog = within(screen.getByRole('dialog'))
  expect((dialog.getByLabelText('项目类型') as HTMLSelectElement).value).toBe('research')
  expect((dialog.getByLabelText('项目名称') as HTMLInputElement).value).toBe('')
  expect((dialog.getByLabelText('研究主题') as HTMLTextAreaElement).value).toBe('')
})

test('opens a saved file, switches sheets, then reloads its project without uploading', async () => {
  const mock = api()
  const user = userEvent.setup()
  const first = render(<App />)
  await user.click(await screen.findByRole('button', { name: '打开项目 药学项目' }))
  await openFiles(user)
  await user.click(await screen.findByRole('button', { name: '预览 实验.xlsx' }))
  expect(await screen.findByRole('cell', { name: '10' })).toBeTruthy()
  await user.selectOptions(screen.getByLabelText('工作表'), '1')
  expect(screen.getByText('这是空表，没有可预览的数据。')).toBeTruthy()
  first.unmount()
  render(<App />)
  await screen.findByRole('cell', { name: '10' })
  expect(sidebar().getByRole('button', { name: '药学项目' })).toBeTruthy()
  expect(window.location.hash).toBe('#project=p1&section=files&view=preview&file=f1')
  expect(mock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
})

test('uploads into selected project and refreshes file history', async () => {
  const mock = api()
  const user = userEvent.setup()
  render(<App />)
  await user.click(await screen.findByRole('button', { name: '打开项目 药学项目' }))
  await openFiles(user)
  await user.click(screen.getByRole('button', { name: '上传文件' }))
  const input = await screen.findByLabelText('批量选择 Excel / Word / PDF / 图片 文件')
  await waitFor(() => expect((input as HTMLInputElement).disabled).toBe(false))
  await user.upload(input, new File(['sample'], '实验.xlsx'))
  await user.click(screen.getByRole('button', { name: '开始上传' }))
  await screen.findByText(/解析完成/)
  expect(screen.queryByRole('table')).toBeNull()
  expect(mock.mock.calls.some(([url, init]) => url.includes('/file-batches/b1/items/') && init?.method === 'POST')).toBe(true)
  await user.click(screen.getByRole('button', { name: /^(返回文件列表|已上传文件)$/ }))
  await waitFor(() => expect(screen.getAllByRole('button', { name: '预览 实验.xlsx' })).toHaveLength(2))
})

test('failed files show their localized error code and can download original', async () => {
  api({ failed: true })
  const user = userEvent.setup()
  render(<App />)
  await user.click(await screen.findByRole('button', { name: '打开项目 药学项目' }))
  await openFiles(user)
  expect(await screen.findByText('Excel 解析失败，请用 Excel 打开并另存为 .xlsx 后重试。')).toBeTruthy()
  expect(screen.queryByText('文件损坏，请重新上传。')).toBeNull()
  expect(screen.getByText('解析失败')).toBeTruthy()
  expect(screen.getByRole('link', { name: '下载 实验.xlsx' }).getAttribute('href')).toBe('/api/v1/projects/p1/files/f1/download')
  expect(screen.queryByRole('button', { name: '预览 实验.xlsx' })).toBeNull()
})

test('downloads original Excel bytes using its original filename without uploading', async () => {
  const mock = api({ failed: true }); const normal = mock.getMockImplementation()!
  const create = vi.fn((_blob: Blob) => 'blob:excel'); const revoke = vi.fn()
  vi.stubGlobal('URL', class extends URL { static createObjectURL = create; static revokeObjectURL = revoke })
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { expect(this.download).toBe(record.filename) })
  mock.mockImplementation((url, init) => url.endsWith('/download') ? Promise.resolve(new Response('excel bytes')) : normal(url, init))
  const user = userEvent.setup(); render(<App />)
  await user.click(await screen.findByRole('button', { name: '打开项目 药学项目' }))
  await openFiles(user)
  fireEvent.click(await screen.findByRole('link', { name: '下载 实验.xlsx' }))
  await waitFor(() => expect(create).toHaveBeenCalledTimes(1)); expect(await create.mock.calls[0][0].text()).toBe('excel bytes')
  expect(revoke).toHaveBeenCalledWith('blob:excel'); expect(mock.mock.calls.every(([, init]) => !init?.method)).toBe(true)
  click.mockRestore()
})

test('late preview response cannot appear in another project', async () => {
  let finish: (value: Response) => void = () => {}
  const mock = api({ slowPreview: new Promise(resolve => { finish = resolve }) })
  const user = userEvent.setup()
  render(<App />)
  await user.click(await screen.findByRole('button', { name: '打开项目 药学项目' }))
  await openFiles(user)
  await user.click(await screen.findByRole('button', { name: '预览 实验.xlsx' }))
  await waitFor(() => expect(mock.mock.calls.some(([url]) => url === '/api/v1/projects/p1/files/f1/preview')).toBe(true))
  await user.click(screen.getByRole('button', { name: '我的项目' }))
  await user.click(screen.getByRole('button', { name: '打开项目 毕业论文项目' }))
  await openFiles(user)
  expect(await screen.findByText('此项目还没有文件。')).toBeTruthy()
  await act(async () => { finish(Response.json(preview)) })
  expect(screen.queryByRole('cell', { name: '10' })).toBeNull()
  expect(sidebar().getByRole('button', { name: '毕业论文项目' })).toBeTruthy()
})

test('project list network failure can be retried', async () => {
  api({ listFailsOnce: true })
  const user = userEvent.setup()
  render(<App />)
  expect((await screen.findByRole('alert')).textContent).toContain('项目列表')
  await user.click(screen.getByRole('button', { name: '重试项目列表' }))
  expect(await screen.findByRole('button', { name: '打开项目 药学项目' })).toBeTruthy()
})

test('failed batch parsing remains in history with a downloadable original', async () => {
  api({ uploadFailed: true })
  const user = userEvent.setup()
  render(<App />)
  await user.click(await screen.findByRole('button', { name: '打开项目 药学项目' }))
  await openFiles(user)
  await user.click(screen.getByRole('button', { name: '上传文件' }))
  const input = await screen.findByLabelText('批量选择 Excel / Word / PDF / 图片 文件')
  await waitFor(() => expect((input as HTMLInputElement).disabled).toBe(false))
  await user.upload(input, new File(['broken'], '实验.xlsx'))
  await user.click(screen.getByRole('button', { name: '开始上传' }))
  await screen.findByText('Excel 解析失败，请用 Excel 打开并另存为 .xlsx 后重试。')
  await user.click(screen.getByRole('button', { name: /^(返回文件列表|已上传文件)$/ }))
  expect(await screen.findByText('解析失败')).toBeTruthy()
  expect(screen.getAllByRole('link', { name: '下载 实验.xlsx' })).toHaveLength(2)
  expect(screen.queryByRole('region', { name: '数据预览，可横向滚动' })).toBeNull()
})

test('missing saved original clears old preview and allows retry', async () => {
  const mock = api()
  const normal = mock.getMockImplementation()!
  const user = userEvent.setup()
  render(<App />)
  await user.click(await screen.findByRole('button', { name: '打开项目 药学项目' }))
  await openFiles(user)
  await user.click(await screen.findByRole('button', { name: '预览 实验.xlsx' }))
  await screen.findByRole('cell', { name: '10' })
  mock.mockImplementation(async (url, init) => url.endsWith('/preview')
    ? Response.json({ detail: { code: 'file_missing', message: '原始文件已缺失，请恢复数据目录或重新上传。' } }, { status: 410 })
    : normal(url, init))
  await user.click(screen.getByRole('button', { name: '重新读取预览' }))
  expect((await screen.findByRole('alert')).textContent).toContain('原始文件已缺失')
  expect(screen.queryByRole('region', { name: '数据预览，可横向滚动' })).toBeNull()
  mock.mockImplementation(normal)
  await user.click(screen.getByRole('button', { name: '重新读取预览' }))
  expect(await screen.findByRole('cell', { name: '10' })).toBeTruthy()
})
