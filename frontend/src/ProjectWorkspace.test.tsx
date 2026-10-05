import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'
import { summaryFixture } from './test/summaryFixture'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.history.replaceState(null, '', '/') })

const project = { id: 'p1', name: '药学项目', research_topic: '分组比较', project_type: 'sci', file_count: 1,
  created_at: '2026-09-29T10:00:00Z', updated_at: '2026-09-29T10:00:00Z' }
const record = { id: 'f1', project_id: 'p1', filename: '实验.xlsx', file_type: 'xlsx', size_bytes: 123,
  sha256: 'a'.repeat(64), uploaded_at: '2026-09-29T10:00:00Z', parse_status: 'parsed', error: null }
const preview = { filename: '实验.xlsx', sheets: [
  { name: '数据', columns: ['组别', '数值'], row_count: 1, column_count: 2, preview_rows: [['A', 10]], warnings: [] },
  { name: '空表', columns: [], row_count: 0, column_count: 0, preview_rows: [], warnings: ['这是空表，没有可预览的数据。'] },
] }

function api(options: { empty?: boolean; failed?: boolean; uploadFailed?: boolean; listFailsOnce?: boolean; slowPreview?: Promise<Response> } = {}) {
  let projects = options.empty ? [] : [project, { ...project, id: 'p2', name: '毕业论文项目', project_type: 'thesis', file_count: 0 }]
  let files: Array<Omit<typeof record, 'error'> & { error: { code: string; message: string } | null }> = options.failed
    ? [{ ...record, parse_status: 'failed', error: { code: 'parse_failed', message: '文件损坏，请重新上传。' } }] : [record]
  const mock = vi.fn(async (url: string, init?: RequestInit) => {
    const summaryProject = projects.find(item => url.startsWith(`/api/v1/projects/${item.id}/summary?`))
    if (summaryProject) return Response.json(summaryFixture(summaryProject.id, summaryProject.project_type as 'sci' | 'thesis'))
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
    if (url.endsWith('/preview')) return options.slowPreview ?? Response.json(preview)
    throw new Error(`Unexpected API: ${url}`)
  })
  vi.stubGlobal('fetch', mock)
  return mock
}

test('creates a project with a type and topic before uploading', async () => {
  const mock = api({ empty: true })
  const user = userEvent.setup()
  render(<App />)
  expect(await screen.findByText('后端连接成功')).toBeTruthy()
  expect(await screen.findByText('还没有项目，请先创建一个项目。')).toBeTruthy()
  expect(screen.queryByLabelText('选择 Excel 文件')).toBeNull()
  await user.type(screen.getByLabelText('项目名称'), '新的毕业论文')
  await user.type(screen.getByLabelText('研究主题'), '药物疗效比较')
  await user.selectOptions(screen.getByLabelText('项目类型'), 'thesis')
  await user.click(screen.getByRole('button', { name: '创建项目' }))
  await screen.findByLabelText('选择 Excel 文件')
  const call = mock.mock.calls.find(([url, init]) => url === '/api/v1/projects' && init?.method === 'POST')
  expect(JSON.parse(call![1]!.body as string)).toEqual({ name: '新的毕业论文', research_topic: '药物疗效比较', project_type: 'thesis' })
  expect(window.location.hash).toContain('p1')
})

