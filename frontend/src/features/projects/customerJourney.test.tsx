import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import ProjectWorkspace from './ProjectWorkspace'
import { apiFetch } from '../../shared/api/client'

vi.mock('../../shared/api/client', () => ({ apiFetch: vi.fn(), onApiSessionChanged: () => () => {} }))
vi.mock('./ProjectResources', () => ({ default: () => null }))
vi.mock('./ProjectSummary', () => ({ default: () => null }))
vi.mock('./ProjectDetails', () => ({ default: ({renderHeader}:{renderHeader?:(language:ReactNode)=>ReactNode}) => renderHeader?.(null) ?? null }))
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
function setup(hash = '', projectType = 'research', ready = true, services = ['analysis']) {
  window.history.replaceState(null, '', '/' + hash)
  const current={...project,project_type:projectType,file_count:ready?1:0}
  vi.mocked(apiFetch).mockImplementation(async (url, init) => {
    if(String(url).endsWith('/research-intake')) return Response.json({current_requirement:ready?{content:{services}}:null})
    if(String(url).includes('/summary?')) return Response.json({tasks:{total:ready?1:0},artifacts:{total:0}})
    return init?.method === 'POST' || String(url) === '/api/v1/projects/p1' ? Response.json(current) : Response.json({ items: [current], total: 1, page: 1, page_size: 5 })
  })
  render(<ProjectWorkspace />)
}
afterEach(() => { cleanup(); vi.clearAllMocks(); window.history.replaceState(null, '', '/') })
it.each(['research','sci','thesis'])('opens an available review-group entry for %s projects',async(projectType)=>{
 setup('#project=p1',projectType);await screen.findByRole('heading',{name:project.name});await waitFor(()=>expect((screen.getByRole('button',{name:'评审与修改'}) as HTMLButtonElement).disabled).toBe(false))
 fireEvent.click(screen.getByRole('button',{name:'评审与修改'}))
 expect(window.location.hash).toBe(`#project=p1&section=${projectType==='research'?'tasks':'reviews'}`)
})
it.each(['research','sci','thesis'])('opens existing manuscript downloads from %s results without creating a manuscript',async(projectType)=>{
 setup('#project=p1&section=artifacts',projectType);await screen.findByRole('heading',{name:project.name})
 fireEvent.click(screen.getByRole('button',{name:'查看已有稿件与 Word 下载'}))
 expect(window.location.hash).toBe('#project=p1&section=manuscripts')
 expect(vi.mocked(apiFetch).mock.calls.every(([,init])=>!init?.method)).toBe(true)
})
it('takes a successfully created project directly to upload without submitting analyses', async () => {
  setup()
  fireEvent.click(screen.getByLabelText('新建研究项目'))
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

it('switches the four result categories through one navigation without changing project data', async () => {
  setup('#project=p1&section=artifacts')
  await screen.findByRole('heading', { name: project.name })
  expect(screen.getAllByRole('navigation', { name: '成果分类' })).toHaveLength(1)
  for (const [name, view] of [['研究单图与组图', 'research-figures'], ['分析报告与成果包', 'research-reports'], ['排版导出记录', 'layout'], ['成果列表', 'list']]) {
    fireEvent.click(screen.getByRole('button', { name }))
    expect(screen.getByRole('button', { name }).getAttribute('aria-current')).toBe('page')
    expect(window.location.hash).toContain('section=artifacts')
    if (view !== 'list') expect(window.location.hash).toContain(`view=${view}`)
  }
  expect(screen.queryByRole('button', { name: '返回项目列表' })).toBeNull()
  expect(vi.mocked(apiFetch).mock.calls.every(([, init]) => !init?.method)).toBe(true)
})

it('blocks later steps and sidebar shortcuts until uploaded materials are available', async () => {
  setup('#project=p1','research',false)
  await screen.findByRole('heading',{name:project.name})
  for(const name of ['第 3 步：选择需求','第 4 步：执行分析','第 5 步：查看结果','分析与成果','稿件写作']) {
    const button=screen.getByRole('button',{name}) as HTMLButtonElement
    expect(button.disabled).toBe(true);fireEvent.click(button)
    expect(window.location.hash).toBe('#project=p1')
  }
  fireEvent.click(screen.getByRole('button',{name:'第 2 步：上传文件'}))
  expect(window.location.hash).toBe('#project=p1&section=files&view=upload')
})
it('replaces analysis with writing when only manuscript services are selected', async () => {
  setup('#project=p1','research',true,['sci_draft'])
  const writing=await screen.findByRole('button',{name:'第 4 步：稿件写作'})
  fireEvent.click(writing)
  expect(window.location.hash).toBe('#project=p1&section=manuscripts&view=research-selection')
  expect(screen.queryByRole('button',{name:'第 4 步：执行分析'})).toBeNull()
})
