import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import App from '../../app/App'
import { summaryFixture } from '../fixtures/summaryFixture'
import { workflowStateFixture } from '../fixtures/workflowStateFixture'

const project = { id: 'chrome-project', name: '导航精简研究', research_topic: '合成资料', project_type: 'research' as const, file_count: 1, created_at: '2026-11-02T00:00:00Z', updated_at: '2026-11-02T00:00:00Z' }
function mount() {
  window.history.replaceState(null, '', '/#project=chrome-project&section=artifacts')
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith('/auth/me')) return Response.json({user:{id:'chrome-user',email:'analyst@example.test',role:'analyst'},csrf_token:'fixture-token'})
    if (url === '/api/v1/projects/chrome-project') return Response.json(project)
    if (url.endsWith('/workflow-state')) return Response.json(workflowStateFixture(project))
    if (url.includes('/summary?')) return Response.json(summaryFixture(project.id))
    if (url.endsWith('/config')) return Response.json({max_upload_bytes:10485760,preview_row_limit:20})
    if (url.endsWith('/files')) return Response.json([])
    if (url.startsWith('/api/v1/assigned-projects?')) return Response.json({items:[],total:0,page:1,page_size:5})
    return Response.json({items:[],total:0,page:1,page_size:10})
  }))
  render(<App />)
}
afterEach(() => {cleanup();vi.unstubAllGlobals();window.history.replaceState(null,'','/')})

it.each([
  ['research', ['项目资料', '上传资料', '选择需求', '任务进度', '查看交付'], 'upload'],
  ['sci', ['项目资料', '上传资料', '图件拼版', '模板设定和资源配置', '文献与初稿'], 'materials'],
  ['thesis', ['项目资料', '上传资料', '图件拼版', '模板与资料整理', '文献与初稿'], 'materials'],
] as const)('puts the numbered %s steps in the customer header', async (projectType, labels, uploadStep) => {
  const customerProject = { ...project, project_type: projectType }
  window.history.replaceState(null, '', `/#customer-project=${project.id}&step=details`)
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith('/auth/me')) return Response.json({ user: { id: 'customer', email: 'customer@example.test', role: 'customer' }, csrf_token: 'fixture-token' })
    if (url === `/api/v1/projects/${project.id}`) return Response.json(customerProject)
    if (url.endsWith('/sci-settings')) return Response.json({ settings: null, revision: 0 })
    if (url.endsWith('/thesis-requirements')) return Response.json({ title: '', keywords: [], sections: [], template: null, language: 'zh-CN', revision: 0 })
    if (url.endsWith('/config')) return Response.json({ max_upload_bytes: 10485760, preview_row_limit: 20 })
    return Response.json({ items: [], total: 0, page: 1, page_size: 12 })
  }))
  render(<App />)

  const header = within((await screen.findByRole('button', { name: '账号' })).closest('header')!)
  const steps = within(await header.findByRole('navigation', { name: '项目操作步骤' }))
  expect(screen.getAllByRole('navigation', { name: '项目操作步骤' })).toHaveLength(1)
  expect(steps.getAllByRole('button').map(button => button.textContent)).toEqual(labels.map((label, index) => `${index + 1}${label}`))
  expect(steps.getByRole('button', { name: '第 1 步：项目资料', current: 'step' })).toBeTruthy()
  expect(header.queryByText(project.name)).toBeNull()
  expect(header.queryByText('我的项目')).toBeNull()
  const content = within(screen.getByRole('main'))
  const detailsHeading = content.getByRole('heading', { name: '项目资料', level: 1 })
  const detailsNext = content.getByRole('button', { name: '下一步 上传资料' })
  expect(detailsHeading.classList.contains('visually-hidden')).toBe(true)
  expect(detailsHeading.closest('.customer-section')?.lastElementChild?.contains(detailsNext)).toBe(true)

  const sidebar = within(screen.getByRole('complementary', { name: '主要导航' }))
  expect(sidebar.getByRole('button', { name: `当前项目 ${project.name}` })).toBeTruthy()
  fireEvent.click(steps.getByRole('button', { name: '第 2 步：上传资料' }))
  const uploadsHeading = await content.findByRole('heading', { name: '上传资料', level: 1 })
  const uploadsNext = content.getByRole('button', { name: /^下一步 / })
  expect(uploadsHeading.classList.contains('visually-hidden')).toBe(true)
  expect(uploadsHeading.closest('.customer-section')?.lastElementChild?.contains(uploadsNext)).toBe(true)
  expect(document.activeElement).toBe(uploadsHeading)
  expect(steps.getByRole('button', { name: '第 2 步：上传资料', current: 'step' })).toBeTruthy()
  expect(new URLSearchParams(window.location.hash.slice(1)).get('step')).toBe(uploadStep)

  fireEvent.click(sidebar.getByRole('button', { name: '我的项目' }))
  expect(header.queryByRole('navigation', { name: '项目操作步骤' })).toBeNull()
  expect(await screen.findByRole('heading', { name: '我的项目' })).toBeTruthy()
})