test('requires an explicit project type before creating', async () => {
  const mock = api({ empty: true })
  const user = userEvent.setup()
  render(<App />)
  await screen.findByText('还没有项目，请先创建一个项目。')
  expect((screen.getByLabelText('项目类型') as HTMLSelectElement).value).toBe('')
  await user.type(screen.getByLabelText('项目名称'), '新项目')
  await user.type(screen.getByLabelText('研究主题'), '新主题')
  fireEvent.submit(screen.getByLabelText('项目名称').closest('form')!)
  expect((await screen.findByRole('alert')).textContent).toContain('请选择项目类型')
  expect(mock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
})

test('clears the explicit project type after successful creation', async () => {
  api({ empty: true })
  const user = userEvent.setup()
  render(<App />)
  await screen.findByText('还没有项目，请先创建一个项目。')
  await user.type(screen.getByLabelText('项目名称'), '新项目')
  await user.type(screen.getByLabelText('研究主题'), '新主题')
  await user.selectOptions(screen.getByLabelText('项目类型'), 'thesis')
  await user.click(screen.getByRole('button', { name: '创建项目' }))
  await screen.findByRole('heading', { name: '新项目' })
  expect((screen.getByLabelText('项目类型') as HTMLSelectElement).value).toBe('')
  expect((screen.getByLabelText('项目名称') as HTMLInputElement).value).toBe('')
  expect((screen.getByLabelText('研究主题') as HTMLTextAreaElement).value).toBe('')
})

test('opens a saved file, switches sheets, then reloads its project without uploading', async () => {
  const mock = api()
  const user = userEvent.setup()
  const first = render(<App />)
  await user.click(await screen.findByRole('button', { name: '打开项目 药学项目' }))
  await user.click(await screen.findByRole('button', { name: '预览 实验.xlsx' }))
  expect(await screen.findByRole('cell', { name: '10' })).toBeTruthy()
  await user.selectOptions(screen.getByLabelText('工作表'), '1')
  expect(screen.getByText('这是空表，没有可预览的数据。')).toBeTruthy()
  first.unmount()
  render(<App />)
  await screen.findByRole('button', { name: '预览 实验.xlsx' })
  expect(screen.getByRole('heading', { name: '药学项目' })).toBeTruthy()
  expect(window.location.hash).toBe('#project=p1')
  expect(mock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
})

test('uploads into selected project and refreshes file history', async () => {
  const mock = api()
  const user = userEvent.setup()
  render(<App />)
  await user.click(await screen.findByRole('button', { name: '打开项目 药学项目' }))
  const input = await screen.findByLabelText('选择 Excel 文件')
  await waitFor(() => expect((input as HTMLInputElement).disabled).toBe(false))
  await user.upload(input, new File(['sample'], '实验.xlsx'))
  await user.click(screen.getByRole('button', { name: '上传并预览' }))
  await screen.findByRole('cell', { name: '10' })
  expect(mock.mock.calls.some(([url, init]) => url === '/api/v1/projects/p1/files' && init?.method === 'POST')).toBe(true)
  await waitFor(() => expect(screen.getAllByRole('button', { name: '预览 实验.xlsx' })).toHaveLength(2))
})

test('failed files show their localized error code and can download original', async () => {
  api({ failed: true })
  const user = userEvent.setup()
  render(<App />)
  await user.click(await screen.findByRole('button', { name: '打开项目 药学项目' }))
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
  fireEvent.click(await screen.findByRole('link', { name: '下载 实验.xlsx' }))
  await waitFor(() => expect(create).toHaveBeenCalledTimes(1)); expect(await create.mock.calls[0][0].text()).toBe('excel bytes')
  expect(revoke).toHaveBeenCalledWith('blob:excel'); expect(mock.mock.calls.every(([, init]) => !init?.method)).toBe(true)
  click.mockRestore()
})

test('late preview response cannot appear in another project', async () => {
  let finish: (value: Response) => void = () => {}
  api({ slowPreview: new Promise(resolve => { finish = resolve }) })
  const user = userEvent.setup()
  render(<App />)
  await user.click(await screen.findByRole('button', { name: '打开项目 药学项目' }))
  await user.click(await screen.findByRole('button', { name: '预览 实验.xlsx' }))
  await user.click(screen.getByRole('button', { name: '打开项目 毕业论文项目' }))
  expect(await screen.findByText('此项目还没有文件。')).toBeTruthy()
  finish(Response.json(preview))
  await waitFor(() => expect(screen.queryByRole('cell', { name: '10' })).toBeNull())
  expect(screen.getByRole('heading', { name: '毕业论文项目' })).toBeTruthy()
})

test('project list network failure can be retried', async () => {
  api({ listFailsOnce: true })
  const user = userEvent.setup()
  render(<App />)
  expect((await screen.findByRole('alert')).textContent).toContain('项目列表')
  await user.click(screen.getByRole('button', { name: '重试项目列表' }))
  expect(await screen.findByRole('button', { name: '打开项目 药学项目' })).toBeTruthy()
})

test('failed upload remains in history and reports saved original separately from parsing', async () => {
  api({ uploadFailed: true })
  const user = userEvent.setup()
  render(<App />)
  await user.click(await screen.findByRole('button', { name: '打开项目 药学项目' }))
  const input = await screen.findByLabelText('选择 Excel 文件')
  await waitFor(() => expect((input as HTMLInputElement).disabled).toBe(false))
  await user.upload(input, new File(['broken'], '实验.xlsx'))
  await user.click(screen.getByRole('button', { name: '上传并预览' }))
  expect((await screen.findByRole('alert')).textContent).toContain('文件已保存，但解析失败')
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
  await user.click(await screen.findByRole('button', { name: '预览 实验.xlsx' }))
  await screen.findByRole('cell', { name: '10' })
  mock.mockImplementation(async (url, init) => url.endsWith('/preview')
    ? Response.json({ detail: { code: 'file_missing', message: '原始文件已缺失，请恢复数据目录或重新上传。' } }, { status: 410 })
    : normal(url, init))
  await user.click(screen.getByRole('button', { name: '预览 实验.xlsx' }))
  expect((await screen.findByRole('alert')).textContent).toContain('原始文件已缺失')
  expect(screen.queryByRole('region', { name: '数据预览，可横向滚动' })).toBeNull()
  mock.mockImplementation(normal)
  await user.click(screen.getByRole('button', { name: '预览 实验.xlsx' }))
  expect(await screen.findByRole('cell', { name: '10' })).toBeTruthy()
})
