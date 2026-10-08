import { afterEach, expect, test, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../../app/App'
import { summaryFixture } from '../fixtures/summaryFixture'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', '/')
})

const project = { id: 'p1', name: '药学项目', research_topic: '分组比较', project_type: 'sci', file_count: 1,
  created_at: '2026-09-29T10:00:00Z', updated_at: '2026-09-29T10:00:00Z' }
const secondProject = { ...project, id: 'p2', name: '毕业论文项目', project_type: 'thesis', file_count: 0 }
const session = { user: { id: 'user-a', email: 'a@paperassist.local', role: 'user' }, csrf_token: 'csrf-a' }
const otherSession = { user: { id: 'user-b', email: 'b@paperassist.local', role: 'user' }, csrf_token: 'csrf-b' }
const record = { id: 'f1', project_id: 'p1', filename: '实验.xlsx', file_type: 'xlsx', size_bytes: 123,
  sha256: 'a'.repeat(64), uploaded_at: '2026-09-29T10:00:00Z', parse_status: 'parsed', error: null }
const preview = { filename: '实验.xlsx', sheets: [
  { name: '数据', columns: ['组别', '数值'], row_count: 1, column_count: 2, preview_rows: [['A', 10]], warnings: [] },
  { name: '空表', columns: [], row_count: 0, column_count: 0, preview_rows: [], warnings: ['空表预览仍保留。'] },
] }

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(finish => { resolve = finish })
  return { promise, resolve }
}

function api(options: { patch?: (init: RequestInit) => Promise<Response> } = {}) {
  let projects = [project, secondProject]
  let currentSession: typeof session | null = session
  const mock = vi.fn(async (url: string, init?: RequestInit): Promise<Response> => {
    if (new URL(url, 'http://localhost').pathname.endsWith('/model-usage')) {
      const budget = { scope_type: 'user', limit_micro_usd: null, revision: 0, estimated_micro_usd: 0,
        reserved_micro_usd: 0, available_micro_usd: null, exceeded: false }
      return Response.json({ currency: 'USD', period: 'cumulative', enforcement_scope: 'unified_only',
        user_budget: budget, project_budget: { ...budget, scope_type: 'project' }, estimated_micro_usd: 0,
        reserved_micro_usd: 0, pending_count: 0, items: [], total: 0, page: 1, page_size: 10 })
    }
    const summaryProject = projects.find(item => url.startsWith(`/api/v1/projects/${item.id}/summary?`))
    if (summaryProject) return Response.json(summaryFixture(summaryProject.id, summaryProject.project_type as 'sci' | 'thesis'))
    if (url.endsWith('/me')) return currentSession ? Response.json(currentSession) : new Response(null, { status: 401 })
    if (url.endsWith('/logout')) { currentSession = null; return new Response(null, { status: 204 }) }
    if (url.endsWith('/login')) { currentSession = otherSession; projects = [{ ...project, name: '乙用户项目' }]; return Response.json(currentSession) }
    if (url.startsWith('/api/v1/projects?')) {
      const parameters = new URL(url, 'http://localhost').searchParams
      return Response.json({ items: projects, total: projects.length, page: Number(parameters.get('page')), page_size: Number(parameters.get('page_size')) })
    }
    if (url === '/api/v1/projects/p1' && init?.method === 'PATCH') {
      if (options.patch) {
        const response = await options.patch(init)
        if (response.ok) {
          const updated = await response.clone().json()
          projects = projects.map(item => item.id === updated.id ? updated : item)
        }
        return response
      }
      const updated = { ...projects[0], ...JSON.parse(String(init.body)), updated_at: '2026-09-30T10:00:00Z' }
      projects = projects.map(item => item.id === updated.id ? updated : item)
      return Response.json(updated)
    }
    if (url === '/api/v1/projects/p1') return Response.json(projects[0])
    if (url === '/api/v1/projects/p2') return Response.json(projects.find(item => item.id === 'p2'))
    if (url.endsWith('/config')) return Response.json({ max_upload_bytes: 10485760, preview_row_limit: 20 })
    if (url.endsWith('/files') && init?.method === 'POST') return Response.json({ file: record, preview }, { status: 201 })
    if (url === '/api/v1/projects/p1/files') return Response.json([record])
    if (url === '/api/v1/projects/p2/files') return Response.json([])
    if (url.endsWith('/preview')) return Response.json(preview)
    throw new Error(`Unexpected API: ${url}`)
  })
  vi.stubGlobal('fetch', mock)
  return mock
}

