import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import ProjectWorkspace from './ProjectWorkspace'

vi.mock('./ProjectResources', () => ({ default: () => null }))
vi.mock('./ProjectSummary', () => ({ default: () => <section aria-label="摘要记录">已保存进展</section> }))
vi.mock('../model-usage/ProjectModelUsage', () => ({ default: ({ active }: { active: boolean }) => active ? <p>用量明细</p> : null }))
vi.mock('../reviews/ReviewsWorkspace', () => ({ default: () => null }))
vi.mock('../journals/JournalWorkspace', () => ({ default: () => null }))
vi.mock('../school-templates/SchoolTemplates', () => ({ default: () => null }))
vi.mock('../manuscripts/ProjectManuscripts', () => ({ default: () => null }))
vi.mock('../tasks/ProjectTasks', () => ({ default: () => null }))
vi.mock('../literature/ProjectLiterature', () => ({ default: () => null }))

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); window.history.replaceState(null, '', '/') })
const project = { id: 'p1', name: '代谢研究', research_topic: '组间比较', project_type: 'sci', file_count: 2,
  created_at: '2026-10-25T00:00:00Z', updated_at: '2026-10-25T00:00:00Z', default_output_language: 'zh-CN' }
function setup(hash = '#project=p1') {
  window.history.replaceState(null, '', `/${hash}`)
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes('/projects?')) return Response.json({ items: [project, { ...project, id: 'p2', name: '另一研究' }], total: 2, page: 1, page_size: 5 })
    if (url === '/api/v1/projects/p2') return Response.json({ ...project, id: 'p2', name: '另一研究' })
    return Response.json({ ...project, ...(init?.body ? JSON.parse(String(init.body)) : {}) })
  })
  vi.stubGlobal('fetch', fetcher)
  render(<ProjectWorkspace />)
  return { user: userEvent.setup(), fetcher }
}

test('opens history and usage inline without navigation or losing an information draft', async () => {
  const { user } = setup()
  const workspace = await screen.findByRole('region', { name: '当前项目工作区' })
  await screen.findByRole('heading', { name: project.name })
  expect(within(workspace).queryByRole('region', { name: '研究任务' })).toBeNull()
  expect(screen.queryByRole('button', { name: '项目概览' })).toBeNull()
  expect(screen.getByLabelText('修改项目名称')).toBeTruthy()
  expect(screen.getByRole('region', { name: '摘要记录' })).toBeTruthy()
  expect(screen.queryByText('用量明细')).toBeNull()
  const info = screen.getByRole('region', { name: '项目资料' })
  const initialHash = window.location.hash

  await user.click(screen.getByRole('button', { name: '进展记录' }))
  expect(screen.queryByRole('region', { name: '摘要记录' })).toBeNull()
  await user.type(screen.getByLabelText('修改项目名称'), '草稿')
  await user.click(screen.getByRole('button', { name: '进展记录' }))
  expect(within(info).getByRole('region', { name: '摘要记录' })).toBeTruthy()
  expect(window.location.hash).toBe(initialHash)
  expect((screen.getByLabelText('修改项目名称') as HTMLInputElement).value).toBe('代谢研究草稿')
  await user.click(screen.getByRole('button', { name: '项目用量' }))
  expect(within(info).getByText('用量明细')).toBeTruthy()
  expect(screen.queryByRole('region', { name: '摘要记录' })).toBeNull()
  expect(window.location.hash).toBe(initialHash)
  await user.click(screen.getByRole('button', { name: '项目用量' }))
  expect(screen.queryByText('用量明细')).toBeNull()
  expect((screen.getByLabelText('修改项目名称') as HTMLInputElement).value).toBe('代谢研究草稿')
})

