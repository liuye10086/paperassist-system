import { afterEach, expect, test, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../../app/App'
import type { Project } from '../../features/projects/projectTypes'
import { summaryFixture } from '../fixtures/summaryFixture'

afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); window.history.replaceState(null, '', '/') })
const project: Project = { id: 'p1', name: '药学项目', research_topic: '分组比较', project_type: 'sci', file_count: 1,
  created_at: '2026-09-29T10:00:00Z', updated_at: '2026-09-30T10:00:00Z' }
const record = { id: 'f1', filename: '实验.xlsx', size_bytes: 123, uploaded_at: project.created_at, parse_status: 'parsed', error: null }
const preview = { filename: record.filename, sheets: [{ name: '数据', columns: ['数值'], row_count: 1, column_count: 1, preview_rows: [[777]], warnings: [] }] }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(finish => { resolve = finish }); return { promise, resolve } }

function api() {
  let projects: Project[] = [project, ...Array.from({ length: 11 }, (_, index) => ({ ...project, id: `p${index + 2}`, name: `其他项目${index + 2}`, project_type: 'thesis' as const }))]
  let files = [record]
  const fetchMock = vi.fn(async (url: string, init?: RequestInit): Promise<Response> => {
    const summaryProject = projects.find(item => url.startsWith(`/api/v1/projects/${item.id}/summary?`))
    if (summaryProject) return Response.json(summaryFixture(summaryProject.id, summaryProject.project_type))
    const parsed = new URL(url, 'http://localhost')
    if (url.endsWith('/me')) return Response.json({ user: { id: 'test', email: 'test@example.com', role: 'user' }, csrf_token: 'test-csrf' })
    if (url.endsWith('/config')) return Response.json({ max_upload_bytes: 10485760, preview_row_limit: 20 })
    if (parsed.pathname === '/api/v1/projects') {
      if (init?.method === 'POST') {
        const created = { ...project, ...JSON.parse(String(init.body)), id: 'new', file_count: 0 }
        projects = [created, ...projects]; return Response.json(created, { status: 201 })
      }
      const page = Number(parsed.searchParams.get('page')); const pageSize = Number(parsed.searchParams.get('page_size'))
      const q = parsed.searchParams.get('q') ?? ''; const type = parsed.searchParams.get('type')
      const matching = projects.filter(item => item.name.includes(q) && (!type || item.project_type === type))
      return Response.json({ items: matching.slice((page - 1) * pageSize, page * pageSize), total: matching.length, page, page_size: pageSize })
    }
    const found = projects.find(item => parsed.pathname === `/api/v1/projects/${item.id}`)
    if (found) {
      if (init?.method === 'PATCH') {
        const changed = { ...found, ...JSON.parse(String(init.body)) }
        projects = projects.map(item => item.id === changed.id ? changed : item); return Response.json(changed)
      }
      return Response.json(found)
    }
    if (url.endsWith('/files') && init?.method === 'POST') {
      files = [...files, { ...record, id: 'f2' }]; projects = projects.map(item => item.id === 'p1' ? { ...item, file_count: 2 } : item)
      return Response.json({ file: files[1], preview }, { status: 201 })
    }
    if (url.endsWith('/files')) return Response.json(url.includes('/p1/') ? files : [])
    if (url.endsWith('/preview')) return Response.json(preview)
    throw new Error(`Unexpected API ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}
function listCalls(mock: ReturnType<typeof api>) { return mock.mock.calls.filter(([url]) => url.startsWith('/api/v1/projects?')) }
function navigate(name: string) { fireEvent.click(screen.getByRole('button', { name })) }
async function openAndPreview() {
  const user = userEvent.setup(); render(<App />)
  await user.click(await screen.findByRole('button', { name: '打开项目 药学项目' }))
  await user.click(await screen.findByRole('button', { name: '项目文件' }))
  await user.click(await screen.findByRole('button', { name: '预览 实验.xlsx' }))
  await screen.findByRole('cell', { name: '777' }); return user
}

test('paginates five projects per page and retains preview and edit draft after paging and no matching filters', async () => {
  const mock = api(); const user = await openAndPreview()
  expect(listCalls(mock)[0][0]).toBe('/api/v1/projects?page=1&page_size=5')
  navigate('项目概览')
  await user.click(screen.getByRole('button', { name: '编辑项目信息' }))
  await user.clear(screen.getByLabelText('修改项目名称')); await user.type(screen.getByLabelText('修改项目名称'), '未保存草稿')
  navigate('我的项目')
  expect(screen.getByText('共 12 个项目 · 第 1 / 3 页')).toBeTruthy()
  expect(screen.getAllByRole('button', { name: /^打开项目 / })).toHaveLength(5)
  expect(screen.queryByLabelText('每页项目数')).toBeNull()
  expect((screen.getByRole('button', { name: '上一页' }) as HTMLButtonElement).disabled).toBe(true)
  await user.click(screen.getByRole('button', { name: '下一页' }))
  await screen.findByRole('button', { name: '打开项目 其他项目10' })
  expect(screen.getByText('共 12 个项目 · 第 2 / 3 页')).toBeTruthy()
  expect(screen.getAllByRole('button', { name: /^打开项目 / })).toHaveLength(5)
  expect(screen.queryByRole('button', { name: '打开项目 药学项目' })).toBeNull()
  await user.click(screen.getByRole('button', { name: '下一页' }))
  await screen.findByRole('button', { name: '打开项目 其他项目12' })
  expect(screen.getByText('共 12 个项目 · 第 3 / 3 页')).toBeTruthy()
  expect(screen.getAllByRole('button', { name: /^打开项目 / })).toHaveLength(2)
  expect((screen.getByRole('button', { name: '下一页' }) as HTMLButtonElement).disabled).toBe(true)
  await user.click(screen.getByRole('button', { name: '上一页' }))
  await screen.findByRole('button', { name: '打开项目 其他项目10' })
  expect(screen.getByText('共 12 个项目 · 第 2 / 3 页')).toBeTruthy()
  expect(listCalls(mock).map(([url]) => url)).toEqual([
    '/api/v1/projects?page=1&page_size=5', '/api/v1/projects?page=2&page_size=5',
    '/api/v1/projects?page=3&page_size=5', '/api/v1/projects?page=2&page_size=5',
  ])
  navigate('项目文件')
  expect(screen.getByRole('cell', { name: '777' })).toBeTruthy()
  navigate('我的项目')
  await user.type(screen.getByLabelText('搜索项目名称'), '无匹配'); await user.click(screen.getByRole('button', { name: '搜索项目' }))
  await screen.findByText('没有匹配的项目。')
  navigate('项目概览')
  expect((screen.getByLabelText('修改项目名称') as HTMLInputElement).value).toBe('未保存草稿')
  navigate('项目文件')
  expect(screen.getByRole('cell', { name: '777' })).toBeTruthy()
  expect(window.location.hash).toBe('#project=p1')
  expect(mock.mock.calls.filter(([url]) => url === '/api/v1/projects/p1/files')).toHaveLength(1)
})

test('restores a hash project by detail even when absent from the current page', async () => {
  const mock = api(); window.location.hash = '#project=p12'; render(<App />)
  await screen.findByRole('heading', { name: '其他项目12' })
  expect(mock.mock.calls.some(([url]) => url === '/api/v1/projects/p12')).toBe(true)
  expect(screen.queryByRole('button', { name: '打开项目 其他项目12' })).toBeNull()
})

test('retains details during a list failure and retries only the list', async () => {
  const mock = api(); const normal = mock.getMockImplementation()!; const user = await openAndPreview()
  let failed = true
  mock.mockImplementation((url, init) => url.startsWith('/api/v1/projects?') && failed ? Promise.reject(new TypeError('offline')) : normal(url, init))
  navigate('我的项目')
  await user.click(screen.getByRole('button', { name: '下一页' }))
  await screen.findByRole('button', { name: '重试项目列表' })
  navigate('项目文件')
  expect(screen.getByRole('heading', { name: '药学项目' })).toBeTruthy(); expect(screen.getByRole('cell', { name: '777' })).toBeTruthy()
  navigate('我的项目')
  failed = false; await user.click(screen.getByRole('button', { name: '重试项目列表' })); await screen.findByRole('button', { name: '打开项目 其他项目10' })
  expect(mock.mock.calls.filter(([url]) => url === '/api/v1/projects/p1')).toHaveLength(1)
})

test('corrects a page beyond the new total to the last valid page', async () => {
  const mock = api(); const normal = mock.getMockImplementation()!; const user = userEvent.setup(); render(<App />)
  await screen.findByRole('button', { name: '打开项目 药学项目' })
  mock.mockImplementation((url, init) => url.includes('page=2&') ? Promise.resolve(Response.json({ items: [], total: 1, page: 2, page_size: 5 })) : normal(url, init))
  navigate('我的项目')
  await user.click(screen.getByRole('button', { name: '下一页' }))
  await waitFor(() => expect(listCalls(mock).map(([url]) => url)).toEqual([
    '/api/v1/projects?page=1&page_size=5', '/api/v1/projects?page=2&page_size=5', '/api/v1/projects?page=1&page_size=5',
  ]))
})

test('updates details when editing removes the project from search results while retaining preview', async () => {
  api(); const user = await openAndPreview()
  navigate('我的项目')
  await user.type(screen.getByLabelText('搜索项目名称'), '药学'); await user.click(screen.getByRole('button', { name: '搜索项目' }))
  await screen.findByText('共 1 个项目 · 第 1 / 1 页')
  navigate('项目概览')
  await user.click(screen.getByRole('button', { name: '编辑项目信息' })); await user.clear(screen.getByLabelText('修改项目名称'))
  await user.type(screen.getByLabelText('修改项目名称'), '改名项目'); await user.click(screen.getByRole('button', { name: '保存修改' }))
  navigate('我的项目')
  await screen.findByText('没有匹配的项目。')
  navigate('项目文件')
  expect(screen.getByRole('heading', { name: '改名项目' })).toBeTruthy(); expect(screen.getByRole('cell', { name: '777' })).toBeTruthy()
})

test('refreshes file counts and metadata after upload without resetting an editing draft', async () => {
  api(); const user = await openAndPreview()
  navigate('项目概览')
  await user.click(screen.getByRole('button', { name: '编辑项目信息' })); await user.type(screen.getByLabelText('修改项目名称'), '草稿')
  navigate('项目文件')
  await user.upload(screen.getByLabelText('选择 Excel 文件'), new File(['data'], '实验.xlsx'))
  await user.click(screen.getByRole('button', { name: '上传并预览' }))
  navigate('项目概览')
  await waitFor(() => expect(screen.getByText(/2 个文件/)).toBeTruthy())
  navigate('我的项目')
  const row = screen.getByRole('cell', { name: '药学项目' }).closest('tr')!
  expect(within(row).getByRole('cell', { name: '2' })).toBeTruthy()
  navigate('项目概览')
  expect((screen.getByLabelText('修改项目名称') as HTMLInputElement).value).toBe('药学项目草稿')
  navigate('项目文件')
  expect(screen.getByRole('cell', { name: '777' })).toBeTruthy()
})

test('creation returns to page one and clears both filters with the fixed page size', async () => {
  const mock = api(); const user = userEvent.setup(); render(<App />)
  await screen.findByRole('button', { name: '打开项目 药学项目' })
  await user.selectOptions(screen.getByLabelText('筛选项目类型'), 'thesis')
  navigate('我的项目')
  await user.type(screen.getByLabelText('搜索项目名称'), '其他'); await user.click(screen.getByRole('button', { name: '搜索项目' }))
  await screen.findByText('共 11 个项目 · 第 1 / 3 页')
  await user.click(screen.getByRole('button', { name: '下一页' }))
  await screen.findByText('共 11 个项目 · 第 2 / 3 页')
  await user.click(screen.getByRole('button', { name: '新建研究项目' }))
  await user.type(screen.getByLabelText('项目名称'), '新药学项目'); await user.type(screen.getByLabelText('研究主题'), '新主题')
  await user.selectOptions(screen.getByLabelText('项目类型'), 'sci'); await user.click(screen.getByRole('button', { name: '创建项目' }))
  await screen.findByRole('heading', { name: '新药学项目' })
  navigate('我的项目')
  await screen.findByRole('button', { name: '打开项目 新药学项目' })
  expect((screen.getByLabelText('搜索项目名称') as HTMLInputElement).value).toBe('')
  expect((screen.getByLabelText('筛选项目类型') as HTMLSelectElement).value).toBe('')
  expect(screen.getByText('共 13 个项目 · 第 1 / 3 页')).toBeTruthy()
  expect(screen.getAllByRole('button', { name: /^打开项目 / })).toHaveLength(5)
  expect(listCalls(mock).at(-1)![0]).toBe('/api/v1/projects?page=1&page_size=5')
})

for (const late of ['response', 'body']) {
  test(`ignores a stale list ${late} after a newer search`, async () => {
    const mock = api(); const normal = mock.getMockImplementation()!; const pending = deferred<Response>(); const body = deferred<unknown>()
    let bodyStarted = false
    mock.mockImplementation(async (url, init) => {
      if (url.includes('q=old')) {
        if (late === 'response') return pending.promise
        const response = Response.json({}); response.json = () => { bodyStarted = true; return body.promise }; return response
      }
      return normal(url, init)
    })
    const user = userEvent.setup(); render(<App />); await screen.findByRole('button', { name: '打开项目 药学项目' })
    navigate('我的项目')
    await user.type(screen.getByLabelText('搜索项目名称'), 'old'); await user.click(screen.getByRole('button', { name: '搜索项目' }))
    if (late === 'body') await waitFor(() => expect(bodyStarted).toBe(true))
    await user.clear(screen.getByLabelText('搜索项目名称')); await user.type(screen.getByLabelText('搜索项目名称'), '药学')
    await user.click(screen.getByRole('button', { name: '搜索项目' })); await screen.findByText('共 1 个项目 · 第 1 / 1 页')
    await act(async () => { const old = { items: [{ ...project, name: '旧结果' }], total: 1, page: 1, page_size: 5 }; if (late === 'response') pending.resolve(Response.json(old)); else body.resolve(old) })
    expect(screen.queryByRole('button', { name: '打开项目 旧结果' })).toBeNull()
    expect(screen.getByRole('button', { name: '打开项目 药学项目' })).toBeTruthy()
  })
}

test('list requests time out after fifteen seconds and allow retry even if fetch ignores abort', async () => {
  const mock = api(); const normal = mock.getMockImplementation()!; let pending = true
  mock.mockImplementation((url, init) => url.startsWith('/api/v1/projects?') && pending ? new Promise(() => {}) : normal(url, init))
  vi.useFakeTimers(); render(<App />); await act(async () => {})
  await act(async () => { await vi.advanceTimersByTimeAsync(15000) })
  expect(screen.getByRole('alert').textContent).toContain('超时')
  pending = false; fireEvent.click(screen.getByRole('button', { name: '重试项目列表' })); await act(async () => {})
  expect(screen.getByRole('button', { name: '打开项目 药学项目' })).toBeTruthy()
})

test('detail network failure offers its own retry and keeps the selected hash', async () => {
  const mock = api(); const normal = mock.getMockImplementation()!; let failed = true
  mock.mockImplementation((url, init) => url === '/api/v1/projects/p1' && failed ? Promise.reject(new TypeError('offline')) : normal(url, init))
  const user = userEvent.setup(); render(<App />); await user.click(await screen.findByRole('button', { name: '打开项目 药学项目' }))
  await screen.findByRole('button', { name: '重试项目详情' }); expect(window.location.hash).toBe('#project=p1')
  expect(screen.queryByLabelText('选择 Excel 文件')).toBeNull()
  failed = false; await user.click(screen.getByRole('button', { name: '重试项目详情' })); await screen.findByRole('heading', { name: '药学项目' })
})

test('detail requests time out after fifteen seconds and retry when fetch ignores abort', async () => {
  const mock = api(); const normal = mock.getMockImplementation()!; let pending = true
  mock.mockImplementation((url, init) => url === '/api/v1/projects/p1' && pending ? new Promise(() => {}) : normal(url, init))
  render(<App />); await screen.findByRole('button', { name: '打开项目 药学项目' })
  vi.useFakeTimers(); fireEvent.click(screen.getByRole('button', { name: '打开项目 药学项目' })); await act(async () => {})
  await act(async () => { await vi.advanceTimersByTimeAsync(15000) })
  expect(screen.getByRole('alert').textContent).toContain('项目详情读取超时')
  expect(screen.queryByLabelText('选择 Excel 文件')).toBeNull()
  pending = false; fireEvent.click(screen.getByRole('button', { name: '重试项目详情' })); await act(async () => {})
  navigate('项目文件')
  expect(screen.getByRole('heading', { name: '药学项目' })).toBeTruthy()
  expect(mock.mock.calls.filter(([url]) => url === '/api/v1/projects/p1')).toHaveLength(2)
})

for (const late of ['response', 'body']) {
  test(`rejects metadata ${late} started by upload before a successful patch`, async () => {
    const mock = api(); const normal = mock.getMockImplementation()!; const pending = deferred<Response>(); const body = deferred<unknown>()
    let reads = 0; let bodyStarted = false
    mock.mockImplementation(async (url, init) => {
      if (url === '/api/v1/projects/p1' && !init?.method && ++reads === 2) {
        if (late === 'response') return pending.promise
        const response = Response.json(project); response.json = () => { bodyStarted = true; return body.promise }; return response
      }
      return normal(url, init)
    })
    const user = await openAndPreview(); navigate('项目概览'); await user.click(screen.getByRole('button', { name: '编辑项目信息' }))
    await user.clear(screen.getByLabelText('修改项目名称')); await user.type(screen.getByLabelText('修改项目名称'), 'PATCH 新名称')
    await user.clear(screen.getByLabelText('修改研究主题')); await user.type(screen.getByLabelText('修改研究主题'), 'PATCH 新主题')
    navigate('项目文件')
    await user.upload(screen.getByLabelText('选择 Excel 文件'), new File(['data'], '实验.xlsx'))
    await user.click(screen.getByRole('button', { name: '上传并预览' })); await waitFor(() => expect(reads).toBe(2))
    if (late === 'body') await waitFor(() => expect(bodyStarted).toBe(true))
    navigate('项目概览')
    await user.click(screen.getByRole('button', { name: '保存修改' })); await screen.findByRole('heading', { name: 'PATCH 新名称' })
    await act(async () => { if (late === 'response') pending.resolve(Response.json(project)); else body.resolve(project) })
    expect(screen.getByRole('heading', { name: 'PATCH 新名称' })).toBeTruthy()
    navigate('项目文件')
    expect(screen.getByText('PATCH 新主题')).toBeTruthy(); expect(screen.getByRole('cell', { name: '777' })).toBeTruthy()
  })
}