function navigate(name: string) { fireEvent.click(screen.getByRole('button', { name })) }

async function openProject() {
  const user = userEvent.setup()
  render(<App />)
  await user.click(await screen.findByRole('button', { name: '打开项目 药学项目' }))
  await screen.findByRole('button', { name: '编辑项目信息' })
  return user
}

async function editName(user: ReturnType<typeof userEvent.setup>, value = '新名称') {
  navigate('项目概览')
  await user.click(screen.getByRole('button', { name: '编辑项目信息' }))
  await user.clear(screen.getByLabelText('修改项目名称'))
  await user.type(screen.getByLabelText('修改项目名称'), value)
}

function patchCalls(mock: ReturnType<typeof api>) {
  return mock.mock.calls.filter(([, init]) => init?.method === 'PATCH')
}

test('shows a locked project type and historical report snapshot notice', async () => {
  api()
  await openProject()
  expect(screen.getByText(/创建后不可更改/)).toBeTruthy()
  navigate('编辑项目信息')
  expect(screen.getByText(/修改.*不会.*历史报告/)).toBeTruthy()
  const details = screen.getByLabelText('修改项目名称').closest('.project-details')!
  expect(within(details as HTMLElement).queryByRole('combobox', { name: '项目类型' })).toBeNull()
  expect(within(details as HTMLElement).getByRole('combobox', { name: '项目默认输出语言' })).toBeTruthy()
})

test('patches only changed name and updates heading and selection without resetting file preview', async () => {
  const mock = api()
  const user = await openProject()
  navigate('项目文件')
  await user.click(screen.getByRole('button', { name: '预览 实验.xlsx' }))
  await screen.findByRole('cell', { name: '10' })
  await user.selectOptions(screen.getByLabelText('工作表'), '1')
  const fileReads = mock.mock.calls.filter(([url]) => url === '/api/v1/projects/p1/files').length
  await editName(user, '  新名称  ')
  await user.click(screen.getByRole('button', { name: '保存修改' }))
  expect(await screen.findByRole('heading', { name: '新名称' })).toBeTruthy()
  navigate('我的项目')
  expect(await screen.findByRole('button', { name: '打开项目 新名称' })).toBeTruthy()
  expect(JSON.parse(String(patchCalls(mock)[0][1]!.body))).toEqual({ name: '新名称' })
  expect(new Headers(patchCalls(mock)[0][1]!.headers).get('X-CSRF-Token')).toBe('csrf-a')
  expect(patchCalls(mock)[0][1]!.credentials).toBe('same-origin')
  navigate('项目文件')
  expect(screen.getByText('空表预览仍保留。')).toBeTruthy()
  expect((screen.getByLabelText('工作表') as HTMLSelectElement).value).toBe('1')
  expect(mock.mock.calls.filter(([url]) => url === '/api/v1/projects/p1/files')).toHaveLength(fileReads)
})

test('patches only the changed research topic', async () => {
  const mock = api()
  const user = await openProject()
  navigate('项目概览')
  await user.click(screen.getByRole('button', { name: '编辑项目信息' }))
  await user.clear(screen.getByLabelText('修改研究主题'))
  await user.type(screen.getByLabelText('修改研究主题'), '  新研究主题  ')
  await user.click(screen.getByRole('button', { name: '保存修改' }))
  expect(await screen.findByText('新研究主题')).toBeTruthy()
  expect(JSON.parse(String(patchCalls(mock)[0][1]!.body))).toEqual({ research_topic: '新研究主题' })
})

