import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'

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
    if (url.endsWith('/me')) return Response.json({ user: { id: 'test-user', email: 'test@paperassist.local', role: 'user' }, csrf_token: 'test-csrf' })
    if (url.endsWith('/health')) return Response.json({ status: 'ok', service: 'paperassist-system' })
    if (url.endsWith('/config')) return Response.json({ max_upload_bytes: 10485760, preview_row_limit: 20 })
    if (url === '/api/v1/projects') {
      if (init?.method === 'POST') {
        const created = { ...project, ...JSON.parse(init.body as string), file_count: 0 }
        projects = [created]
        return Response.json(created, { status: 201 })
      }
      if (options.listFailsOnce) { options.listFailsOnce = false; throw new TypeError('offline') }
      return Response.json(projects)
    }
    if (url.endsWith('/files') && init?.method === 'POST') {
      files = [...files, options.uploadFailed
        ? { ...record, id: 'f2', parse_status: 'failed', error: { code: 'parse_failed', message: '文件损坏，请重新上传。' } }
        : { ...record, id: 'f2' }]
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

test('opens a saved file, switches sheets, then reloads its project without uploading', async () => {
  const mock = api()
  const user = userEvent.setup()
  const first = render(<App />)
  await user.selectOptions(await screen.findByLabelText('当前项目'), 'p1')
  await user.click(await screen.findByRole('button', { name: '预览 实验.xlsx' }))
  expect(await screen.findByRole('cell', { name: '10' })).toBeTruthy()
  await user.selectOptions(screen.getByLabelText('工作表'), '1')
  expect(screen.getByText('这是空表，没有可预览的数据。')).toBeTruthy()
  first.unmount()
  render(<App />)
  await screen.findByRole('button', { name: '预览 实验.xlsx' })
  expect((screen.getByLabelText('当前项目') as HTMLSelectElement).value).toBe('p1')
  expect(mock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
})

test('uploads into selected project and refreshes file history', async () => {
  const mock = api()
  const user = userEvent.setup()
  render(<App />)
  await user.selectOptions(await screen.findByLabelText('当前项目'), 'p1')
  const input = await screen.findByLabelText('选择 Excel 文件')
  await waitFor(() => expect((input as HTMLInputElement).disabled).toBe(false))
  await user.upload(input, new File(['sample'], '实验.xlsx'))
  await user.click(screen.getByRole('button', { name: '上传并预览' }))
  await screen.findByRole('cell', { name: '10' })
  expect(mock.mock.calls.some(([url, init]) => url === '/api/v1/projects/p1/files' && init?.method === 'POST')).toBe(true)
  await waitFor(() => expect(screen.getAllByRole('button', { name: '预览 实验.xlsx' })).toHaveLength(2))
})

test('failed files show their saved reason and can download original', async () => {
  api({ failed: true })
  const user = userEvent.setup()
  render(<App />)
  await user.selectOptions(await screen.findByLabelText('当前项目'), 'p1')
  expect(await screen.findByText('文件损坏，请重新上传。')).toBeTruthy()
  expect(screen.getByText('解析失败')).toBeTruthy()
  expect(screen.getByRole('link', { name: '下载 实验.xlsx' }).getAttribute('href')).toBe('/api/v1/projects/p1/files/f1/download')
  expect(screen.queryByRole('button', { name: '预览 实验.xlsx' })).toBeNull()
})

test('late preview response cannot appear in another project', async () => {
  let finish: (value: Response) => void = () => {}
  api({ slowPreview: new Promise(resolve => { finish = resolve }) })
  const user = userEvent.setup()
  render(<App />)
  await user.selectOptions(await screen.findByLabelText('当前项目'), 'p1')
  await user.click(await screen.findByRole('button', { name: '预览 实验.xlsx' }))
  await user.selectOptions(screen.getByLabelText('当前项目'), 'p2')
  expect(await screen.findByText('此项目还没有文件。')).toBeTruthy()
  finish(Response.json(preview))
  await waitFor(() => expect(screen.queryByRole('cell', { name: '10' })).toBeNull())
  expect(within(screen.getByLabelText('当前项目')).getByRole('option', { name: /毕业论文项目/ })).toBeTruthy()
})

test('project list network failure can be retried', async () => {
  api({ listFailsOnce: true })
  const user = userEvent.setup()
  render(<App />)
  expect((await screen.findByRole('alert')).textContent).toContain('项目列表')
  await user.click(screen.getByRole('button', { name: '重试项目列表' }))
  expect(await screen.findByLabelText('当前项目')).toBeTruthy()
})

test('failed upload remains in history and reports saved original separately from parsing', async () => {
  api({ uploadFailed: true })
  const user = userEvent.setup()
  render(<App />)
  await user.selectOptions(await screen.findByLabelText('当前项目'), 'p1')
  const input = await screen.findByLabelText('选择 Excel 文件')
  await waitFor(() => expect((input as HTMLInputElement).disabled).toBe(false))
  await user.upload(input, new File(['broken'], '实验.xlsx'))
  await user.click(screen.getByRole('button', { name: '上传并预览' }))
  expect((await screen.findByRole('alert')).textContent).toContain('文件已保存，但解析失败')
  expect(await screen.findByText('解析失败')).toBeTruthy()
  expect(screen.getAllByRole('link', { name: '下载 实验.xlsx' })).toHaveLength(2)
  expect(screen.queryByRole('table')).toBeNull()
})

test('missing saved original clears old preview and allows retry', async () => {
  const mock = api()
  const normal = mock.getMockImplementation()!
  const user = userEvent.setup()
  render(<App />)
  await user.selectOptions(await screen.findByLabelText('当前项目'), 'p1')
  await user.click(await screen.findByRole('button', { name: '预览 实验.xlsx' }))
  await screen.findByRole('cell', { name: '10' })
  mock.mockImplementation(async (url, init) => url.endsWith('/preview')
    ? Response.json({ detail: { code: 'file_missing', message: '原始文件已缺失，请恢复数据目录或重新上传。' } }, { status: 410 })
    : normal(url, init))
  await user.click(screen.getByRole('button', { name: '预览 实验.xlsx' }))
  expect((await screen.findByRole('alert')).textContent).toContain('原始文件已缺失')
  expect(screen.queryByRole('table')).toBeNull()
  mock.mockImplementation(normal)
  await user.click(screen.getByRole('button', { name: '预览 实验.xlsx' }))
  expect(await screen.findByRole('cell', { name: '10' })).toBeTruthy()
})
