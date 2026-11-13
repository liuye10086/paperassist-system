import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { clearApiSession, setApiSession } from '../../shared/api/client'
import CustomerFeedback from './CustomerFeedback'
import CustomerWorkspace from './CustomerWorkspace'
import { customerBase, type Feedback } from './customerWorkspaceApi'

const project = {
  id: 'customer-project-1', name: '客户项目样例', research_topic: '比较病例与对照',
  project_type: 'research', file_count: 0, created_at: '2026-11-11T00:00:00Z', updated_at: '2026-11-11T00:00:00Z',
}
const base = '/api/v1/projects/' + project.id
const customer = customerBase(project.id)
const delivery = {
  id: 'released-1', kind: 'analysis', title: '已发布演示成果', revision: 1,
  member_count: 1, published_at: project.created_at,
}
const memberUrl = customer + '/deliveries/released-1/members/figure-1/download'

beforeEach(() => { setApiSession('csrf', 'customer-test'); sessionStorage.clear() })
afterEach(() => {
  cleanup()
  clearApiSession()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', window.location.pathname)
})

it('creates a customer project, opens five steps, and sends feedback on a published delivery', async () => {
  const feedback: Feedback[] = []
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.startsWith('/api/v1/projects?')) return Response.json({ items: [], total: 0, page: 1, page_size: 5 })
    if (url === '/api/v1/projects' && init?.method === 'POST') return Response.json(project, { status: 201 })
    if (url === base) return Response.json(project)
    if (url === customer + '/progress') return Response.json({
      status: 'needs_materials', requirement_version: 1, submitted_at: project.created_at,
      updated_at: project.updated_at, note: '请补充样本分组表。', feedback: [],
    })
    if (url.startsWith(base + '/files?')) {
      const page = Number(new URL(url, 'http://testserver').searchParams.get('page'))
      return Response.json({ items: [{ id: `file-${page}`, filename: `资料-${page}.xlsx`, parse_status: 'stored' }],
        total: 6, page, page_size: 5 })
    }
    if (url.startsWith(base + '/file-batches?')) {
      return Response.json({ items: [], total: 0, page: 1, page_size: 5 })
    }
    if (url === customer + '/deliveries') return Response.json({ items: [delivery] })
    if (url === customer + '/deliveries/released-1') return Response.json({
      ...delivery, members: [{ id: 'figure-1', name: 'heatmap.png', format: 'png', size_bytes: 1000, download_url: memberUrl }],
      package_url: null, feedback,
    })
    if (url === customer + '/feedback' && init?.method === 'POST') {
      const entry = { id: 'feedback-1', message: JSON.parse(String(init.body)).message, created_at: project.created_at }
      feedback.push(entry)
      return Response.json(entry, { status: 201 })
    }
    return Response.json({ detail: { code: 'project_not_found' } }, { status: 404 })
  })
  vi.stubGlobal('fetch', fetch)
  render(<CustomerWorkspace />)
  expect(screen.queryByRole('heading', { name: '我的项目' })).toBeNull()
  const projectPager = screen.getByRole('navigation', { name: '项目分页' })
  expect(Array.from(projectPager.children, child => child.textContent)).toEqual(['上一页', '共 0 个项目 · 第 1 / 1 页', '下一页'])
  fireEvent.click(screen.getByRole('button', { name: '新建研究项目' }))
  const dialog = screen.getByRole('dialog', { name: '新建项目' })
  expect(within(dialog).getByLabelText('项目名称').closest('form')?.classList.contains('project-form')).toBe(true)
  fireEvent.change(within(dialog).getByLabelText('项目名称'), { target: { value: project.name } })
  fireEvent.change(within(dialog).getByLabelText('研究目标'), { target: { value: project.research_topic } })
  fireEvent.click(within(dialog).getByRole('button', { name: '创建项目' }))
  const detailsHeading = await screen.findByRole('heading', { name: '项目资料', level: 1 })
  expect(screen.queryByRole('heading', { name: project.name })).toBeNull()
  expect(screen.getByRole('textbox', { name: '修改项目名称' })).toHaveProperty('value', project.name)
  expect(document.activeElement).toBe(detailsHeading)
  const stepper = screen.getByRole('navigation', { name: '项目操作步骤' })
  expect(within(stepper).getAllByRole('button')).toHaveLength(5)
  expect(within(stepper).queryByRole('button', { name: /执行分析/ })).toBeNull()
  const [, create] = fetch.mock.calls.find(([url]) => url === '/api/v1/projects')!
  expect(new Headers(create?.headers).get('Idempotency-Key')).toBeTruthy()
  expect(JSON.parse(String(create?.body))).toMatchObject({
    name: project.name, research_topic: project.research_topic, project_type: 'research', delivery_kinds: ['analysis'],
  })
  fireEvent.click(within(stepper).getByRole('button', { name: /任务进度/ }))
  const progressHeading = await screen.findByRole('heading', { name: '任务进度', level: 1 })
  expect(screen.queryByRole('heading', { name: project.name })).toBeNull()
  expect(document.activeElement).toBe(progressHeading)
  await screen.findByText('待补资料')
  expect(screen.getByText('请补充样本分组表。')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '补交资料' }))
  const uploadHeading = await screen.findByRole('heading', { name: '上传资料', level: 1 })
  expect(screen.queryByRole('heading', { name: project.name })).toBeNull()
  expect(document.activeElement).toBe(uploadHeading)
  const filePager = await screen.findByRole('navigation', { name: '文件分页' })
  expect(Array.from(filePager.children, child => child.textContent)).toEqual(['上一页', '第 1 / 2 页 · 共 6 个文件', '下一页'])
  fireEvent.click(within(filePager).getByRole('button', { name: '下一页' }))
  await screen.findByText('资料-2.xlsx')
  expect(within(await screen.findByRole('navigation', { name: '文件分页' })).getByText('第 2 / 2 页 · 共 6 个文件')).toBeTruthy()
  fireEvent.click(within(stepper).getByRole('button', { name: /查看交付/ }))
  const deliveriesHeading = await screen.findByRole('heading', { name: '已发布交付', level: 1 })
  expect(screen.queryByRole('heading', { name: project.name })).toBeNull()
  expect(document.activeElement).toBe(deliveriesHeading)
  fireEvent.click(await screen.findByRole('button', { name: '查看交付 已发布演示成果' }))
  expect((await screen.findByRole('link', { name: '下载 heatmap.png' })).getAttribute('href')).toBe(memberUrl)
  expect(document.activeElement).toBe(screen.getByRole('heading', { name: delivery.title, level: 1 }))
  fireEvent.change(screen.getByRole('textbox', { name: '反馈内容' }), { target: { value: '热图配色清晰。' } })
  fireEvent.click(screen.getByRole('button', { name: '发送反馈' }))
  await screen.findByText('反馈已发送。')
  await screen.findByText('热图配色清晰。')
  const [, sent] = fetch.mock.calls.find(([url]) => url === customer + '/feedback')!
  expect(JSON.parse(String(sent?.body))).toEqual({ message: '热图配色清晰。', snapshot_id: delivery.id })
  expect(new Headers(sent?.headers).get('Idempotency-Key')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '返回交付列表' }))
  expect(document.activeElement).toBe(await screen.findByRole('button', { name: '查看交付 已发布演示成果' }))
})