test('cancels draft without a patch or clearing file preview', async () => {
  const mock = api()
  const user = await openProject()
  navigate('项目文件')
  await user.click(screen.getByRole('button', { name: '预览 实验.xlsx' }))
  await screen.findByRole('cell', { name: '10' })
  await editName(user)
  await user.click(screen.getByRole('button', { name: '取消修改' }))
  expect(patchCalls(mock)).toHaveLength(0)
  expect(screen.getByRole('heading', { name: '药学项目' })).toBeTruthy()
  navigate('项目文件')
  expect(screen.getByRole('cell', { name: '10' })).toBeTruthy()
  navigate('项目概览')
  await user.click(screen.getByRole('button', { name: '编辑项目信息' }))
  expect((screen.getByLabelText('修改项目名称') as HTMLInputElement).value).toBe('药学项目')
})

test('does not patch a draft with no actual changes', async () => {
  const mock = api()
  const user = await openProject()
  await editName(user, '  药学项目  ')
  await user.click(screen.getByRole('button', { name: '保存修改' }))
  expect(patchCalls(mock)).toHaveLength(0)
  expect(screen.getByRole('heading', { name: '药学项目' })).toBeTruthy()
})

for (const field of ['修改项目名称', '修改研究主题']) {
  test(`rejects whitespace in ${field} before patching`, async () => {
    const mock = api()
    const user = await openProject()
    navigate('项目概览')
    await user.click(screen.getByRole('button', { name: '编辑项目信息' }))
    await user.clear(screen.getByLabelText(field))
    await user.type(screen.getByLabelText(field), '   ')
    await user.click(screen.getByRole('button', { name: '保存修改' }))
    expect((await screen.findByRole('alert')).textContent).toContain('请填写项目名称和研究主题')
    expect(patchCalls(mock)).toHaveLength(0)
    expect((screen.getByLabelText(field) as HTMLInputElement).value).toBe('   ')
  })
}

for (const failure of ['422', 'network']) {
  test(`retains draft after ${failure} and allows successful retry`, async () => {
    let fail = true
    const mock = api({ patch: async init => {
      if (fail) {
        fail = false
        if (failure === 'network') throw new TypeError('offline')
        return Response.json({ detail: { code: 'project_update_invalid', message: '项目资料校验失败。' } }, { status: 422 })
      }
      return Response.json({ ...project, ...JSON.parse(String(init.body)) })
    } })
    const user = await openProject()
    await editName(user)
    await user.click(screen.getByRole('button', { name: '保存修改' }))
    expect((await screen.findByRole('alert')).textContent).toContain(failure === 'network' ? '无法连接后端' : '请仅提交有效的项目名称或研究主题')
    expect(screen.getByRole('alert').textContent).not.toContain('项目资料校验失败')
    expect((screen.getByLabelText('修改项目名称') as HTMLInputElement).value).toBe('新名称')
    await user.click(screen.getByRole('button', { name: '保存修改' }))
    expect(await screen.findByRole('heading', { name: '新名称' })).toBeTruthy()
    expect(patchCalls(mock)).toHaveLength(2)
  })
}

test('disables editing controls and prevents duplicate patches while saving', async () => {
  const pending = deferred<Response>()
  const mock = api({ patch: () => pending.promise })
  const user = await openProject()
  await editName(user)
  const form = screen.getByLabelText('修改项目名称').closest('form')!
  fireEvent.submit(form)
  fireEvent.submit(form)
  expect((screen.getByRole('button', { name: '正在保存……' }) as HTMLButtonElement).disabled).toBe(true)
  expect((screen.getByRole('button', { name: '取消修改' }) as HTMLButtonElement).disabled).toBe(true)
  expect((screen.getByLabelText('修改项目名称') as HTMLInputElement).disabled).toBe(true)
  expect((screen.getByLabelText('修改研究主题') as HTMLTextAreaElement).disabled).toBe(true)
  expect(patchCalls(mock)).toHaveLength(1)
  await act(async () => pending.resolve(Response.json({ ...project, name: '新名称' })))
  expect(await screen.findByRole('heading', { name: '新名称' })).toBeTruthy()
})

