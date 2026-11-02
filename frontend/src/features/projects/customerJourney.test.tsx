import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import ProjectWorkspace from './ProjectWorkspace'
import { apiFetch } from '../../shared/api/client'

vi.mock('../../shared/api/client', () => ({ apiFetch: vi.fn(), onApiSessionChanged: () => () => {} }))
vi.mock('./ProjectResources', () => ({ default: () => null }))
vi.mock('./ProjectSummary', () => ({ default: () => null }))
vi.mock('./ProjectDetails', () => ({ default: () => null }))
vi.mock('../research-intake/ResearchIntake', () => ({ default: () => null }))
vi.mock('../research-results/ResearchWorkspace', () => ({ default: () => null }))
vi.mock('../manuscripts/ProjectManuscripts', () => ({ default: () => null }))
vi.mock('../reviews/ReviewsWorkspace', () => ({ default: () => null }))
vi.mock('../journals/JournalWorkspace', () => ({ default: () => null }))
vi.mock('../school-templates/SchoolTemplates', () => ({ default: () => null }))
vi.mock('../literature/ProjectLiterature', () => ({ default: () => null }))
vi.mock('../model-usage/ProjectModelUsage', () => ({ default: () => null }))
vi.mock('../tasks/ProjectTasks', () => ({ default: () => null }))
const project = { id: 'p1', name: '客户流程', research_topic: '比较两组样本', project_type: 'research', file_count: 0, created_at: '2026-11-02T00:00:00Z', updated_at: '2026-11-02T00:00:00Z' }
function setup(hash = '') {
  window.history.replaceState(null, '', '/' + hash)
  vi.mocked(apiFetch).mockImplementation(async (url, init) => init?.method === 'POST' || String(url) === '/api/v1/projects/p1' ? Response.json(project) : Response.json({ items: [project], total: 1, page: 1, page_size: 5 }))
  render(<ProjectWorkspace />)
}
afterEach(() => { cleanup(); vi.clearAllMocks(); window.history.replaceState(null, '', '/') })
it('takes a successfully created project directly to upload without submitting analyses', async () => {
  setup()
  fireEvent.click(screen.getByLabelText('开始一项新研究'))
  fireEvent.change(screen.getByLabelText('项目名称'), { target: { value: project.name } })
  fireEvent.change(screen.getByLabelText('研究主题'), { target: { value: project.research_topic } })
  fireEvent.click(screen.getByRole('button', { name: '创建项目' }))
  await screen.findByRole('heading', { name: project.name })
  expect(window.location.hash).toBe('#project=p1&section=files&view=upload')
  expect(vi.mocked(apiFetch).mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
})
it('offers ordered navigation without marking unopened work complete', async () => {
  setup('#project=p1')
  await screen.findByRole('heading', { name: project.name })
  const navigation = screen.getByRole('navigation', { name: '项目操作步骤' })
  expect(navigation.textContent).toContain('上传文件')
  fireEvent.click(screen.getByRole('button', { name: '第 3 步：选择需求' }))
  expect(window.location.hash).toBe('#project=p1&section=overview&view=requirements')
  expect(screen.getByRole('button', { name: '第 3 步：选择需求' }).getAttribute('aria-current')).toBe('step')
  expect(navigation.textContent).not.toContain('已完成')
  fireEvent.click(screen.getByRole('button', { name: '第 1 步：项目资料' }))
  expect(window.location.hash).toBe('#project=p1&section=overview&view=settings')
})
it('lets research clients continue either writing service or leave results without mutating completion', async () => {
  setup('#project=p1&section=artifacts')
  await screen.findByRole('heading', { name: project.name })
  expect(screen.getByRole('button', { name: '继续写 SCI 论文' })).toBeTruthy()
  expect(screen.getByRole('button', { name: '继续写毕业论文' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '暂时结束，返回我的项目' }))
  expect(window.location.hash).toBe('#workspace=projects')
  expect(vi.mocked(apiFetch).mock.calls.every(([, init]) => !init?.method)).toBe(true)
})