it('keeps one project step navigation in the header and hides it when leaving the project',async()=>{
  mount();await screen.findByRole('navigation',{name:'项目操作步骤'})
  const header=screen.getByRole('button',{name:'账号'}).closest('header')!
  expect(within(header).getByText(project.name)).toBeTruthy()
  expect(within(header).getByRole('navigation',{name:'项目操作步骤'})).toBeTruthy()
  expect(screen.getAllByRole('navigation',{name:'项目操作步骤'})).toHaveLength(1)
  fireEvent.click(within(header).getByRole('button',{name:'第 2 步：已提交需求'}))
  expect(window.location.hash).toContain('view=requirements')
  fireEvent.click(screen.getByRole('button',{name:'分配给我的项目'}))
  expect(within(header).queryByRole('navigation',{name:'项目操作步骤'})).toBeNull()
  expect(within(header).queryByText(project.name)).toBeNull()
  expect(within(header).getByText('分配给我的项目')).toBeTruthy()
})

it('keeps analyst workspace actions in the account menu and retains the project',async()=>{
  mount();await screen.findByRole('navigation',{name:'项目操作步骤'})
  const account=screen.getByRole('button',{name:'账号'})
  const header=account.closest('header')!
  expect(account.textContent).toBe('A')
  expect(screen.queryByRole('button',{name:'本人用量'})).toBeNull()
  expect(screen.queryByRole('navigation',{name:'面包屑导航'})).toBeNull()
  expect(screen.queryByLabelText('服务运行提示')).toBeNull()
  expect(screen.queryByText('从一份数据开始')).toBeNull()
  expect(screen.queryByText('界面语言',{exact:true})).toBeNull()
  expect(screen.getByRole('combobox',{name:'界面语言'})).toBeTruthy()
  fireEvent.click(account)
  expect(screen.queryByRole('button',{name:'管理员'})).toBeNull()
  fireEvent.click(screen.getByRole('button',{name:'本人用量'}))
  expect(account.getAttribute('aria-expanded')).toBe('false')
  expect(screen.getByRole('heading',{name:'本人用量'})).toBeTruthy()
  expect(screen.queryByRole('navigation',{name:'项目操作步骤'})).toBeNull()
  expect(within(header).queryByText(project.name)).toBeNull()
  fireEvent.click(account)
  fireEvent.click(screen.getByRole('button',{name:'项目工作区'}))
  expect(screen.getByRole('button',{name:project.name})).toBeTruthy()
  expect(within(header).getByText(project.name)).toBeTruthy()
  expect(screen.getByRole('button',{name:'第 4 步：查看结果'}).getAttribute('aria-current')).toBe('step')
  expect(vi.mocked(fetch).mock.calls.every(([,init])=>!init?.method||init.method==='GET')).toBe(true)
})