test('times out after fifteen seconds and rereads server result while preserving preview', async () => {
  const mock = api({ patch: init => new Promise((_resolve, reject) => {
    init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
  }) })
  const normal = mock.getMockImplementation()!
  let reads = 0
  mock.mockImplementation(async (url, init) => {
    if (url === '/api/v1/projects/p1' && init?.method !== 'PATCH') {
      return Response.json(++reads > 1 ? { ...project, name: '服务端已保存' } : project)
    }
    const response = await normal(url, init)
    if (url.startsWith('/api/v1/projects?') && reads > 1) {
      const page = await response.json()
      return Response.json({ ...page, items: page.items.map((item: typeof project) => item.id === 'p1' ? { ...item, name: '服务端已保存' } : item) })
    }
    return response
  })
  const user = await openProject()
  navigate('项目文件')
  await user.click(screen.getByRole('button', { name: '预览 实验.xlsx' }))
  await screen.findByRole('cell', { name: '10' })
  await editName(user)
  vi.useFakeTimers()
  fireEvent.submit(screen.getByLabelText('修改项目名称').closest('form')!)
  await act(async () => { await vi.advanceTimersByTimeAsync(14_999) })
  expect(screen.queryByRole('alert')).toBeNull()
  await act(async () => { await vi.advanceTimersByTimeAsync(1) })
  expect(screen.getByRole('alert').textContent).toContain('超时')
  expect(screen.getByRole('alert').textContent).toContain('核对')
  expect((screen.getByLabelText('修改项目名称') as HTMLInputElement).value).toBe('新名称')
  fireEvent.click(screen.getByRole('button', { name: '重新读取项目' }))
  await act(async () => {})
  expect(screen.getByRole('heading', { name: '服务端已保存' })).toBeTruthy()
  navigate('我的项目')
  expect(screen.getByRole('button', { name: '打开项目 服务端已保存' })).toBeTruthy()
  navigate('项目文件')
  expect(screen.getByRole('cell', { name: '10' })).toBeTruthy()
  expect(patchCalls(mock)).toHaveLength(1)
})

for (const late of ['response', 'body']) {
  test(`ignores a late patch ${late} after switching projects`, async () => {
    const pending = deferred<Response>()
    const body = deferred<unknown>()
    let bodyStarted = false
    const mock = api({ patch: async () => {
      if (late === 'response') return pending.promise
      const response = Response.json(project)
      response.json = () => { bodyStarted = true; return body.promise }
      return response
    } })
    const user = await openProject()
    await editName(user)
    await user.click(screen.getByRole('button', { name: '保存修改' }))
    if (late === 'body') await waitFor(() => expect(bodyStarted).toBe(true))
    navigate('我的项目')
    await user.click(screen.getByRole('button', { name: '打开项目 毕业论文项目' }))
    await screen.findByRole('heading', { name: '毕业论文项目' })
    expect(patchCalls(mock)[0][1]!.signal!.aborted).toBe(true)
    await act(async () => {
      if (late === 'response') pending.resolve(Response.json({ ...project, name: '迟到名称' }))
      else body.resolve({ ...project, name: '迟到名称' })
    })
    expect(screen.queryByText(/迟到名称/)).toBeNull()
    expect(screen.getByRole('heading', { name: '毕业论文项目' })).toBeTruthy()
    navigate('项目概览')
    await user.click(screen.getByRole('button', { name: '编辑项目信息' }))
    expect((screen.getByLabelText('修改项目名称') as HTMLInputElement).value).toBe('毕业论文项目')
  })
}