it('preserves Back and Forward after a cancelled departure from an upload', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url === base) return Response.json(project)
    const items = url.startsWith('/api/v1/projects?') ? [project] : []
    return Response.json({ items, total: items.length, page: 1, page_size: 5 })
  }))
  const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValue(true)
  render(<CustomerWorkspace />)
  fireEvent.click(await screen.findByRole('button', { name: '打开项目 ' + project.name }))
  const details = window.location.hash
  fireEvent.click(await screen.findByRole('button', { name: '下一步 上传资料' }))
  const upload = window.location.hash
  const input = await screen.findByLabelText('批量选择 Excel / Word / PDF / 图片 文件')
  fireEvent.change(input, { target: { files: [new File(['sample'], 'sample.xlsx')] } })

  await act(async () => window.history.back())
  await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1))
  await waitFor(() => expect(window.location.hash).toBe(upload))
  expect(screen.getByText(/sample\.xlsx/)).toBeTruthy()

  await act(async () => window.history.back())
  await waitFor(() => expect(window.location.hash).toBe(details))
  await screen.findByRole('button', { name: '下一步 上传资料' })
  await act(async () => window.history.forward())
  await waitFor(() => expect(window.location.hash).toBe(upload))
  await screen.findByLabelText('批量选择 Excel / Word / PDF / 图片 文件')
})

it('keeps a foreign project address outside the customer steps and delivery API', async () => {
  window.history.replaceState(null, '', '#customer-project=foreign&step=deliveries')
  const fetch = vi.fn(async () => Response.json({ detail: { code: 'project_not_found' } }, { status: 404 }))
  vi.stubGlobal('fetch', fetch)
  render(<CustomerWorkspace />)
  await screen.findByText('项目不存在或无权访问。')
  expect(screen.queryByRole('navigation', { name: '项目操作步骤' })).toBeNull()
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
  expect(fetch).toHaveBeenCalledWith('/api/v1/projects/foreign', expect.anything())
})

it('keeps the feedback draft and idempotency key after an invalid success receipt', async () => {
  const entry = { id: 'saved', message: '请补充颜色说明。', created_at: project.created_at }
  const fetch = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>()
    .mockResolvedValueOnce(new Response('<html></html>'))
    .mockResolvedValueOnce(Response.json(entry))
  vi.stubGlobal('fetch', fetch)
  const saved = vi.fn()
  render(<CustomerFeedback projectId={project.id} entries={[]} onSaved={saved} />)
  const input = screen.getByRole('textbox', { name: '反馈内容' }) as HTMLTextAreaElement
  fireEvent.change(input, { target: { value: entry.message } })
  fireEvent.click(screen.getByRole('button', { name: '发送反馈' }))
  await screen.findByText('反馈发送结果待确认，请重试原请求。')
  expect(input.value).toBe(entry.message)
  expect(saved).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '重试发送反馈' }))
  await screen.findByText('反馈已发送。')
  expect(saved).toHaveBeenCalledOnce()
  const [first, second] = fetch.mock.calls.map(([, init]) => new Headers(init?.headers).get('Idempotency-Key'))
  expect(first).toBeTruthy()
  expect(second).toBe(first)
})