test.each(['activity', 'usage'] as const)('opens and reopens a saved %s link with progress expanded by default', async view => {
  const { user } = setup(`#project=p1&section=overview&view=${view}`)
  await screen.findByRole('heading', { name: project.name })
  const info = screen.getByRole('region', { name: '项目资料' })
  expect(within(info).getByLabelText('修改项目名称')).toBeTruthy()
  expect(within(info).getByRole('region', { name: '摘要记录' })).toBeTruthy()
  expect(screen.queryByText('用量明细')).toBeNull()
  await user.click(screen.getByRole('button', { name: '项目用量' }))
  expect(within(info).getByText('用量明细')).toBeTruthy()
  expect(screen.queryByRole('region', { name: '摘要记录' })).toBeNull()
  await user.click(screen.getByRole('button', { name: '我的项目' }))
  await user.click(screen.getByRole('button', { name: '打开项目 代谢研究' }))
  expect(screen.getByRole('region', { name: '摘要记录' })).toBeTruthy()
  expect(screen.queryByText('用量明细')).toBeNull()
  await user.click(screen.getByRole('button', { name: '进展记录' }))
  expect(screen.queryByRole('region', { name: '摘要记录' })).toBeNull()
  await user.click(screen.getByRole('button', { name: '第 2 步：上传文件' }))
  expect(window.location.hash).toContain('section=files')
  await user.click(screen.getByRole('button', { name: '第 1 步：项目资料' }))
  expect(screen.getByRole('region', { name: '摘要记录' })).toBeTruthy()
  expect(screen.queryByText('用量明细')).toBeNull()
})

test('protects a hidden metadata draft on cross-project navigation and keeps it after cancelling', async () => {
  const { user } = setup()
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  await screen.findByRole('heading', { name: project.name })

  await user.type(screen.getByLabelText('修改项目名称'), '未保存')
  await user.click(screen.getByRole('button', { name: '我的项目' }))
  expect(confirm).not.toHaveBeenCalled()
  const unload = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(unload)
  expect(unload.defaultPrevented).toBe(true)
  await user.click(screen.getByRole('button', { name: '打开项目 另一研究' }))
  expect(confirm).toHaveBeenCalledTimes(1)
  expect(window.location.hash).toBe('#workspace=projects')
  await user.click(within(screen.getByRole('complementary', {name:'主要导航'})).getByRole('button', { name: project.name }))
  await user.click(screen.getByRole('button', { name: '第 1 步：项目资料' }))
  expect((screen.getByLabelText('修改项目名称') as HTMLInputElement).value).toBe('代谢研究未保存')
  confirm.mockReturnValue(true)
  await user.click(screen.getByRole('button', { name: '我的项目' }))
  await user.click(screen.getByRole('button', { name: '打开项目 另一研究' }))
  await screen.findByRole('heading', { name: '另一研究' })
  expect((screen.getByLabelText('修改项目名称') as HTMLInputElement).value).toBe('另一研究')
  const cleanUnload = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(cleanUnload)
  expect(cleanUnload.defaultPrevented).toBe(false)
})

test('keeps metadata and output language drafts across overview views and saves through original contracts', async () => {
  const { user, fetcher } = setup()
  await screen.findByRole('heading', { name: project.name })

  await user.type(screen.getByLabelText('修改项目名称'), '草稿')
  await user.click(screen.getByRole('button', { name: '第 2 步：上传文件' }))
  await user.click(screen.getByRole('button', { name: '第 1 步：项目资料' }))
  expect((screen.getByLabelText('修改项目名称') as HTMLInputElement).value).toBe('代谢研究草稿')
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'PATCH')).toHaveLength(0)
  await user.click(screen.getByRole('button', { name: '保存修改：项目名称' }))
  await waitFor(() => expect(fetcher.mock.calls.some(([url, init]) => url === '/api/v1/projects/p1'
    && init?.method === 'PATCH' && init.body === JSON.stringify({ name: '代谢研究草稿' }))).toBe(true))
  await user.selectOptions(screen.getByLabelText('项目默认输出语言'), 'en')
  await user.click(screen.getByRole('button', { name: '第 2 步：上传文件' }))
  await user.click(screen.getByRole('button', { name: '第 1 步：项目资料' }))
  expect((screen.getByLabelText('项目默认输出语言') as HTMLSelectElement).value).toBe('en')
  await user.click(screen.getByRole('button', { name: '保存输出语言' }))
  await waitFor(() => expect(fetcher.mock.calls.some(([url, init]) => url === '/api/v1/projects/p1/language'
    && init?.method === 'PATCH' && init.body === JSON.stringify({ default_output_language: 'en' }))).toBe(true))
})