for (const late of ['response', 'body']) {
  test(`keeps a late patch ${late} out of a new account after logout and login`, async () => {
    const pending = deferred<Response>()
    const body = deferred<unknown>()
    let bodyStarted = false
    const mock = api({ patch: async () => {
      if (late === 'response') return pending.promise
      const response = Response.json(project)
      response.json = () => { bodyStarted = true; return body.promise }
      return response
    } })
    const user = await openProject()
    await editName(user)
    await user.click(screen.getByRole('button', { name: '保存修改' }))
    if (late === 'body') await waitFor(() => expect(bodyStarted).toBe(true))
    await user.click(screen.getByRole('button', { name: '账号' }))
    await user.click(screen.getByRole('button', { name: '退出登录' }))
    expect(patchCalls(mock)[0][1]!.signal!.aborted).toBe(true)
    await user.type(await screen.findByLabelText('邮箱'), otherSession.user.email)
    await user.type(screen.getByLabelText('密码'), 'valid-password')
    await user.click(screen.getByRole('button', { name: /^登录$/ }))
    await user.click(await screen.findByRole('button', { name: '打开项目 乙用户项目' }))
    await screen.findByRole('heading', { name: '乙用户项目' })
    await act(async () => {
      if (late === 'response') pending.resolve(Response.json({ ...project, name: '甲用户迟到名称' }))
      else body.resolve({ ...project, name: '甲用户迟到名称' })
    })
    expect(screen.queryByText(/甲用户迟到名称/)).toBeNull()
    expect(screen.getByRole('heading', { name: '乙用户项目' })).toBeTruthy()
  })
}

test('retains an editing draft during same-project refresh and ignores stale list after successful patch', async () => {
  const staleList = deferred<Response>()
  const mock = api()
  const normal = mock.getMockImplementation()!
  let lists = 0
  mock.mockImplementation(async (url, init) => {
    if (url.startsWith('/api/v1/projects?') && ++lists === 2) return staleList.promise
    return normal(url, init)
  })
  const user = await openProject()
  await editName(user)
  navigate('项目文件')
  const input = await screen.findByLabelText('选择 Excel 文件')
  await waitFor(() => expect((input as HTMLInputElement).disabled).toBe(false))
  await user.upload(input, new File(['sample'], '实验.xlsx'))
  await user.click(screen.getByRole('button', { name: '上传并预览' }))
  await screen.findByRole('cell', { name: '10' })
  navigate('项目概览')
  expect((screen.getByLabelText('修改项目名称') as HTMLInputElement).value).toBe('新名称')
  await waitFor(() => expect(lists).toBe(2))
  await user.click(screen.getByRole('button', { name: '保存修改' }))
  await screen.findByRole('heading', { name: '新名称' })
  await act(async () => staleList.resolve(Response.json({ items: [project, secondProject], total: 2, page: 1, page_size: 5 })))
  expect(screen.getByRole('heading', { name: '新名称' })).toBeTruthy()
  navigate('我的项目')
  expect(await screen.findByRole('button', { name: '打开项目 新名称' })).toBeTruthy()
  navigate('项目文件')
  expect(screen.getByRole('cell', { name: '10' })).toBeTruthy()
})

test('does not reset draft when a same-project list refresh completes', async () => {
  const mock = api()
  const user = await openProject()
  await editName(user)
  navigate('项目文件')
  const input = await screen.findByLabelText('选择 Excel 文件')
  await waitFor(() => expect((input as HTMLInputElement).disabled).toBe(false))
  await user.upload(input, new File(['sample'], '实验.xlsx'))
  await user.click(screen.getByRole('button', { name: '上传并预览' }))
  await waitFor(() => expect(mock.mock.calls.filter(([url]) => url.startsWith('/api/v1/projects?'))).toHaveLength(2))
  await screen.findByRole('cell', { name: '10' })
  navigate('项目概览')
  expect((screen.getByLabelText('修改项目名称') as HTMLInputElement).value).toBe('新名称')
})
